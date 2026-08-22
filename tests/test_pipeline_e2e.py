"""
End-to-End Pipeline test using real/mock raw data.
"""
import json
import struct
import unittest
from pathlib import Path
from src.pipeline import run_from_raw_file
from config.settings import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.parser import calc_checksum, SOF, TYPE_PRESENCE, TYPE_TARGET


class TestPipelineE2E(unittest.TestCase):
    def setUp(self):
        self.test_raw_path = RAW_DATA_DIR / "test_raw_sample.jsonl"
        self.base_time = 1785397655000  # aligned to 5000ms

        # Generate 100 frames (5 seconds worth at 20Hz)
        with open(self.test_raw_path, "w", encoding="utf-8") as f:
            for i in range(100):
                frame_ts = self.base_time + i * 50

                # 1. Presence packet
                p_payload = struct.pack("<IIII", 1, 0, 0, 0)
                p_hdr = struct.pack(">BHHH", SOF, i * 2, len(p_payload), TYPE_PRESENCE)
                p_frame = p_hdr + bytes([calc_checksum(p_hdr)]) + p_payload + bytes([calc_checksum(p_payload)])

                # 2. Target packet (x=0.5 in zone_B, y=1.5 in zone_B, z=0.5, dop=3, id=1)
                t_payload = struct.pack("<Ifffii", 1, 0.5, 1.5, 0.5, 3, 1)
                t_hdr = struct.pack(">BHHH", SOF, i * 2 + 1, len(t_payload), TYPE_TARGET)
                t_frame = t_hdr + bytes([calc_checksum(t_hdr)]) + t_payload + bytes([calc_checksum(t_payload)])

                combined = p_frame + t_frame
                record = {
                    "host_epoch_ms": frame_ts,
                    "len": len(combined),
                    "hex": combined.hex(),
                }
                f.write(json.dumps(record) + "\n")

    def tearDown(self):
        if self.test_raw_path.exists():
            self.test_raw_path.unlink()

    def test_e2e_file_processing(self):
        run_from_raw_file(self.test_raw_path)
        # Check that CSV file was created in processed/
        csv_files = list(PROCESSED_DATA_DIR.glob("mm_*.csv"))
        self.assertTrue(len(csv_files) > 0)

        latest_csv = sorted(csv_files, key=lambda p: p.stat().st_mtime)[-1]
        with open(latest_csv, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

        # Header + 4 zone rows = 5 lines
        self.assertEqual(len(lines), 5)
        self.assertIn("timestamp,zone,mm_presence,mm_target_count,mm_frame_count", lines[0])
        self.assertTrue(any("zone_A" in l for l in lines[1:]))
        self.assertTrue(any("zone_B" in l for l in lines[1:]))
        self.assertTrue(any("zone_C" in l for l in lines[1:]))
        self.assertTrue(any("zone_D" in l for l in lines[1:]))


if __name__ == "__main__":
    unittest.main()
