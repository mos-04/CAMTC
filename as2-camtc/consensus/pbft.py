"""
AS2-CAMTC Consensus: PBFT engine with tier-specific committee size and quorum.
"""
import asyncio
import hashlib
import json
import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from blockchain.block import Block, Transaction

logger = logging.getLogger(__name__)

TIER_CONFIG = {
    1: {"committee_size": 3, "quorum_pct": 0.90, "timeout_ms": 500},
    2: {"committee_size": 5, "quorum_pct": 0.67, "timeout_ms": 5000},
    3: {"committee_size": 7, "quorum_pct": 0.67, "timeout_ms": 15000},
}


class Phase(Enum):
    IDLE = "idle"
    PREPREPARE = "preprepare"
    PREPARE = "prepare"
    COMMIT = "commit"
    FINALIZED = "finalized"
    FAILED = "failed"


@dataclass
class ConsensusRound:
    round_id: str
    tier: int
    block: Optional[Block] = None
    leader: str = ""
    committee: List[str] = field(default_factory=list)
    phase: Phase = Phase.IDLE
    prepare_votes: Dict[str, bool] = field(default_factory=dict)
    commit_votes: Dict[str, bool] = field(default_factory=dict)
    start_time: float = 0.0
    finalized_at: Optional[float] = None

    @property
    def latency_ms(self) -> float:
        if self.finalized_at and self.start_time:
            return (self.finalized_at - self.start_time) * 1000
        return 0.0


class PBFTEngine:
    def __init__(
        self,
        node_id: str,
        reputation,
        on_block_finalized: Callable[[Block, ConsensusRound], None],
        validator_ids: List[str],
        byzantine_node_ids: Optional[List[str]] = None,
    ):
        self.node_id = node_id
        self.reputation = reputation
        self.on_block_finalized = on_block_finalized
        self.validator_ids = validator_ids
        self._byzantine_list = byzantine_node_ids if isinstance(byzantine_node_ids, list) else list(byzantine_node_ids or [])
        self.byzantine_node_ids = set(self._byzantine_list)
        self._rounds: List[ConsensusRound] = []
        self._round_id = 0

    def _next_round_id(self) -> str:
        self._round_id += 1
        return f"R{self._round_id}"

    async def _validator_prepare(self, validator_id: str, block: Block, cr: ConsensusRound) -> bool:
        if validator_id in set(self._byzantine_list):
            logger.info("[PBFT T%d] PREPARE %s (byzantine) ✗", cr.tier, validator_id)
            return False
        if not block or not block.transactions:
            return False
        if block.calculate_hash() != block.hash:
            return False
        logger.info("[PBFT T%d] PREPARE %s ✓", cr.tier, validator_id)
        return True

    async def _validator_commit(self, validator_id: str, block: Block, cr: ConsensusRound) -> bool:
        if validator_id in set(self._byzantine_list):
            logger.info("[PBFT T%d] COMMIT %s (byzantine) ✗", cr.tier, validator_id)
            return False
        if block.calculate_hash() != block.hash:
            return False
        return True

    async def run_round(
        self,
        tier: int,
        transactions: List[Transaction],
        previous_hash: str,
        block_index: int,
    ) -> Optional[Block]:
        cfg = TIER_CONFIG.get(tier, TIER_CONFIG[3])
        committee_size = cfg["committee_size"]
        quorum_pct = cfg["quorum_pct"]
        timeout_ms = cfg["timeout_ms"]

        committee = self.reputation.weighted_sample(committee_size)
        if len(committee) < 2:
            committee = (self.validator_ids + [])[:committee_size]
        leader = self.reputation.select_leader(committee)

        round_id = self._next_round_id()
        cr = ConsensusRound(
            round_id=round_id,
            tier=tier,
            block=None,
            leader=leader,
            committee=committee,
            phase=Phase.PREPREPARE,
            start_time=time.monotonic(),
        )
        self._rounds.append(cr)

        logger.info("[PBFT T%d] leader=%s | committee=%s", tier, leader, committee)

        nonce = int(time.time() * 1000) + block_index
        block = Block(
            index=block_index,
            tier=tier,
            transactions=transactions,
            previous_hash=previous_hash,
            validator_id=leader,
            committee=committee,
            signatures={},
            timestamp=time.time(),
            nonce=nonce,
        )
        cr.block = block
        logger.info("[PBFT T%d] PRE-PREPARE | block_hash=%s", tier, block.hash[:16] + "...")

        prepare_votes = {}
        for v in committee:
            ok = await self._validator_prepare(v, block, cr)
            prepare_votes[v] = ok
            count = sum(1 for x in prepare_votes.values() if x)
            logger.info("[PBFT T%d] PREPARE %d/%d %s %s", tier, count, len(committee), v, "✓" if ok else "✗")
            if count >= max(2, int(len(committee) * quorum_pct) + 1):
                break
        cr.prepare_votes = prepare_votes
        quorum_needed = max(2, int(len(committee) * quorum_pct) + 1)
        prepare_ok = sum(1 for x in prepare_votes.values() if x)
        if prepare_ok < quorum_needed:
            logger.warning("[PBFT T%d] PREPARE no quorum %d < %d", tier, prepare_ok, quorum_needed)
            cr.phase = Phase.FAILED
            return None
        logger.info("[PBFT T%d] PREPARE %d/%d QUORUM", tier, prepare_ok, len(committee))

        commit_votes = {}
        for v in committee:
            ok = await self._validator_commit(v, block, cr)
            commit_votes[v] = ok
        cr.commit_votes = commit_votes
        commit_ok = sum(1 for x in commit_votes.values() if x)
        if commit_ok < quorum_needed:
            logger.warning("[PBFT T%d] COMMIT no quorum", tier)
            cr.phase = Phase.FAILED
            return None
        logger.info("[PBFT T%d] COMMIT %d/%d QUORUM → FINALIZED", tier, commit_ok, len(committee))

        cr.phase = Phase.FINALIZED
        cr.finalized_at = time.monotonic()
        for v in committee:
            if commit_votes.get(v):
                self.reputation.reward(v)
                logger.info("[REP] %s: %.3f→%.3f", v, self.reputation.get(v) - 0.01, self.reputation.get(v))
            else:
                if v in set(self._byzantine_list):
                    self.reputation.penalize_severe(v)
                else:
                    self.reputation.penalize(v)

        block.signatures = {v: "sig_" + v for v in committee if commit_votes.get(v)}
        logger.info("[PBFT T%d] ✅ Block #%d | latency=%.0fms | txs=%d", tier, block_index, cr.latency_ms, len(transactions))
        self.on_block_finalized(block, cr)
        return block

    def get_round_stats(self) -> List[dict]:
        return [
            {
                "round_id": r.round_id,
                "tier": r.tier,
                "phase": r.phase.value,
                "latency_ms": r.latency_ms,
                "leader": r.leader,
            }
            for r in self._rounds[-50:]
        ]
