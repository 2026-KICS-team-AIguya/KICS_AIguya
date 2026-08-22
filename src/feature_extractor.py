"""
Feature Extractor for HLK-LD6004 mmWave sensor.
Extracts per-zone direct sensor features and derived physical features.
"""
import math
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from config.zones import ZONE_NAMES, DEFAULT_ZONES, ZoneBoundingBox
from src.parser import ParsedPacket, TYPE_PRESENCE, TYPE_TARGET


@dataclass
class ZoneFeatures:
    zone: str
    mm_presence: Optional[int] = None
    mm_target_count: Optional[int] = None
    mm_avg_velocity: Optional[float] = None
    mm_avg_distance: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone": self.zone,
            "mm_presence": "" if self.mm_presence is None else self.mm_presence,
            "mm_target_count": "" if self.mm_target_count is None else self.mm_target_count,
            "mm_avg_velocity": "" if self.mm_avg_velocity is None else round(self.mm_avg_velocity, 2),
            "mm_avg_distance": "" if self.mm_avg_distance is None else round(self.mm_avg_distance, 2),
        }


class MMwaveFeatureExtractor:
    """
    Extracts zone-level mmWave features from a list of ParsedPackets.
    Maintains strict separation between direct sensor outputs and derived features.
    """

    def __init__(self, zones: Optional[List[ZoneBoundingBox]] = None):
        self.zones = zones or DEFAULT_ZONES
        self.zone_map = {z.name: z for z in self.zones}

    def extract_from_window(
        self, packets: List[ParsedPacket]
    ) -> Dict[str, ZoneFeatures]:
        """
        Extract features for each of the 4 zones from all packets in a time window.
        Returns a dict mapping zone_name -> ZoneFeatures.
        """
        # Initialize features for all 4 zones
        features = {
            z_name: ZoneFeatures(zone=z_name) for z_name in ZONE_NAMES
        }

        if not packets:
            return features

        # Zone-specific accumulators
        zone_presence_samples: Dict[str, List[int]] = {z: [] for z in ZONE_NAMES}
        zone_targets: Dict[str, List[Dict[str, Any]]] = {z: [] for z in ZONE_NAMES}

        for pkt in packets:
            # 1. Direct Presence State (0x0A0A)
            if pkt.msg_type == TYPE_PRESENCE and pkt.presence_zones is not None:
                for idx, z_name in enumerate(ZONE_NAMES):
                    if idx < len(pkt.presence_zones):
                        zone_presence_samples[z_name].append(
                            pkt.presence_zones[idx]
                        )

            # 2. Target Location & 3D Coordinates (0x0A04)
            elif pkt.msg_type == TYPE_TARGET and pkt.targets is not None:
                # Group targets into zones based on bounding box
                for t in pkt.targets:
                    dist = math.sqrt(t.x**2 + t.y**2 + t.z**2)
                    matched_zone = None
                    for z_box in self.zones:
                        if z_box.contains(t.x, t.y, t.z):
                            matched_zone = z_box.name
                            break
                    if matched_zone and matched_zone in zone_targets:
                        zone_targets[matched_zone].append(
                            {"dist": dist, "dop": t.doppler}
                        )

        # Compute aggregate features per zone
        for z_name in ZONE_NAMES:
            p_samples = zone_presence_samples[z_name]
            t_list = zone_targets[z_name]

            # mm_presence: 1 if occupied anywhere in the window, else 0 (or None if no samples)
            if p_samples:
                # Majority vote or max presence
                features[z_name].mm_presence = 1 if any(p > 0 for p in p_samples) else 0
            else:
                features[z_name].mm_presence = None

            # mm_target_count: max target count observed in this zone
            # Note: normalized per target frames count
            if t_list:
                features[z_name].mm_target_count = len(t_list) // max(len([p for p in packets if p.msg_type == TYPE_TARGET]), 1) or 1
                features[z_name].mm_avg_velocity = sum(t["dop"] for t in t_list) / len(t_list)
                features[z_name].mm_avg_distance = sum(t["dist"] for t in t_list) / len(t_list)
            else:
                features[z_name].mm_target_count = 0 if features[z_name].mm_presence is not None else None
                features[z_name].mm_avg_velocity = None
                features[z_name].mm_avg_distance = None

        return features
