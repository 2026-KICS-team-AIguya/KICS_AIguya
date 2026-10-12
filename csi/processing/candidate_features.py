"""
Raw CSI CSV → 후보 feature CSV (AI 담당 feature 검증용).

기존 feature(offline_feature.py)와 별도 파일로 저장한다.
timestamp 기준(5초 grid, 첫 완전한 grid부터)은 offline_feature.py와 같으므로
timestamp + link_id로 join할 수 있다.

계산 정의 (window = 5초, 패킷은 raw 파일 순서 = 수신 순서):
  X[p, k] = 패킷 p의 서브캐리어 k 진폭 sqrt(I^2 + Q^2)
            서브캐리어 128개 중 null(28~36) 9개 제외 → 119개
  같은 window 안에서 중복 packet_id는 첫 번째만 사용

  csi_sc_corr_mean      서브캐리어 시계열(X의 각 열)끼리의 Pearson 상관계수,
                        상삼각(대각 제외) 평균. window 안에서 값이 변하지 않는
                        서브캐리어는 그 window 계산에서 제외
  csi_temporal_var_mean 서브캐리어별 시간 방향 분산(모분산)의 평균
  csi_temporal_diff_mean / csi_temporal_diff_std
                        packet_id가 바로 이어지는 연속 패킷 쌍만 사용.
                        d = mean_k |X[p, k] - X[p-1, k]| 의 평균 / 표준편차
  csi_amp_range         window 안 X 전체(packet x subcarrier)의 max - min
  csi_rssi_std          패킷 RSSI의 표준편차(모표준편차)

  패킷 수가 MIN_PACKETS 미만이면 위 feature는 모두 빈칸.
  연속 패킷 쌍이 2개 미만이면 temporal_diff 두 개만 빈칸.

사용 예:
    venv/bin/python csi/processing/candidate_features.py \
        data/csi/raw/csi_20261008_8.csv --end-ms 1791454415000
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logger"))

from tcp_receiver import (  # noqa: E402
    WINDOW_MS,
    grid_start_ms,
    next_grid_start_ms,
)
from offline_feature import readme_filename  # noqa: E402

SUBCARRIER_COUNT = 128
NULL_SUBCARRIERS = set(range(28, 37))
VALID_SUBCARRIERS = np.array(
    [k for k in range(SUBCARRIER_COUNT) if k not in NULL_SUBCARRIERS]
)
MIN_PACKETS = 30
DEFAULT_OUTPUT_DIR = Path("data/csi/candidate")

FEATURE_FIELDS = [
    "timestamp",
    "link_id",
    "csi_packet_count",
    "csi_consecutive_pair_count",
    "csi_sc_corr_mean",
    "csi_temporal_var_mean",
    "csi_temporal_diff_mean",
    "csi_temporal_diff_std",
    "csi_amp_range",
    "csi_rssi_std",
]


def packet_amplitudes(csi_data: str) -> np.ndarray | None:
    values = json.loads(csi_data)
    if len(values) != SUBCARRIER_COUNT * 2:
        return None
    iq = np.asarray(values, dtype=np.float32).reshape(-1, 2)
    amp = np.sqrt((iq * iq).sum(axis=1))
    return amp[VALID_SUBCARRIERS]


def sc_corr_mean(x: np.ndarray) -> float | None:
    varying = x.std(axis=0) > 0
    if varying.sum() < 2:
        return None
    corr = np.corrcoef(x[:, varying], rowvar=False)
    upper = corr[np.triu_indices_from(corr, k=1)]
    return float(upper.mean())


def window_features(
    packet_ids: list[int],
    amps: list[np.ndarray],
    rssis: list[int],
) -> list:
    n = len(amps)
    if n < MIN_PACKETS:
        return [n, "", "", "", "", "", "", ""]

    x = np.vstack(amps).astype(np.float64)

    ids = np.asarray(packet_ids, dtype=np.int64)
    consecutive = ((ids[1:] - ids[:-1]) & 0xFFFFFFFF) == 1
    pair_count = int(consecutive.sum())

    if pair_count >= 2:
        d = np.abs(np.diff(x, axis=0)).mean(axis=1)[consecutive]
        diff_mean = round(float(d.mean()), 4)
        diff_std = round(float(d.std()), 4)
    else:
        diff_mean = diff_std = ""

    corr = sc_corr_mean(x)

    return [
        n,
        pair_count,
        round(corr, 4) if corr is not None else "",
        round(float(x.var(axis=0).mean()), 4),
        diff_mean,
        diff_std,
        round(float(x.max() - x.min()), 4),
        round(float(np.std(rssis)), 4),
    ]


def process(
    raw_path: Path,
    output_path: Path | None,
    link: str,
    end_ms: int | None,
    overwrite: bool,
) -> None:
    csv.field_size_limit(1 << 24)

    # window_start → (packet_ids, amps, rssis)
    windows: dict[int, tuple[list[int], list[np.ndarray], list[int]]] = {}
    seen: dict[int, set[int]] = {}
    feature_start: int | None = None
    last_ms: int | None = None
    bad_rows = 0

    with raw_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("link_id") != link:
                continue
            try:
                host_ms = int(row["host_epoch_ms"])
                packet_id = int(row["packet_id"])
                rssi = int(row["rssi"])
                amp = packet_amplitudes(row["csi_data"])
            except (KeyError, TypeError, ValueError):
                bad_rows += 1
                continue
            if amp is None:
                bad_rows += 1
                continue

            if feature_start is None:
                feature_start = next_grid_start_ms(host_ms)
            last_ms = host_ms
            if host_ms < feature_start:
                continue

            w = grid_start_ms(host_ms)
            ids_seen = seen.setdefault(w, set())
            if packet_id in ids_seen:
                continue
            ids_seen.add(packet_id)

            ids, amps, rssis = windows.setdefault(w, ([], [], []))
            ids.append(packet_id)
            amps.append(amp)
            rssis.append(rssi)

    if feature_start is None:
        raise SystemExit(f"No valid {link} rows in {raw_path}")

    stop = grid_start_ms(last_ms)
    if end_ms is not None:
        stop = min(stop, end_ms)
    starts = range(feature_start, stop, WINDOW_MS)

    if output_path is None:
        name = readme_filename(feature_start).replace(".csv", "_cand.csv")
        output_path = DEFAULT_OUTPUT_DIR / name
    if output_path.exists() and not overwrite:
        raise SystemExit(
            f"Output already exists: {output_path} (--overwrite 사용)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FEATURE_FIELDS)
        for w in starts:
            ids, amps, rssis = windows.get(w, ([], [], []))
            writer.writerow([w, link, *window_features(ids, amps, rssis)])

    print(f"raw          : {raw_path}")
    print(f"bad rows     : {bad_rows}")
    print(f"windows      : {len(starts)}")
    print(f"output       : {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Raw CSI CSV에서 후보 feature(서브캐리어 상관 등) 계산"
    )
    parser.add_argument("raw", type=Path, help="raw CSI CSV 경로")
    parser.add_argument("--link", default="link_3", help="기본값: link_3")
    parser.add_argument(
        "--end-ms",
        type=int,
        help="유효 구간 종료 시각 epoch ms (이 시각 이후 시작하는 window 제외)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="출력 경로 (기본값: data/csi/candidate/csi_YYYYMMDD_HHMM_cand.csv)",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    process(args.raw, args.output, args.link, args.end_ms, args.overwrite)


if __name__ == "__main__":
    main()
