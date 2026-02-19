"""
AS2-CAMTC IoT Engine: FastAPI app - sensor tasks, priority, gateway submit, alerts.
"""
import asyncio
import logging
import os
import random
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

from config import SENSORS
from context_engine import ContextEngine
from priority_engine import PriorityEngine
from reputation import SensorReputation
from sensors import SensorData, generate_reading

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("IOT")

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:5000")
ML_SERVICE_URL = os.environ.get("ML_SERVICE_URL", "http://localhost:8000")

sensor_reputation: SensorReputation = None
context_engine: ContextEngine = None
priority_engine: PriorityEngine = None
_alerts: deque = deque(maxlen=50)
_tx_per_sensor: dict = {}
_sensor_tasks: list = []

# --- Prometheus metrics ---
IOT_TX_COUNT = Counter("iot_tx_total", "Total IoT transactions submitted", ["sensor_type"])
IOT_ALERTS_COUNT = Counter("iot_alerts_total", "Total IoT alerts generated", ["sensor_type"])
IOT_SENSOR_REPUTATION = Gauge("iot_sensor_reputation", "Sensor reputation scores", ["sensor_id"])
IOT_SUBMIT_LATENCY = Histogram("iot_submit_latency_seconds", "Gateway submission latency", buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5])


class SensorDataRequest(BaseModel):
    sensor_id: str
    sensor_type: str
    raw_data: dict
    location: str = "unknown"


def _assign_tier(p: float) -> int:
    if p > 0.85:
        return 1
    if p > 0.60:
        return 2
    return 3


async def _submit_to_gateway(domain: str, tx_type: str, urgency: float, value: float, reputation: float, latency_sensitivity: float, data: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{GATEWAY_URL}/submit",
                json={
                    "domain": domain,
                    "tx_type": tx_type,
                    "urgency": urgency,
                    "value": value,
                    "reputation": reputation,
                    "latency_sensitivity": latency_sensitivity,
                    "data": data,
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("[IOT] gateway submit failed | error=%s", e)
        return {"error": str(e)}


async def _sensor_loop(sensor_id: str, cfg: dict):
    interval_s = cfg["interval_ms"] / 1000.0
    normal_prob = cfg["normal_prob"]
    sensor_type = cfg["type"]
    location = cfg.get("location", "unknown")
    while True:
        try:
            is_alert = random.random() > normal_prob
            data = generate_reading(sensor_id, sensor_type, is_alert=is_alert)
            result = await priority_engine.compute(sensor_id, sensor_type, data.raw, location)
            rep = sensor_reputation.get(sensor_id)
            gw = await _submit_to_gateway(
                domain="iot",
                tx_type=sensor_type,
                urgency=result.final_priority,
                value=0.3,
                reputation=rep,
                latency_sensitivity=0.8,
                data={
                    "sensor_id": sensor_id,
                    "location": location,
                    "data_hash": data.data_hash,
                    "is_alert": data.is_alert,
                },
            )
            if "error" not in gw:
                _tx_per_sensor[sensor_id] = _tx_per_sensor.get(sensor_id, 0) + 1
                IOT_TX_COUNT.labels(sensor_type=sensor_type).inc()
                if data.is_alert:
                    _alerts.append({"sensor_id": sensor_id, "type": sensor_type, "time": time.time(), "tier": result.tier})
                    IOT_ALERTS_COUNT.labels(sensor_type=sensor_type).inc()
                    sensor_reputation.reward(sensor_id)
                else:
                    sensor_reputation.reward(sensor_id)
            else:
                sensor_reputation.penalize(sensor_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("[IOT] sensor_loop %s | error=%s", sensor_id, e)
            sensor_reputation.penalize(sensor_id)
        await asyncio.sleep(interval_s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sensor_reputation, context_engine, priority_engine, _sensor_tasks
    sensor_ids = list(SENSORS.keys())
    sensor_reputation = SensorReputation(sensor_ids)
    context_engine = ContextEngine()
    priority_engine = PriorityEngine(ML_SERVICE_URL, sensor_reputation, context_engine)
    _sensor_tasks = [asyncio.create_task(_sensor_loop(sid, SENSORS[sid])) for sid in sensor_ids]
    logger.info("[IOT] started %d sensor tasks", len(_sensor_tasks))
    yield
    for t in _sensor_tasks:
        t.cancel()
    await asyncio.gather(*_sensor_tasks, return_exceptions=True)


app = FastAPI(title="AS2-CAMTC IoT Engine", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/sensor/{sensor_id}/data")
async def sensor_data(sensor_id: str, body: SensorDataRequest):
    if sensor_id != body.sensor_id:
        raise HTTPException(400, "sensor_id mismatch")
    result = await priority_engine.compute(body.sensor_id, body.sensor_type, body.raw_data, body.location)
    gw = await _submit_to_gateway(
        domain="iot",
        tx_type=body.sensor_type,
        urgency=result.final_priority,
        value=0.3,
        reputation=sensor_reputation.get(body.sensor_id),
        latency_sensitivity=0.8,
        data={"sensor_id": body.sensor_id, "location": body.location},
    )
    return {"priority_result": {"final_priority": result.final_priority, "tier": result.tier}, "gateway": gw}


@app.post("/simulate/fire")
async def simulate_fire():
    sensor_id = "FIRE_001"
    data = generate_reading(sensor_id, "fire", is_alert=True)
    data.raw["smoke_level"] = 0.95
    data.raw["temperature"] = 48.0
    result = await priority_engine.compute(sensor_id, "fire", data.raw, "Building B")
    gw = await _submit_to_gateway(
        domain="iot",
        tx_type="fire",
        urgency=result.final_priority,
        value=0.3,
        reputation=sensor_reputation.get(sensor_id),
        latency_sensitivity=0.8,
        data={"sensor_id": sensor_id, "location": "Building B", "is_alert": True},
    )
    _alerts.append({"sensor_id": sensor_id, "type": "fire", "time": time.time(), "tier": result.tier})
    return {"alert": "fire", "tier": result.tier, "gateway": gw}


@app.get("/sensors")
async def get_sensors():
    out = []
    for sid, cfg in SENSORS.items():
        out.append({
            "sensor_id": sid,
            "type": cfg["type"],
            "location": cfg.get("location", ""),
            "reputation": sensor_reputation.get(sid),
            "tx_count": _tx_per_sensor.get(sid, 0),
        })
    return out


@app.get("/alerts")
async def get_alerts():
    return list(_alerts)


@app.get("/metrics")
async def metrics():
    if sensor_reputation:
        for sid in SENSORS:
            IOT_SENSOR_REPUTATION.labels(sensor_id=sid).set(sensor_reputation.get(sid))
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stats")
async def get_stats():
    tier_counts = {1: 0, 2: 0, 3: 0}
    for a in _alerts:
        t = a.get("tier", 2)
        tier_counts[t] = tier_counts.get(t, 0) + 1
    return {
        "tx_per_sensor": dict(_tx_per_sensor),
        "alerts_per_type": {},
        "avg_latency_per_tier": {},
        "tier_distribution": tier_counts,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
