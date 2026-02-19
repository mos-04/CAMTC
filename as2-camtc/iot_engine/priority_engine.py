"""
AS2-CAMTC IoT Engine: Priority computation (ML + context + sensor reputation).
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from context_engine import ContextEngine
from reputation import SensorReputation

logger = logging.getLogger(__name__)


def _assign_tier(priority: float) -> int:
    if priority > 0.85:
        return 1
    if priority > 0.60:
        return 2
    return 3


def _base_urgency_from_raw(sensor_type: str, raw: dict) -> float:
    st = (sensor_type or "").lower()
    if st == "fire":
        smoke = raw.get("smoke_level", 0) or 0
        temp = raw.get("temperature", 20) or 20
        temp_norm = min(1.0, (temp - 15) / 45)
        return min(1.0, smoke * 0.7 + temp_norm * 0.3)
    if st == "gas":
        co = raw.get("ppm_co", 0) or 0
        return min(1.0, co / 1000)
    if st == "temperature":
        t = raw.get("temp_c", 20) or 20
        return min(1.0, (t - 15) / 35)
    if st == "traffic":
        acc = 1.0 if raw.get("accident_detected") else 0.0
        count = raw.get("vehicle_count", 0) or 0
        return min(1.0, acc * 0.7 + min(1.0, count / 200) * 0.3)
    if st in ("motion", "smoke", "flood", "wind", "vibration", "air_quality"):
        keys = list(raw.keys())
        v = sum((raw.get(k) or 0) for k in keys if isinstance(raw.get(k), (int, float))) / max(1, len(keys))
        return min(1.0, v) if isinstance(v, (int, float)) else 0.5
    return 0.5


@dataclass
class PriorityResult:
    final_priority: float
    tier: int
    ml_priority: float
    context_factor: float
    sensor_rep: float


class PriorityEngine:
    def __init__(self, ml_url: str, reputation: SensorReputation, context: ContextEngine):
        self.ml_url = ml_url.rstrip("/")
        self.reputation = reputation
        self.context = context

    async def compute(
        self,
        sensor_id: str,
        sensor_type: str,
        raw_data: dict,
        location: str,
        time_of_day: Optional[int] = None,
    ) -> PriorityResult:
        import datetime
        if time_of_day is None:
            time_of_day = datetime.datetime.now().hour
        base_urgency = _base_urgency_from_raw(sensor_type, raw_data)
        context_factor = self.context.adjust_urgency(sensor_type, raw_data, base_urgency, time_of_day)
        urgency = min(1.0, base_urgency * context_factor)
        sensor_rep = self.reputation.get(sensor_id)

        ml_priority = 0.5
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(
                    f"{self.ml_url}/score",
                    json={
                        "domain": "iot",
                        "tx_type": sensor_type,
                        "urgency": urgency,
                        "value": 0.3,
                        "reputation": sensor_rep,
                        "latency_sensitivity": 0.8,
                        "data": {"sensor_id": sensor_id, "location": location},
                    },
                )
                if r.is_success:
                    body = r.json()
                    ml_priority = body.get("priority", 0.5)
        except Exception as e:
            logger.warning("[PRIORITY] ML call failed | error=%s", e)

        final_priority = ml_priority * 0.6 + urgency * 0.3 + sensor_rep * 0.1
        final_priority = max(0.0, min(1.0, final_priority))
        tier = _assign_tier(final_priority)
        return PriorityResult(
            final_priority=final_priority,
            tier=tier,
            ml_priority=ml_priority,
            context_factor=context_factor,
            sensor_rep=sensor_rep,
        )
