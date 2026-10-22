# -*- coding: utf-8 -*-
"""
AI 모델 entry point.

- 학습 파이프라인: python ai/main.py train  (scripts/train_real_model.py 실행)
  generate_mock_data.py / train_model.py는 이전 synthetic 방식으로 보관만 한다 — 01 보고서 5-2절
- 서버 통합용: `from ai.main import CongestionPredictor` 후 5초 feature 행마다 update() 호출.
  입출력 형식은 ai/docs/02_inference_interface.md 참고.

[중요] 모델은 raw feature가 아니라 "처음 2분 기준 대비 RSSI 흔들림"으로 만든 움직임 입력
[30초 평균, 3분 최댓값]을 받는다(config.MotionTracker). update()는 link별로 처음 CALIBRATION_WINDOWS개
window를 모아 baseline을 추정한 뒤, 그 2분도 움직임 기록에 넣고 바로 예측을 시작한다.
자세한 배경은 ai/docs/01_model_experiment_report.md 4절, 5-5절 참고.
"""

import json
import math
import os
import subprocess
import sys

import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
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
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(REPO_ROOT, "data", "ai", "model_hgb_final.joblib")
MOTION_IDX = FEATURES.index(MOTION_FEATURE)
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")


def _to_float(value):
    """숫자로 바꿀 수 없거나 빈칸/NaN이면 None. CSV 결측(빈칸)과 dict 결측을 같은 방식으로 다룬다."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


class CongestionPredictor:
    """link별 calibration(baseline 추정) -> 움직임 입력 계산 -> 혼잡도 예측을 한 번에 처리하는 wrapper."""

    def __init__(self, model_path=MODEL_PATH, calibration_windows=CALIBRATION_WINDOWS):
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"모델 파일이 없습니다: {model_path}\n"
                f"구글드라이브에서 받아 위 경로에 두거나, `python ai/main.py train` 으로 학습하세요."
            )
        self.model = joblib.load(model_path)
        if self.model.n_features_in_ != len(MOTION_INPUTS) or set(self.model.classes_) != set(LEVELS):
            raise ValueError(
                f"모델 파일 형식이 현재 코드와 다릅니다: {model_path}\n"
                f"이전(특징값 8개) 모델일 수 있습니다. `python ai/main.py train` 으로 다시 학습하세요."
            )
        self.calibration_windows = calibration_windows
        self._calib_buffer = {}  # link_id -> calibration 구간 feature 벡터 list
        self._baseline = {}  # link_id -> {"mean": [...], "std": [...]}
        self._motion = {}  # link_id -> MotionTracker (최근 30초·3분 움직임 기록)

    @staticmethod
    def check_schema(row: dict):
        """서비스 시작 시 1회 호출. FEATURES 컬럼이 아예 없으면(연동 실수) 바로 에러를 낸다."""
        missing = [f for f in FEATURES if f not in row]
        if missing:
            raise ValueError(
                f"feature 컬럼이 없습니다: {missing}\n필요한 컬럼 목록은 ai/scripts/config.py FEATURES 참고."
            )

    def update(self, row: dict) -> dict:
        """5초 feature 행 하나를 받아 결과 dict를 반환. 결측이 있어도 예외를 던지지 않는다."""
        link_id = row.get("link_id", "default")
        result = {"timestamp": row.get("timestamp"), "link_id": link_id}

        values = [_to_float(row.get(f)) for f in FEATURES]
        missing = [f for f, v in zip(FEATURES, values) if v is None]
        if missing:
            return {
                **result,
                "status": "skipped",
                "reason": f"missing: {', '.join(missing)}",
            }
        packets = _to_float(row.get("csi_packet_count"))
        if packets is not None and packets < MIN_PACKETS:
            return {**result, "status": "skipped", "reason": f"packets: {int(packets)} < {MIN_PACKETS}"}

        if link_id not in self._baseline:
            buf = self._calib_buffer.setdefault(link_id, [])
            buf.append(values)
            if len(buf) < self.calibration_windows:
                return {
                    **result,
                    "status": "calibrating",
                    "progress": f"{len(buf)}/{self.calibration_windows}",
                }
            mean, std = fit_baseline(buf)
            self._baseline[link_id] = {"mean": mean.tolist(), "std": std.tolist()}
            del self._calib_buffer[link_id]
            # 학습(train_real_model.py)과 같게 calibration 2분도 움직임 기록에 넣는다. 마지막 행은 아래에서 넣는다.
            for past in buf[:-1]:
                self._push_motion(link_id, past)

        motion = self._push_motion(link_id, values)
        proba = dict(zip(self.model.classes_, self.model.predict_proba([motion])[0]))
        proba = {lv: float(proba.get(lv, 0.0)) for lv in LEVELS}
        level = max(LEVELS, key=proba.get)
        return {
            **result,
            "status": "ok",
            "level": level,
            "confidence": proba[level],
            "proba": proba,
            "motion": dict(zip(MOTION_INPUTS, motion)),  # 모델 입력 (디버깅·분석용)
        }

    def _push_motion(self, link_id, values):
        baseline = self._baseline[link_id]
        z = apply_baseline(values, baseline["mean"], baseline["std"])[MOTION_IDX]
        return self._motion.setdefault(link_id, MotionTracker()).push(z)

    def reset_calibration(self, link_id=None):
        """배치 환경이 바뀌었을 때(가구 이동, 장소 변경 등) baseline을 다시 잡는다. None이면 전체 link."""
        if link_id is None:
            self._calib_buffer.clear()
            self._baseline.clear()
            self._motion.clear()
        else:
            self._calib_buffer.pop(link_id, None)
            self._baseline.pop(link_id, None)
            self._motion.pop(link_id, None)

    def save_calibration(self, path):
        """서비스 재시작 시 calibration을 다시 하지 않도록 baseline을 저장. 움직임 기록(최근 3분)은 저장하지 않는다."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"features": FEATURES, "baseline": self._baseline},
                f,
                ensure_ascii=False,
                indent=2,
            )

    def load_calibration(self, path):
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if saved["features"] != FEATURES:
            raise ValueError(
                "저장된 calibration의 feature 목록이 현재 config.FEATURES와 다릅니다. 다시 calibration 하세요."
            )
        self._baseline = saved["baseline"]
        self._calib_buffer.clear()
        self._motion.clear()


def run_pipeline():
    """실측 구간 라벨로 학습 → 날짜별 교차 검증 → 모델 저장."""
    for script in ["train_real_model.py"]:
        path = os.path.join(SCRIPTS_DIR, script)
        print(f"\n{'=' * 60}\n실행: {script}\n{'=' * 60}")
        subprocess.run([sys.executable, path], check=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        run_pipeline()
    else:
        print("사용법: python ai/main.py train")
        print("  (train_real_model.py: 실측 학습 · 날짜별 교차 검증 · 모델 저장)")
        print("서버에서 쓸 때는 `from ai.main import CongestionPredictor` 로 import.")
