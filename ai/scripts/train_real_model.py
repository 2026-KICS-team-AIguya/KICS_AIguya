# -*- coding: utf-8 -*-
"""
실측 라벨로 혼잡도 3단계 모델 학습 (프로토타입, ai/docs/01_model_experiment_report.md 5-3절).

배경:
- synthetic(CountFi) 모델은 실측에서 항상 "여유"였다(5-2절).
- 10/14 "빈 방 vs 34명 착석" 기준점 보간 모델은 재설치된 빈 방과 비교한 값이라, 10/15 같은 설치에서
  연속으로 찍은 수업에서는 착석 35명을 "여유"로 판단했다. 착석 수업은 오히려 흔들림이 낮았다.
- 10/15 실측(1명 → 35명 입장, 수업, 퇴실)은 같은 설치·연속·인원 기록이 모두 있는 첫 데이터다.

방법:
1. 세션마다 calibration(첫 24개 유효 window) → z-score. ai/main.py update()와 같은 함수.
2. 동적 feature만 사용(DYNAMIC_FEATURES). 장소·설치·재부팅마다 방향이 바뀌는 정적 feature 제외.
3. real_sessions.py의 구간 라벨(입장 중은 인원 기준, 착석 수업·퇴실은 "혼잡")로 직접 학습.
   착석 수업(조용한데 사람 많음)과 소수 활동(움직임 많은데 사람 적음)을 나누려면 비선형 경계가
   필요해 얕은 gradient boosting을 쓴다.
4. 평가는 실측만: (a) 세션 하나를 통째로 빼고 학습 후 그 세션 예측, (b) 10/15 안에서 시간 블록을
   빼고 예측. 화면과 같은 1분(12 window) 평균 등급도 함께 본다.

한계: 다인원 실측은 10/15 한 세션뿐이라 다른 장소·날짜로 일반화된다는 근거는 없다.
"""

import os
import sys

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    CALIBRATION_WINDOWS,
    FEATURES,
    LEVELS,
    SMOOTHING_WINDOWS,
    apply_baseline,
    decide_level,
    fit_baseline,
    to_level,
)
from real_sessions import SESSIONS  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL_DIR = os.path.join(REPO_ROOT, "data", "ai", "real")
LABELED_1008_PATH = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")
MODEL_OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "model_hgb_final.joblib")

DYNAMIC_FEATURES = [
    "csi_amp_std",
    "csi_amp_var",
    "csi_distortion_cv_pct",
    "csi_sc_corr_mean",
    "csi_temporal_var_mean",
    "csi_temporal_diff_mean",
    "csi_temporal_diff_std",
    "csi_rssi_std",
]
DYNAMIC_IDX = [FEATURES.index(f) for f in DYNAMIC_FEATURES]
# 10/15 안에서 빼고 검증할 시간 블록
BLOCKS_1015 = [
    ("12:27", "12:45"),
    ("12:45", "13:00"),
    ("13:00", "13:30"),
    ("13:30", "14:04"),
]


def kst_hhmm(ts):
    return (
        pd.to_datetime(ts, unit="ms", utc=True)
        .dt.tz_convert("Asia/Seoul")
        .dt.strftime("%H:%M")
    )


def load_windows():
    """모든 실측 window를 (session, hhmm, n, activity, label, z...) 한 표로 만든다."""
    parts = []
    for name, spec in SESSIONS.items():
        if not spec.get("use", True):
            continue
        d = pd.read_csv(os.path.join(REAL_DIR, spec["file"])).sort_values("timestamp")
        d = d.dropna(subset=FEATURES).copy()  # 추론도 결측 window는 skipped
        d["hhmm"] = kst_hhmm(d["timestamp"])
        calib = d
        if "baseline" in spec:
            start, end = spec["baseline"]
            calib = d[(d["hhmm"] >= start) & (d["hhmm"] < end)]
        mean, std = fit_baseline(calib[FEATURES].values[:CALIBRATION_WINDOWS])
        z = pd.DataFrame(
            apply_baseline(d[FEATURES].values, mean, std),
            columns=FEATURES,
            index=d.index,
        )
        for start, end, n, activity, level in spec["segments"]:
            mask = (d["hhmm"] >= start) & (d["hhmm"] < end)
            seg = z[mask].copy()
            seg["session"], seg["hhmm"] = name, d.loc[mask, "hhmm"]
            seg["n"], seg["activity"] = n, activity
            seg["label"] = level or to_level(n)
            parts.append(seg)

    real = pd.read_csv(LABELED_1008_PATH)
    real = real[~real["possible_session_warmup"].astype(bool)]
    real = real.dropna(subset=FEATURES).sort_values(["session", "timestamp"])
    for session, d in real.groupby("session"):
        mean, std = fit_baseline(d[FEATURES].values[:CALIBRATION_WINDOWS])
        seg = pd.DataFrame(
            apply_baseline(d[FEATURES].values, mean, std), columns=FEATURES
        )
        seg["session"], seg["hhmm"] = f"1008_{session}", kst_hhmm(d["timestamp"]).values
        seg["n"], seg["activity"] = d["n_people"].values, "기록 없음"
        seg["label"] = [to_level(n) for n in d["n_people"]]
        parts.append(seg)
    return pd.concat(parts, ignore_index=True)


def build_model():
    return Pipeline(
        [
            # 입력은 FEATURES 11개 그대로 받고 동적 feature만 골라 쓴다 → 추론 코드 변경 불필요
            ("dynamic", ColumnTransformer([("keep", "passthrough", DYNAMIC_IDX)])),
            (
                "clf",
                HistGradientBoostingClassifier(
                    max_depth=3,
                    max_iter=150,
                    learning_rate=0.05,
                    l2_regularization=1.0,
                    class_weight="balanced",
                    random_state=15,
                ),
            ),
        ]
    )


def smoothed_levels(model, frame):
    """화면과 같은 방식: 최근 SMOOTHING_WINDOWS개 확률 평균 → decide_level."""
    proba = pd.DataFrame(
        model.predict_proba(frame[FEATURES].values), columns=model.classes_
    )
    smooth = proba.rolling(SMOOTHING_WINDOWS, min_periods=1).mean()
    return [decide_level(row) for row in smooth.to_dict("records")]


def summarize(frame, pred, smooth):
    rows = []
    keys = ["session", "activity", "label"]
    frame = frame.assign(pred=pred, smooth=smooth)
    for (session, activity, label), g in frame.groupby(keys, sort=False):
        row = {
            "세션": session,
            "구간": f"{g['hhmm'].min()}~{g['hhmm'].max()}",
            "인원": f"{g['n'].min()}~{g['n'].max()}",
            "행동": activity,
            "정답": label,
            "window": len(g),
            "정답률(5초)": int(round((g["pred"] == label).mean() * 100)),
            "정답률(1분평균)": int(round((g["smooth"] == label).mean() * 100)),
        }
        row.update({lv: int(round((g["smooth"] == lv).mean() * 100)) for lv in LEVELS})
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate_leave_one_session_out(data):
    out = []
    for session in data["session"].unique():
        train, test = data[data["session"] != session], data[data["session"] == session]
        if train["label"].nunique() < len(LEVELS):
            continue
        model = build_model().fit(train[FEATURES].values, train["label"].values)
        pred = model.predict(test[FEATURES].values)
        out.append(summarize(test, pred, smoothed_levels(model, test)))
    return pd.concat(out, ignore_index=True)


def evaluate_1015_blocks(data):
    out = []
    in_1015 = data["session"] == "1015_class"
    for start, end in BLOCKS_1015:
        held = in_1015 & (data["hhmm"] >= start) & (data["hhmm"] < end)
        model = build_model().fit(
            data.loc[~held, FEATURES].values, data.loc[~held, "label"].values
        )
        test = data[held]
        pred = model.predict(test[FEATURES].values)
        out.append(summarize(test, pred, smoothed_levels(model, test)))
    return pd.concat(out, ignore_index=True)


def main():
    pd.set_option("display.width", 250)
    data = load_windows()
    print("학습 데이터 (window 수):")
    print(data.groupby(["session", "label"]).size().unstack(fill_value=0).to_string())

    print("\n=== (a) 세션 하나를 빼고 학습 → 그 세션 예측 ===")
    print(
        "※ 10/15를 빼면 다인원 학습 데이터가 없어 보통·혼잡을 배울 수 없으므로 생략된다."
    )
    print(evaluate_leave_one_session_out(data).to_string(index=False))

    print("\n=== (b) 10/15 안에서 시간 블록을 빼고 학습 → 그 블록 예측 ===")
    print("※ 같은 세션의 인접 구간으로 학습하므로 (a)보다 낙관적인 수치다.")
    print(evaluate_1015_blocks(data).to_string(index=False))

    model = build_model().fit(data[FEATURES].values, data["label"].values)
    print("\n=== 최종 모델 (전체 학습) — 학습 데이터 재현, 참고용 ===")
    print(
        summarize(
            data, model.predict(data[FEATURES].values), smoothed_levels(model, data)
        ).to_string(index=False)
    )
    joblib.dump(model, MODEL_OUT_PATH)
    print(f"\n최종 모델 저장: {MODEL_OUT_PATH}")


if __name__ == "__main__":
    main()
