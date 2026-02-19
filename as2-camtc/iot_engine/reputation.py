"""
AS2-CAMTC IoT Engine: Sensor reputation (same logic as consensus/reputation).
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

INIT = 0.80
REWARD = 0.01
PENALIZE = 0.03
PENALIZE_SEVERE = 0.05


class SensorReputation:
    def __init__(self, sensor_ids: List[str]):
        self._scores: Dict[str, float] = {s: INIT for s in sensor_ids}
        self._history: Dict[str, List[float]] = {s: [] for s in sensor_ids}

    def get(self, sensor_id: str) -> float:
        return self._scores.get(sensor_id, INIT)

    def get_all(self) -> Dict[str, float]:
        return dict(self._scores)

    def reward(self, sensor_id: str) -> None:
        old = self._scores.get(sensor_id, INIT)
        new = min(1.0, old + REWARD)
        self._scores[sensor_id] = new
        self._history.setdefault(sensor_id, []).append(new)

    def penalize(self, sensor_id: str) -> None:
        old = self._scores.get(sensor_id, INIT)
        new = max(0.0, old - PENALIZE)
        self._scores[sensor_id] = new
        self._history.setdefault(sensor_id, []).append(new)

    def penalize_severe(self, sensor_id: str) -> None:
        old = self._scores.get(sensor_id, INIT)
        new = max(0.0, old - PENALIZE_SEVERE)
        self._scores[sensor_id] = new
        self._history.setdefault(sensor_id, []).append(new)
