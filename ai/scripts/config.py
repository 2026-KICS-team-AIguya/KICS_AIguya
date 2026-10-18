# -*- coding: utf-8 -*-
"""ai/ 파이프라인 공용 설정. train_model.py, main.py 양쪽에서 import해서 쓴다."""

import numpy as np

FEATURES = [
    "csi_rssi_mean",
    "csi_amp_mean",
    "csi_amp_std",
    "csi_amp_var",
    "csi_distortion_cv_pct",
    "csi_sc_corr_mean",
    "csi_temporal_var_mean",
    "csi_temporal_diff_mean",
    "csi_temporal_diff_std",
    "csi_amp_range",
    "csi_rssi_std",
]

# TODO: 팀 확정값으로 교체. 현재는 강의실 프로토타입 기준 임시값(README 미결사항 참고)
CAPACITY = 30

LEVELS = ["여유", "보통", "혼잡"]

# session 시작 후 이 개수만큼의 유효 window(5초 x 24 = 2분)로 baseline을 잡는다.
# 학습(train_model.py)과 추론(main.py)이 같은 함수로 정규화해야 기준이 어긋나지 않는다.
CALIBRATION_WINDOWS = 24
MIN_STD = 1e-6  # calibration 구간에서 값이 거의 안 변한 feature의 0 나눗셈 방지
# 화면 등급이 5초마다 깜빡이지 않도록 최근 window 확률을 평균한다 (12개 = 1분).
# 10/14 실측 기준 1분 평균이 퇴실(혼잡)은 바로 잡으면서 착석·빈 방 등급은 안정적이었다.
SMOOTHING_WINDOWS = 12


def fit_baseline(values_2d):
    """calibration 구간 feature 행렬(window x FEATURES) -> (mean, std)."""
    arr = np.asarray(values_2d, dtype=float)
    return arr.mean(axis=0), np.maximum(arr.std(axis=0, ddof=1), MIN_STD)


def apply_baseline(values, mean, std):
    """feature 값(1개 행 또는 행렬)을 baseline 기준 z-score로 변환."""
    return (np.asarray(values, dtype=float) - mean) / std


# 등급 결정: 확률이 가장 큰 등급 대신 "여유 0, 보통 1, 혼잡 2" 확률 가중 점수로 정한다.
# 여유와 혼잡 사이에서 확률이 갈리는 애매한 구간이 "보통"으로 나온다 (10/15 실측에서 10~20명 입장 구간의
# "보통"이 최댓값 방식 35~40% → 점수 방식 70~89%, 학습에서 뺀 데이터 기준).
LEVEL_SCORE_CUTS = (0.5, 1.5)


def decide_level(proba):
    """{등급: 확률} → 등급. 학습 평가(train_real_model.py)와 추론(main.py)이 같이 쓴다."""
    score = proba.get("보통", 0.0) + 2 * proba.get("혼잡", 0.0)
    low, high = LEVEL_SCORE_CUTS
    if score < low:
        return "여유"
    return "보통" if score < high else "혼잡"


def to_level(n_people, capacity=CAPACITY):
    pct = n_people / capacity
    if pct <= 0.30:
        return "여유"
    if pct < 0.70:
        return "보통"
    return "혼잡"
