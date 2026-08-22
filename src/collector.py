"""
UART Raw Data Collector for HLK-LD6004 mmWave sensor.
Saves raw incoming bytes with host_epoch_ms timestamps into the raw/ directory.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable
import serial

# Ensure project root is in python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    DEFAULT_SERIAL_PORT,
    DEFAULT_BAUD_RATE,
    SERIAL_TIMEOUT_SEC,
    RAW_DATA_DIR,
    PARSED_DATA_DIR,
)
from src.parser import LD6004Parser, ParsedPacket


class LD6004Collector:
    """Collects raw UART data from LD6004 and saves to disk without loss."""

    def __init__(
        self,
        port: str = DEFAULT_SERIAL_PORT,
        baud: int = DEFAULT_BAUD_RATE,
        save_raw: bool = True,
        save_parsed: bool = True,
        on_packet: Optional[Callable[[ParsedPacket], None]] = None,
    ):
        self.port = port
        self.baud = baud
        self.save_raw = save_raw
        self.save_parsed = save_parsed
        self.on_packet = on_packet

        self.parser = LD6004Parser()
        self.is_running = False
        self.ser: Optional[serial.Serial] = None

        self.raw_file = None
        self.parsed_file = None

    def start(self, duration_sec: Optional[float] = None):
        """Start collecting data from serial port."""
        session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_filepath = RAW_DATA_DIR / f"raw_{session_time}.jsonl"
        parsed_filepath = PARSED_DATA_DIR / f"parsed_{session_time}.jsonl"

        print(f"[*] Opening {self.port} at {self.baud} baud...")
        self.ser = serial.Serial(
            self.port, self.baud, timeout=SERIAL_TIMEOUT_SEC
        )
        self.ser.reset_input_buffer()

        # Flush initial noise
        time.sleep(0.5)
        self.ser.reset_input_buffer()

        print(f"[*] Connected. Saving Raw to: {raw_filepath}")
        if self.save_parsed:
            print(f"[*] Saving Parsed to: {parsed_filepath}")

        if self.save_raw:
            self.raw_file = open(raw_filepath, "w", encoding="utf-8")
        if self.save_parsed:
            self.parsed_file = open(parsed_filepath, "w", encoding="utf-8")

        self.is_running = True
        start_time = time.time()
        total_bytes = 0
        total_packets = 0

        try:
            while self.is_running:
                if duration_sec and (time.time() - start_time >= duration_sec):
                    break

                in_wait = self.ser.in_waiting
                if in_wait > 0:
                    host_epoch_ms = int(time.time() * 1000)
                    chunk = self.ser.read(in_wait)
                    total_bytes += len(chunk)

                    # Save raw chunk with precise host_epoch_ms
                    if self.save_raw and self.raw_file:
                        raw_record = {
                            "host_epoch_ms": host_epoch_ms,
                            "len": len(chunk),
                            "hex": chunk.hex(),
                        }
                        self.raw_file.write(json.dumps(raw_record) + "\n")
                        self.raw_file.flush()

                    # Feed parser
                    packets = self.parser.feed(chunk, host_epoch_ms)
                    for pkt in packets:
                        total_packets += 1
                        if self.save_parsed and self.parsed_file:
                            self.parsed_file.write(
                                json.dumps(pkt.to_dict()) + "\n"
                            )
                            self.parsed_file.flush()

                        if self.on_packet:
                            self.on_packet(pkt)
                else:
                    time.sleep(0.005)

        except KeyboardInterrupt:
            print("\n[!] Collection interrupted by user.")
        finally:
            self.stop()
            elapsed = time.time() - start_time
            print(f"\n[+] Session Finished in {elapsed:.2f}s")
            print(
                f"[+] Total bytes received: {total_bytes} bytes ({total_bytes/max(elapsed, 0.001):.1f} B/s)"
            )
            print(
                f"[+] Total valid packets parsed: {total_packets} ({total_packets/max(elapsed, 0.001):.2f} Hz)"
            )

    def stop(self):
        """Stop collector and close files/serial port."""
        self.is_running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        if self.raw_file:
            self.raw_file.close()
            self.raw_file = None
        if self.parsed_file:
            self.parsed_file.close()
            self.parsed_file = None


if __name__ == "__main__":
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else None
    collector = LD6004Collector()
    collector.start(duration_sec=duration)
