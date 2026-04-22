"""Tests for IdentityClient against a mock server."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from regent import IdentityClient, RegisterAgentRequest
from regent.errors import RegentAPIError, RegentNetworkError

BASE_URL = "http://api-identity"


@pytest.fixture()
def client() -> IdentityClient:
    return IdentityClient(base_url=BASE_URL)


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


@respx.mock
async def test_register_posts_to_agents_and_returns_model(
    client: IdentityClient, agent_response: dict  # type: ignore[type-arg]
) -> None:
    route = respx.post(f"{BASE_URL}/v1/agents").mock(
        return_value=Response(201, json=agent_response)
    )

    req = RegisterAgentRequest(
        responsible_party_id="rp_xyz", kyc_provider="jumio", metadata={"region": "EU"}
    )
    result = await client.register(req)

    assert route.called
    assert result.agent_id == "agent_abc123"
    assert result.status == "active"
    assert result.revoked_at is None


@respx.mock
async def test_register_raises_api_error_on_409(client: IdentityClient) -> None:
    respx.post(f"{BASE_URL}/v1/agents").mock(
        return_value=Response(409, json={"code": "AGENT_NOT_FOUND", "message": "Conflict"})
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.register(
            RegisterAgentRequest(responsible_party_id="rp", kyc_provider="jumio")
        )

    assert exc_info.value.code == "AGENT_NOT_FOUND"
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# get_agent()
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_agent_returns_model(
    client: IdentityClient, agent_response: dict  # type: ignore[type-arg]
) -> None:
    respx.get(f"{BASE_URL}/v1/agents/agent_abc123").mock(
        return_value=Response(200, json=agent_response)
    )

    result = await client.get_agent("agent_abc123")

    assert result.agent_id == "agent_abc123"
    assert result.kyc_provider == "jumio"


@respx.mock
async def test_get_agent_raises_agent_not_found(client: IdentityClient) -> None:
    respx.get(f"{BASE_URL}/v1/agents/bad_id").mock(
        return_value=Response(404, json={"code": "AGENT_NOT_FOUND", "message": "Not found"})
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.get_agent("bad_id")

    assert exc_info.value.code == "AGENT_NOT_FOUND"
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# verify_agent()
# ---------------------------------------------------------------------------


@respx.mock
async def test_verify_agent_returns_verify_response(
    client: IdentityClient, verify_response: dict  # type: ignore[type-arg]
) -> None:
    respx.get(f"{BASE_URL}/v1/agents/agent_abc123/verify").mock(
        return_value=Response(200, json=verify_response)
    )

    result = await client.verify_agent("agent_abc123")

    assert result.verified is True
    assert result.agent_id == "agent_abc123"


@respx.mock
async def test_verify_agent_raises_on_404(client: IdentityClient) -> None:
    respx.get(f"{BASE_URL}/v1/agents/missing/verify").mock(
        return_value=Response(404, json={"code": "AGENT_NOT_FOUND", "message": "Not found"})
    )

    with pytest.raises(RegentAPIError):
        await client.verify_agent("missing")


# ---------------------------------------------------------------------------
# revoke_agent()
# ---------------------------------------------------------------------------


@respx.mock
async def test_revoke_agent_returns_updated_agent(
    client: IdentityClient, agent_response: dict  # type: ignore[type-arg]
) -> None:
    revoked = {**agent_response, "status": "revoked", "revoked_at": "2024-01-04T00:00:00+00:00"}
    respx.patch(f"{BASE_URL}/v1/agents/agent_abc123/revoke").mock(
        return_value=Response(200, json=revoked)
    )

    result = await client.revoke_agent("agent_abc123")

    assert result.status == "revoked"
    assert result.revoked_at is not None


@respx.mock
async def test_revoke_agent_raises_already_revoked(client: IdentityClient) -> None:
    respx.patch(f"{BASE_URL}/v1/agents/agent_abc123/revoke").mock(
        return_value=Response(
            409,
            json={"code": "AGENT_ALREADY_REVOKED", "message": "Already revoked"},
        )
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.revoke_agent("agent_abc123")

    assert exc_info.value.code == "AGENT_ALREADY_REVOKED"
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Network / auth error handling
# ---------------------------------------------------------------------------


@respx.mock
async def test_network_error_raises_regent_network_error(client: IdentityClient) -> None:
    import httpx

    respx.get(f"{BASE_URL}/v1/agents/agent_abc123").mock(
        side_effect=httpx.NetworkError("Connection refused")
    )

    with pytest.raises(RegentNetworkError):
        await client.get_agent("agent_abc123")


@respx.mock
async def test_api_key_sent_in_authorization_header(
    agent_response: dict,  # type: ignore[type-arg]
) -> None:
    route = respx.get(f"{BASE_URL}/v1/agents/agent_abc123").mock(
        return_value=Response(200, json=agent_response)
    )

    auth_client = IdentityClient(base_url=BASE_URL, api_key="secret-token")
    await auth_client.get_agent("agent_abc123")
    await auth_client.aclose()

    assert route.calls[0].request.headers["Authorization"] == "Bearer secret-token"


@respx.mock
async def test_fallback_error_code_on_plain_500(client: IdentityClient) -> None:
    respx.get(f"{BASE_URL}/v1/agents/agent_abc123").mock(
        return_value=Response(500, json={"message": "Internal Server Error"})
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.get_agent("agent_abc123")

    assert exc_info.value.code == "NETWORK_ERROR"
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@respx.mock
async def test_context_manager_closes_client(
    agent_response: dict,  # type: ignore[type-arg]
) -> None:
    respx.get(f"{BASE_URL}/v1/agents/agent_abc123").mock(
        return_value=Response(200, json=agent_response)
    )

    async with IdentityClient(base_url=BASE_URL) as c:
        result = await c.get_agent("agent_abc123")

    assert result.agent_id == "agent_abc123"
