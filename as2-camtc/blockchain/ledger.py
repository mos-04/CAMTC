"""
AS2-CAMTC Blockchain: Ledger with tier processing loops and PBFT integration.
"""
import asyncio
import logging
import time
from typing import Callable, Dict, List, Optional

from blockchain.block import Block, Transaction, genesis_block
from blockchain.mempool import Mempool

logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)
logger = logging.getLogger("CHAIN")

TIER_CONFIG = {
    1: {"batch_size": 5, "max_wait_ms": 500},
    2: {"batch_size": 10, "max_wait_ms": 5000},
    3: {"batch_size": 20, "max_wait_ms": 15000},
}


class BlockchainLedger:
    def __init__(
        self,
        node_id: str,
        validator_ids: List[str],
        byzantine_ids: List[str],
        on_block_callback: Callable[[Block, object], None],
    ):
        self.node_id = node_id
        self.validator_ids = validator_ids
        self.byzantine_ids = byzantine_ids
        self.on_block_callback = on_block_callback
        self.chain: List[Block] = [genesis_block()]
        self.mempool = Mempool()
        self.reputation = None
        self.pbft = None
        self._tier_tasks: List[asyncio.Task] = []
        self._stats = {
            "total_blocks": 0,
            "total_txs": 0,
            "tier_blocks": {1: 0, 2: 0, 3: 0},
            "tier_txs": {1: 0, 2: 0, 3: 0},
            "latencies_ms": [],
            "reputations": {},
        }
        self._lock = asyncio.Lock()

    def set_reputation(self, reputation):
        self.reputation = reputation

    def set_pbft(self, pbft):
        self.pbft = pbft

    async def submit_transaction(self, tx: Transaction) -> None:
        await self.mempool.push(tx)

    async def _process_tier(self, tier: int) -> None:
        cfg = TIER_CONFIG[tier]
        batch_size = cfg["batch_size"]
        max_wait_s = cfg["max_wait_ms"] / 1000.0
        last_batch_time = time.monotonic()
        while True:
            try:
                batch = await self.mempool.pop_batch(tier, batch_size)
                now = time.monotonic()
                if not batch and (now - last_batch_time) < max_wait_s:
                    await asyncio.sleep(0.1)
                    continue
                if not batch:
                    last_batch_time = now
                    await asyncio.sleep(0.1)
                    continue
                last_batch_time = now
                previous_block = self.chain[-1]
                block_index = len(self.chain)
                block = await self.pbft.run_round(tier, batch, previous_block.hash, block_index)
                if block:
                    async with self._lock:
                        self._on_block_finalized(block, None)
            except asyncio.CancelledError:
                logger.info("[CHAIN] tier=%d process stopped", tier)
                break
            except Exception as e:
                logger.exception("[CHAIN] tier=%d error | error=%s", tier, e)
                await asyncio.sleep(0.5)

    def _on_block_finalized(self, block: Block, cr: Optional[object]) -> None:
        self.chain.append(block)
        self._stats["total_blocks"] += 1
        self._stats["total_txs"] += len(block.transactions)
        self._stats["tier_blocks"][block.tier] = self._stats["tier_blocks"].get(block.tier, 0) + 1
        self._stats["tier_txs"][block.tier] = self._stats["tier_txs"].get(block.tier, 0) + len(block.transactions)
        if cr and getattr(cr, "latency_ms", None) is not None:
            self._stats["latencies_ms"].append(cr.latency_ms)
            if len(self._stats["latencies_ms"]) > 1000:
                self._stats["latencies_ms"] = self._stats["latencies_ms"][-500:]
        if self.reputation:
            self._stats["reputations"] = self.reputation.get_all()
        logger.info("[CHAIN] Block appended | height=%d | valid=%s", len(self.chain), self.validate_chain())
        self.on_block_callback(block, cr)

    async def start(self) -> None:
        self._tier_tasks = [
            asyncio.create_task(self._process_tier(1)),
            asyncio.create_task(self._process_tier(2)),
            asyncio.create_task(self._process_tier(3)),
        ]
        logger.info("[CHAIN] tier loops started")

    async def stop(self) -> None:
        for t in self._tier_tasks:
            t.cancel()
        await asyncio.gather(*self._tier_tasks, return_exceptions=True)

    def get_stats(self) -> dict:
        lat = self._stats["latencies_ms"]
        avg_latency_ms = sum(lat) / len(lat) if lat else 0.0
        return {
            "total_blocks": self._stats["total_blocks"],
            "total_txs": self._stats["total_txs"],
            "tier_blocks": dict(self._stats["tier_blocks"]),
            "tier_txs": dict(self._stats["tier_txs"]),
            "avg_latency_ms": round(avg_latency_ms, 2),
            "reputations": dict(self._stats["reputations"]),
            "chain_valid": self.validate_chain(),
        }

    def get_chain(self, last_n: int = 20) -> List[dict]:
        blocks = self.chain[-last_n:] if last_n else self.chain
        return [b.to_dict() for b in blocks]

    def validate_chain(self) -> bool:
        for i in range(1, len(self.chain)):
            prev = self.chain[i - 1]
            curr = self.chain[i]
            if curr.previous_hash != prev.hash:
                return False
            if curr.calculate_hash() != curr.hash:
                return False
        return True
