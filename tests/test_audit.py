"""Tests for AuditClient against a mock server."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from regent import AuditClient, IngestEventRequest
from regent.errors import RegentAPIError, RegentNetworkError

BASE_URL = "http://api-audit"


@pytest.fixture()
def client() -> AuditClient:
    return AuditClient(base_url=BASE_URL)


# ---------------------------------------------------------------------------
# ingest_event()
# ---------------------------------------------------------------------------


@respx.mock
async def test_ingest_event_posts_and_returns_model(
    client: AuditClient, audit_event_response: dict  # type: ignore[type-arg]
) -> None:
    route = respx.post(f"{BASE_URL}/v1/audit/events").mock(
        return_value=Response(201, json=audit_event_response)
    )

    req = IngestEventRequest(
        event_id="evt_001",
        agent_id="agent_abc123",
        event_type="payment.authorized",
        payload={"amount": "100.00"},
        metadata={},
    )
    result = await client.ingest_event(req)

    assert route.called
    assert result.event_id == "evt_001"
    assert result.status == "received"
    assert result.batch_id is None


@respx.mock
async def test_ingest_event_idempotent_200(
    client: AuditClient, audit_event_response: dict  # type: ignore[type-arg]
) -> None:
    respx.post(f"{BASE_URL}/v1/audit/events").mock(
        return_value=Response(200, json=audit_event_response)
    )

    req = IngestEventRequest(event_id="evt_001", agent_id="agent_abc123", event_type="t")
    result = await client.ingest_event(req)

    assert result.event_id == "evt_001"


# ---------------------------------------------------------------------------
# get_event()
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_event_returns_model(
    client: AuditClient, audit_event_response: dict  # type: ignore[type-arg]
) -> None:
    respx.get(f"{BASE_URL}/v1/audit/events/evt_001").mock(
        return_value=Response(200, json=audit_event_response)
    )

    result = await client.get_event("evt_001")

    assert result.event_id == "evt_001"
    assert result.agent_id == "agent_abc123"


@respx.mock
async def test_get_event_raises_event_not_found(client: AuditClient) -> None:
    respx.get(f"{BASE_URL}/v1/audit/events/missing").mock(
        return_value=Response(
            404, json={"code": "EVENT_NOT_FOUND", "message": "No event with ID missing"}
        )
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.get_event("missing")

    assert exc_info.value.code == "EVENT_NOT_FOUND"
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_agent_events()
# ---------------------------------------------------------------------------


@respx.mock
async def test_list_agent_events_returns_list(
    client: AuditClient, audit_event_response: dict  # type: ignore[type-arg]
) -> None:
    respx.get(f"{BASE_URL}/v1/audit/agents/agent_abc123/events").mock(
        return_value=Response(200, json=[audit_event_response])
    )

    results = await client.list_agent_events("agent_abc123")

    assert len(results) == 1
    assert results[0].event_id == "evt_001"


@respx.mock
async def test_list_agent_events_sends_pagination_params(
    client: AuditClient,
) -> None:
    route = respx.get(f"{BASE_URL}/v1/audit/agents/agent_abc123/events").mock(
        return_value=Response(200, json=[])
    )

    await client.list_agent_events("agent_abc123", limit=10, offset=20)

    request_url = str(route.calls[0].request.url)
    assert "limit=10" in request_url
    assert "offset=20" in request_url


@respx.mock
async def test_list_agent_events_omits_none_params(client: AuditClient) -> None:
    route = respx.get(f"{BASE_URL}/v1/audit/agents/agent_abc123/events").mock(
        return_value=Response(200, json=[])
    )

    await client.list_agent_events("agent_abc123")

    assert "limit" not in str(route.calls[0].request.url)
    assert "offset" not in str(route.calls[0].request.url)


# ---------------------------------------------------------------------------
# get_batch()
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_batch_returns_model(
    client: AuditClient, batch_response: dict  # type: ignore[type-arg]
) -> None:
    batch_id = batch_response["id"]
    respx.get(f"{BASE_URL}/v1/audit/batches/{batch_id}").mock(
        return_value=Response(200, json=batch_response)
    )

    result = await client.get_batch(batch_id)

    assert result.status == "anchored"
    assert result.event_count == 5


@respx.mock
async def test_get_batch_raises_batch_not_found(client: AuditClient) -> None:
    respx.get(f"{BASE_URL}/v1/audit/batches/missing").mock(
        return_value=Response(
            404, json={"code": "BATCH_NOT_FOUND", "message": "No batch with ID missing"}
        )
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.get_batch("missing")

    assert exc_info.value.code == "BATCH_NOT_FOUND"


# ---------------------------------------------------------------------------
# verify_event()
# ---------------------------------------------------------------------------


@respx.mock
async def test_verify_event_returns_proof(
    client: AuditClient, merkle_proof_response: dict  # type: ignore[type-arg]
) -> None:
    respx.post(f"{BASE_URL}/v1/audit/verify/evt_001").mock(
        return_value=Response(200, json=merkle_proof_response)
    )

    result = await client.verify_event("evt_001")

    assert result.verified is True
    assert len(result.merkle_proof) == 2


@respx.mock
async def test_verify_event_raises_not_yet_anchored(client: AuditClient) -> None:
    respx.post(f"{BASE_URL}/v1/audit/verify/evt_pending").mock(
        return_value=Response(
            409,
            json={"code": "NOT_YET_ANCHORED", "message": "Event has not been batched yet"},
        )
    )

    with pytest.raises(RegentAPIError) as exc_info:
        await client.verify_event("evt_pending")

    assert exc_info.value.code == "NOT_YET_ANCHORED"
    assert exc_info.value.status_code == 409


@respx.mock
async def test_verify_event_raises_event_not_found(client: AuditClient) -> None:
    respx.post(f"{BASE_URL}/v1/audit/verify/missing").mock(
        return_value=Response(404, json={"code": "EVENT_NOT_FOUND", "message": "Not found"})
    )

    with pytest.raises(RegentAPIError):
        await client.verify_event("missing")


# ---------------------------------------------------------------------------
# Network error handling
# ---------------------------------------------------------------------------


@respx.mock
async def test_network_error_raises_regent_network_error(client: AuditClient) -> None:
    import httpx

    respx.get(f"{BASE_URL}/v1/audit/events/evt_001").mock(
        side_effect=httpx.NetworkError("Connection refused")
    )

    with pytest.raises(RegentNetworkError):
        await client.get_event("evt_001")


@respx.mock
async def test_timeout_raises_regent_network_error(client: AuditClient) -> None:
    import httpx

    respx.post(f"{BASE_URL}/v1/audit/events").mock(
        side_effect=httpx.TimeoutException("Timed out")
    )

    with pytest.raises(RegentNetworkError):
        await client.ingest_event(
            IngestEventRequest(event_id="e", agent_id="a", event_type="t")
        )
