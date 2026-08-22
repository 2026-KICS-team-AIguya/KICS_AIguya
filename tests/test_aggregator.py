"""
Unit tests for 5-Second Grid Aggregator and Zone Feature Extraction.
"""
import unittest
from src.parser import ParsedPacket, TargetInfo, TYPE_PRESENCE, TYPE_TARGET
from src.aggregator import GridAggregator
from config.zones import ZONE_NAMES


class TestAggregator(unittest.TestCase):
    def test_5s_grid_alignment_and_4_zones(self):
        aggregator = GridAggregator(grid_interval_ms=5000)

        # Generate mock packets spanning two 5-second intervals:
        # Window 1: [1785397655000, 1785397660000)
        # Window 2: [1785397660000, 1785397665000)
        packets = []

        # Window 1 packets (10 frames)
        for i in range(10):
            ts = 1785397655000 + i * 50
            packets.append(
                ParsedPacket(
                    host_epoch_ms=ts,
                    frame_id=i,
                    msg_type=TYPE_PRESENCE,
                    data_len=16,
                    payload_raw=b"",
                    presence_zones=[1, 0, 0, 1],  # zone_A and zone_D occupied
                )
            )

        # Window 2 packets (5 frames)
        for i in range(5):
            ts = 1785397660000 + i * 50
            packets.append(
                ParsedPacket(
                    host_epoch_ms=ts,
                    frame_id=10 + i,
                    msg_type=TYPE_PRESENCE,
                    data_len=16,
                    payload_raw=b"",
                    presence_zones=[0, 1, 0, 0],  # zone_B occupied
                )
            )

        rows = aggregator.aggregate_packets(packets)

        # Should produce 2 timestamps * 4 zones = 8 rows total
        self.assertEqual(len(rows), 8)

        # Verify Window 1 rows
        w1_rows = [r for r in rows if r["timestamp"] == 1785397655000]
        self.assertEqual(len(w1_rows), 4)
        w1_zones = {r["zone"]: r for r in w1_rows}

        self.assertIn("zone_A", w1_zones)
        self.assertIn("zone_B", w1_zones)
        self.assertIn("zone_C", w1_zones)
        self.assertIn("zone_D", w1_zones)

        self.assertEqual(w1_zones["zone_A"]["mm_presence"], 1)
        self.assertEqual(w1_zones["zone_B"]["mm_presence"], 0)
        self.assertEqual(w1_zones["zone_C"]["mm_presence"], 0)
        self.assertEqual(w1_zones["zone_D"]["mm_presence"], 1)
        self.assertEqual(w1_zones["zone_A"]["mm_frame_count"], 10)

        # Verify Window 2 rows
        w2_rows = [r for r in rows if r["timestamp"] == 1785397660000]
        self.assertEqual(len(w2_rows), 4)
        w2_zones = {r["zone"]: r for r in w2_rows}
        self.assertEqual(w2_zones["zone_B"]["mm_presence"], 1)
        self.assertEqual(w2_zones["zone_A"]["mm_presence"], 0)
        self.assertEqual(w2_zones["zone_B"]["mm_frame_count"], 5)

    def test_missing_values_are_empty_strings(self):
        aggregator = GridAggregator(grid_interval_ms=5000)
        # Empty packet in window -> should output empty string for features
        empty_pkt = ParsedPacket(
            host_epoch_ms=1785397655000,
            frame_id=1,
            msg_type=0x9999,  # unknown type without presence/targets
            data_len=0,
            payload_raw=b"",
        )
        rows = aggregator.aggregate_packets([empty_pkt])
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual(r["mm_presence"], "")
            self.assertEqual(r["mm_target_count"], "")
            self.assertEqual(r["mm_avg_velocity"], "")


if __name__ == "__main__":
    unittest.main()
