# CSI 단독 혼잡도 분류 모델 — 실험 보고서

**목적**: ESP32 Wi-Fi CSI만으로 여유/보통/혼잡 3-class 분류가 가능한지 1차 검증.
**상태**: 프로토타입 실험. 최종 확정 모델 아님 — 특히 "보통/혼잡" 클래스는 아래 4절을 반드시 읽을 것.

---

## 1. 데이터 구성

### 실측 (N=0, 4~7명)
- `data/ai/labeled_real_final.csv` — 강의실에서 수집한 session 3개(1658/1804/1933)를
  카카오톡 실시간 라벨(이희수 작성)과 timestamp 기준 매칭. 1,490개 window.
- N=0(180개)은 전부 session(1804) 시작 후 15분 이내로, "진짜 0명"이 아니라
  "세션/링크 시작 직후 warmup 구간"일 가능성이 있어 `possible_session_warmup=True`로
  플래그만 하고 삭제는 안 했다. 모델 학습 시 포함 여부는 재검토 가능.

### Mock (N=0~30명) — 100% synthetic
- `data/ai/mock_data_n0_30.csv` — 실측(N=4~7)을 anchor로, 외부데이터(CountFi, 0~20명 실측)의
  "N에 따른 변화 모양"을 빌려 외삽. N=21~30(CountFi 실측 범위 밖)은 근거 없는 외삽을 피하기
  위해 N=20 값에서 보합 처리.
- "가상 session" 24개를 만들어 baseline/scale을 랜덤화함(domain randomization) — 자세한
  이유와 한계는 4절 참고.
- 희수님 피드백 반영: 노이즈를 지우지 않고 오히려 실측 수준으로 주입(진폭 스케일 jitter,
  결측률 10% 시뮬레이션, N에 따라 커지는 noise 배율 등).

---

## 2. Feature (11개, config.py 참고)

기존 production 5개(`csi_rssi_mean`, `csi_amp_mean`, `csi_amp_std`, `csi_amp_var`,
`csi_distortion_cv_pct`) + candidate 6개(`csi_sc_corr_mean`, `csi_temporal_var_mean`,
`csi_temporal_diff_mean`, `csi_temporal_diff_std`, `csi_amp_range`, `csi_rssi_std`).

정의/계산식은 `csi/` 담당(희수)과 합의한 것 그대로이며, 이 문서에서 다시 정의하지 않는다.

---

## 3. 핵심 발견 — Session(환경) 효과가 인원수 효과보다 크다

같은 강의실, 같은 날 찍은 세 session(1658/1804/1933)인데도 `csi_sc_corr_mean` 등
feature의 절대값 수준 자체가 session마다 크게 달랐다(예: sc_corr_mean 평균이
0.31~0.38 vs 0.50~0.54). EHUNAM/CountFi 외부데이터 분석 때 봤던 "환경 효과가
인원수 효과를 가린다"는 문제가 우리 자체 데이터에서도 동일하게 재현됨.

**대응**: session(group) 내부 z-score 정규화 적용. 정규화 후 session-centered
Spearman rho가 `csi_sc_corr_mean` 기준 거의 0에서 +0.19(p<0.0001)로 개선 —
정규화가 필수라는 것을 확인.

---

## 4. 중요한 한계 (반드시 읽을 것)

### 4-1. "보통"/"혼잡" 라벨은 전부 synthetic이다
실측 데이터는 N=0,4~7명(전부 "여유" 등급)뿐이다. "보통"/"혼잡"에 해당하는 실측 사례가
**단 하나도 없다**. 즉 이 두 클래스에 대한 모델 성능 지표는 "synthetic 데이터끼리
얼마나 일관된가"를 재는 것이지 "실제로 혼잡을 맞히는가"를 검증한 게 아니다.

### 4-2. mock 데이터는 "품질"이 아니라 "본질적 한계"의 문제다
아무리 노이즈를 현실적으로 넣어도, mock은 "다른 하드웨어(CountFi)에서 본 패턴이
우리 환경에도 비슷할 것"이라는 **가설**이지 **증거**가 아니다. 이 가설이 맞는지는
실측 고밀도(8명 이상) 데이터로만 검증 가능하다.

### 4-3. Domain-randomization 실험 결과를 과신하지 말 것
"가상 session 24개"로 cross-validation 했을 때 macro-F1이 0.51 -> 0.6~0.7대로
크게 개선됐지만, **24개 가상 session이 전부 같은 생성 로직(같은 CountFi shape)에서
baseline/scale만 다르게 뽑은 것**이라, 이 개선은 "모델이 baseline 차이에 안 흔들리는
법을 배웠다"는 것만 증명하지 "CountFi에서 빌려온 패턴 가설 자체가 맞다"는 것을
증명하지 않는다. 가설이 틀렸어도 24개 안에서는 똑같이 틀렸을 것이므로 교차검증에서
드러나지 않는다.

### 4-4. 실배치 시 session calibration이 필수 전제다
모델은 **session 내부 정규화된 feature**로 학습됐다. 즉 raw feature를 그대로 넣으면
안 되고, 배치 환경(시연 당일 session 등)의 baseline(평균/표준편차)을 먼저 추정해야
한다. `ai/main.py`의 `CongestionPredictor.normalize()`가 이 역할을 하는데,
**session_mean/session_std를 어떻게 구할지(예: session 시작 후 1~2분 calibration
구간)는 아직 운영 설계가 안 됐다** — server 통합 전에 반드시 정해야 함.

### 4-5. N=0 라벨의 신뢰도
N=0(180개)가 전부 session 시작 직후 구간이라 "진짜 0명 효과"인지 "session
warmup 효과"인지 구분이 안 된다. 재수집 시 session 중간에 "일시적으로 전원 퇴실"
같은 시나리오를 넣으면 이 혼동을 풀 수 있다.

---

## 5. 모델 비교 (session-정규화, GroupKFold 기준)

| 모델 | macro-F1 | 혼잡 F1 | 비고 |
|---|---|---|---|
| RandomForest | 0.407 | 0.067 | baseline |
| **HistGradientBoosting (채택)** | 0.508~0.6대 | 0.166~0.78대(※4-3 참고) | NaN 네이티브 처리, 결측 행 안 버림 |

GradientBoosting이 일관되게 나아서 채택. 참고 논문(ESP32 CSI 기반 room-level
occupancy 연구, `ai/docs/`에 별도 레퍼런스 없음 — 대화 기록 참고)에서도 gradient
boosting 계열을 CSI occupancy에 사용한 사례가 있어 방향이 일치함.
RandomForest/LogisticRegression과의 추가 비교는 미완료(시간 관계상 보류, 필요 시
`train_model.py`의 `HistGradientBoostingClassifier` 부분만 교체해서 재실행 가능).

---

## 5-1. 정규화 기준 통일 후 재학습 (2026-10-13)

**문제**: 학습은 session 전체 통계로, 추론(`main.py update()`)은 시작 후 2분 통계로 정규화해 기준이 달랐다.
이전 모델(v1)을 실서비스 방식(빈 방 calibration)으로 평가하면 0~30명 대부분을 "보통"으로 예측했다(정확도 0.34).

**수정**:
- 학습도 session 시작 후 첫 24개 유효 window로 정규화. 정규화 함수는 `config.fit_baseline` / `apply_baseline` 하나로 학습·추론 공용.
- mock을 N=0부터 생성하고, 가상 session마다 0~4명 상태의 calibration window 24개 추가.
- mock 노이즈를 "같은 session·같은 인원" 안의 window 간 표준편차로 변경(이전에는 인원·session 차이까지 섞인 큰 값이라 calibration std 규모가 실서비스와 달랐음).

**결과** (GroupKFold 27 group, 테스트 fold 합산): acc 0.767, macro-F1 0.687

| 인원 | 정답 | 여유 | 보통 | 혼잡 |
|---|---|---|---|---|
| 0~7 | 여유 | 81~100% | | |
| 8~9 | 여유 | 29~53% | 43~69% | |
| 12~19 | 보통 | | 59~98% | |
| 21~30 | 혼잡 | | 46~54% | 40~48% |

실측 테스트 fold(0, 4~7명)는 100% 여유. 실측 리플레이(`replay_test.py`)도 여유 99.9%.

**남은 한계**: CountFi가 0~20명까지라 21명 이상은 20명 값으로 보합 처리 → 혼잡/보통 경계(21명) 구분이 약하다.
8~9명은 정답(여유)과 보통 사이에서 흔들린다. 전부 synthetic 기준 수치이므로 실측 검증 필요.

---

## 6. 다음 우선순위

1. **실측 고밀도(8명 이상) 데이터 수집** — 이게 없으면 위 4-1~4-3 한계는 근본적으로
   해결 안 됨. 기회될 때(수업 끝난 직후 등) 5~10분이라도 틈틈이 수집 권장.
2. **session calibration 운영 설계** (4-4) — server 통합 전 필수.
3. N=0 라벨 신뢰도 재검증 (4-5).
4. 모델 비교 마저 하기 (RandomForest/LogisticRegression, 5절).

---

## 7. 재현 방법

```bash
python ai/main.py train
# 내부적으로 순서대로 실행:
#   ai/scripts/build_labels.py       (카카오톡 export + 실측 CSI -> data/ai/labeled_real_final.csv)
#   ai/scripts/generate_mock_data.py (mock 생성 -> data/ai/mock_data_n0_30.csv, CountFi 경로 수정 필요)
#   ai/scripts/train_model.py        (학습 + 평가 + data/ai/model_hgb_final.joblib 저장)
```

데이터 파일(`data/kakao/`, `data/csi/processed/`, `data/csi/candidate/`)과 CountFi
feature-selection 산출물은 git에 없음 — 구글드라이브에서 받아 배치할 것.
