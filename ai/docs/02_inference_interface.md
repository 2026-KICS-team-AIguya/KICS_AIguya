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
  "proba": {"여유": 0.03, "보통": 0.10, "혼잡": 0.87}
}
```

| status | 의미 | 추가 필드 | 백엔드 처리 |
|---|---|---|---|
| `calibrating` | 시작 후 기준값 수집 중 (window 24개 = 약 2분) | `progress` ("12/24") | 결과 없음. "측정 준비 중"으로 표시 |
| `ok` | 정상 예측 | `level`, `confidence`, `proba` | DB 저장 |
| `skipped` | 이번 window에 결측 feature가 있음 | `reason` | 건너뛰거나 "데이터 불량"으로 저장. 서비스는 계속 동작 |

`update()`는 결측이나 calibration 중에도 예외를 던지지 않는다. 예외가 나는 경우는 `check_schema()`(컬럼 누락)와 모델 파일 없음뿐이다.

## 5. 운영 시 주의

- **calibration 시작 시점**: 서비스를 켠 직후 2분이 기준값이 된다. 평소 상태(가능하면 사람이 적을 때)에서 시작할 것.
- **재시작**: `save_calibration(path)`로 기준값을 저장해 두면 재시작 후 `load_calibration(path)`로 바로 예측할 수 있다.
- **환경 변화**: 가구 이동, 장소 변경 등이 있으면 `reset_calibration(link_id)`로 다시 잡는다.
- **센서 없이 테스트**: `python ai/scripts/replay_test.py`가 실측 데이터를 5초 스트림처럼 흘려 보내는 예시다.

## 6. 현재 한계

- CSI 전용 모델이다. mmWave 결과와 대기시간 예측은 아직 포함되지 않는다.
- "보통"/"혼잡"은 synthetic 데이터로 학습했다. 정확도는 실측 검증 전이다 (`01_model_experiment_report.md` 4절).
- **학습과 추론의 정규화 기준이 다르다.** 학습은 session 전체(여러 인원 구간 포함)의 평균/표준편차로 정규화했지만,
  추론은 시작 후 2분만으로 기준값을 잡는다. 이 2분 동안의 인원 상태에 따라 예측이 한쪽으로 치우칠 수 있다
  (실측 리플레이에서 정답 "여유"를 "보통"으로 예측한 비율: session별 2~27%).
  최근 N분 이동 통계로 정규화하는 방식은 후속 과제로 남긴다.
- README 7절 "스케일러는 train에만 fit, 서버에선 로드만" 규칙의 예외다. 이 모델은 환경별 baseline 차이가
  인원수 효과보다 커서(`01_model_experiment_report.md` 3절) 배치 환경에서 기준값을 새로 잡는 것이 설계상 전제다.
