# -*- coding: utf-8 -*-
"""ai/ 파이프라인 공용 설정. train_model.py, main.py 양쪽에서 import해서 쓴다."""

from collections import deque

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

# 정원(등급 기준 인원). 10/16 시연 최대 인원 20명 기준: 여유 0~6명 · 보통 7~13명 · 혼잡 14명 이상.
# 바꾸면 학습 라벨이 달라지므로 train_real_model.py로 다시 학습해야 한다. 실제 서비스 공간 좌석 수로 교체 필요.
CAPACITY = 20

LEVELS = ["여유", "보통", "혼잡"]

# session 시작 후 이 개수만큼의 유효 window(5초 x 24 = 2분)로 baseline을 잡는다.
# 학습(train_real_model.py)과 추론(main.py)이 같은 함수로 정규화해야 기준이 어긋나지 않는다.
CALIBRATION_WINDOWS = 24
MIN_STD = 1e-6  # calibration 구간에서 값이 거의 안 변한 feature의 0 나눗셈 방지
# 5초 window의 패킷이 이보다 적으면 특징값을 믿을 수 없어 판정을 건너뛴다 (36pps 기준 기대 180개).
MIN_PACKETS = 30

# 움직임 특징 (01_model_experiment_report.md 5-5절).
# 10/15·10/19 두 날 모두 같은 방향으로 움직인 신호는 RSSI 흔들림뿐이었다(입장 z≈+5, 퇴실 z≈+7).
# 5초 순간값 대신 "최근 30초 평균"과 "그 평균의 최근 3분 최댓값"을 모델 입력으로 쓴다.
# 3분 최댓값은 사람들이 몰려 들어와 앉은 뒤 신호가 잠잠해져도 한동안 혼잡을 유지하게 한다.
MOTION_FEATURE = "csi_rssi_std"
MOTION_SHORT_WINDOWS = 6  # 5초 x 6 = 30초
MOTION_HOLD_WINDOWS = 36  # 5초 x 36 = 3분
MOTION_INPUTS = ["rssi_std_30s_mean", "rssi_std_3min_max"]


def fit_baseline(values_2d):
    """calibration 구간 feature 행렬(window x FEATURES) -> (mean, std)."""
    arr = np.asarray(values_2d, dtype=float)
    return arr.mean(axis=0), np.maximum(arr.std(axis=0, ddof=1), MIN_STD)


def apply_baseline(values, mean, std):
    """feature 값(1개 행 또는 행렬)을 baseline 기준 z-score로 변환."""
    return (np.asarray(values, dtype=float) - mean) / std


class MotionTracker:
    """baseline z-score된 RSSI 흔들림을 5초마다 받아 모델 입력 [30초 평균, 3분 최댓값]을 만든다.

    학습(train_real_model.py)과 추론(main.py)이 같은 클래스를 써서 입력 계산이 어긋나지 않게 한다.
    """

    def __init__(self):
        self._z = deque(maxlen=MOTION_SHORT_WINDOWS)
        self._short = deque(maxlen=MOTION_HOLD_WINDOWS)

    def push(self, z):
        self._z.append(float(z))
        short = sum(self._z) / len(self._z)
        self._short.append(short)
        return [short, max(self._short)]


def to_level(n_people, capacity=CAPACITY):
    pct = n_people / capacity
    if pct <= 0.30:
        return "여유"
    if pct < 0.70:
        return "보통"
    return "혼잡"
