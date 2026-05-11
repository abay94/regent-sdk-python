#!/usr/bin/env python3
"""
Binance Trading Agent — Real trades with Regent Protocol oversight
===================================================================

A real AI trading agent that:
1. Connects to Regent Protocol via SDK (identity, mandates, audit, guardian)
2. Connects to Binance testnet (BTC/USDT spot)
3. Authorizes every trade through Regent before executing
4. Logs every action to the tamper-proof audit trail

PREREQUISITES (done once by a human on the dashboard):
    1. Sign up at https://web.regentprotocol.org
    2. Complete email verification + KYC
    3. Register an agent (gets agent_id)
    4. Create a spending mandate (sets limits)
    5. Create an API key (gets rgnt_xxx)

SETUP:
    1. Get Binance testnet API key: https://testnet.binance.vision
    2. pip install httpx pydantic
    3. Export env vars (all from the dashboard):
       export REGENT_API_KEY="rgnt_xxx"
       export REGENT_ORG_ID="your-org-uuid"
       export REGENT_AGENT_ID="agent_xxx"
       export REGENT_MANDATE_ID="mandate-uuid"       # optional
       export BINANCE_API_KEY="your_testnet_api_key"
       export BINANCE_API_SECRET="your_testnet_secret"
    4. Run:
       python binance_trading_agent.py
"""

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, UTC
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from regent import RegentClient, AuthorizeRequest, IngestEventRequest
from regent.errors import RegentAPIError

# Rich is optional — falls back to plain prints if not installed.
try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# ============================================================================
# CONFIG
# ============================================================================

REGENT_BASE_URL = os.environ.get("REGENT_BASE_URL", "https://api.regentprotocol.org")
REGENT_API_KEY = os.environ.get("REGENT_API_KEY", "")
REGENT_ORG_ID = os.environ.get("REGENT_ORG_ID", "")
REGENT_AGENT_ID = os.environ.get("REGENT_AGENT_ID", "")
REGENT_MANDATE_ID = os.environ.get("REGENT_MANDATE_ID", "")

BINANCE_BASE = os.environ.get("BINANCE_BASE_URL", "https://testnet.binance.vision")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

SYMBOL = "BTCUSDT"
TRADE_AMOUNT_USD = 50.0
MAX_TRADES = 5
LOOP_INTERVAL = 30
PRICE_THRESHOLD = 0.00001  # 0.001% — low threshold for testnet (price barely moves)

# ============================================================================
# DEMO MODE
# ============================================================================
# DEMO_MODE=true runs a deterministic 11-step scripted sequence designed for
# a ~1.5 min screencast. Mandate must be: per_tx=$50, daily=$300, monthly=$5000.

DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

DEMO_SEQUENCE: list[dict] = [
    # Phase 1 — baseline (2 trades, normal pacing)
    {"side": "BUY",  "amount": 50,   "sleep": 10, "phase": "P1 baseline"},
    {"side": "SELL", "amount": 50,   "sleep": 10, "phase": "P1 baseline"},
    # Phase 2 — Guardian burst (5 trades in ~2.5s, then 8s pause for alert)
    {"side": "BUY",  "amount": 50,   "sleep": 0.5, "phase": "P2 burst"},
    {"side": "BUY",  "amount": 200,  "sleep": 0.5, "phase": "P2 burst"},
    {"side": "SELL", "amount": 50,   "sleep": 0.5, "phase": "P2 burst"},
    {"side": "BUY",  "amount": 500,  "sleep": 0.5, "phase": "P2 burst"},
    {"side": "BUY",  "amount": 1000, "sleep": 8,   "phase": "P2 burst"},
    # Phase 3 — recovery (risk score visibly elevated)
    {"side": "BUY",  "amount": 50,   "sleep": 10, "phase": "P3 recovery"},
    # Phase 4 — hit daily limit exactly
    {"side": "BUY",  "amount": 50,   "sleep": 10, "phase": "P4 hit limit"},
    # Phase 5 — rejections (daily, then per-tx)
    {"side": "BUY",  "amount": 50,   "sleep": 10, "phase": "P5 reject"},
    {"side": "BUY",  "amount": 500,  "sleep": 8,  "phase": "P5 reject"},
]


# ============================================================================
# BINANCE CLIENT
# ============================================================================

class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.http = httpx.AsyncClient(timeout=15.0)

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key}

    async def get_price(self, symbol: str) -> float:
        resp = await self.http.get(f"{self.base_url}/api/v3/ticker/price", params={"symbol": symbol})
        resp.raise_for_status()
        return float(resp.json()["price"])

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 3) -> list:
        resp = await self.http.get(
            f"{self.base_url}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    async def place_order(self, symbol: str, side: str, quote_qty: float) -> dict:
        params = self._sign({
            "symbol": symbol, "side": side, "type": "MARKET",
            "quoteOrderQty": f"{quote_qty:.2f}",
        })
        resp = await self.http.post(
            f"{self.base_url}/api/v3/order", params=params, headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_account(self) -> dict:
        params = self._sign({})
        resp = await self.http.get(
            f"{self.base_url}/api/v3/account", params=params, headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self.http.aclose()


# ============================================================================
# TRADING AGENT
# ============================================================================

class BinanceTradingAgent:
    def __init__(self, regent: RegentClient, binance: BinanceClient, agent_id: str, mandate_id: str | None):
        self.regent = regent
        self.binance = binance
        self.agent_id = agent_id
        self.mandate_id = mandate_id
        self.trades: list[dict] = []
        self.rejections: list[dict] = []
        # Demo / TUI state (populated only when demo mode runs)
        self._agent_info: dict = {}     # cached from setup(): bot_name, did, status, etc.
        self._mandate_info: dict = {}    # cached from setup(): per_tx, daily, monthly limits
        self._last_klines: list = []    # last 60 1m closes for sparkline
        self._last_price: float = 0.0
        self._current_phase: str = "setup"
        self._is_revoked: bool = False
        self._last_risk_score: float | None = None

    async def setup(self):
        print("\n" + "=" * 60)
        print("  BINANCE TRADING AGENT + REGENT PROTOCOL")
        print("=" * 60)

        # 1. Verify agent exists
        print("\n[1/3] Connecting to Regent Protocol...")
        agent = await self.regent.identity.get_agent(self.agent_id)
        print(f"  Agent ID:      {agent.agent_id}")
        print(f"  DID:           {agent.did or 'N/A'}")
        print(f"  Status:        {agent.status}")
        print(f"  On-chain:      {agent.onchain_status}")
        print(f"  KMS Signed:    {'Yes' if agent.identity_signature else 'No'}")

        if agent.status != "active":
            print(f"\n  ERROR: Agent is {agent.status}, not active. Cannot trade.")
            raise SystemExit(1)

        # 2. Check mandate (if configured)
        if self.mandate_id:
            print(f"\n[2/3] Checking mandate...")
            mandate = await self.regent.payment.get_mandate(self.mandate_id)
            print(f"  Mandate ID:    {mandate.id}")
            print(f"  Currency:      {mandate.currency}")
            print(f"  Per-trade max: ${mandate.limits.per_tx_limit or 'unlimited'}")
            print(f"  Daily limit:   ${mandate.limits.daily_limit or 'unlimited'}")
            print(f"  Monthly limit: ${mandate.limits.monthly_limit or 'unlimited'}")
            if mandate.status != "active":
                print(f"  WARNING: Mandate is {mandate.status}")
        else:
            print(f"\n[2/3] No mandate configured — trading without spending limits")
            # Try to find one automatically
            mandates = await self.regent.payment.list_agent_mandates(self.agent_id)
            active = [m for m in mandates if m.status == "active"]
            if active:
                self.mandate_id = str(active[0].id)
                print(f"  Found active mandate: {self.mandate_id}")
                print(f"  Per-trade: ${active[0].limits.per_tx_limit or 'unlimited'}")
            else:
                print(f"  No mandates found. Audit logging only — no authorization checks.")

        # 3. Verify Binance connectivity
        print(f"\n[3/3] Connecting to Binance testnet...")
        price = await self.binance.get_price(SYMBOL)
        account = await self.binance.get_account()
        usdt = next((b for b in account["balances"] if b["asset"] == "USDT"), None)
        btc = next((b for b in account["balances"] if b["asset"] == "BTC"), None)
        print(f"  BTC/USDT:  ${price:,.2f}")
        print(f"  USDT bal:  {float(usdt['free']):,.2f}" if usdt else "  USDT bal:  0")
        print(f"  BTC bal:   {float(btc['free']):.6f}" if btc else "  BTC bal:   0")

        # Log startup
        await self.regent.audit.ingest_event(IngestEventRequest(
            event_id=f"agent-started-{uuid.uuid4().hex[:12]}",
            agent_id=self.agent_id,
            event_type="agent.started",
            payload={"exchange": "binance-testnet", "symbol": SYMBOL, "price": str(price)},
        ))

        print(f"\n" + "-" * 60)
        print(f"  Ready. Monitoring {SYMBOL} every {LOOP_INTERVAL}s.")
        print(f"  Will execute up to {MAX_TRADES} trades.")
        if self.mandate_id:
            print(f"  Authorization: ON (mandate {self.mandate_id[:16]}...)")
        else:
            print(f"  Authorization: OFF (no mandate — audit only)")
        print("-" * 60)

    async def run_loop(self):
        rounds = 0
        while len(self.trades) < MAX_TRADES and rounds < MAX_TRADES * 3:
            rounds += 1
            print(f"\n--- Round {rounds} ---")
            try:
                await self._trading_round(rounds)
            except Exception as e:
                print(f"  Error: {e}")
            if len(self.trades) < MAX_TRADES:
                print(f"  Waiting {LOOP_INTERVAL}s...")
                await asyncio.sleep(LOOP_INTERVAL)

    async def _trading_round(self, round_num: int):
        klines = await self.binance.get_klines(SYMBOL, "1m", 3)
        prev_close = float(klines[-2][4])
        curr_close = float(klines[-1][4])
        change = (curr_close - prev_close) / prev_close

        print(f"  Price: ${curr_close:,.2f}  (change: {change*100:+.3f}%)")

        if abs(change) < PRICE_THRESHOLD:
            print(f"  No signal (threshold: {PRICE_THRESHOLD*100:.1f}%)")
            return

        side = "BUY" if change < 0 else "SELL"
        amount_usd = TRADE_AMOUNT_USD
        print(f"  Signal: {side} ${amount_usd:.2f} of BTC")

        # Authorize through Regent (if mandate configured)
        jti = None
        if self.mandate_id:
            print(f"  Authorizing via Regent...")
            try:
                auth = await self.regent.payment.authorize(
                    self.mandate_id,
                    AuthorizeRequest(amount=Decimal(str(amount_usd)), currency="USD"),
                )
                jti = auth.jti
                print(f"  AUTHORIZED (jti: {jti[:20]}..., risk: {auth.guardian_score or 'N/A'})")
            except RegentAPIError as e:
                print(f"  REJECTED: {e.code}")
                self.rejections.append({
                    "round": round_num, "side": side, "amount": amount_usd,
                    "reason": e.code, "time": datetime.now(UTC).isoformat(),
                })
                await self.regent.audit.ingest_event(IngestEventRequest(
                    event_id=f"trade-rejected-{uuid.uuid4().hex[:12]}",
                    agent_id=self.agent_id,
                    event_type="trade.rejected",
                    payload={"side": side, "amount": str(amount_usd), "reason": e.code, "price": str(curr_close)},
                ))
                return

        # Execute on Binance
        print(f"  Executing on Binance testnet...")
        try:
            order = await self.binance.place_order(SYMBOL, side, amount_usd)
            order_id = order.get("orderId", "unknown")
            filled_qty = order.get("executedQty", "0")
            filled_quote = order.get("cummulativeQuoteQty", "0")
            print(f"  FILLED: order={order_id}, qty={filled_qty} BTC, value=${float(filled_quote):,.2f}")
        except Exception as e:
            print(f"  ORDER FAILED: {e}")
            return

        trade = {
            "side": side, "price": curr_close, "amount_usd": float(filled_quote),
            "btc_qty": float(filled_qty), "order_id": str(order_id),
            "jti": jti, "time": datetime.now(UTC).isoformat(),
        }
        self.trades.append(trade)

        # Log to audit trail
        await self.regent.audit.ingest_event(IngestEventRequest(
            event_id=f"trade-{order_id}-{uuid.uuid4().hex[:8]}",
            agent_id=self.agent_id,
            event_type="trade.executed",
            payload={
                "exchange": "binance-testnet", "symbol": SYMBOL, "side": side,
                "price": str(curr_close), "amount_usd": str(filled_quote),
                "btc_qty": str(filled_qty), "order_id": str(order_id),
                "authorization_jti": jti,
            },
        ))
        print(f"  Trade #{len(self.trades)} logged to Regent audit trail.")

    # ========================================================================
    # DEMO MODE — scripted sequence + Rich TUI
    # ========================================================================

    async def _execute_trade(self, side: str, amount: float) -> None:
        """Authorize → fill on Binance → audit. Used by _demo_loop.

        Mirrors the logic in _trading_round but without the price-signal
        decision: just executes the (side, amount) the caller picked.
        """
        jti = None
        try:
            price = await self.binance.get_price(SYMBOL)
        except Exception:
            price = self._last_price or 0.0
        self._last_price = price

        # 1. Authorize through Regent (if mandate configured)
        if self.mandate_id:
            try:
                auth = await self.regent.payment.authorize(
                    self.mandate_id,
                    AuthorizeRequest(amount=Decimal(str(amount)), currency="USD"),
                )
                jti = auth.jti
                if auth.guardian_score is not None:
                    self._last_risk_score = float(auth.guardian_score)
            except RegentAPIError as e:
                self.rejections.append({
                    "side": side, "amount": amount, "reason": e.code,
                    "time": datetime.now(UTC).isoformat(), "price": price,
                })
                try:
                    await self.regent.audit.ingest_event(IngestEventRequest(
                        event_id=f"trade-rejected-{uuid.uuid4().hex[:12]}",
                        agent_id=self.agent_id,
                        event_type="trade.rejected",
                        payload={
                            "side": side, "amount": str(amount),
                            "reason": e.code, "price": str(price),
                        },
                    ))
                except Exception:
                    pass  # Don't break the demo on audit failure
                return

        # 2. Fill on Binance testnet
        try:
            order = await self.binance.place_order(SYMBOL, side, amount)
        except Exception as e:
            self.rejections.append({
                "side": side, "amount": amount,
                "reason": f"BINANCE_ERROR: {str(e)[:40]}",
                "time": datetime.now(UTC).isoformat(), "price": price,
            })
            return

        order_id = str(order.get("orderId", "unknown"))
        filled_qty = float(order.get("executedQty", "0"))
        filled_quote = float(order.get("cummulativeQuoteQty", "0"))

        self.trades.append({
            "side": side, "price": price, "amount_usd": filled_quote,
            "btc_qty": filled_qty, "order_id": order_id, "jti": jti,
            "time": datetime.now(UTC).isoformat(),
        })

        # 3. Audit
        try:
            await self.regent.audit.ingest_event(IngestEventRequest(
                event_id=f"trade-{order_id}-{uuid.uuid4().hex[:8]}",
                agent_id=self.agent_id,
                event_type="trade.executed",
                payload={
                    "exchange": "binance-testnet", "symbol": SYMBOL, "side": side,
                    "price": str(price), "amount_usd": str(filled_quote),
                    "btc_qty": str(filled_qty), "order_id": order_id,
                    "authorization_jti": jti,
                },
            ))
        except Exception:
            pass

    # --- TUI helpers ---------------------------------------------------------

    def _portfolio(self) -> dict:
        """Compute USDT/BTC balance and P&L from local trade history.

        Start: USDT=5000, BTC=0. BUY → USDT -= amount, BTC += qty.
        SELL → USDT += amount, BTC -= qty. P&L = total - 5000.
        """
        usdt, btc = 5000.0, 0.0
        for t in self.trades:
            if t["side"] == "BUY":
                usdt -= t["amount_usd"]
                btc += t["btc_qty"]
            else:
                usdt += t["amount_usd"]
                btc -= t["btc_qty"]
        btc_value = btc * (self._last_price or 0.0)
        total = usdt + btc_value
        pnl = total - 5000.0
        return {"usdt": usdt, "btc": btc, "btc_value": btc_value,
                "total": total, "pnl": pnl, "pnl_pct": (pnl / 5000.0) * 100}

    def _mandate_usage(self) -> dict:
        """Sum trade + rejection amounts today / this month UTC."""
        now = datetime.now(UTC)
        today = now.date()
        month_start = today.replace(day=1)
        daily, monthly = 0.0, 0.0
        for t in self.trades:
            ts = datetime.fromisoformat(t["time"]).date()
            if ts >= today:
                daily += t["amount_usd"]
            if ts >= month_start:
                monthly += t["amount_usd"]
        return {"daily": daily, "monthly": monthly}

    def _sparkline(self, prices: list[float], width: int = 50) -> str:
        """Unicode block sparkline from a list of float prices."""
        if not prices or len(prices) < 2:
            return "·" * width
        blocks = "▁▂▃▄▅▆▇█"
        lo, hi = min(prices), max(prices)
        rng = hi - lo if hi != lo else 1.0
        # Sample down to `width` points
        step = max(1, len(prices) // width)
        sampled = prices[::step][:width]
        return "".join(blocks[min(7, int((p - lo) / rng * 7))] for p in sampled)

    def _render_dashboard(self) -> "Layout":  # type: ignore[name-defined]
        """Build the live Rich Layout for the TUI."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="main", ratio=3),
            Layout(name="side", ratio=2),
        )
        layout["main"].split_column(
            Layout(name="price", size=8),
            Layout(name="feed"),
        )
        layout["side"].split_column(
            Layout(name="portfolio", size=7),
            Layout(name="mandate", size=8),
            Layout(name="risk", size=5),
            Layout(name="onchain", size=7),
        )

        # ---- HEADER ----
        info = self._agent_info
        m = self._mandate_info
        status_color = "red" if self._is_revoked else "green"
        status_label = "● REVOKED" if self._is_revoked else "● ACTIVE"
        mandate_line = (
            f"Mandate: [bold cyan]${int(m.get('per_tx', 0))}[/]/[bold cyan]${int(m.get('daily', 0))}[/]/[bold cyan]${int(m.get('monthly', 0))}[/]"
            if m else "Mandate: [dim]not configured[/]"
        )
        header_text = Text.from_markup(
            f"[bold]{info.get('bot_name', 'agent')}[/]   "
            f"agent: [dim]{(info.get('agent_id') or '')[:24]}…[/]   "
            f"[cyan]{info.get('did', '')[:38]}…[/]\n"
            f"[{status_color}]{status_label}[/]   {mandate_line}   "
            f"On-chain: [cyan]{info.get('onchain_status', '—')}[/]"
        )
        layout["header"].update(Panel(header_text, title="Regent Protocol · Live Demo",
                                       border_style="cyan"))

        # ---- PRICE + SPARKLINE ----
        closes = [float(k[4]) for k in (self._last_klines or [])]
        spark = self._sparkline(closes, width=56)
        price_disp = self._last_price or (closes[-1] if closes else 0.0)
        change = 0.0
        if len(closes) >= 2:
            change = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] else 0.0
        change_color = "green" if change >= 0 else "red"
        change_arrow = "▲" if change >= 0 else "▼"
        price_text = Text.from_markup(
            f"[bold cyan]BTC/USDT[/]   [bold]${price_disp:,.2f}[/]   "
            f"[{change_color}]{change_arrow} {abs(change):.2f}%[/]   "
            f"[dim](last 60m)[/]\n[cyan]{spark}[/]"
        )
        layout["price"].update(Panel(price_text, border_style="cyan"))

        # ---- TRADE FEED ----
        feed_table = Table.grid(padding=(0, 1), expand=True)
        feed_table.add_column(width=8)   # time
        feed_table.add_column(width=2)   # icon
        feed_table.add_column(width=5)   # side
        feed_table.add_column(width=8, justify="right")  # amount
        feed_table.add_column(ratio=1)   # detail
        # Merge trades + rejections, newest first
        feed_items = (
            [{"ok": True,  **t} for t in self.trades] +
            [{"ok": False, **r} for r in self.rejections]
        )
        feed_items.sort(key=lambda x: x["time"], reverse=True)
        for item in feed_items[:15]:
            ts = item["time"][11:19] if "T" in item["time"] else item["time"][:8]
            if item["ok"]:
                feed_table.add_row(
                    f"[dim]{ts}[/]", "[green]✓[/]", f"[green]{item['side']}[/]",
                    f"[bold]${item['amount_usd']:.2f}[/]",
                    f"[dim]jti {str(item.get('jti') or '')[:10]}…  @${item['price']:,.0f}[/]",
                )
            else:
                feed_table.add_row(
                    f"[dim]{ts}[/]", "[red]✗[/]", f"[red]{item['side']}[/]",
                    f"[red]${item['amount']:.2f}[/]",
                    f"[red]{item['reason']}[/]",
                )
        if not feed_items:
            feed_table.add_row("", "", "[dim]waiting…[/]", "", "")
        layout["feed"].update(Panel(feed_table, title="Trade Feed", border_style="cyan"))

        # ---- PORTFOLIO ----
        p = self._portfolio()
        pnl_color = "green" if p["pnl"] >= 0 else "red"
        pnl_sign = "+" if p["pnl"] >= 0 else ""
        portfolio_text = Text.from_markup(
            f"[dim]USDT[/]   [bold]${p['usdt']:,.2f}[/]\n"
            f"[dim]BTC [/]   [bold]{p['btc']:.6f}[/] "
            f"[dim](≈${p['btc_value']:,.2f})[/]\n"
            f"[dim]P&L [/]   [{pnl_color}]{pnl_sign}${p['pnl']:,.2f}[/] "
            f"[{pnl_color}]({pnl_sign}{p['pnl_pct']:.2f}%)[/]"
        )
        layout["portfolio"].update(Panel(portfolio_text, title="Portfolio",
                                          border_style="green"))

        # ---- MANDATE USAGE ----
        u = self._mandate_usage()
        per_tx_lim = m.get("per_tx", 0) or 1
        daily_lim = m.get("daily", 0) or 1
        monthly_lim = m.get("monthly", 0) or 1
        last_amount = self.trades[-1]["amount_usd"] if self.trades else 0
        mandate_table = Table.grid(padding=(0, 1), expand=True)
        mandate_table.add_column(width=8)
        mandate_table.add_column(ratio=1)
        mandate_table.add_column(width=14, justify="right")
        for label, used, lim in [
            ("per-tx", last_amount, per_tx_lim),
            ("daily",  u["daily"],  daily_lim),
            ("month",  u["monthly"], monthly_lim),
        ]:
            pct = min(100, int((used / lim) * 100)) if lim else 0
            bar_color = "red" if pct >= 95 else "yellow" if pct >= 70 else "green"
            filled = pct // 5
            bar = f"[{bar_color}]" + ("▓" * filled) + "[/]" + ("░" * (20 - filled))
            mandate_table.add_row(
                f"[dim]{label}[/]", bar,
                f"[bold]${int(used)}[/]/[dim]${int(lim)}[/]",
            )
        layout["mandate"].update(Panel(mandate_table, title="Mandate Usage",
                                        border_style="yellow"))

        # ---- RISK GAUGE ----
        rs = self._last_risk_score
        if rs is None:
            risk_text = Text.from_markup("[dim]no score yet — Guardian watching…[/]")
        else:
            filled = int(rs * 20)
            color = "red" if rs >= 0.7 else "yellow" if rs >= 0.4 else "green"
            risk_bar = f"[{color}]" + "▓" * filled + "[/]" + "░" * (20 - filled)
            risk_text = Text.from_markup(
                f"[bold]{rs:.3f}[/]   {risk_bar}\n"
                f"[dim]Guardian (Isolation Forest + SHAP)[/]"
            )
        layout["risk"].update(Panel(risk_text, title="Risk Gauge", border_style="red"))

        # ---- ON-CHAIN ----
        onchain_text = Text.from_markup(
            f"[dim]Status:    [/][cyan]{info.get('onchain_status', '—')}[/]\n"
            f"[dim]Trades OK: [/][green]{len(self.trades)}[/]\n"
            f"[dim]Rejected:  [/][red]{len(self.rejections)}[/]\n"
            f"[dim]Solana tx: [/][cyan]{(info.get('solana_tx') or '—')[:24]}…[/]"
        )
        layout["onchain"].update(Panel(onchain_text, title="On-Chain",
                                        border_style="cyan"))

        # ---- FOOTER ----
        total_actions = len(self.trades) + len(self.rejections)
        footer = Text.from_markup(
            f"[{status_color}]{status_label}[/]   "
            f"{total_actions} actions · "
            f"[green]{len(self.trades)} authorized[/] · "
            f"[red]{len(self.rejections)} rejected[/]   "
            f"phase: [bold]{self._current_phase}[/]"
        )
        layout["footer"].update(Panel(Align.center(footer), border_style="dim"))

        return layout

    async def _refresh_agent_info(self) -> None:
        """Pull current agent + mandate state into self._agent_info / _mandate_info."""
        try:
            a = await self.regent.identity.get_agent(self.agent_id)
            self._agent_info = {
                "agent_id": a.agent_id,
                "did": a.did or "",
                "status": a.status,
                "onchain_status": a.onchain_status,
                "solana_tx": a.solana_tx or "",
                "bot_name": (a.metadata or {}).get("bot_name", "demo-bot")
                            if hasattr(a, "metadata") and isinstance(a.metadata, dict)
                            else "demo-bot",
            }
        except Exception:
            pass
        if self.mandate_id:
            try:
                m = await self.regent.payment.get_mandate(self.mandate_id)
                self._mandate_info = {
                    "per_tx": float(m.limits.per_tx_limit or 0),
                    "daily": float(m.limits.daily_limit or 0),
                    "monthly": float(m.limits.monthly_limit or 0),
                }
            except Exception:
                pass

    async def _refresh_risk_score(self) -> None:
        """Best-effort pull of latest Guardian score (independent of authorize response)."""
        try:
            rs = await self.regent.guardian.get_latest_score(self.agent_id)
            if rs and rs.score is not None:
                self._last_risk_score = float(rs.score)
        except Exception:
            pass

    async def _demo_loop(self) -> None:
        """Run the 11-step scripted sequence + revoke + post-revoke attempt."""
        await self._refresh_agent_info()
        try:
            self._last_klines = await self.binance.get_klines(SYMBOL, "1m", 60)
            self._last_price = float(self._last_klines[-1][4])
        except Exception:
            pass

        if not RICH_AVAILABLE:
            # Plain-text fallback
            print("\n" + "=" * 60)
            print("  DEMO MODE — plain output (install `rich` for TUI)")
            print("=" * 60)
            for i, step in enumerate(DEMO_SEQUENCE, 1):
                self._current_phase = step["phase"]
                print(f"\n[{i}/{len(DEMO_SEQUENCE)}] {step['phase']}: "
                      f"{step['side']} ${step['amount']}")
                await self._execute_trade(step["side"], float(step["amount"]))
                if self.trades and self.trades[-1].get("time") == max(
                    (t["time"] for t in self.trades), default=""
                ):
                    last = self.trades[-1]
                    print(f"  ✓ FILLED  jti={(last.get('jti') or '')[:16]}…")
                elif self.rejections and self.rejections[-1].get("time") == max(
                    (r["time"] for r in self.rejections), default=""
                ):
                    last = self.rejections[-1]
                    print(f"  ✗ REJECTED  {last['reason']}")
                await asyncio.sleep(step["sleep"])
            # Wait for manual revoke from the dashboard (5-min fallback)
            print(f"\n--- WAITING FOR MANUAL REVOCATION ---")
            print(f"    On the dashboard: Agents → {self.agent_id[:24]}… → Revoke")
            start = time.time()
            manual = False
            while time.time() - start < 300:
                try:
                    a = await self.regent.identity.get_agent(self.agent_id)
                    if a.status != "active":
                        manual = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)
            if not manual:
                print(f"    Timeout — falling back to programmatic revoke")
                try:
                    await self.regent.identity.revoke_agent(self.agent_id)
                except Exception:
                    pass
            self._is_revoked = True
            self._current_phase = "REVOKED"
            await asyncio.sleep(2)
            print(f"\n--- POST-REVOKE TRADE (should fail) ---")
            await self._execute_trade("BUY", 50.0)
            await asyncio.sleep(5)
            return

        # Rich TUI mode
        console = Console()
        with Live(self._render_dashboard(), console=console,
                  refresh_per_second=2, screen=True) as live:
            for i, step in enumerate(DEMO_SEQUENCE, 1):
                self._current_phase = f"{step['phase']} ({i}/{len(DEMO_SEQUENCE)})"
                live.update(self._render_dashboard())
                await self._execute_trade(step["side"], float(step["amount"]))
                # Refresh klines every 3rd step (Binance rate limit friendly)
                if i % 3 == 0:
                    try:
                        self._last_klines = await self.binance.get_klines(SYMBOL, "1m", 60)
                    except Exception:
                        pass
                # Pull risk score periodically
                if i % 2 == 0:
                    await self._refresh_risk_score()
                live.update(self._render_dashboard())
                await asyncio.sleep(step["sleep"])

            # Wait for manual revoke from dashboard (5-min fallback)
            self._current_phase = "waiting for manual revoke from dashboard…"
            live.update(self._render_dashboard())
            start = time.time()
            manual = False
            while time.time() - start < 300:
                try:
                    a = await self.regent.identity.get_agent(self.agent_id)
                    if a.status != "active":
                        manual = True
                        break
                except Exception:
                    pass
                elapsed = int(time.time() - start)
                self._current_phase = f"waiting for manual revoke… ({elapsed}s elapsed)"
                live.update(self._render_dashboard())
                await asyncio.sleep(2)
            if not manual:
                try:
                    await self.regent.identity.revoke_agent(self.agent_id)
                except Exception:
                    pass
            self._is_revoked = True
            self._current_phase = "REVOKED"
            await self._refresh_agent_info()
            live.update(self._render_dashboard())
            await asyncio.sleep(3)

            # Post-revoke attempt — should fail with AGENT_NOT_ACTIVE
            self._current_phase = "post-revoke attempt"
            live.update(self._render_dashboard())
            await self._execute_trade("BUY", 50.0)
            live.update(self._render_dashboard())
            await asyncio.sleep(5)

    async def print_summary(self):
        print("\n" + "=" * 60)
        print("  TRADING SESSION SUMMARY")
        print("=" * 60)

        agent = await self.regent.identity.get_agent(self.agent_id)
        print(f"\n  Agent ID:      {agent.agent_id}")
        print(f"  DID:           {agent.did or 'N/A'}")
        print(f"  On-chain:      {agent.onchain_status}")
        if agent.solana_tx:
            print(f"  Solana TX:     https://explorer.solana.com/tx/{agent.solana_tx}?cluster=devnet")

        print(f"\n  Trades executed: {len(self.trades)}")
        total_bought = sum(t["amount_usd"] for t in self.trades if t["side"] == "BUY")
        total_sold = sum(t["amount_usd"] for t in self.trades if t["side"] == "SELL")
        for i, t in enumerate(self.trades, 1):
            jti_str = f"jti={t['jti'][:16]}..." if t["jti"] else "no-mandate"
            print(f"    [{i}] {t['side']:4s} ${t['amount_usd']:>8.2f}  @ ${t['price']:>10,.2f}  ({jti_str})")
        print(f"    Total bought: ${total_bought:,.2f}")
        print(f"    Total sold:   ${total_sold:,.2f}")

        if self.rejections:
            print(f"\n  Rejections: {len(self.rejections)}")
            for r in self.rejections:
                print(f"    {r['side']} ${r['amount']:.2f} — {r['reason']}")

        events = await self.regent.audit.list_agent_events(self.agent_id, limit=15)
        print(f"\n  Audit trail: {len(events)} events")
        for e in events[:10]:
            print(f"    [{e.status:10s}] {e.event_type:25s}  hash={e.payload_hash[:16]}...")

        print(f"\n  DID Document: https://api.regentprotocol.org/v1/did/{agent.did}")
        print("\n" + "=" * 60)
        print("  Every trade was logged to the Regent audit trail and")
        print("  anchored on Solana. The on-chain record proves what")
        print("  this agent did, who was responsible, and when.")
        print("=" * 60 + "\n")


# ============================================================================
# MAIN
# ============================================================================

async def main():
    missing = []
    if not REGENT_API_KEY:
        missing.append("REGENT_API_KEY")
    if not REGENT_ORG_ID:
        missing.append("REGENT_ORG_ID")
    if not REGENT_AGENT_ID:
        missing.append("REGENT_AGENT_ID")
    if not BINANCE_API_KEY:
        missing.append("BINANCE_API_KEY")
    if not BINANCE_API_SECRET:
        missing.append("BINANCE_API_SECRET")

    if missing:
        print("ERROR: Missing required environment variables:")
        for v in missing:
            print(f"  - {v}")
        print("\nSetup:")
        print("  1. Register agent + create API key at https://web.regentprotocol.org")
        print("  2. Get Binance testnet key at https://testnet.binance.vision")
        print("  3. Export all env vars and run again")
        return

    regent = RegentClient(
        base_url=REGENT_BASE_URL,
        api_key=REGENT_API_KEY,
        org_id=REGENT_ORG_ID,
    )
    binance = BinanceClient(BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_BASE)

    try:
        agent = BinanceTradingAgent(
            regent=regent,
            binance=binance,
            agent_id=REGENT_AGENT_ID,
            mandate_id=REGENT_MANDATE_ID or None,
        )
        await agent.setup()
        if DEMO_MODE:
            await agent._demo_loop()
        else:
            await agent.run_loop()
        await agent.print_summary()
    finally:
        await regent.aclose()
        await binance.close()


if __name__ == "__main__":
    asyncio.run(main())
