"""
AS2-CAMTC Gateway: FastAPI app - submit tx via ML scoring, ledger, PBFT; optional contract sync.
"""
import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.block import Transaction
from blockchain.ledger import BlockchainLedger
from consensus.pbft import PBFTEngine
from consensus.reputation import ReputationEngine
from gateway.schemas import SubmitRequest, SubmitResponse
from integration.connector import BlockchainConnector

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("GATEWAY")

VALIDATORS = (
    [f"HC_V{i}" for i in range(1, 8)]
    + [f"FIN_V{i}" for i in range(1, 8)]
    + [f"IOT_V{i}" for i in range(1, 8)]
)
ML_SERVICE_URL = os.environ.get("ML_SERVICE_URL", "http://localhost:8000")
GANACHE_URL = os.environ.get("GANACHE_URL", "http://localhost:8545")

ledger: BlockchainLedger = None
connector: BlockchainConnector = None
_byzantine_ids: list = []

# --- Prometheus metrics ---
GW_TX_COUNT = Counter("gateway_tx_total", "Total transactions submitted", ["domain", "tier"])
GW_TX_LATENCY = Histogram("gateway_tx_latency_seconds", "End-to-end tx latency", ["domain"], buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5])
GW_BLOCKS_FINALIZED = Counter("gateway_blocks_finalized_total", "Total blocks finalized", ["tier"])
GW_CHAIN_HEIGHT = Gauge("gateway_chain_height", "Current blockchain height")
GW_MEMPOOL_SIZE = Gauge("gateway_mempool_size", "Mempool queue size", ["tier"])


def on_block_finalized(block, cr):
    logger.info("[CHAIN] Block finalized | height=%s | tier=%s | txs=%s", block.index, block.tier, len(block.transactions))
    if connector:
        try:
            connector.process_finalized_block(block, cr)
        except Exception as e:
            logger.exception("[GATEWAY] connector error | error=%s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ledger, connector
    reputation = ReputationEngine(VALIDATORS)
    pbft = PBFTEngine(
        node_id="GATEWAY",
        reputation=reputation,
        on_block_finalized=on_block_finalized,
        validator_ids=VALIDATORS,
        byzantine_node_ids=_byzantine_ids,
    )
    ledger = BlockchainLedger(
        node_id="GATEWAY",
        validator_ids=VALIDATORS,
        byzantine_ids=_byzantine_ids,
        on_block_callback=on_block_finalized,
    )
    ledger.set_reputation(reputation)
    ledger.set_pbft(pbft)
    connector = BlockchainConnector(ganache_url=GANACHE_URL)
    await ledger.start()
    logger.info("[GATEWAY] ledger started | validators=%d", len(VALIDATORS))
    yield
    await ledger.stop()
    ledger = None
    connector = None


app = FastAPI(title="AS2-CAMTC Gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/submit", response_model=SubmitResponse)
async def submit(req: SubmitRequest):
    t0 = time.perf_counter()
    tx_id = str(uuid.uuid4())[:8].upper()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{ML_SERVICE_URL}/score",
                json={
                    "domain": req.domain,
                    "tx_type": req.tx_type,
                    "urgency": req.urgency,
                    "value": req.value,
                    "reputation": req.reputation,
                    "latency_sensitivity": req.latency_sensitivity,
                    "data": req.data,
                },
            )
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPError as e:
        logger.exception("[GATEWAY] ML score failed | error=%s", e)
        raise HTTPException(status_code=502, detail=f"ML service error: {e}")
    except Exception as e:
        logger.exception("[GATEWAY] submit error | error=%s", e)
        raise HTTPException(status_code=500, detail=str(e))

    priority = body.get("priority", 0.5)
    tier = body.get("tier", 2)
    ml_latency_ms = body.get("latency_ms", 0.0)
    explanation = body.get("explanation", {})

    tx = Transaction(
        tx_id=tx_id,
        domain=req.domain,
        tx_type=req.tx_type,
        urgency=req.urgency,
        value=req.value,
        sender_reputation=req.reputation,
        latency_sensitivity=req.latency_sensitivity,
        priority_score=priority,
        tier=tier,
        timestamp=time.time(),
        data=req.data,
        sender_id=req.sender_id or "gateway",
    )
    await ledger.submit_transaction(tx)
    total_ms = (time.perf_counter() - t0) * 1000
    GW_TX_COUNT.labels(domain=req.domain, tier=str(tier)).inc()
    GW_TX_LATENCY.labels(domain=req.domain).observe(total_ms / 1000)
    return SubmitResponse(
        tx_id=tx_id,
        priority=priority,
        tier=tier,
        ml_latency_ms=ml_latency_ms,
        total_latency_ms=round(total_ms, 2),
        explanation=explanation,
    )


@app.get("/metrics")
async def metrics():
    stats = ledger.get_stats()
    GW_CHAIN_HEIGHT.set(stats.get("total_blocks", 0))
    sizes = ledger.mempool.all_sizes()
    for t in [1, 2, 3]:
        GW_MEMPOOL_SIZE.labels(tier=str(t)).set(sizes.get(t, sizes.get(str(t), 0)))
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/chain")
async def get_chain(last_n: int = 20):
    return ledger.get_chain(last_n=last_n)


@app.get("/stats")
async def get_stats():
    return ledger.get_stats()


@app.get("/mempool")
async def get_mempool():
    return ledger.mempool.all_sizes()


@app.get("/reputation")
async def get_reputation():
    return ledger.reputation.get_all()


@app.get("/consensus-rounds")
async def get_consensus_rounds():
    return ledger.pbft.get_round_stats()


@app.post("/simulate/byzantine")
async def simulate_byzantine(validator_id: str = ""):
    if validator_id:
        _byzantine_ids.append(validator_id)
    return {"injected": validator_id, "byzantine_list": list(_byzantine_ids)}


@app.post("/simulate/healthcare")
async def simulate_healthcare_bulk():
    results = []
    for i in range(20):
        req = SubmitRequest(
            domain="healthcare",
            tx_type=["cardiac_alert", "medication_order", "vitals_log"][i % 3],
            urgency=0.5 + i * 0.02,
            value=0.6,
            reputation=0.85,
            latency_sensitivity=0.7,
            data={"patient_id": f"P{i}"},
        )
        try:
            r = await submit(req)
            results.append({"tx_id": r.tx_id, "tier": r.tier, "priority": r.priority})
        except Exception as e:
            results.append({"error": str(e)})
    return {"submitted": len(results), "results": results}


@app.post("/simulate/finance")
async def simulate_finance_bulk():
    results = []
    for i in range(20):
        req = SubmitRequest(
            domain="finance",
            tx_type=["hft", "limit", "settlement"][i % 3],
            urgency=0.4,
            value=0.5 + i * 0.02,
            reputation=0.8,
            latency_sensitivity=0.6,
            data={"order_id": f"ORD{i}"},
        )
        try:
            r = await submit(req)
            results.append({"tx_id": r.tx_id, "tier": r.tier, "priority": r.priority})
        except Exception as e:
            results.append({"error": str(e)})
    return {"submitted": len(results), "results": results}


@app.post("/simulate/iot")
async def simulate_iot_bulk():
    results = []
    for i in range(20):
        req = SubmitRequest(
            domain="iot",
            tx_type=["fire", "gas", "temperature", "traffic", "motion"][i % 5],
            urgency=0.6,
            value=0.3,
            reputation=0.75,
            latency_sensitivity=0.8,
            data={"sensor_id": f"S{i}"},
        )
        try:
            r = await submit(req)
            results.append({"tx_id": r.tx_id, "tier": r.tier, "priority": r.priority})
        except Exception as e:
            results.append({"error": str(e)})
    return {"submitted": len(results), "results": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
