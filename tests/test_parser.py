"""
Unit tests for TinyFrame Parser.
"""
import struct
import unittest
from src.parser import LD6004Parser, calc_checksum, SOF, TYPE_PRESENCE, TYPE_TARGET


class TestParser(unittest.TestCase):
    def test_checksum_calculation(self):
        data = bytes([0x01, 0x00, 0x01, 0x00, 0x10, 0x0A, 0x0A])
        ck = calc_checksum(data)
        self.assertIsInstance(ck, int)
        self.assertTrue(0 <= ck <= 255)

    def test_parse_presence_packet(self):
        parser = LD6004Parser()
        # Create a mock 0x0A0A Presence packet (Zone 0 & Zone 2 occupied)
        payload = struct.pack("<IIII", 1, 0, 1, 0)
        hdr = struct.pack(">BHHH", SOF, 100, len(payload), TYPE_PRESENCE)
        h_ck = calc_checksum(hdr)
        d_ck = calc_checksum(payload)
        raw_frame = hdr + bytes([h_ck]) + payload + bytes([d_ck])

        pkts = parser.feed(raw_frame, host_epoch_ms=1785397655000)
        self.assertEqual(len(pkts), 1)
        pkt = pkts[0]
        self.assertEqual(pkt.msg_type, TYPE_PRESENCE)
        self.assertEqual(pkt.presence_zones, [1, 0, 1, 0])

    def test_parse_target_packet(self):
        parser = LD6004Parser()
        # Create a mock 0x0A04 Target packet (1 target: x=1.5, y=2.0, z=0.5, doppler=5, id=42)
        target_payload = struct.pack("<Ifffii", 1, 1.5, 2.0, 0.5, 5, 42)
        hdr = struct.pack(">BHHH", SOF, 101, len(target_payload), TYPE_TARGET)
        h_ck = calc_checksum(hdr)
        d_ck = calc_checksum(target_payload)
        raw_frame = hdr + bytes([h_ck]) + target_payload + bytes([d_ck])

        pkts = parser.feed(raw_frame, host_epoch_ms=1785397655050)
        self.assertEqual(len(pkts), 1)
        pkt = pkts[0]
        self.assertEqual(pkt.msg_type, TYPE_TARGET)
        self.assertEqual(pkt.target_count, 1)
        self.assertEqual(len(pkt.targets), 1)
        t = pkt.targets[0]
        self.assertEqual(t.id, 42)
        self.assertAlmostEqual(t.x, 1.5, places=2)
        self.assertAlmostEqual(t.y, 2.0, places=2)
        self.assertEqual(t.doppler, 5)

    def test_stream_fragmentation(self):
        """Test feeding fragmented bytes one by one."""
        parser = LD6004Parser()
        payload = struct.pack("<IIII", 0, 1, 0, 0)
        hdr = struct.pack(">BHHH", SOF, 102, len(payload), TYPE_PRESENCE)
        raw_frame = hdr + bytes([calc_checksum(hdr)]) + payload + bytes([calc_checksum(payload)])

        all_pkts = []
        for byte_val in raw_frame:
            pkts = parser.feed(bytes([byte_val]), host_epoch_ms=1785397655100)
            all_pkts.extend(pkts)

        self.assertEqual(len(all_pkts), 1)
        self.assertEqual(all_pkts[0].presence_zones, [0, 1, 0, 0])


if __name__ == "__main__":
    unittest.main()
