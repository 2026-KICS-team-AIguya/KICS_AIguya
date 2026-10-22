# -*- coding: utf-8 -*-
"""
실측 라벨로 혼잡도 3단계 모델 학습 — 움직임 특징 결정트리 (ai/docs/01_model_experiment_report.md 5-5절).

배경:
- 10/15 하루치 다인원 데이터로 학습한 HistGradientBoosting(동적 특징값 8개)은 10/19 시연에서 혼잡을
  한 번도 내지 못했다. 날짜별 교차 검증에서도 혼잡 재현율 0%.
- 원인: 서브캐리어 상관·시간 변화 특징은 날마다 방향이 반대로 바뀌었고(10/15 군중은 상관 상승,
  10/19 군중은 하락), 모델이 하루치 패턴을 외웠다. 반면 RSSI 흔들림은 두 날 모두 입장 z≈+5,
  퇴실 z≈+7로 같은 방향이었다.

방법:
1. 세션마다 calibration(첫 24개 유효 window) → z-score. ai/main.py update()와 같은 함수.
2. RSSI 흔들림 z로 config.MotionTracker가 [30초 평균, 3분 최댓값]을 만든다. 추론과 같은 클래스.
3. real_sessions.py의 구간 라벨로 얕은 결정트리(깊이 3)를 학습한다. 기준값(+2, +4 같은 경계)과
   혼잡 유지 시간을 사람이 정하지 않고 모델이 데이터에서 정한다.
4. 평가는 날짜별 교차 검증: 한 날(10/14, 10/15, 10/19)을 통째로 빼고 학습 → 그날 예측.

한계:
- 착석 인원은 감지하지 못한다. 앉은 사람은 RSSI가 거의 흔들리지 않는다(10/19 착석 21명 z≈0).
  3분 최댓값으로 입장 직후 착석은 버티지만, 그보다 오래 조용하면 등급이 내려간다.
- 10/19 구간 시각은 현장 진술과 신호로 추정했다. 다인원 실측은 2회뿐이다.
- 10/8 세션은 카톡 기반 인원 라벨이고 연속 시계열이 아니어서 학습에서 뺐다.
"""

import os
import sys

import joblib
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.tree import DecisionTreeClassifier, export_text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    CALIBRATION_WINDOWS,
    FEATURES,
    LEVELS,
    MIN_PACKETS,
    MOTION_FEATURE,
    MOTION_INPUTS,
    MotionTracker,
    apply_baseline,
    fit_baseline,
    to_level,
)
from real_sessions import SESSIONS  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL_DIR = os.path.join(REPO_ROOT, "data", "ai", "real")
# 서버·테스트가 이 경로를 쓰므로 파일 이름은 유지한다 (내용은 결정트리).
MODEL_OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "model_hgb_final.joblib")
MOTION_IDX = FEATURES.index(MOTION_FEATURE)


def kst_time(ts):
    return (
        pd.to_datetime(ts, unit="ms", utc=True)
        .dt.tz_convert("Asia/Seoul")
        .dt.strftime("%H:%M:%S")
    )


def session_motion(d):
    """한 세션의 유효 window를 시간순으로 흘려 (z 전체, 움직임 입력) 표를 만든다. 추론과 같은 순서."""
    mean, std = fit_baseline(d[FEATURES].values[:CALIBRATION_WINDOWS])
    z = apply_baseline(d[FEATURES].values, mean, std)
    tracker = MotionTracker()
    motion = [tracker.push(v) for v in z[:, MOTION_IDX]]
    return pd.DataFrame(motion, columns=MOTION_INPUTS, index=d.index)


def load_windows():
    """라벨이 붙은 실측 window를 (session, day, time, n, activity, label, 움직임 입력) 한 표로 만든다."""
    parts = []
    for name, spec in SESSIONS.items():
        if not spec.get("use", True):
            continue
        d = pd.read_csv(os.path.join(REAL_DIR, spec["file"])).sort_values("timestamp")
        # 추론도 결측·패킷 부족 window는 skipped → 학습에서도 뺀다
        d = d[d["csi_packet_count"] >= MIN_PACKETS].dropna(subset=FEATURES).copy()
        d["time"] = kst_time(d["timestamp"])
        motion = session_motion(d)
        for start, end, n, activity, level in spec["segments"]:
            mask = (d["time"] >= start) & (d["time"] < end)
            seg = motion[mask].copy()
            seg["session"], seg["day"], seg["time"] = name, name[:4], d.loc[mask, "time"]
            seg["n"], seg["activity"] = n, activity
            seg["label"] = level or to_level(n)
            parts.append(seg)
    return pd.concat(parts, ignore_index=True)


def build_model():
    return DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=0)


def evaluate_leave_one_day_out(data):
    """한 날을 통째로 빼고 학습 → 그날 예측. 학습한 날과 다른 날에도 통하는지 본다."""
    pred = pd.Series(index=data.index, dtype=object)
    for day in data["day"].unique():
        test = data["day"] == day
        model = build_model().fit(
            data.loc[~test, MOTION_INPUTS].values, data.loc[~test, "label"].values
        )
        pred[test] = model.predict(data.loc[test, MOTION_INPUTS].values)
    return pred


def summarize(data, pred):
    frame = data.assign(pred=pred)
    rows = []
    for (session, activity, label), g in frame.groupby(
        ["session", "activity", "label"], sort=False
    ):
        row = {
            "세션": session,
            "구간": f"{g['time'].min()}~{g['time'].max()}",
            "인원": f"{g['n'].min()}~{g['n'].max()}",
            "행동": activity,
            "정답": label,
            "window": len(g),
        }
        row.update({lv: int(round((g["pred"] == lv).mean() * 100)) for lv in LEVELS})
        rows.append(row)
    return pd.DataFrame(rows)


def report(data, pred):
    y = data["label"]
    print(f"정확도 {accuracy_score(y, pred) * 100:.1f}%  (window {len(y)}개)")
    for day in data["day"].unique():
        m = data["day"] == day
        print(f"  {day} 정확도 {accuracy_score(y[m], pred[m]) * 100:.1f}%")
    print(classification_report(y, pred, labels=LEVELS, digits=3, zero_division=0))


def main():
    pd.set_option("display.width", 250)
    data = load_windows()
    print("학습 데이터 (window 수):")
    print(data.groupby(["session", "label"]).size().unstack(fill_value=0).to_string())

    print("\n=== 날짜별 교차 검증 (한 날 제외 학습 → 그날 예측) ===")
    pred = evaluate_leave_one_day_out(data)
    report(data, pred)
    print(summarize(data, pred).to_string(index=False))

    model = build_model().fit(data[MOTION_INPUTS].values, data["label"].values)
    print("\n=== 최종 모델 (전체 학습) 판단 규칙 ===")
    print(export_text(model, feature_names=MOTION_INPUTS))
    joblib.dump(model, MODEL_OUT_PATH)
    print(f"최종 모델 저장: {MODEL_OUT_PATH}")


if __name__ == "__main__":
    main()
