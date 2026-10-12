# -*- coding: utf-8 -*-
"""
카카오톡 대화 내보내기(.txt)에서 이희수님이 남긴 "n월 n일 n시 n분 / N명" 형식의
인원수 라벨을 파싱하고, 같은 날짜의 실측 CSI(csi/processed + csi/candidate)와
timestamp 기준으로 매칭해 학습용 라벨 데이터셋을 만든다.

[개발 환경 안내]
이 스크립트는 레포 루트 기준 상대경로(data/...)를 사용한다.
카카오톡 export(.txt)와 CSI csv는 용량/민감정보 문제로 git에 포함되어 있지 않다 —
구글드라이브에서 받아 data/kakao/, data/csi/processed/, data/csi/candidate/ 에 배치할 것.

규칙:
- 라벨 시각은 "보낸 시각"이 아니라 메시지 본문에 적힌 시각(예: "5시 56분")을 사용한다
  (본문 작성 시점과 전송 시점 사이 지연이 있을 수 있어 본문 시각이 더 정확하다고 판단).
- 라벨은 다음 라벨이 나오기 전까지 유지되는 step function으로 간주한다.
- 직전 라벨로부터 15분(STALE_THRESHOLD_SEC) 이상 지난 CSI window는 라벨 신뢰도가
  낮다고 보고 is_stale=True로 표시만 하고 제거는 하지 않는다(필요 시 분석 단계에서 필터링).
- N=0 라벨이 해당 session 시작 후 15분 이내(elapsed_sec<=900)이면 "session warmup
  구간일 수 있다"고 보고 possible_session_warmup=True로 표시만 한다(삭제하지 않음).
"""

import re
import glob
import os
import pandas as pd
import pytz
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KAKAO_DIR = os.path.join(REPO_ROOT, "data", "kakao")
CSI_PROCESSED_DIR = os.path.join(REPO_ROOT, "data", "csi", "processed")
CSI_CANDIDATE_DIR = os.path.join(REPO_ROOT, "data", "csi", "candidate")
OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")

LABEL_AUTHOR = "이희수"
STALE_THRESHOLD_SEC = 900  # 15분
WARMUP_THRESHOLD_SEC = 900  # 15분

KST = pytz.timezone("Asia/Seoul")

HEADER_RE = re.compile(
    r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(오전|오후)\s*(\d{1,2}):(\d{2}),\s*([^:]+?)\s*:\s*(.*)$"
)
CONTENT_DATE_RE = re.compile(
    r"(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2})시\s*(?:(\d{1,2})분)?"
)
COUNT_RE = re.compile(r"^(\d{1,2})명\s*$")


def parse_kakao_labels(txt_path):
    """카카오톡 export에서 (epoch_ms, n_people) 라벨 리스트 추출."""
    with open(txt_path, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f]

    labels = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if not m or m.group(7).strip() != LABEL_AUTHOR:
            continue
        year = int(m.group(1))
        period = m.group(
            4
        )  # 오전/오후 - 본문의 "N시"는 12시간제라 헤더의 오전/오후로 보정 필요
        msg = m.group(8)
        dm = CONTENT_DATE_RE.search(msg)
        if not dm:
            continue
        month, day, hour12 = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        minute = int(dm.group(4)) if dm.group(4) else 0
        if period == "오후" and hour12 != 12:
            hour = hour12 + 12
        elif period == "오전" and hour12 == 12:
            hour = 0
        else:
            hour = hour12

        # 카운트가 같은 줄(공백 뒤)에 있을 수도, 바로 다음 줄에 있을 수도 있음
        count = None
        tail = msg[dm.end() :].strip()
        if tail:
            cm = COUNT_RE.match(tail)
            if cm:
                count = int(cm.group(1))
        if count is None and i + 1 < len(lines):
            cm = COUNT_RE.match(lines[i + 1].strip())
            if cm:
                count = int(cm.group(1))
        if count is None:
            continue

        dt = KST.localize(datetime(year, month, day, hour, minute))
        labels.append((int(dt.timestamp() * 1000), count))

    labels.sort()
    return pd.DataFrame(labels, columns=["label_ts_ms", "n_people"]).drop_duplicates()


def load_csi(session_date_prefix):
    """해당 날짜(YYYYMMDD)의 session별 csi(15개 production) + candidate(6개) join."""
    processed_files = sorted(
        glob.glob(os.path.join(CSI_PROCESSED_DIR, f"csi_{session_date_prefix}_*.csv"))
    )
    rows = []
    for fp in processed_files:
        session = os.path.splitext(os.path.basename(fp))[0].split("_")[-1]
        cand_fp = os.path.join(
            CSI_CANDIDATE_DIR, f"csi_{session_date_prefix}_{session}_cand.csv"
        )
        f1 = pd.read_csv(fp)
        f2 = pd.read_csv(cand_fp)
        merged = f1.merge(
            f2,
            on=["timestamp", "link_id", "csi_packet_count"],
            how="inner",
            suffixes=("", "_dup"),
        )
        merged["session"] = session
        rows.append(merged)
    return (
        pd.concat(rows, ignore_index=True)
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def main():
    txt_files = glob.glob(os.path.join(KAKAO_DIR, "*.txt"))
    assert txt_files, f"카카오톡 export(.txt)를 {KAKAO_DIR} 에 넣어주세요."
    label_df = pd.concat([parse_kakao_labels(f) for f in txt_files], ignore_index=True)
    label_df = label_df.sort_values("label_ts_ms").drop_duplicates(subset="label_ts_ms")
    print(f"파싱된 라벨 수: {len(label_df)}")

    csi_df = load_csi("20261008")
    print(f"CSI window 수: {len(csi_df)}")

    merged = pd.merge_asof(
        csi_df,
        label_df,
        left_on="timestamp",
        right_on="label_ts_ms",
        direction="backward",
    )
    merged["label_age_sec"] = (merged["timestamp"] - merged["label_ts_ms"]) / 1000
    merged["is_stale"] = merged["label_age_sec"] > STALE_THRESHOLD_SEC

    merged["session_start_ts"] = merged.groupby("session")["timestamp"].transform("min")
    merged["elapsed_sec"] = (merged["timestamp"] - merged["session_start_ts"]) / 1000
    merged["possible_session_warmup"] = (merged["n_people"] == 0) & (
        merged["elapsed_sec"] <= WARMUP_THRESHOLD_SEC
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    merged.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved: {OUT_PATH}")

    clean = merged[~merged["is_stale"] & merged["n_people"].notna()]
    print(f"\n유효(non-stale) labeled window: {len(clean)}")
    print(clean["n_people"].value_counts().sort_index())


if __name__ == "__main__":
    main()
