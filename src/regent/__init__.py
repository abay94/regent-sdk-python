"""Regent Protocol Python SDK.

Provides async clients for all four Regent API services and typed
Pydantic models for every request and response.

Quick start::

    from regent import IdentityClient, RegisterAgentRequest

    async with IdentityClient(base_url="http://api-identity") as client:
        agent = await client.register(
            RegisterAgentRequest(
                responsible_party_id="rp_xyz",
                kyc_provider="jumio",
                metadata={"region": "EU"},
            )
        )
        print(agent.agent_id)
"""

from .client import RegentClient
from .clients import AuditClient, GuardianClient, IdentityClient, PaymentClient
from .errors import RegentAPIError, RegentError, RegentNetworkError
from .types import (
    AgentResponse,
    AlertResponse,
    AuditEventResponse,
    AuthorizationResponse,
    AuthorizeRequest,
    BatchResponse,
    CreateMandateRequest,
    IngestEventRequest,
    MandateLimits,
    MandateResponse,
    MerkleProofResponse,
    ModelInfoResponse,
    RegisterAgentRequest,
    RiskScoreResponse,
    ShapFactor,
    VerifyResponse,
)

__all__ = [
    # Unified client
    "RegentClient",
    # Individual clients
    "IdentityClient",
    "AuditClient",
    "GuardianClient",
    "PaymentClient",
    # Errors
    "RegentError",
    "RegentAPIError",
    "RegentNetworkError",
    # Types — Identity
    "RegisterAgentRequest",
    "AgentResponse",
    "VerifyResponse",
    # Types — Audit
    "IngestEventRequest",
    "AuditEventResponse",
    "BatchResponse",
    "MerkleProofResponse",
    # Types — Guardian
    "ShapFactor",
    "RiskScoreResponse",
    "AlertResponse",
    "ModelInfoResponse",
    # Types — Payment
    "MandateLimits",
    "CreateMandateRequest",
    "MandateResponse",
    "AuthorizeRequest",
    "AuthorizationResponse",
]
