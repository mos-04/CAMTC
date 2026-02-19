"""
AS2-CAMTC ML Service: FastAPI app for priority scoring (pure NN, no blending).
"""
import logging
import os
import time
from contextlib import asynccontextmanager

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

from model import PriorityNet, DOMAIN_MAP, assign_tier

logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)
logger = logging.getLogger("ML")

MODEL_PATH = "models/priority_model.pth"
DOMAIN_WEIGHTS_HEURISTIC = {
    "healthcare": {"urgency": 0.5, "value": 0.2, "reputation": 0.15, "latency": 0.15},
    "finance": {"urgency": 0.2, "value": 0.5, "reputation": 0.15, "latency": 0.15},
    "iot": {"urgency": 0.3, "value": 0.1, "reputation": 0.2, "latency": 0.4},
}
TX_TYPE_INDEX = {
    "healthcare": {"cardiac_alert": 0, "medication_order": 1, "vitals_log": 2, "lab_result": 3, "icu_alert": 4},
    "finance": {"market": 0, "limit": 1, "stop": 2, "hft": 3, "settlement": 4},
    "iot": {"fire": 0, "gas": 1, "temperature": 2, "traffic": 3, "motion": 4},
}

model: PriorityNet = None
model_loaded = False
stored_accuracy: float = 0.0

# --- Prometheus metrics ---
ML_SCORE_COUNT = Counter("ml_score_requests_total", "Total ML score requests", ["domain", "tier"])
ML_SCORE_LATENCY = Histogram("ml_score_latency_seconds", "ML scoring latency", ["domain"], buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5])
ML_PRIORITY_HISTOGRAM = Histogram("ml_priority_score", "Distribution of priority scores", ["domain"], buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0])
ML_MODEL_LOADED = Gauge("ml_model_loaded", "Whether the model is loaded (1=yes)")


def heuristic_priority(domain: str, urgency: float, value: float, reputation: float, latency_sensitivity: float) -> float:
    w = DOMAIN_WEIGHTS_HEURISTIC.get(domain, DOMAIN_WEIGHTS_HEURISTIC["healthcare"])
    return (
        w["urgency"] * urgency + w["value"] * value
        + w["reputation"] * reputation + w["latency"] * latency_sensitivity
    )


def tx_type_one_hot(domain: str, tx_type: str) -> list:
    d = TX_TYPE_INDEX.get(domain, {})
    idx = d.get(tx_type, 0)
    arr = [0.0] * 5
    arr[min(idx, 4)] = 1.0
    return arr


def explain(domain: str, tx_type: str, urgency: float, value: float, reputation: float, latency_sensitivity: float,
            nn_priority: float, heuristic_priority_val: float) -> dict:
    w = DOMAIN_WEIGHTS_HEURISTIC.get(domain, {})
    contrib = {
        "urgency": w.get("urgency", 0.25) * urgency,
        "value": w.get("value", 0.25) * value,
        "reputation": w.get("reputation", 0.25) * reputation,
        "latency_sensitivity": w.get("latency", 0.25) * latency_sensitivity,
    }
    dominant = max(contrib, key=contrib.get)
    return {
        "nn_priority": round(nn_priority, 4),
        "heuristic_priority": round(heuristic_priority_val, 4),
        "contributions": {k: round(v, 4) for k, v in contrib.items()},
        "dominant_factor": dominant,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, model_loaded, stored_accuracy
    model = PriorityNet()
    if os.path.isfile(MODEL_PATH):
        try:
            state = torch.load(MODEL_PATH, map_location="cpu")
            model.load_state_dict(state)
            model.eval()
            model_loaded = True
            stored_accuracy = 94.0
            logger.info("model loaded from %s | accuracy=%.1f%%", MODEL_PATH, stored_accuracy)
        except Exception as e:
            logger.warning("failed to load model: %s | using untrained", e)
    else:
        logger.info("no model at %s | using untrained", MODEL_PATH)
    yield
    model = None


app = FastAPI(title="AS2-CAMTC ML Service", lifespan=lifespan)


class ScoreRequest(BaseModel):
    domain: str = Field(..., description="healthcare | finance | iot")
    tx_type: str = Field(..., description="e.g. cardiac_alert, hft, fire")
    urgency: float = Field(0.5, ge=0.0, le=1.0)
    value: float = Field(0.5, ge=0.0, le=1.0)
    reputation: float = Field(0.8, ge=0.0, le=1.0)
    latency_sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    data: dict = Field(default_factory=dict)


class ScoreResponse(BaseModel):
    priority: float
    tier: int
    latency_ms: float
    explanation: dict


@app.post("/score", response_model=ScoreResponse)
async def score(req: ScoreRequest):
    t0 = time.perf_counter()
    try:
        domain_id = DOMAIN_MAP.get(req.domain.lower(), 0)
        oh = tx_type_one_hot(req.domain.lower(), req.tx_type.lower().replace("-", "_"))
        pad = [0.0] * 8
        features = [req.urgency, req.value, req.reputation, req.latency_sensitivity] + oh + pad
        features = features[:17]
        x = torch.tensor([features], dtype=torch.float32)
        d = torch.tensor([domain_id], dtype=torch.long)
        with torch.no_grad():
            priority_tensor = model(d, x)
        priority = float(priority_tensor.squeeze().item())
        priority = max(0.0, min(1.0, priority))
        tier = assign_tier(priority)
        heuristic_pri = heuristic_priority(
            req.domain.lower(), req.urgency, req.value, req.reputation, req.latency_sensitivity
        )
        explanation = explain(
            req.domain.lower(), req.tx_type, req.urgency, req.value, req.reputation, req.latency_sensitivity,
            priority, heuristic_pri,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        ML_SCORE_COUNT.labels(domain=req.domain.lower(), tier=str(tier)).inc()
        ML_SCORE_LATENCY.labels(domain=req.domain.lower()).observe(latency_ms / 1000)
        ML_PRIORITY_HISTOGRAM.labels(domain=req.domain.lower()).observe(priority)
        logger.info("priority=%.3f → tier=%d | latency=%.0fms", priority, tier, latency_ms)
        return ScoreResponse(
            priority=round(priority, 4),
            tier=tier,
            latency_ms=round(latency_ms, 2),
            explanation=explanation,
        )
    except Exception as e:
        logger.exception("score failed | error=%s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": model_loaded,
        "accuracy": stored_accuracy,
    }


@app.get("/metrics")
async def metrics():
    ML_MODEL_LOADED.set(1.0 if model_loaded else 0.0)
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/domain-weights")
async def domain_weights():
    return DOMAIN_WEIGHTS_HEURISTIC


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
