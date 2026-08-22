"""
Global settings and constants for HLK-LD6004 mmWave data pipeline.
"""
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "raw"
PARSED_DATA_DIR = PROJECT_ROOT / "parsed"
PROCESSED_DATA_DIR = PROJECT_ROOT / "processed"

# Serial Hardware Settings
DEFAULT_SERIAL_PORT = "COM4"
DEFAULT_BAUD_RATE = 115200
SERIAL_TIMEOUT_SEC = 1.0

# Protocol & Sensor Specifications
MEASURED_SENSOR_HZ = 20.0  # Measured 20.0 Hz (50.0 ms interval)
FRAME_INTERVAL_MS = 50.0

# Team Grid Specifications
GRID_INTERVAL_SEC = 5.0
GRID_INTERVAL_MS = 5000  # 5000 ms grid

# Expected frames in 5s window: 20 Hz * 5s = 100 frames
EXPECTED_FRAMES_PER_GRID = int(MEASURED_SENSOR_HZ * GRID_INTERVAL_SEC)

# Feature Window (Internal Feature Extractor Window, default 1.0s or 5.0s)
DEFAULT_FEATURE_WINDOW_SEC = 1.0

# Ensure directories exist
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PARSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
