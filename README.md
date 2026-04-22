# Regent SDK for Python

Python SDK for [Regent Protocol](https://regentprotocol.org) — AI agent identity, spending mandates, audit trails, and risk scoring.

Regent gives AI agents verifiable identity, enforceable spending limits, and tamper-proof audit trails anchored on Solana.

## Install

```bash
pip install regent-sdk
```

Or from source:

```bash
git clone https://github.com/abay94/regent-sdk-python.git
cd regent-sdk-python
pip install -e .
```

## Quick Start

```python
import asyncio
from decimal import Decimal
from regent import RegentClient, AuthorizeRequest, IngestEventRequest

async def main():
    async with RegentClient(
        base_url="https://api.regentprotocol.org",
        api_key="rgnt_your_api_key",
        org_id="your-org-uuid",
    ) as regent:

        # Check agent identity
        agent = await regent.identity.get_agent("agent_your_id")
        print(f"Agent: {agent.agent_id}  DID: {agent.did}  On-chain: {agent.onchain_status}")

        # Authorize a payment
        auth = await regent.payment.authorize(
            "your-mandate-uuid",
            AuthorizeRequest(amount=Decimal("50.00"), currency="USD"),
        )
        print(f"Authorized: {auth.jti}")

        # Log to audit trail
        await regent.audit.ingest_event(IngestEventRequest(
            event_id="trade-001",
            agent_id="agent_your_id",
            event_type="trade.executed",
            payload={"pair": "BTC/USD", "amount": "50.00"},
        ))

asyncio.run(main())
```

## Setup

Before using the SDK, set up on the [Regent Dashboard](https://web.regentprotocol.org):

1. **Sign up** and complete email verification + KYC
2. **Register an agent** — gets an `agent_id` and DID
3. **Create a spending mandate** (optional) — sets per-transaction, daily, and monthly limits
4. **Create an API key** — gets a `rgnt_` key for authentication

You'll need three values:
- `api_key` — your `rgnt_xxx` API key
- `org_id` — your organization UUID (Settings page)
- `agent_id` — your agent's ID (Agents page)

## RegentClient

The unified entry point. Wraps all four service clients with a single API key.

```python
from regent import RegentClient

async with RegentClient(
    base_url="https://api.regentprotocol.org",
    api_key="rgnt_xxx",
    org_id="your-org-uuid",
) as regent:
    regent.identity   # IdentityClient
    regent.payment    # PaymentClient
    regent.audit      # AuditClient
    regent.guardian    # GuardianClient
```

## Identity

Manage agent lifecycle — registration, verification, revocation.

```python
# Get agent details
agent = await regent.identity.get_agent("agent_abc123")
# agent.agent_id, agent.did, agent.status, agent.onchain_status, agent.solana_tx

# Verify KMS signature
sig = await regent.identity.verify_signature("agent_abc123")
# sig["signed"], sig["public_key_pem"], sig["identity_signature"]

# Revoke agent (irreversible)
revoked = await regent.identity.revoke_agent("agent_abc123")
```

## Payment

Spending mandates and payment authorization.

```python
from regent import AuthorizeRequest
from decimal import Decimal

# List mandates for an agent
mandates = await regent.payment.list_agent_mandates("agent_abc123")
mandate = next(m for m in mandates if m.status == "active")

# Authorize a payment
auth = await regent.payment.authorize(
    str(mandate.id),
    AuthorizeRequest(amount=Decimal("50.00"), currency="USD"),
)
# auth.status     → "authorized"
# auth.jwt_token  → signed proof (5-min TTL)
# auth.jti        → unique ID (replay protection)
# auth.guardian_score → risk score (0=normal, 1=anomaly)

# Get mandate details
mandate = await regent.payment.get_mandate("mandate-uuid")
# mandate.limits.per_tx_limit, mandate.limits.daily_limit, mandate.limits.monthly_limit
```

### Authorization flow

```python
from regent.errors import RegentAPIError

try:
    auth = await regent.payment.authorize(mandate_id, AuthorizeRequest(...))
    # Authorized — proceed with trade
    # Use auth.jti to link the trade back to this authorization
except RegentAPIError as e:
    if e.code == "MANDATE_LIMIT_EXCEEDED":
        print("Over limit — skip trade")
    elif e.code == "AGENT_NOT_ACTIVE":
        print("Agent revoked — stop trading")
    else:
        print(f"Rejected: {e.code}")
```

## Audit

Tamper-proof event logging with Merkle proofs anchored on Solana.

```python
from regent import IngestEventRequest

# Log an event
event = await regent.audit.ingest_event(IngestEventRequest(
    event_id="trade-12345",          # idempotency key — safe to retry
    agent_id="agent_abc123",
    event_type="trade.executed",
    payload={
        "exchange": "binance",
        "pair": "BTCUSDT",
        "side": "BUY",
        "amount": "50.00",
        "price": "94250.00",
        "authorization_jti": "abc-123",
    },
))
# event.payload_hash → SHA-256 hash of your payload
# event.status → "received" → "batched" → "anchored"

# List events for an agent
events = await regent.audit.list_agent_events("agent_abc123", limit=20)

# Verify Merkle proof (proves event is in an anchored batch)
proof = await regent.audit.verify_event("trade-12345")
# proof.verified → True
# proof.merkle_root → on-chain root
# proof.merkle_proof → hash path
```

## Guardian

ML-based risk scoring and anomaly detection.

```python
# Get latest risk score
score = await regent.guardian.get_latest_score("agent_abc123")
# score.score → 0.03 (0=normal, 1=anomaly)
# score.shap_factors → explains WHY the score is what it is

# List anomaly alerts
alerts = await regent.guardian.list_alerts("agent_abc123", status="open")

# Acknowledge an alert
await regent.guardian.acknowledge_alert("agent_abc123", "alert-uuid")
```

## Error Handling

All errors inherit from `RegentError`:

```python
from regent.errors import RegentError, RegentAPIError, RegentNetworkError

try:
    agent = await regent.identity.get_agent("agent_xxx")
except RegentAPIError as e:
    # API returned an error (4xx/5xx)
    print(e.code)          # "AGENT_NOT_FOUND"
    print(e.status_code)   # 404
    print(e.message)       # "No agent with ID agent_xxx"
    print(e.request_id)    # for support
except RegentNetworkError as e:
    # Network failure (timeout, DNS, connection refused)
    print(f"Network error: {e}")
except RegentError as e:
    # Catch-all for any SDK error
    print(f"Error: {e.code} — {e}")
```

### Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `AGENT_NOT_FOUND` | 404 | No agent with this ID |
| `AGENT_ALREADY_REVOKED` | 409 | Agent already revoked |
| `MANDATE_NOT_FOUND` | 404 | No mandate with this ID |
| `MANDATE_LIMIT_EXCEEDED` | 402 | Per-tx, daily, or monthly limit exceeded |
| `MANDATE_ALREADY_INACTIVE` | 409 | Mandate already revoked/expired |
| `EVENT_NOT_FOUND` | 404 | No audit event with this ID |
| `NOT_YET_ANCHORED` | 409 | Event not yet batched — try again later |
| `UNAUTHORIZED` | 401 | Invalid or missing API key |

## Examples

- [`examples/quickstart.py`](examples/quickstart.py) — Minimal 30-line example
- [`examples/binance_trading_agent.py`](examples/binance_trading_agent.py) — Full Binance testnet trading bot with Regent oversight

## How it works

```
Your Agent (this SDK)              Regent Protocol                  Blockchain
        |                                |                              |
        |-- get_agent(id) -------------->|                              |
        |   (verify identity + DID)      |                              |
        |                                |                              |
        |-- authorize(amount) ---------->|                              |
        |   checks: agent active?        |                              |
        |   checks: mandate limits?      |                              |
        |   checks: risk score?          |                              |
        |   returns: JWT + jti           |                              |
        |                                |                              |
        |-- [execute trade on exchange]  |                              |
        |                                |                              |
        |-- ingest_event(trade) -------->|                              |
        |   payload SHA-256 hashed       |-- batch into Merkle tree --> |
        |                                |-- anchor root on Solana ---->|
        |                                |                              |
        |   Anyone can verify:           |                              |
        |   hash + proof + on-chain root = tamper-proof                 |
```

## Requirements

- Python 3.11+
- Dependencies: `httpx`, `pydantic` (installed automatically)

## License

MIT
