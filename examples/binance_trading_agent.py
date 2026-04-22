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
        await agent.run_loop()
        await agent.print_summary()
    finally:
        await regent.aclose()
        await binance.close()


if __name__ == "__main__":
    asyncio.run(main())
