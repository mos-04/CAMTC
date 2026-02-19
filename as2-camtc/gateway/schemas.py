"""
AS2-CAMTC Gateway: Pydantic schemas for API.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SubmitRequest(BaseModel):
    domain: str = Field(..., description="healthcare | finance | iot")
    tx_type: str = Field(..., description="e.g. cardiac_alert, hft, fire")
    urgency: float = Field(0.5, ge=0.0, le=1.0)
    value: float = Field(0.5, ge=0.0, le=1.0)
    reputation: float = Field(0.8, ge=0.0, le=1.0)
    latency_sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    data: Dict[str, Any] = Field(default_factory=dict)
    sender_id: Optional[str] = None


class SubmitResponse(BaseModel):
    tx_id: str
    priority: float
    tier: int
    ml_latency_ms: float
    total_latency_ms: float
    explanation: dict
