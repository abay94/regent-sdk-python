"""Shared pytest fixtures for SDK tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from regent.types import (
    AgentResponse,
    AlertResponse,
    AuditEventResponse,
    BatchResponse,
    MerkleProofResponse,
    RiskScoreResponse,
    ShapFactor,
    VerifyResponse,
)

NOW = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
AGENT_ID = "agent_abc123"
EVENT_ID = "evt_001"
BATCH_ID = str(uuid.uuid4())
MANDATE_ID = str(uuid.uuid4())
ALERT_ID = str(uuid.uuid4())


@pytest.fixture()
def agent_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": str(uuid.uuid4()),
        "agent_id": AGENT_ID,
        "responsible_party_id": "rp_xyz",
        "status": "active",
        "kyc_provider": "jumio",
        "kyc_reference": "jumio_ref_001",
        "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMFww...\n-----END PUBLIC KEY-----",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "activated_at": NOW.isoformat(),
        "revoked_at": None,
    }


@pytest.fixture()
def verify_response() -> dict:  # type: ignore[type-arg]
    return {
        "agent_id": AGENT_ID,
        "status": "active",
        "verified": True,
        "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMFww...\n-----END PUBLIC KEY-----",
        "checked_at": NOW.isoformat(),
    }


@pytest.fixture()
def audit_event_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": str(uuid.uuid4()),
        "event_id": EVENT_ID,
        "agent_id": AGENT_ID,
        "event_type": "payment.authorized",
        "payload_hash": "0x" + "ab" * 32,
        "status": "received",
        "batch_id": None,
        "merkle_index": None,
        "merkle_proof": None,
        "received_at": NOW.isoformat(),
        "anchored_at": None,
    }


@pytest.fixture()
def batch_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": BATCH_ID,
        "status": "anchored",
        "merkle_root": "0x" + "cd" * 32,
        "celestia_blob_id": "celestia_blob_abc",
        "arbitrum_tx_hash": "0x" + "ef" * 32,
        "event_count": 5,
        "created_at": NOW.isoformat(),
        "anchored_at": NOW.isoformat(),
    }


@pytest.fixture()
def merkle_proof_response() -> dict:  # type: ignore[type-arg]
    return {
        "event_id": EVENT_ID,
        "payload_hash": "0x" + "ab" * 32,
        "merkle_root": "0x" + "cd" * 32,
        "merkle_proof": ["0x" + "11" * 32, "0x" + "22" * 32],
        "verified": True,
    }


@pytest.fixture()
def risk_score_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": str(uuid.uuid4()),
        "agent_id": AGENT_ID,
        "score": 0.12,
        "features": {"tx_count_1h": 3.0, "amount_mean_1h": 150.0},
        "shap_factors": [{"feature": "tx_count_1h", "value": 0.05}],
        "model_version": "1.2",
        "scored_at": NOW.isoformat(),
        "trigger_event_id": EVENT_ID,
    }


@pytest.fixture()
def alert_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": ALERT_ID,
        "agent_id": AGENT_ID,
        "alert_type": "anomaly",
        "score": 0.91,
        "previous_score": 0.10,
        "message": "Risk score exceeded threshold",
        "status": "open",
        "risk_score_id": str(uuid.uuid4()),
        "created_at": NOW.isoformat(),
        "acknowledged_at": None,
    }


@pytest.fixture()
def mandate_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": MANDATE_ID,
        "agent_id": AGENT_ID,
        "owner_id": "owner_001",
        "status": "active",
        "currency": "USD",
        "limits": {"daily_limit": "1000.00", "monthly_limit": "10000.00", "per_tx_limit": "500.00"},
        "metadata": {},
        "created_at": NOW.isoformat(),
        "activated_at": NOW.isoformat(),
        "expires_at": None,
        "revoked_at": None,
    }


@pytest.fixture()
def authorization_response() -> dict:  # type: ignore[type-arg]
    return {
        "id": str(uuid.uuid4()),
        "mandate_id": MANDATE_ID,
        "agent_id": AGENT_ID,
        "amount": "250.00",
        "currency": "USD",
        "status": "authorized",
        "rejection_reason": None,
        "jwt_token": "eyJhbGciOiJSUzI1NiJ9.test.signature",
        "jti": str(uuid.uuid4()),
        "guardian_score": 0.12,
        "authorized_at": NOW.isoformat(),
    }
