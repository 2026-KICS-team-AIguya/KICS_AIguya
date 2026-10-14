"""실측 feature CSV 또는 명시적인 인공 입력으로 서버 연결을 테스트한다."""
import argparse
import csv
import math
import sys
import time
from itertools import count as sequence
from pathlib import Path

import requests

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.scripts.config import FEATURES
from pipeline.stream_csi import post_frame


def feature_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(FEATURES) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing feature columns: {sorted(missing)}")
        for row in reader:
            result = {}
            for name in FEATURES:
                value = float(row[name]) if row[name].strip() else None
                result[name] = value if value is not None and math.isfinite(value) else None
            yield result


def synthetic_rows(count=None):
    # 정확도 평가용 데이터가 아니다. 로드·준비·추론·API 연결 확인에만 사용한다.
    for index in range(count) if count is not None else sequence():
        yield {name: feature_index + 1 + math.sin(index / 7) * .2 for feature_index, name in enumerate(FEATURES)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--feature-file", type=Path)
    source.add_argument("--synthetic", action="store_true")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--location", default="sangnok")
    parser.add_argument("--floor", type=int, default=1)
    parser.add_argument("--link", default="link_3")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--continuous", action="store_true", help="Keep synthetic test input running until Ctrl+C")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("count must be positive")
    if args.continuous and not args.synthetic:
        parser.error("--continuous is only available with --synthetic")
    rows = feature_rows(args.feature_file) if args.feature_file else synthetic_rows(None if args.continuous else args.count)
    print("TEST REPLAY: restart the backend before switching to live sensors.", flush=True)
    if args.continuous:
        print("Continuous synthetic input. Stop this terminal with Ctrl+C.", flush=True)
    try:
        with requests.Session() as session:
            for index, features in enumerate(rows):
                if not args.continuous and index >= args.count:
                    break
                timestamp = int(time.time() * 1000) // 5000 * 5000 - 5000
                frame = {"timestamp": timestamp, "link_id": args.link, "features": features}
                result = post_frame(session, args.server, frame, args.location, args.floor,
                                    input_kind="synthetic" if args.synthetic else "replay")
                print(timestamp, result["inference"], flush=True)
                time.sleep(5)
    except KeyboardInterrupt:
        print("Replay stopped.", flush=True)
    else:
        print("Replay finished. No more data will be sent; the dashboard becomes stale after 30 seconds.", flush=True)


if __name__ == "__main__":
    main()
