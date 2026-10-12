"""
Raw CSI CSV → 5초 feature CSV 오프라인 변환기.

실시간 수집기(csi/logger/tcp_receiver.py)와 같은 계산 함수를 재사용하므로
같은 raw를 넣으면 live feature와 같은 값이 나온다.
차이점: 패킷이 없는 window의 RSSI·진폭·왜곡도는 README 규격대로 빈칸으로 둔다.

사용 예:
    python3 csi/processing/offline_feature.py \
        data/csi/raw/csi_20261008_8.csv --expected-pps 36 \
        --parts 4 --part 4 \
        --output data/csi/processed/csi_20261008_8_q4.csv

    --output을 생략하면 README 규격 이름(csi_YYYYMMDD_HHMM.csv)으로 저장한다.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logger"))

from tcp_receiver import (  # noqa: E402
    WINDOW_MS,
    WindowStats,
    calculate_packet_mean_amplitude,
    grid_start_ms,
    next_grid_start_ms,
    update_window_stats,
)

FEATURE_FIELDS = [
    "timestamp",
    "link_id",
    "csi_packet_count",
    "csi_missing_rate",
    "csi_rssi_mean",
    "csi_amp_mean",
    "csi_amp_std",
    "csi_amp_var",
    "csi_distortion_cv_pct",
    "csi_expected_packet_count",
    "csi_id_gap_count",
    "csi_received_row_count",
    "csi_duplicate_count",
    "csi_reset_count",
    "csi_over_expected_count",
]

KST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT_DIR = Path("data/csi/processed")


def readme_filename(window_start_ms: int) -> str:
    """README 규격 파일명: csi_{YYYYMMDD}_{HHMM}.csv (KST, 첫 window 기준)."""
    start = datetime.fromtimestamp(window_start_ms / 1_000, KST)
    return f"csi_{start:%Y%m%d_%H%M}.csv"


def feature_row(
    window_start: int,
    link_id: str,
    stats: WindowStats,
    expected_packet_count: int,
) -> list:
    packet_count = len(stats.packet_ids)
    missing_count = max(expected_packet_count - packet_count, 0)
    missing_rate = (
        missing_count / expected_packet_count
        if expected_packet_count > 0
        else 0.0
    )

    # 결측은 빈칸 (README 규격, -1·0 금지)
    rssi_mean = (
        round(stats.rssi_sum / stats.rssi_count, 2)
        if stats.rssi_count > 0
        else ""
    )

    if stats.amp_count > 0:
        amp_mean = stats.amp_sum / stats.amp_count
        amp_var = max(
            0.0,
            (stats.amp_sq_sum / stats.amp_count) - amp_mean * amp_mean,
        )
        amp_std = math.sqrt(amp_var)
        cv = (amp_std / amp_mean) * 100.0 if amp_mean > 0 else ""
        amp_cols = [
            round(amp_mean, 4),
            round(amp_std, 4),
            round(amp_var, 4),
            round(cv, 2) if cv != "" else "",
        ]
    else:
        amp_cols = ["", "", "", ""]

    return [
        window_start,
        link_id,
        packet_count,
        round(missing_rate, 6),
        rssi_mean,
        *amp_cols,
        expected_packet_count,
        stats.id_gap_count,
        stats.received_rows,
        stats.duplicate_count,
        stats.reset_count,
        max(packet_count - expected_packet_count, 0),
    ]


def process(
    raw_path: Path,
    output_path: Path | None,
    expected_pps: float,
    parts: int,
    part: int,
    only_links: set[str] | None = None,
    overwrite: bool = False,
    end_ms: int | None = None,
) -> None:
    expected_packet_count = round(expected_pps * (WINDOW_MS / 1_000))

    windows: dict[tuple[int, str], WindowStats] = {}
    last_packet_ids: dict[str, int] = {}
    links: set[str] = set()
    first_ms: int | None = None
    last_ms: int | None = None
    bad_rows = 0

    csv.field_size_limit(1 << 24)

    # raw 파일 순서 = 수신 순서이므로 정렬 없이 그대로 재생한다
    # (packet_id gap 계산이 순서에 의존).
    with raw_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                host_ms = int(row["host_epoch_ms"])
                link_id = row["link_id"]
                packet_id = int(row["packet_id"])
                rssi = int(row["rssi"])
            except (KeyError, TypeError, ValueError):
                bad_rows += 1
                continue

            if only_links and link_id not in only_links:
                continue

            if first_ms is None:
                first_ms = host_ms
                # live와 동일하게 첫 완전한 5초 grid부터 집계
                feature_start = next_grid_start_ms(host_ms)
            last_ms = host_ms
            links.add(link_id)

            if host_ms < feature_start:
                continue

            stats = windows.setdefault(
                (grid_start_ms(host_ms), link_id), WindowStats()
            )
            update_window_stats(
                stats=stats,
                packet_id=packet_id,
                link_id=link_id,
                last_packet_ids=last_packet_ids,
                rssi=rssi,
                mean_amplitude=calculate_packet_mean_amplitude(
                    row.get("csi_data") or ""
                ),
            )

    if first_ms is None:
        raise SystemExit(f"No valid rows in {raw_path}")

    # 마지막 불완전 window는 제외
    stop = grid_start_ms(last_ms)
    if end_ms is not None:
        # 링크 끊김 등으로 잘라낼 때: end_ms 이후에 시작하는 window는 버린다
        stop = min(stop, end_ms)
    all_starts = list(range(feature_start, stop, WINDOW_MS))
    n = len(all_starts)
    lo = n * (part - 1) // parts
    hi = n * part // parts
    selected = all_starts[lo:hi]

    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / readme_filename(feature_start)

    # 같은 분(HHMM)에 시작한 세션끼리 이름이 겹칠 수 있으므로 덮어쓰지 않는다
    if output_path.exists() and not overwrite:
        raise SystemExit(
            f"Output already exists: {output_path} "
            "(--output으로 다른 이름을 주거나 --overwrite 사용)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FEATURE_FIELDS)
        for window_start in selected:
            for link_id in sorted(links):
                writer.writerow(
                    feature_row(
                        window_start,
                        link_id,
                        windows.get((window_start, link_id), WindowStats()),
                        expected_packet_count,
                    )
                )

    print(f"raw          : {raw_path}")
    print(f"links        : {', '.join(sorted(links))}")
    print(f"bad rows     : {bad_rows}")
    print(f"total windows: {n} ({n * WINDOW_MS / 60_000:.1f} min)")
    print(
        f"part {part}/{parts}     : windows {lo}~{hi - 1} "
        f"({len(selected)} windows, "
        f"{selected[0] if selected else '-'} ~ "
        f"{selected[-1] + WINDOW_MS if selected else '-'})"
    )
    print(f"output       : {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Raw CSI CSV를 5초 feature CSV로 오프라인 변환"
    )
    parser.add_argument("raw", type=Path, help="raw CSI CSV 경로")
    parser.add_argument(
        "--expected-pps",
        type=float,
        required=True,
        help="수집 당시 TX PPS (예: 36)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="출력 경로 (기본값: data/csi/processed/csi_YYYYMMDD_HHMM.csv)",
    )
    parser.add_argument(
        "--parts",
        type=int,
        default=1,
        help="시간순으로 N등분 (기본값: 1 = 전체)",
    )
    parser.add_argument(
        "--part",
        type=int,
        default=1,
        help="N등분 중 출력할 구간 번호, 1부터 (기본값: 1)",
    )
    parser.add_argument(
        "--links",
        help="사용할 link ID, 쉼표 구분 (기본값: raw에 있는 전부. 예: link_3)",
    )
    parser.add_argument(
        "--end-ms",
        type=int,
        help="유효 구간 종료 시각 epoch ms (이 시각 이후 시작하는 window 제외)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="출력 파일이 이미 있으면 덮어쓴다",
    )
    args = parser.parse_args()

    if args.expected_pps <= 0:
        parser.error("--expected-pps must be positive")
    if not 1 <= args.part <= args.parts:
        parser.error("--part must be between 1 and --parts")

    only_links = (
        {x.strip() for x in args.links.split(",") if x.strip()}
        if args.links
        else None
    )
    process(
        args.raw,
        args.output,
        args.expected_pps,
        args.parts,
        args.part,
        only_links=only_links,
        overwrite=args.overwrite,
        end_ms=args.end_ms,
    )


if __name__ == "__main__":
    main()
