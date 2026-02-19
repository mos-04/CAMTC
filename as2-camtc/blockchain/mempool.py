"""
AS2-CAMTC Blockchain: Tiered mempool with async push/pop.
"""
import asyncio
import logging
from collections import deque
from typing import Deque, Dict, List

from blockchain.block import Transaction

logger = logging.getLogger(__name__)


class Mempool:
    """Three queues by tier: 1 (highest), 2, 3 (lowest)."""

    def __init__(self):
        self._queues: Dict[int, Deque[Transaction]] = {
            1: deque(),
            2: deque(),
            3: deque(),
        }
        self._lock = asyncio.Lock()

    async def push(self, tx: Transaction) -> None:
        async with self._lock:
            tier = tx.tier
            if tier not in self._queues:
                tier = min(3, max(1, tier))
            self._queues[tier].append(tx)
        logger.info("[MEMPOOL] %s → Tier-%d queue | queue_size=%d", tx.tx_id, tier, len(self._queues[tier]))

    async def pop_batch(self, tier: int, size: int) -> List[Transaction]:
        async with self._lock:
            q = self._queues.get(tier, self._queues[3])
            batch: List[Transaction] = []
            for _ in range(min(size, len(q))):
                if q:
                    batch.append(q.popleft())
            return batch

    def size(self, tier: int) -> int:
        return len(self._queues.get(tier, deque()))

    def all_sizes(self) -> Dict[int, int]:
        return {t: len(q) for t, q in self._queues.items()}
