"""
Main Pipeline for HLK-LD6004 mmWave Sensor.
Supports both live hardware acquisition and offline file replay/aggregation.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import List

# Ensure project root is in python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DEFAULT_SERIAL_PORT, DEFAULT_BAUD_RATE
from src.collector import LD6004Collector
from src.parser import LD6004Parser, ParsedPacket
from src.aggregator import GridAggregator


def run_live(port: str, baud: int, duration: float):
    """Run live data collection, parsing, and CSV generation."""
    print(f"\n==================================================")
    print(f"  HLK-LD6004 Live Pipeline: {duration}s session")
    print(f"  Port: {port} @ {baud} baud")
    print(f"==================================================\n")

    collected_packets: List[ParsedPacket] = []

    def packet_callback(pkt: ParsedPacket):
        collected_packets.append(pkt)

    collector = LD6004Collector(
        port=port,
        baud=baud,
        save_raw=True,
        save_parsed=True,
        on_packet=packet_callback,
    )

    collector.start(duration_sec=duration)

    print("\n[*] Processing collected packets into 5-second Feature CSV...")
    aggregator = GridAggregator()
    rows = aggregator.aggregate_packets(collected_packets)
    csv_path = aggregator.save_csv(rows)
    print(f"[OK] Pipeline complete! Output saved to: {csv_path}\n")


def run_from_raw_file(raw_filepath: Path):
    """Replay and parse a raw JSONL file to generate Feature CSV."""
    if not raw_filepath.exists():
        print(f"[!] Error: File not found: {raw_filepath}")
        return

    print(f"\n[*] Replaying raw file: {raw_filepath}")
    parser = LD6004Parser()
    packets: List[ParsedPacket] = []

    with open(raw_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            ts = record["host_epoch_ms"]
            chunk = bytes.fromhex(record["hex"])
            pkts = parser.feed(chunk, ts)
            packets.extend(pkts)

    print(f"[+] Parsed {len(packets)} packets from raw file.")
    aggregator = GridAggregator()
    rows = aggregator.aggregate_packets(packets)
    csv_path = aggregator.save_csv(rows)
    print(f"[OK] Complete! Output saved to: {csv_path}\n")


def main():
    parser = argparse.ArgumentParser(description="HLK-LD6004 mmWave Pipeline")
    parser.add_argument(
        "--live", action="store_true", help="Run live acquisition from sensor"
    )
    parser.add_argument(
        "--port",
        type=str,
        default=DEFAULT_SERIAL_PORT,
        help="Serial port (e.g. COM4)",
    )
    parser.add_argument(
        "--baud", type=int, default=DEFAULT_BAUD_RATE, help="Baud rate (default 115200)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=15.0,
        help="Acquisition duration in seconds",
    )
    parser.add_argument(
        "--file", type=str, default=None, help="Process existing raw JSONL file"
    )

    args = parser.parse_args()

    if args.file:
        run_from_raw_file(Path(args.file))
    elif args.live:
        run_live(args.port, args.baud, args.duration)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
