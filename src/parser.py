"""
TinyFrame Protocol Parser for HLK-LD6004 mmWave radar.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

SOF = 0x01
HEADER_SIZE = 8

# Message types
TYPE_TARGET = 0x0A04
TYPE_CLOUD = 0x0A08
TYPE_PRESENCE = 0x0A0A
TYPE_BOOT = 0x0100


def calc_checksum(data: bytes) -> int:
    """Calculate TinyFrame checksum (bitwise NOT of XOR sum)."""
    r = 0
    for b in data:
        r ^= b
    return (~r) & 0xFF


@dataclass
class TargetInfo:
    id: int
    x: float
    y: float
    z: float
    doppler: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "z": round(self.z, 3),
            "doppler": self.doppler,
        }


@dataclass
class ParsedPacket:
    host_epoch_ms: int
    frame_id: int
    msg_type: int
    data_len: int
    payload_raw: bytes
    presence_zones: Optional[List[int]] = None
    target_count: Optional[int] = None
    targets: Optional[List[TargetInfo]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "host_epoch_ms": self.host_epoch_ms,
            "frame_id": self.frame_id,
            "msg_type": f"0x{self.msg_type:04X}",
            "data_len": self.data_len,
        }
        if self.presence_zones is not None:
            d["presence_zones"] = self.presence_zones
        if self.target_count is not None:
            d["target_count"] = self.target_count
            d["targets"] = [t.to_dict() for t in (self.targets or [])]
        return d


class LD6004Parser:
    """Stream parser for LD6004 TinyFrame packets."""

    def __init__(self):
        self.buffer = bytearray()
        self.total_frames_parsed = 0
        self.checksum_errors = 0

    def feed(self, chunk: bytes, host_epoch_ms: int) -> List[ParsedPacket]:
        """
        Feed raw byte chunk and return any newly completed ParsedPackets.
        """
        self.buffer.extend(chunk)
        packets: List[ParsedPacket] = []

        while True:
            idx = self.buffer.find(bytes([SOF]))
            if idx < 0:
                self.buffer.clear()
                break
            if idx > 0:
                del self.buffer[:idx]

            if len(self.buffer) < HEADER_SIZE:
                break

            # Parse header
            header_bytes = bytes(self.buffer[:HEADER_SIZE])
            frame_id = struct.unpack(">H", header_bytes[1:3])[0]
            data_len = struct.unpack(">H", header_bytes[3:5])[0]
            msg_type = struct.unpack(">H", header_bytes[5:7])[0]
            head_ck = header_bytes[7]

            if head_ck != calc_checksum(header_bytes[0:7]) or data_len > 2048:
                self.checksum_errors += 1
                del self.buffer[0]
                continue

            frame_size = HEADER_SIZE + data_len + 1
            if len(self.buffer) < frame_size:
                # Wait for more bytes
                break

            payload = bytes(self.buffer[HEADER_SIZE : HEADER_SIZE + data_len])
            data_ck = self.buffer[HEADER_SIZE + data_len]
            expected_data_ck = calc_checksum(payload) if data_len > 0 else 0xFF

            # Consume the frame from buffer
            del self.buffer[:frame_size]

            if data_ck != expected_data_ck:
                self.checksum_errors += 1
                continue

            self.total_frames_parsed += 1
            packet = self._parse_payload(
                host_epoch_ms, frame_id, msg_type, data_len, payload
            )
            if packet:
                packets.append(packet)

        return packets

    def _parse_payload(
        self,
        host_epoch_ms: int,
        frame_id: int,
        msg_type: int,
        data_len: int,
        payload: bytes,
    ) -> Optional[ParsedPacket]:
        packet = ParsedPacket(
            host_epoch_ms=host_epoch_ms,
            frame_id=frame_id,
            msg_type=msg_type,
            data_len=data_len,
            payload_raw=payload,
        )

        if msg_type == TYPE_PRESENCE:
            if len(payload) >= 16:
                packet.presence_zones = [
                    struct.unpack("<I", payload[i : i + 4])[0]
                    for i in range(0, 16, 4)
                ]
            return packet

        elif msg_type == TYPE_TARGET:
            if len(payload) >= 4:
                raw_count = struct.unpack("<I", payload[0:4])[0]
                count = min(raw_count, 3)
                targets = []
                for i in range(count):
                    off = 4 + i * 20
                    if off + 20 > len(payload):
                        break
                    x = struct.unpack("<f", payload[off : off + 4])[0]
                    y = struct.unpack("<f", payload[off + 4 : off + 8])[0]
                    z = struct.unpack("<f", payload[off + 8 : off + 12])[0]
                    dop = struct.unpack("<i", payload[off + 12 : off + 16])[0]
                    cid = struct.unpack("<i", payload[off + 16 : off + 20])[0]
                    targets.append(TargetInfo(id=cid, x=x, y=y, z=z, doppler=dop))
                packet.target_count = raw_count
                packet.targets = targets
            return packet

        return packet
