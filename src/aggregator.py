"""
5-Second Grid Aggregator for HLK-LD6004 mmWave sensor features.
Outputs team-compliant Feature CSVs (mm_YYYYMMDD_HHMM.csv).
"""
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from config.settings import GRID_INTERVAL_MS, PROCESSED_DATA_DIR
from config.zones import ZONE_NAMES
from src.parser import ParsedPacket
from src.feature_extractor import MMwaveFeatureExtractor, ZoneFeatures


class GridAggregator:
    """
    Aggregates parsed mmWave frames into 5-second synchronized time grids.
    Enforces [start, end) interval rules, creates 4 zone rows per timestamp,
    and outputs missing values as empty strings.
    """

    def __init__(self, grid_interval_ms: int = GRID_INTERVAL_MS):
        self.grid_interval_ms = grid_interval_ms
        self.extractor = MMwaveFeatureExtractor()

    def aggregate_packets(
        self, packets: List[ParsedPacket]
    ) -> List[Dict[str, Any]]:
        """
        Groups a list of ParsedPackets by 5-second grids and computes per-zone features.
        Returns a list of row dicts for CSV output.
        """
        if not packets:
            return []

        # Find overall start and end grid boundaries
        min_ts = min(p.host_epoch_ms for p in packets)
        max_ts = max(p.host_epoch_ms for p in packets)

        # Align to 5-second grid boundary: start_grid = floor(min_ts / grid_ms) * grid_ms
        start_grid = (min_ts // self.grid_interval_ms) * self.grid_interval_ms
        end_grid = ((max_ts // self.grid_interval_ms) + 1) * self.grid_interval_ms

        # Bucket packets into 5s windows: [grid_start, grid_start + grid_interval_ms)
        grid_buckets: Dict[int, List[ParsedPacket]] = {
            t: [] for t in range(start_grid, end_grid, self.grid_interval_ms)
        }

        for pkt in packets:
            grid_key = (pkt.host_epoch_ms // self.grid_interval_ms) * self.grid_interval_ms
            if grid_key in grid_buckets:
                grid_buckets[grid_key].append(pkt)

        # Generate 4 rows per grid timestamp
        rows: List[Dict[str, Any]] = []

        for grid_ts in sorted(grid_buckets.keys()):
            bucket_packets = grid_buckets[grid_ts]
            frame_count = len(bucket_packets)

            # Extract features for all 4 zones
            zone_feats = self.extractor.extract_from_window(bucket_packets)

            for z_name in ZONE_NAMES:
                zf = zone_feats.get(z_name, ZoneFeatures(zone=z_name))
                row = {
                    "timestamp": grid_ts,
                    "zone": z_name,
                    "mm_presence": "" if zf.mm_presence is None else zf.mm_presence,
                    "mm_target_count": "" if zf.mm_target_count is None else zf.mm_target_count,
                    "mm_frame_count": frame_count,
                    "mm_avg_velocity": "" if zf.mm_avg_velocity is None else round(zf.mm_avg_velocity, 2),
                    "mm_avg_distance": "" if zf.mm_avg_distance is None else round(zf.mm_avg_distance, 2),
                }
                rows.append(row)

        return rows

    def save_csv(
        self,
        rows: List[Dict[str, Any]],
        output_filepath: Optional[Path] = None,
        custom_dt: Optional[datetime] = None,
    ) -> Path:
        """
        Saves aggregated rows to standard CSV file (mm_YYYYMMDD_HHMM.csv).
        """
        if output_filepath is None:
            # Generate default filename based on earliest timestamp or current time
            if rows and rows[0]["timestamp"]:
                dt = datetime.fromtimestamp(rows[0]["timestamp"] / 1000.0)
            else:
                dt = custom_dt or datetime.now()
            filename = f"mm_{dt.strftime('%Y%m%d_%H%M')}.csv"
            output_filepath = PROCESSED_DATA_DIR / filename

        fieldnames = [
            "timestamp",
            "zone",
            "mm_presence",
            "mm_target_count",
            "mm_frame_count",
            "mm_avg_velocity",
            "mm_avg_distance",
        ]

        with open(output_filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        print(f"[+] Successfully generated Feature CSV: {output_filepath} ({len(rows)} rows)")
        return output_filepath
