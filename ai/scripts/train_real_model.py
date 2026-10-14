# -*- coding: utf-8 -*-
"""
실측 기준점 + 보간으로 혼잡도 3단계 모델 학습 (프로토타입).

배경 (ai/docs/01_model_experiment_report.md 5-2절):
- 이전 모델은 CountFi 기반 synthetic으로 학습해 "인원이 늘면 RSSI 평균이 크게 오른다"고 배웠지만,
  실측에서 RSSI 평균은 장소·설치·재부팅마다 오르내려 실서비스에서 항상 "여유"만 나왔다.
- 실측에서 일관되게 반응한 것은 동적 feature(시간에 따른 흔들림, 서브캐리어 상관, RSSI 흔들림)다.

방법:
1. 세션마다 빈 방 구간 첫 24개 window로 calibration → z-score (ai/main.py update()와 같은 함수).
2. 동적 feature만 사용 (DYNAMIC_FEATURES). 정적 feature(RSSI 평균, 진폭 평균, 진폭 범위)는 무시.
3. 실측 기준점 두 개로 "혼잡 방향" v를 정한다: 빈 방 = 0, 34명 착석 = 1.
4. 0~34명 사이는 신호가 인원에 비례한다고 가정(보간)하고, 실측 빈 방의 흔들림을 노이즈로 붙여
   보간 샘플을 만든다. 등급은 config.to_level(인원) 기준.
5. 보간 샘플 + 실측 기준점으로 로지스틱 회귀 학습. 평가는 실측만으로 한다.

한계: 보간 가정(인원 비례)은 검증되지 않았다. 34명 기준점은 재설치된 빈 방 대비 값 하나뿐이다.
돌아다니는 소수는 활동량이 커서 "보통/혼잡"으로 나올 수 있다(활동량 기반 판단).
"""

import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    CALIBRATION_WINDOWS,
    FEATURES,
    LEVELS,
    apply_baseline,
    fit_baseline,
    to_level,
)
from real_sessions import (  # noqa: E402
    CROWD_PEOPLE,
    CROWD_SEGMENT,
    EMPTY_SEGMENTS,
    SESSIONS_1014,
)

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
N_SYNTH = 6000
rng = np.random.default_rng(14)


def kst_hhmm(ts):
    return (
        pd.to_datetime(ts, unit="ms", utc=True)
        .dt.tz_convert("Asia/Seoul")
        .dt.strftime("%H:%M")
    )


def load_1014():
    """세션별 (유효 window, 구간 라벨) DataFrame과 calibration 기준을 만든다."""
    frames, baselines = {}, {}
    for name, spec in SESSIONS_1014.items():
        d = pd.read_csv(os.path.join(REAL_DIR, spec["file"])).sort_values("timestamp")
        d = d.dropna(subset=FEATURES).copy()  # 추론도 결측 window는 skipped
        d["hhmm"] = kst_hhmm(d["timestamp"])
        d["segment"] = -1
        for i, (start, end, _, _) in enumerate(spec["segments"]):
            d.loc[(d["hhmm"] >= start) & (d["hhmm"] < end), "segment"] = i
        frames[name] = d
        if "baseline" in spec:
            start, end = spec["baseline"]
            calib = d[(d["hhmm"] >= start) & (d["hhmm"] < end)].head(
                CALIBRATION_WINDOWS
            )
            baselines[name] = fit_baseline(calib[FEATURES].values)
    for name, spec in SESSIONS_1014.items():
        if "baseline_session" in spec:
            baselines[name] = baselines[spec["baseline_session"]]
    return frames, baselines


def load_1008():
    """10/8 실측: warmup 의심 구간 제외, 세션 첫 24개 유효 window를 기준으로 사용."""
    real = pd.read_csv(LABELED_1008_PATH)
    real = real[~real["possible_session_warmup"].astype(bool)]
    real = real.dropna(subset=FEATURES).sort_values(["session", "timestamp"])
    out = []
    for session, d in real.groupby("session"):
        mean, std = fit_baseline(d[FEATURES].values[:CALIBRATION_WINDOWS])
        z = apply_baseline(d[FEATURES].values, mean, std)
        out.append((f"1008_{session}", d["n_people"].values, z))
    return out


def z_of(frames, baselines, name, segment):
    d = frames[name]
    mean, std = baselines[name]
    return apply_baseline(d.loc[d["segment"] == segment, FEATURES].values, mean, std)


def build_training_set(frames, baselines):
    empty_z = np.vstack([z_of(frames, baselines, n, s) for n, s in EMPTY_SEGMENTS])
    crowd_z = z_of(frames, baselines, *CROWD_SEGMENT)
    direction = crowd_z.mean(axis=0) - empty_z.mean(axis=0)  # 빈 방 → 34명 착석

    # 보간 샘플: 인원 n에 비례해 direction 방향으로 이동 + 실측 빈 방 흔들림(부트스트랩)
    people = rng.uniform(0, CROWD_PEOPLE * 1.3, N_SYNTH)
    noise = empty_z[rng.integers(0, len(empty_z), N_SYNTH)] - empty_z.mean(axis=0)
    synth_x = (people / CROWD_PEOPLE)[:, None] * direction + noise
    synth_y = np.array([to_level(n) for n in people])

    x = np.vstack([synth_x, empty_z, crowd_z])
    y = np.concatenate(
        [synth_y, [to_level(0)] * len(empty_z), [to_level(CROWD_PEOPLE)] * len(crowd_z)]
    )
    return x, y, direction


def build_model():
    return Pipeline(
        [
            # 동적 feature만 사용. 입력은 FEATURES 11개 그대로 받아 추론 코드 변경이 필요 없다.
            ("dynamic", ColumnTransformer([("keep", "passthrough", DYNAMIC_IDX)])),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]
    )


def report(model, frames, baselines):
    rows = []
    for name, spec in SESSIONS_1014.items():
        for i, (start, end, n, activity) in enumerate(spec["segments"]):
            z = z_of(frames, baselines, name, i)
            if len(z) == 0:
                continue
            rows.append((name, f"{start}~{end}", n, activity, model.predict(z)))
    for name, people, z in load_1008():
        for n in sorted(set(people)):
            rows.append((name, "-", n, "기록 없음", model.predict(z[people == n])))

    table = []
    for name, span, n, activity, pred in rows:
        share = pd.Series(pred).value_counts(normalize=True)
        table.append(
            {
                "세션": name,
                "구간": span,
                "인원": n,
                "행동": activity,
                "정답": to_level(n),
                "window": len(pred),
                **{lv: int(round(share.get(lv, 0) * 100)) for lv in LEVELS},
            }
        )
    print(pd.DataFrame(table).to_string(index=False))


def main():
    frames, baselines = load_1014()
    x, y, direction = build_training_set(frames, baselines)
    print("혼잡 방향 (빈 방 → 34명 착석, 동적 feature z):")
    print(
        pd.Series(direction[DYNAMIC_IDX], index=DYNAMIC_FEATURES).round(2).to_string()
    )

    model = build_model().fit(x, y)
    print("\n=== 실측 평가 (세션별 빈 방 기준 calibration 후 예측, 등급 비율 %) ===")
    print("※ 34명 착석·빈 방 구간은 기준점으로 학습에 쓰였으므로 맞히는 것이 당연하다.")
    report(model, frames, baselines)

    joblib.dump(model, MODEL_OUT_PATH)
    print(f"\n최종 모델 저장: {MODEL_OUT_PATH}")


if __name__ == "__main__":
    main()
