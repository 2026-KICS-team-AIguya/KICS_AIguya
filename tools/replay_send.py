"""
실측 CSI feature CSV를 5초마다 /ingest로 다시 보내는 리플레이 전송기.

mock_send.py는 CSI feature를 2개만 보내서 AI 모델(feature 11개 필요)을 붙이면 전부 skipped가 된다.
이 스크립트는 희수 실측 feature(기본: data/ai/labeled_real_final.csv)를 그대로 보내므로
실제 센서 없이 서버-AI 연동을 끝까지 테스트할 수 있다.

사용 예:
  python tools/replay_send.py                       # 전체 session, 5초 간격, timestamp는 현재 시각부터 5초씩
  python tools/replay_send.py --session 1658        # 특정 session만
  python tools/replay_send.py --interval 0.2        # 빠르게 재생 (calibration 2분을 5초 안에)
  python tools/replay_send.py --keep-timestamp      # CSV 원래 timestamp 유지
  python tools/replay_send.py --dry-run --limit 3   # 전송 없이 payload만 출력

CSV는 git에 없다 → 구글드라이브에서 받아 data/ai/ 에 둘 것.
"""

import argparse
import csv
import json
import os
import time

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")
DEFAULT_SERVER = "http://127.0.0.1:8000/ingest"
WINDOW_MS = 5000


def now_grid_ms() -> int:
    """현재 시각을 5초 grid로 내림. 규격: window 시작 시각."""
    return int(time.time() * 1000) // WINDOW_MS * WINDOW_MS


def to_value(text):
    """CSV 빈칸은 결측 → None(JSON null). 숫자는 int/float로 변환."""
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return float(text)


def load_rows(path, session=None):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if session is not None:
        rows = [r for r in rows if r.get("session") == session]
    return sorted(rows, key=lambda r: (r.get("session", ""), int(r["timestamp"])))


def to_payload(row, timestamp, link_id):
    features = {k: to_value(v) for k, v in row.items() if k.startswith("csi_")}
    return {
        "timestamp": timestamp,
        "source": "csi",
        "input_kind": "replay",
        "identifier": link_id or row.get("link_id") or "link_1",
        "features": features,
    }


def main():
    parser = argparse.ArgumentParser(
        description="실측 CSI feature CSV를 /ingest로 리플레이 전송"
    )
    parser.add_argument("--csv", default=DEFAULT_CSV, help="feature CSV 경로")
    parser.add_argument("--session", help="이 session만 전송 (예: 1658)")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="/ingest 주소")
    parser.add_argument("--interval", type=float, default=5.0, help="전송 간격(초)")
    parser.add_argument(
        "--link", help="identifier를 이 값으로 고정 (기본: CSV의 link_id)"
    )
    parser.add_argument(
        "--keep-timestamp", action="store_true", help="CSV 원래 timestamp 유지"
    )
    parser.add_argument("--limit", type=int, help="앞에서부터 N행만 전송")
    parser.add_argument(
        "--dry-run", action="store_true", help="전송하지 않고 payload만 출력"
    )
    args = parser.parse_args()

    rows = load_rows(args.csv, args.session)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("전송할 행이 없습니다. --csv / --session 값을 확인하세요.")
    print(
        f"{len(rows)}행 전송 시작 → {'dry-run' if args.dry_run else args.server} (Ctrl+C로 중지)"
    )

    sent = failed = 0
    # 빠르게 재생해도 timestamp는 행마다 5초씩 증가시켜 5초 grid 규격을 유지한다
    start_ts = now_grid_ms()
    for i, row in enumerate(rows, 1):
        ts = (
            int(row["timestamp"])
            if args.keep_timestamp
            else start_ts + (i - 1) * WINDOW_MS
        )
        payload = to_payload(row, ts, args.link)

        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            try:
                r = requests.post(args.server, json=payload, timeout=3)
                ok = r.status_code == 200
                if not ok:
                    print(f"  ⚠ {r.status_code} {r.text[:100]}")
            except requests.RequestException as e:
                print("전송 실패:", e)
                ok = False
            sent += ok
            failed += not ok
            label = f"실제 {row['n_people']}명" if row.get("n_people") else ""
            print(
                f"[{i}/{len(rows)}] session={row.get('session', '-')} ts={ts} {label}"
            )

        if i < len(rows):
            time.sleep(args.interval)

    if not args.dry_run:
        print(f"완료: 성공 {sent}, 실패 {failed}")


if __name__ == "__main__":
    main()
