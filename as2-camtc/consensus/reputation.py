"""
AS2-CAMTC Consensus: Reputation engine with reward/penalize and weighted sampling.
"""
import logging
import random
from collections import defaultdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ALPHA = 0.01
BETA = 0.03
GAMMA = 0.05
INIT = 0.80


class ReputationEngine:
    def __init__(self, validator_ids: List[str]):
        self._scores: Dict[str, float] = {v: INIT for v in validator_ids}
        self._history: Dict[str, List[float]] = defaultdict(list)
        self._validator_ids = validator_ids

    def get(self, validator_id: str) -> float:
        return self._scores.get(validator_id, INIT)

    def get_all(self) -> Dict[str, float]:
        return dict(self._scores)

    def reward(self, validator_id: str) -> None:
        old = self._scores.get(validator_id, INIT)
        new = min(1.0, old + ALPHA)
        self._scores[validator_id] = new
        self._history[validator_id].append(new)
        logger.debug("[REP] %s: %.3f→%.3f (reward)", validator_id, old, new)

    def penalize(self, validator_id: str) -> None:
        old = self._scores.get(validator_id, INIT)
        new = max(0.0, old - BETA)
        self._scores[validator_id] = new
        self._history[validator_id].append(new)
        logger.debug("[REP] %s: %.3f→%.3f (penalize)", validator_id, old, new)

    def penalize_severe(self, validator_id: str) -> None:
        old = self._scores.get(validator_id, INIT)
        new = max(0.0, old - GAMMA)
        self._scores[validator_id] = new
        self._history[validator_id].append(new)
        logger.debug("[REP] %s: %.3f→%.3f (penalize_severe)", validator_id, old, new)

    def weighted_sample(self, committee_size: int, exclude: Optional[List[str]] = None) -> List[str]:
        exclude = exclude or []
        candidates = [v for v in self._validator_ids if v not in exclude]
        if not candidates or committee_size >= len(candidates):
            return candidates[:committee_size] if candidates else []
        weights = [self._scores.get(v, INIT) for v in candidates]
        total = sum(weights)
        if total <= 0:
            return random.sample(candidates, min(committee_size, len(candidates)))
        probs = [w / total for w in weights]
        chosen = random.choices(candidates, weights=probs, k=committee_size)
        return list(dict.fromkeys(chosen))[:committee_size]

    def select_leader(self, committee: List[str]) -> str:
        if not committee:
            return ""
        scores = [(v, 0.7 * self._scores.get(v, INIT) + 0.3 * random.random()) for v in committee]
        return max(scores, key=lambda x: x[1])[0]

    def snapshot(self) -> dict:
        return {"scores": dict(self._scores), "history": dict(self._history)}
