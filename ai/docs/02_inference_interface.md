# 혼잡도 모델 추론 인터페이스 (백엔드 연동용)

CSI feature 5초 행 하나를 넣으면 혼잡도(여유/보통/혼잡)를 돌려주는 `CongestionPredictor` 사용법이다.
별도 AI 서버 없이 백엔드 프로세스에서 import해서 쓴다.

## 1. 준비물

| 항목 | 위치 | 비고 |
|---|---|---|
| 코드 | `ai/main.py`, `ai/scripts/config.py` | git |
| 모델 파일 | `data/ai/model_hgb_final.joblib` | git에 없음 → 구글드라이브에서 받아 이 경로에 둘 것 |
| 환경 | `ai/requirements.txt` | **scikit-learn 버전을 반드시 맞출 것** (모델 저장 버전과 다르면 로드 실패 가능) |

```bash
pip install -r ai/requirements.txt
```

## 2. 사용법

```python
from ai.main import CongestionPredictor   # 레포 루트가 sys.path에 있어야 함

predictor = CongestionPredictor()          # 다른 경로면 CongestionPredictor(model_path="...")
predictor.check_schema(first_row)          # 서비스 시작 시 1회. feature 컬럼이 빠져 있으면 ValueError

# 5초마다 feature 행이 들어올 때
result = predictor.update(row)
```

## 3. 입력 `row`

CSI 신호처리가 5초마다 만드는 dict 하나. README 5절 규격 그대로.

```python
{
  "timestamp": 1785397655000,   # window 시작, epoch ms
  "link_id": "link_A",          # link별로 calibration을 따로 잡는다 (없으면 "default")
  "csi_rssi_mean": ..., "csi_rssi_std": ...,
  "csi_amp_mean": ..., "csi_amp_std": ..., "csi_amp_var": ..., "csi_amp_range": ...,
  "csi_distortion_cv_pct": ..., "csi_sc_corr_mean": ...,
  "csi_temporal_var_mean": ..., "csi_temporal_diff_mean": ..., "csi_temporal_diff_std": ...,
}
```

- 필수 feature 11개 목록은 `ai/scripts/config.py`의 `FEATURES`가 기준이다.
- 다른 컬럼(`csi_packet_count` 등)은 같이 넣어도 무시된다.
- 결측은 빈칸(`""`), `None`, `NaN` 모두 허용한다. 이 경우 예외 없이 `skipped`가 반환된다.

## 4. 출력 `result`

```python
{
  "timestamp": 1785397655000,
  "link_id": "link_A",
  "status": "ok",
  "level": "혼잡",
  "confidence": 0.87,
  "proba": {"여유": 0.03, "보통": 0.10, "혼잡": 0.87},
  "window_proba": {"여유": 0.10, "보통": 0.20, "혼잡": 0.70}
}
```

- `level` / `confidence` / `proba`는 **최근 12개 window(1분) 확률 평균** 기준이다(`config.SMOOTHING_WINDOWS`).
  `level`은 평균 확률의 "여유 0, 보통 1, 혼잡 2" 가중 점수로 정한다(`config.decide_level`). 여유와 혼잡 사이에서 애매하면 "보통"이 된다. 화면 등급이 5초마다 깜빡이지 않게 하기 위함이며, 우르르 퇴실 같은 큰 변화는 1분 안에 반영된다.
- `window_proba`는 이번 5초 window만의 확률(디버깅·분석용).

| status | 의미 | 추가 필드 | 백엔드 처리 |
|---|---|---|---|
| `calibrating` | 시작 후 기준값 수집 중 (window 24개 = 약 2분) | `progress` ("12/24") | 결과 없음. "측정 준비 중"으로 표시 |
| `ok` | 정상 예측 | `level`, `confidence`, `proba` | DB 저장 |
| `skipped` | 이번 window에 결측 feature가 있음 | `reason` | 건너뛰거나 "데이터 불량"으로 저장. 서비스는 계속 동작 |

`update()`는 결측이나 calibration 중에도 예외를 던지지 않는다. 예외가 나는 경우는 `check_schema()`(컬럼 누락)와 모델 파일 없음뿐이다.

## 5. 운영 시 주의

- **calibration 시작 시점 (가장 중요)**: 서비스를 켠 직후 2분이 기준값이 된다. 모델은 이 2분 대비 변화로 판단하므로
  **반드시 빈 방(0~4명)에서 시작할 것.** 사람이 많은 상태에서 시작하면 그 상태를 기준으로 삼아 "여유"로 잘못 판단한다.
- **센서 안정화**: 센서를 켠 직후 신호가 안정되지 않았을 수 있다(`01_model_experiment_report.md` 4-5). 센서를 먼저 켜 두고
  충분히 안정화한 뒤 calibration을 시작할 것.
- **재시작**: `save_calibration(path)`로 기준값을 저장해 두면 재시작 후 `load_calibration(path)`로 바로 예측할 수 있다.
- **환경 변화**: 가구 이동, 장소 변경 등이 있으면 `reset_calibration(link_id)`로 다시 잡는다.
- **센서 없이 테스트**: `python ai/scripts/replay_test.py`가 실측 데이터를 5초 스트림처럼 흘려 보내는 예시다.

## 6. 현재 한계

- CSI 전용 모델이다. mmWave 결과와 대기시간 예측은 아직 포함되지 않는다.
- **프로토타입 모델**이다 (`01_model_experiment_report.md` 5-3절). 10/15 강의실 연속 실측(입장 → 수업 → 퇴실)과
  10/8·10/14 소수 인원 실측으로 직접 학습했다. 다인원 실측이 이 한 세션뿐이라 다른 장소·날짜로 일반화된다는 근거는 없다.
- 등급 기준은 정원 20명(`config.CAPACITY`) 기준이다: 여유 0~6명 · 보통 7~13명 · 혼잡 14명 이상 (10/16 시연 기준).
  정원을 바꾸면 모델을 다시 학습해야 한다.
- 동적 feature(시간에 따른 흔들림, 서브캐리어 상관, RSSI 흔들림)만 사용한다.
- calibration 시작 상태가 학습 데이터와 비슷해야 한다: 10/15는 설치 인원 1~3명이 움직이는 상태로 시작했다.
  완전히 조용한 빈 방에서 시작하면 기준이 달라져 등급이 높게 나올 수 있다(미검증).
- 학습과 추론은 같은 정규화 함수(`config.fit_baseline` / `apply_baseline`)로 "session 시작 후 첫 24개 window" 기준
  z-score를 쓴다. ESP32를 재부팅하거나 장비 위치가 바뀌면 반드시 다시 calibration해야 한다.
- README 7절 "스케일러는 train에만 fit, 서버에선 로드만" 규칙의 예외다. 이 모델은 환경별 baseline 차이가
  인원수 효과보다 커서(`01_model_experiment_report.md` 3절) 배치 환경에서 기준값을 새로 잡는 것이 설계상 전제다.
