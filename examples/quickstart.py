#!/usr/bin/env python3
"""Regent SDK — Quick Start Example.

Shows the core flow: connect → check agent → authorize → log event.

Setup:
    pip install regent-sdk
    export REGENT_API_KEY="rgnt_your_key"
    export REGENT_ORG_ID="your-org-uuid"
    export REGENT_AGENT_ID="agent_your_id"
    export REGENT_MANDATE_ID="your-mandate-uuid"
    python quickstart.py
"""

import asyncio
import os
import uuid
from decimal import Decimal

from regent import RegentClient, AuthorizeRequest, IngestEventRequest
from regent.errors import RegentAPIError

API_KEY = os.environ["REGENT_API_KEY"]
ORG_ID = os.environ["REGENT_ORG_ID"]
AGENT_ID = os.environ["REGENT_AGENT_ID"]
MANDATE_ID = os.environ.get("REGENT_MANDATE_ID", "")


async def main():
    async with RegentClient(
        base_url="https://api.regentprotocol.org",
        api_key=API_KEY,
        org_id=ORG_ID,
    ) as regent:

        # 1. Check agent identity
        agent = await regent.identity.get_agent(AGENT_ID)
        print(f"Agent: {agent.agent_id}  Status: {agent.status}  On-chain: {agent.onchain_status}")

        # 2. Authorize a payment (if mandate configured)
        if MANDATE_ID:
            try:
                auth = await regent.payment.authorize(
                    MANDATE_ID,
                    AuthorizeRequest(amount=Decimal("25.00"), currency="USD"),
                )
                print(f"Authorized: jti={auth.jti}  risk={auth.guardian_score}")
            except RegentAPIError as e:
                print(f"Rejected: {e.code}")

        # 3. Log an event to the audit trail
        event = await regent.audit.ingest_event(IngestEventRequest(
            event_id=f"quickstart-{uuid.uuid4().hex[:12]}",
            agent_id=AGENT_ID,
            event_type="demo.quickstart",
            payload={"message": "Hello from Regent SDK"},
        ))
        print(f"Event logged: {event.event_id}  hash={event.payload_hash[:24]}...")


if __name__ == "__main__":
    asyncio.run(main())
