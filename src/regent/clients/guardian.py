from __future__ import annotations

import httpx

from .._http import HttpClient
from ..types import AlertResponse, ModelInfoResponse, RiskScoreResponse


class GuardianClient:
    """Async client for risk scoring and anomaly alerts.

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

    async def get_latest_score(self, agent_id: str) -> RiskScoreResponse:
        data = await self._http.get(f"{self._prefix}/agents/{agent_id}/score")
        return RiskScoreResponse.model_validate(data)

    async def list_scores(
        self,
        agent_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RiskScoreResponse]:
        data = await self._http.get(
            f"{self._prefix}/agents/{agent_id}/scores",
            params={"limit": limit, "offset": offset},
        )
        return [RiskScoreResponse.model_validate(item) for item in data]

    async def list_alerts(
        self,
        agent_id: str,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[AlertResponse]:
        data = await self._http.get(
            f"{self._prefix}/agents/{agent_id}/alerts",
            params={"status": status, "limit": limit, "offset": offset},
        )
        return [AlertResponse.model_validate(item) for item in data]

    async def acknowledge_alert(self, agent_id: str, alert_id: str) -> AlertResponse:
        data = await self._http.post(
            f"{self._prefix}/agents/{agent_id}/alerts/{alert_id}/acknowledge",
            json={},
        )
        return AlertResponse.model_validate(data)

    async def get_model_info(self) -> ModelInfoResponse:
        data = await self._http.get(f"{self._prefix}/models")
        return ModelInfoResponse.model_validate(data)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GuardianClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
