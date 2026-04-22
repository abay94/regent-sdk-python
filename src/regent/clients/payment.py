from __future__ import annotations

import httpx

from .._http import HttpClient
from ..types import (
    AuthorizationResponse,
    AuthorizeRequest,
    CreateMandateRequest,
    MandateResponse,
)


class PaymentClient:
    """Async client for mandate lifecycle and payment authorization.

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

    async def create_mandate(self, req: CreateMandateRequest) -> MandateResponse:
        data = await self._http.post(f"{self._prefix}/mandates", json=req.model_dump(mode="json"))
        return MandateResponse.model_validate(data)

    async def get_mandate(self, mandate_id: str) -> MandateResponse:
        data = await self._http.get(f"{self._prefix}/mandates/{mandate_id}")
        return MandateResponse.model_validate(data)

    async def list_agent_mandates(self, agent_id: str) -> list[MandateResponse]:
        data = await self._http.get(f"{self._prefix}/agents/{agent_id}/mandates")
        return [MandateResponse.model_validate(item) for item in data]

    async def authorize(self, mandate_id: str, req: AuthorizeRequest) -> AuthorizationResponse:
        data = await self._http.post(
            f"{self._prefix}/mandates/{mandate_id}/authorize",
            json=req.model_dump(mode="json"),
        )
        return AuthorizationResponse.model_validate(data)

    async def revoke_mandate(self, mandate_id: str) -> MandateResponse:
        data = await self._http.post(f"{self._prefix}/mandates/{mandate_id}/revoke")
        return MandateResponse.model_validate(data)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> PaymentClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
