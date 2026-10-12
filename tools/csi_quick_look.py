#!/usr/bin/env python3
"""
CSI Data Quality & Distortion Quick-Look Analyzer
Usage:
    python3 tools/csi_quick_look.py
    python3 tools/csi_quick_look.py --file data/csi/feature/csi_20260826_113000.csv
"""

import argparse
import csv
import glob
from pathlib import Path


def analyze_feature_file(file_path: Path):
    print("=" * 70)
    print(f" 📊 CSI 3-Hour Sensing Data Quality & Distortion Report")
    print(f" 📁 File: {file_path}")
    print("=" * 70)

    if not file_path.exists():
        print(f"Error: File {file_path} does not exist.")
        return

    records_by_link: dict[str, list[dict]] = {}

    with file_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            link = row["link_id"]
            records_by_link.setdefault(link, []).append(row)

    if not records_by_link:
        print("No records found in CSV file.")
        return

    print(f"\n[1] Overall Link Summary (Total 5-second Windows: {len(next(iter(records_by_link.values())))})")
    print(f"{'Link ID':<10} | {'Packets':<10} | {'Missing Rate':<14} | {'Avg RSSI':<10} | {'Amp Mean':<10} | {'Distortion (CV)':<18} | {'Status'}")
    print("-" * 90)

    for link in sorted(records_by_link):
        rows = records_by_link[link]
        total_packets = sum(int(r["csi_packet_count"]) for r in rows)
        missing_rates = [float(r["csi_missing_rate"]) for r in rows]
        avg_missing = sum(missing_rates) / len(missing_rates) if missing_rates else 0.0

        rssis = [float(r["csi_rssi_mean"]) for r in rows if float(r.get("csi_rssi_mean", 0)) != 0]
        avg_rssi = sum(rssis) / len(rssis) if rssis else -50.0

        amps = [float(r["csi_amp_mean"]) for r in rows]
        avg_amp = sum(amps) / len(amps) if amps else 0.0

        distortions = [float(r.get("csi_distortion_cv_pct", r.get("csi_distortion_cv", 0))) for r in rows]
        avg_distortion = sum(distortions) / len(distortions) if distortions else 0.0

        # Motion / Distortion events (CV > 20%)
        event_count = sum(1 for d in distortions if d > 20.0)

        status = "🟢 우수 (안정)" if avg_missing < 0.05 else "🟡 보통" if avg_missing < 0.15 else "🔴 점검 필요"

        print(
            f"{link:<10} | {total_packets:<10} | {avg_missing*100:6.2f}%        | {avg_rssi:6.1f} dBm  | {avg_amp:8.2f}   | {avg_distortion:6.2f}% ({event_count}회 감지) | {status}"
        )

    print("\n[2] Key Sensing Insights")
    print(" - 결측률 (Missing Rate): < 5% 이면 RF 채널 환경 매우 안정적")
    print(" - 왜곡도 (Distortion CV): 평상시 5~15% (정적 상태), 사람 이동/혼잡 시 20~40%+ 로 급증")
    print("=" * 70 + "\n")


def find_latest_feature_file() -> Path | None:
    files = glob.glob("data/csi/feature/csi_*.csv")
    if not files:
        return None
    files.sort(key=lambda x: Path(x).stat().st_mtime, reverse=True)
    return Path(files[0])


def main():
    parser = argparse.ArgumentParser(description="Quick-look analysis for CSI sensing & distortion")
    parser.add_argument("file", nargs="?", type=Path, help="Path to feature CSV file (defaults to latest)")
    parser.add_argument("--file", dest="file_opt", type=Path, help="Optional flag path to feature CSV file")
    args = parser.parse_args()

    target_file = args.file or args.file_opt or find_latest_feature_file()
    if not target_file:
        print("No CSI feature CSV files found in data/csi/feature/")
        return

    analyze_feature_file(target_file)


if __name__ == "__main__":
    main()
