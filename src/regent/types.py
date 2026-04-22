"""Public Pydantic models for all Regent Protocol API request and response types."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Identity types
# ---------------------------------------------------------------------------


class RegisterAgentRequest(BaseModel):
    responsible_party_id: str
    settlement_chain: str = "solana"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    id: uuid.UUID
    agent_id: str
    did: str | None = None
    responsible_party_id: str
    status: str
    settlement_chain: str = "solana"
    kyc_provider: str | None = None
    kyc_reference: str | None = None
    public_key_pem: str | None = None
    identity_payload: str | None = None
    identity_signature: str | None = None
    onchain_status: str = "pending"
    solana_tx: str | None = None
    solana_revoke_tx: str | None = None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    revoked_at: datetime | None = None


class VerifyResponse(BaseModel):
    agent_id: str
    did: str | None = None
    status: str
    verified: bool
    public_key_pem: str | None = None
    checked_at: datetime


# ---------------------------------------------------------------------------
# Audit types
# ---------------------------------------------------------------------------


class IngestEventRequest(BaseModel):
    event_id: str = Field(max_length=64, description="Idempotency key")
    agent_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    event_id: str
    agent_id: str
    event_type: str
    payload_hash: str
    status: str
    batch_id: uuid.UUID | None
    merkle_index: int | None
    merkle_proof: list[str] | None
    received_at: datetime
    anchored_at: datetime | None


class BatchResponse(BaseModel):
    id: uuid.UUID
    status: str
    merkle_root: str | None
    celestia_blob_id: str | None
    arbitrum_tx_hash: str | None
    event_count: int
    created_at: datetime
    anchored_at: datetime | None


class MerkleProofResponse(BaseModel):
    event_id: str
    payload_hash: str
    merkle_root: str
    merkle_proof: list[str]
    verified: bool


# ---------------------------------------------------------------------------
# Guardian types
# ---------------------------------------------------------------------------


class ShapFactor(BaseModel):
    feature: str
    value: float


class RiskScoreResponse(BaseModel):
    id: uuid.UUID
    agent_id: str
    score: float
    features: dict[str, float]
    shap_factors: list[ShapFactor]
    model_version: str
    scored_at: datetime
    trigger_event_id: str | None


class AlertResponse(BaseModel):
    id: uuid.UUID
    agent_id: str
    alert_type: str
    score: float
    previous_score: float | None
    message: str
    status: str
    risk_score_id: uuid.UUID
    created_at: datetime
    acknowledged_at: datetime | None


class ModelInfoResponse(BaseModel):
    model_filename: str
    explainer_filename: str
    artifacts_dir: str
    alert_threshold: float
    drift_threshold: float


# ---------------------------------------------------------------------------
# Payment types
# ---------------------------------------------------------------------------


class MandateLimits(BaseModel):
    daily_limit: Decimal | None = None
    monthly_limit: Decimal | None = None
    per_tx_limit: Decimal | None = None


class CreateMandateRequest(BaseModel):
    agent_id: str
    owner_id: str
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 currency code")
    limits: MandateLimits = Field(default_factory=MandateLimits)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MandateResponse(BaseModel):
    id: uuid.UUID
    agent_id: str
    owner_id: str
    status: str
    currency: str
    limits: MandateLimits
    metadata: dict[str, Any]
    created_at: datetime
    activated_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class AuthorizeRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    idempotency_key: str | None = None


class AuthorizationResponse(BaseModel):
    id: uuid.UUID
    mandate_id: uuid.UUID
    agent_id: str
    amount: Decimal
    currency: str
    status: Literal["authorized", "rejected"]
    rejection_reason: str | None
    jwt_token: str | None
    jti: str | None
    guardian_score: float | None
    authorized_at: datetime
