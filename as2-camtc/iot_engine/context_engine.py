"""
AS2-CAMTC IoT Engine: Context-aware urgency adjustment (time, sensor type, raw data).
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ContextEngine:
    def adjust_urgency(
        self,
        sensor_type: str,
        raw_data: Dict[str, Any],
        base_urgency: float,
        time_of_day: int,
    ) -> float:
        factor = 1.0
        st = (sensor_type or "").lower()

        if st == "fire":
            smoke = raw_data.get("smoke_level", 0) or 0
            temp = raw_data.get("temperature", 0) or 0
            if smoke > 0.8 and temp > 40:
                factor = 1.25
        elif st == "gas":
            ppm = raw_data.get("ppm_co", 0) or raw_data.get("ppm_methane", 0) or 0
            if ppm > 500:
                factor = 1.15
        elif st == "motion":
            if 22 <= time_of_day or time_of_day < 6:
                factor = 1.20
        elif st == "traffic":
            speed = raw_data.get("speed_avg", 100) or 100
            count = raw_data.get("vehicle_count", 0) or 0
            if speed < 10 and count > 50:
                factor = 1.10
        elif st == "vibration":
            mag = raw_data.get("magnitude", 0) or 0
            if mag > 7.0:
                factor = 1.30
        elif st == "flood":
            rise = raw_data.get("rise_rate", 0) or 0
            if rise > 0.5:
                factor = 1.20

        return min(1.0, base_urgency * factor)
