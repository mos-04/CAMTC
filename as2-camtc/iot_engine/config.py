"""
AS2-CAMTC IoT Engine: Sensor definitions and intervals.
"""
SENSORS = {
    "FIRE_001": {"type": "fire", "interval_ms": 5000, "normal_prob": 0.95, "location": "Building B"},
    "GAS_002": {"type": "gas", "interval_ms": 3000, "normal_prob": 0.98, "location": "Warehouse A1"},
    "TEMP_003": {"type": "temperature", "interval_ms": 10000, "normal_prob": 1.00, "location": "Server Room"},
    "TRAFFIC_004": {"type": "traffic", "interval_ms": 2000, "normal_prob": 0.90, "location": "Highway 101"},
    "MOTION_005": {"type": "motion", "interval_ms": 1500, "normal_prob": 0.95, "location": "Bank Vault"},
    "SMOKE_006": {"type": "smoke", "interval_ms": 4000, "normal_prob": 0.96, "location": "Mall A"},
    "FLOOD_007": {"type": "flood", "interval_ms": 8000, "normal_prob": 0.99, "location": "Basement C"},
    "WIND_008": {"type": "wind", "interval_ms": 6000, "normal_prob": 0.92, "location": "Rooftop"},
    "VIBR_009": {"type": "vibration", "interval_ms": 3000, "normal_prob": 0.97, "location": "Bridge"},
    "AIR_010": {"type": "air_quality", "interval_ms": 7000, "normal_prob": 1.00, "location": "City Center"},
}
