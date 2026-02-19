"""
AS2-CAMTC Scripts: Benchmark 5 scenarios x 100 runs (latency + tier distribution).
"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="[%(message)s]")
logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:5000")

SCENARIOS = [
    {"name": "cardiac_alert", "domain": "healthcare", "tx_type": "cardiac_alert", "expected_tier": 1,
     "payload": {"urgency": 0.95, "value": 0.8, "reputation": 0.9, "latency_sensitivity": 0.95, "data": {"patient_id": "P_BENCH"}}},
    {"name": "hft_order", "domain": "finance", "tx_type": "hft", "expected_tier": 1,
     "payload": {"urgency": 0.7, "value": 0.95, "reputation": 0.9, "latency_sensitivity": 0.95, "data": {"order_id": "HFT_BENCH"}}},
    {"name": "fire_alarm", "domain": "iot", "tx_type": "fire", "expected_tier": 1,
     "payload": {"urgency": 0.98, "value": 0.3, "reputation": 0.85, "latency_sensitivity": 0.95, "data": {"sensor_id": "FIRE_BENCH"}}},
    {"name": "medication_order", "domain": "healthcare", "tx_type": "medication_order", "expected_tier": 2,
     "payload": {"urgency": 0.5, "value": 0.6, "reputation": 0.8, "latency_sensitivity": 0.5, "data": {"patient_id": "P_MED"}}},
    {"name": "vitals_log", "domain": "healthcare", "tx_type": "vitals_log", "expected_tier": 3,
     "payload": {"urgency": 0.2, "value": 0.3, "reputation": 0.7, "latency_sensitivity": 0.3, "data": {"patient_id": "P_VIT"}}},
]


async def run_one(scenario: dict, run: int) -> tuple:
    payload = {"domain": scenario["domain"], "tx_type": scenario["tx_type"], **scenario["payload"]}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{GATEWAY_URL}/submit", json=payload)
            r.raise_for_status()
            body = r.json()
    except Exception as e:
        return (run, None, None, str(e))
    latency_ms = (time.perf_counter() - t0) * 1000
    tier = body.get("tier")
    return (run, latency_ms, tier, None)


async def run_scenario(scenario: dict, n: int = 100) -> dict:
    results = []
    for i in range(n):
        _, lat, tier, err = await run_one(scenario, i)
        results.append((lat, tier, err))
    latencies = [r[0] for r in results if r[0] is not None]
    tiers = [r[1] for r in results if r[1] is not None]
    errors = sum(1 for r in results if r[2] is not None)
    tier_dist = {1: 0, 2: 0, 3: 0}
    for t in tiers:
        tier_dist[t] = tier_dist.get(t, 0) + 1
    if not latencies:
        return {"name": scenario["name"], "expected_tier": scenario["expected_tier"], "mean_ms": 0, "median_ms": 0, "p95_ms": 0, "min_ms": 0, "max_ms": 0, "tier_distribution": tier_dist, "errors": errors}
    latencies.sort()
    return {
        "name": scenario["name"],
        "expected_tier": scenario["expected_tier"],
        "mean_ms": sum(latencies) / len(latencies),
        "median_ms": latencies[len(latencies) // 2],
        "p95_ms": latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0],
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "tier_distribution": tier_dist,
        "errors": errors,
    }


def main():
    async def _main():
        print("Benchmark: 5 scenarios x 100 runs")
        print("GATEWAY_URL =", GATEWAY_URL)
        print()
        for sc in SCENARIOS:
            out = await run_scenario(sc, 100)
            print(f"Scenario: {out['name']} (expected tier {out['expected_tier']})")
            print(f"  Latency ms: mean={out['mean_ms']:.2f} median={out['median_ms']:.2f} p95={out['p95_ms']:.2f} min={out['min_ms']:.2f} max={out['max_ms']:.2f}")
            print(f"  Tier distribution: {out['tier_distribution']} | errors={out['errors']}")
            print()
        return 0
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
