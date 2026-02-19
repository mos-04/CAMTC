"""
AS2-CAMTC IoT Engine: Realistic sensor data generation with numpy and keccak hashes.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)


def _keccak_256(data: bytes) -> str:
    h = hashlib.sha256(data)
    return h.hexdigest()


@dataclass
class SensorData:
    sensor_id: str
    sensor_type: str
    raw: Dict[str, Any]
    data_hash: str
    is_alert: bool
    location: str


def generate_reading(sensor_id: str, sensor_type: str, is_alert: bool = False) -> SensorData:
    rng = np.random.default_rng(hash(sensor_id) % (2**32))
    raw = {}
    loc = "unknown"

    if sensor_type == "fire":
        smoke = float(rng.uniform(0.85, 1.0)) if is_alert else float(rng.uniform(0.0, 0.3))
        temp = float(rng.uniform(45, 60)) if is_alert else float(rng.uniform(18, 28))
        humidity = float(rng.uniform(20, 80))
        raw = {"smoke_level": smoke, "temperature": temp, "humidity": humidity}
        loc = "Building B"
    elif sensor_type == "gas":
        ppm_co = float(rng.uniform(400, 800)) if is_alert else float(rng.uniform(0, 50))
        ppm_methane = float(rng.uniform(200, 500)) if is_alert else float(rng.uniform(0, 20))
        raw = {"ppm_co": ppm_co, "ppm_methane": ppm_methane, "temperature": float(rng.uniform(15, 30))}
        loc = "Warehouse A1"
    elif sensor_type == "temperature":
        raw = {
            "temp_c": float(rng.uniform(35, 50)) if is_alert else float(rng.uniform(18, 26)),
            "humidity": float(rng.uniform(30, 70)),
            "pressure": float(rng.uniform(1000, 1020)),
        }
        loc = "Server Room"
    elif sensor_type == "traffic":
        raw = {
            "vehicle_count": int(rng.integers(80, 200)) if is_alert else int(rng.integers(5, 50)),
            "speed_avg": float(rng.uniform(2, 8)) if is_alert else float(rng.uniform(40, 80)),
            "accident_detected": is_alert,
        }
        loc = "Highway 101"
    elif sensor_type == "motion":
        raw = {
            "motion_detected": is_alert or rng.random() > 0.7,
            "confidence": float(rng.uniform(0.9, 1.0)) if is_alert else float(rng.uniform(0.0, 0.5)),
            "zone_id": int(rng.integers(1, 10)),
        }
        loc = "Bank Vault"
    elif sensor_type == "smoke":
        raw = {
            "smoke_density": float(rng.uniform(0.8, 1.0)) if is_alert else float(rng.uniform(0.0, 0.2)),
            "visibility_m": float(rng.uniform(1, 5)) if is_alert else float(rng.uniform(50, 100)),
        }
        loc = "Mall A"
    elif sensor_type == "flood":
        raw = {
            "water_level_m": float(rng.uniform(0.5, 1.5)) if is_alert else float(rng.uniform(0.0, 0.1)),
            "rise_rate": float(rng.uniform(0.3, 1.0)) if is_alert else float(rng.uniform(0.0, 0.05)),
        }
        loc = "Basement C"
    elif sensor_type == "wind":
        raw = {
            "speed_kmh": float(rng.uniform(80, 120)) if is_alert else float(rng.uniform(5, 40)),
            "direction_deg": float(rng.uniform(0, 360)),
            "gust_kmh": float(rng.uniform(100, 150)) if is_alert else float(rng.uniform(10, 50)),
        }
        loc = "Rooftop"
    elif sensor_type == "vibration":
        raw = {
            "magnitude": float(rng.uniform(7.0, 9.0)) if is_alert else float(rng.uniform(0.1, 3.0)),
            "frequency_hz": float(rng.uniform(10, 100)),
            "duration_s": float(rng.uniform(0.1, 5.0)),
        }
        loc = "Bridge"
    elif sensor_type == "air_quality":
        raw = {
            "aqi": int(rng.integers(200, 500)) if is_alert else int(rng.integers(20, 80)),
            "pm25": float(rng.uniform(80, 200)) if is_alert else float(rng.uniform(5, 35)),
            "pm10": float(rng.uniform(100, 300)) if is_alert else float(rng.uniform(10, 50)),
            "co2_ppm": float(rng.uniform(1200, 2000)) if is_alert else float(rng.uniform(400, 800)),
        }
        loc = "City Center"
    else:
        raw = {"value": float(rng.random()), "is_alert": is_alert}

    payload = json.dumps(raw, sort_keys=True, default=str)
    data_hash = _keccak_256(payload.encode())
    return SensorData(sensor_id=sensor_id, sensor_type=sensor_type, raw=raw, data_hash=data_hash, is_alert=is_alert, location=loc)
