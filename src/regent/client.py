"""Unified Regent Protocol client.

Single entry point for all Regent services. Routes through the
api-platform gateway with API key authentication.

Usage::

    from regent import RegentClient

    async with RegentClient(
        base_url="https://api.regentprotocol.org",
        api_key="rgnt_xxx",
        org_id="your-org-uuid",
    ) as regent:
        agent = await regent.identity.get_agent("agent_abc123")
        mandates = await regent.payment.list_agent_mandates("agent_abc123")
        auth = await regent.payment.authorize(mandate_id, AuthorizeRequest(...))
        await regent.audit.ingest_event(IngestEventRequest(...))
"""

from __future__ import annotations

from .clients.audit import AuditClient
from .clients.guardian import GuardianClient
from .clients.identity import IdentityClient
from .clients.payment import PaymentClient


class RegentClient:
    """Unified async client for the Regent Protocol API gateway."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        org_id: str,
        timeout: float = 30.0,
    ) -> None:
        self.identity = IdentityClient(base_url, api_key=api_key, org_id=org_id, timeout=timeout)
        self.payment = PaymentClient(base_url, api_key=api_key, org_id=org_id, timeout=timeout)
        self.audit = AuditClient(base_url, api_key=api_key, org_id=org_id, timeout=timeout)
        self.guardian = GuardianClient(base_url, api_key=api_key, org_id=org_id, timeout=timeout)

    async def aclose(self) -> None:
        await self.identity.aclose()
        await self.payment.aclose()
        await self.audit.aclose()
        await self.guardian.aclose()

    async def __aenter__(self) -> RegentClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
