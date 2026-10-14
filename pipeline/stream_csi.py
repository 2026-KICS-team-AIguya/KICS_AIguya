"""완성된 raw CSV 행을 읽어 11개 특징값을 /ingest로 전달한다."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.features import FeatureAssembler


class CsvTail:
    def __init__(self, path, from_start=False):
        self.file = Path(path).open(encoding="utf-8-sig", newline="")
        self.fields = None
        self.from_start = from_start

    def rows(self):
        while True:
            position = self.file.tell()
            line = self.file.readline()
            if not line.endswith("\n"):
                self.file.seek(position)
                return
            values = next(csv.reader([line]))
            if self.fields is None:
                self.fields = values
                if not self.from_start:
                    self.file.seek(0, 2)
                continue
            if len(values) != len(self.fields):
                print("Skipping malformed raw CSV row", file=sys.stderr)
                continue
            yield dict(zip(self.fields, values))

    def close(self):
        self.file.close()


def post_frame(session, server, frame, location, floor, input_kind="sensor"):
    payload = {"source": "csi", "identifier": frame["link_id"], "timestamp": frame["timestamp"],
               "location_id": location, "floor": floor, "features": frame["features"], "input_kind": input_kind}
    # 요청 중 연결이 끊겨도 같은 행을 재전송한다. 서버는 중복으로 기준값을 늘리지 않는다.
    for attempt in range(3):
        try:
            response = session.post(server.rstrip("/") + "/ingest", json=payload, timeout=10)
            if response.status_code < 500:
                response.raise_for_status()
                return response.json()
        except requests.ConnectionError:
            if attempt == 2:
                raise
        except requests.Timeout:
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    response.raise_for_status()


def active_raw_file(directory, now=None):
    """과거 CSV를 재생하지 않고 현재 수집기가 쓰는 파일만 찾는다."""
    now = time.time() if now is None else now
    files = sorted(directory.glob("csi_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files:
        if not 0 <= now - path.stat().st_mtime <= 30:
            continue
        with path.open(encoding="utf-8-sig", newline="") as file:
            header = file.readline()
        required = {"host_epoch_ms", "link_id", "packet_id", "rssi", "csi_data"}
        if header.endswith("\n") and required.issubset(next(csv.reader([header]))):
            return path
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--raw-file", type=Path)
    source.add_argument("--raw-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data/csi/raw")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--location", default="sangnok")
    parser.add_argument("--floor", type=int, default=2)
    parser.add_argument("--link", default="link_3")
    parser.add_argument("--expected-pps", type=float, default=36)
    args = parser.parse_args()
    if args.expected_pps <= 0:
        parser.error("expected-pps must be positive")
    tail = None
    try:
        path = args.raw_file
        if path is None:
            print(f"Waiting for an active CSI capture in {args.raw_dir}", flush=True)
            while path is None:
                path = active_raw_file(args.raw_dir)
                if path is None:
                    time.sleep(1)
        assembler = FeatureAssembler(args.link, args.expected_pps)
        tail = CsvTail(path)
        print(f"Live capture: {path}\nDestination: {args.server} / {args.location} / floor {args.floor} / {args.link}", flush=True)
        with requests.Session() as session:
            while True:
                for row in tail.rows():
                    try:
                        assembler.add(row)
                    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
                        print(f"Skipping malformed packet: {error}", file=sys.stderr)
                for frame in assembler.complete(int(time.time() * 1000)):
                    result = post_frame(session, args.server, frame, args.location, args.floor)
                    inference = result["inference"]
                    print(frame["timestamp"], inference["status"], inference.get("progress") or inference.get("level", ""), flush=True)
                time.sleep(.25)
    except KeyboardInterrupt:
        pass
    except requests.RequestException as error:
        detail = error.response.text[:500] if error.response is not None else "Check the backend address and connection."
        raise SystemExit(f"CSI forwarding stopped: {error}\n{detail}") from error
    finally:
        if tail is not None:
            tail.close()


if __name__ == "__main__":
    main()
