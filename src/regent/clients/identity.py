from __future__ import annotations

import httpx

from .._http import HttpClient
from ..types import AgentResponse, RegisterAgentRequest, VerifyResponse


class IdentityClient:
    """Async client for agent identity operations.

    When ``org_id`` is provided, routes through the api-platform gateway
    (``/v1/organizations/{org_id}/agents/...``).  Without it, calls the
    internal identity service directly (``/v1/agents/...``).
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

    async def register(self, req: RegisterAgentRequest) -> AgentResponse:
        data = await self._http.post(f"{self._prefix}/agents", json=req.model_dump())
        return AgentResponse.model_validate(data)

    async def get_agent(self, agent_id: str) -> AgentResponse:
        data = await self._http.get(f"{self._prefix}/agents/{agent_id}")
        return AgentResponse.model_validate(data)

    async def verify_agent(self, agent_id: str) -> VerifyResponse:
        data = await self._http.get(f"{self._prefix}/agents/{agent_id}/verify")
        return VerifyResponse.model_validate(data)

    async def verify_signature(self, agent_id: str) -> dict:
        return await self._http.get(f"{self._prefix}/agents/{agent_id}/verify-signature")

    async def revoke_agent(self, agent_id: str) -> AgentResponse:
        data = await self._http.post(f"{self._prefix}/agents/{agent_id}/revoke")
        return AgentResponse.model_validate(data)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> IdentityClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
