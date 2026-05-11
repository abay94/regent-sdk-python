"""Internal async HTTP client used by all Regent SDK clients.

Not part of the public API — subject to change without notice.
"""

from __future__ import annotations

from typing import Any, TypeVar
from urllib.parse import urlencode

import httpx

from .errors import RegentAPIError, RegentNetworkError

T = TypeVar("T")


class HttpClient:
    """Thin async wrapper around ``httpx.AsyncClient``.

    Handles authentication headers, timeout, JSON serialisation,
    and maps HTTP errors to typed ``RegentError`` subclasses.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, *, json: Any = None) -> Any:
        return await self._request("PATCH", path, json=json)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        # Strip None values from query params
        clean_params: dict[str, str] | None = None
        if params:
            clean_params = {k: str(v) for k, v in params.items() if v is not None}

        try:
            response = await self._client.request(
                method,
                path,
                params=clean_params,
                json=json,
            )
        except httpx.TimeoutException as exc:
            raise RegentNetworkError(f"Request to {path} timed out", cause=exc) from exc
        except httpx.NetworkError as exc:
            raise RegentNetworkError(f"Network error on {path}: {exc}", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise RegentNetworkError(f"HTTP error on {path}: {exc}", cause=exc) from exc

        if not response.is_success:
            self._raise_api_error(response)

        return response.json()

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            pass

        # FastAPI's HTTPException wraps a dict detail in {"detail": {...}}.
        # An upstream service raising HTTPException(detail={"code": ...}) returns
        # {"detail": {"code": ...}}, but a gateway proxying that with its own
        # HTTPException can produce {"detail": {"detail": {"code": ...}}} — so
        # walk down the detail chain until we find the actual error fields.
        node: dict[str, Any] = body
        for _ in range(4):  # cap depth — guards against pathological inputs
            if isinstance(node, dict) and "code" not in node and isinstance(node.get("detail"), dict):
                node = node["detail"]
            else:
                break

        code: str = node.get("code") if isinstance(node, dict) else None
        code = code or "NETWORK_ERROR"
        message: str = (
            (node.get("message") if isinstance(node, dict) else None)
            or f"HTTP {response.status_code}"
        )
        request_id: str | None = (
            (node.get("request_id") if isinstance(node, dict) else None)
            or response.headers.get("x-request-id")
        )
        details: dict[str, Any] | None = (
            node.get("details") if isinstance(node, dict) else None
        )

        raise RegentAPIError(
            message,
            code=code,
            status_code=response.status_code,
            request_id=request_id,
            details=details,
        )
