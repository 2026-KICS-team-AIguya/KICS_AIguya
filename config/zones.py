"""
Zone configurations for HLK-LD6004 mmWave sensor.
"""
from dataclasses import dataclass
from typing import List

# Standard Zone Names required by the project
ZONE_NAMES = [
    "zone_A",
    "zone_B",
    "zone_C",
    "zone_D",
]

@dataclass
class ZoneBoundingBox:
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float = -10.0
    z_max: float = 10.0

    def contains(self, x: float, y: float, z: float = 0.0) -> bool:
        return (self.x_min <= x <= self.x_max and
                self.y_min <= y <= self.y_max and
                self.z_min <= z <= self.z_max)

# Default 4-zone bounding boxes (can be customized based on physical deployment)
DEFAULT_ZONES: List[ZoneBoundingBox] = [
    ZoneBoundingBox(name="zone_A", x_min=-3.0, x_max=0.0, y_min=0.0, y_max=3.0),
    ZoneBoundingBox(name="zone_B", x_min=0.0,  x_max=3.0, y_min=0.0, y_max=3.0),
    ZoneBoundingBox(name="zone_C", x_min=-3.0, x_max=0.0, y_min=3.0, y_max=6.0),
    ZoneBoundingBox(name="zone_D", x_min=0.0,  x_max=3.0, y_min=3.0, y_max=6.0),
]
