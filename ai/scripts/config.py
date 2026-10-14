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


def to_level(n_people, capacity=CAPACITY):
    pct = n_people / capacity
    if pct <= 0.30:
        return "여유"
    if pct < 0.70:
        return "보통"
    return "혼잡"
