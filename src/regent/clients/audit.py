from __future__ import annotations

import httpx

from .._http import HttpClient
from ..types import (
    AuditEventResponse,
    BatchResponse,
    IngestEventRequest,
    MerkleProofResponse,
)


class AuditClient:
    """Async client for audit event ingestion, querying, and verification.

    When ``org_id`` is provided, routes through the api-platform gateway.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        org_id: str | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._http = HttpClient(base_url, api_key=api_key, timeout=timeout, client=client)
        self._prefix = f"/v1/organizations/{org_id}" if org_id else "/v1"

    async def ingest_event(self, req: IngestEventRequest) -> AuditEventResponse:
        data = await self._http.post(f"{self._prefix}/audit/events", json=req.model_dump())
        return AuditEventResponse.model_validate(data)

    async def get_event(self, event_id: str) -> AuditEventResponse:
        data = await self._http.get(f"{self._prefix}/events/{event_id}")
        return AuditEventResponse.model_validate(data)

    async def list_agent_events(
        self,
        agent_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[AuditEventResponse]:
        data = await self._http.get(
            f"{self._prefix}/agents/{agent_id}/events",
            params={"limit": limit, "offset": offset},
        )
        return [AuditEventResponse.model_validate(item) for item in data]

    async def get_batch(self, batch_id: str) -> BatchResponse:
        data = await self._http.get(f"{self._prefix}/batches/{batch_id}")
        return BatchResponse.model_validate(data)

    async def verify_event(self, event_id: str) -> MerkleProofResponse:
        data = await self._http.post(f"{self._prefix}/events/{event_id}/verify", json={})
        return MerkleProofResponse.model_validate(data)

    async def seal_batch(self) -> dict:
        return await self._http.post(f"{self._prefix}/audit/seal-batch", json={})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AuditClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
