# -*- coding: utf-8 -*-
"""ai/ 파이프라인 공용 설정. train_model.py, main.py 양쪽에서 import해서 쓴다."""

FEATURES = [
    'csi_rssi_mean', 'csi_amp_mean', 'csi_amp_std', 'csi_amp_var', 'csi_distortion_cv_pct',
    'csi_sc_corr_mean', 'csi_temporal_var_mean', 'csi_temporal_diff_mean',
    'csi_temporal_diff_std', 'csi_amp_range', 'csi_rssi_std',
]

# TODO: 팀 확정값으로 교체. 현재는 강의실 프로토타입 기준 임시값(README 미결사항 참고)
CAPACITY = 30

LEVELS = ['여유', '보통', '혼잡']


def to_level(n_people, capacity=CAPACITY):
    pct = n_people / capacity
    if pct <= 0.30:
        return '여유'
    if pct < 0.70:
        return '보통'
    return '혼잡'
