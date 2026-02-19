# AS2-CAMTC: ML-Adaptive Multi-Tier Blockchain Consensus

Production-ready, deployable multi-tier blockchain consensus system with ML priority scoring, PBFT consensus, and smart contract integration (Healthcare, Finance, IoT).

## Architecture

- **ML Service (8000)**: PriorityNet model — scores transactions by domain (healthcare, finance, IoT) and assigns tier 1/2/3.
- **Gateway (5000)**: Receives submissions, calls ML for priority, enqueues to tiered mempool, runs PBFT per tier, syncs finalized blocks to contracts.
- **Blockchain core**: Tiered mempool, PBFT with reputation-weighted committee selection, chain validation.
- **Contracts**: HealthcareContract, FinanceContract, IoTContract (Solidity 0.8.20) on Ganache.
- **IoT Engine (9000)**: Simulated sensors, context-aware urgency, priority engine, submits to gateway.

## File structure

```
as2-camtc/
├── ml_service/       # PriorityNet, training, FastAPI /score
├── blockchain/       # block, mempool, ledger
├── consensus/        # reputation, pbft
├── contracts/         # Solidity + deployed/
├── integration/      # connector (block → contract calls)
├── gateway/          # FastAPI gateway
├── iot_engine/       # sensors, context, priority, FastAPI
├── scripts/         # deploy_contracts, train_model, benchmark
├── monitoring/       # prometheus.yml
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Startup sequence

### Step 1: Start everything

```bash
docker-compose up
```

### Step 2: Deploy contracts (runs once; check logs)

```bash
docker-compose up deploy_contracts
# or
docker-compose logs deploy_contracts
```

Contracts are written to `contracts/deployed/*.abi.json` and `*.address.txt`. Gateway and connector read these at runtime.

### Step 3: Demo — Cardiac alert

```bash
curl -X POST "http://localhost:5000/submit" \
  -H "Content-Type: application/json" \
  -d '{"domain":"healthcare","tx_type":"cardiac_alert","urgency":0.95,"value":0.80,"reputation":0.90,"latency_sensitivity":0.95,"data":{"patient_id":"P9999"}}'
```

### Step 4: Demo — Fire alarm (IoT)

```bash
curl -X POST "http://localhost:9000/simulate/fire"
```

### Step 5: Check status

```bash
curl http://localhost:5000/stats
curl http://localhost:5000/chain
curl http://localhost:5000/reputation
curl http://localhost:9000/stats
curl http://localhost:9000/alerts
```

## Expected demo output (terminal)

```
[ML]       priority=0.912 → tier=1 | latency=18ms
[MEMPOOL]  TX_ABC123 → Tier-1 queue | queue_size=1
[PBFT T1]  leader=HC_V1 | committee=['HC_V1','HC_V2','HC_V3']
[PBFT T1]  PRE-PREPARE | block_hash=0x1a2b3c...
[PBFT T1]  PREPARE 1/3 HC_V1 ✓
[PBFT T1]  PREPARE 2/3 HC_V2 ✓
[PBFT T1]  PREPARE 3/3 HC_V3 ✓ QUORUM
[PBFT T1]  COMMIT  3/3 QUORUM → FINALIZED
[PBFT T1]  ✅ Block #42 | latency=289ms | txs=1
[REP]      HC_V1: 0.910→0.920 | HC_V2: 0.890→0.900 | HC_V3: 0.880→0.890
[CHAIN]    Block appended | height=43 | valid=true
[CONTRACT] HealthcareContract.submitRecord() | tx=0xdef456 | status=✅
[CONTRACT] EmergencyAlert emitted | patient=P9999 | tier=1
```

## Scripts

- **Deploy contracts**: `python scripts/deploy_contracts.py` (or run `deploy_contracts` service). Requires Ganache and `py-solc-x` with solc 0.8.20.
- **Train model (standalone)**: `python scripts/train_model.py` — writes `ml_service/models/priority_model.pth`.
- **Benchmark**: `python scripts/benchmark.py` — 5 scenarios × 100 runs, latency and tier distribution (set `GATEWAY_URL` if needed).

## API summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/submit` | POST | Submit tx (domain, tx_type, urgency, value, reputation, latency_sensitivity, data) |
| `/chain?last_n=20` | GET | Last N blocks |
| `/stats` | GET | Chain stats, tier counts, avg latency, chain_valid, reputations |
| `/mempool` | GET | Queue sizes per tier |
| `/reputation` | GET | Validator reputations |
| `/consensus-rounds` | GET | Recent PBFT round stats |
| `/simulate/byzantine?validator_id=X` | POST | Inject byzantine node (takes effect on next rounds) |
| `/simulate/healthcare` | POST | Bulk 20 healthcare txs |
| `/simulate/finance` | POST | Bulk 20 finance txs |
| `/simulate/iot` | POST | Bulk 20 IoT txs |

IoT Engine: `/sensor/{id}/data`, `/simulate/fire`, `/sensors`, `/alerts`, `/stats`.

## Requirements

- Docker and Docker Compose
- Python 3.11+ for local runs
- Ganache (via Docker) for contracts

## License

MIT.
