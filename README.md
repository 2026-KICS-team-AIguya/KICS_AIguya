# KICS_AIguya

무선 신호(Wi-Fi CSI + mmWave) 기반 실시간 혼잡도·대기시간 예측 서비스

## 구조

| 폴더 | 담당 | 내용 |
|---|---|---|
| csi/ | 희수 | ESP32 CSI 수집·신호처리 |
| mmwave/ | 진호 | 레이더 수집·파싱 |
| external/ | 채은 | 외부 데이터 |
| pipeline/ | 송주 | 전처리 (오프라인·실시간 공용) |
| ai/ | 전체 | 모델 학습·평가 |
| server/ | 송주 | FastAPI 실시간 서버 |
| web/ | 송주 | 대시보드 |
| tools/ | - | 더미 생성기 등 |
| docs/ | - | 규격 문서, 회의록 |

## 데이터 규격

- 타임스탬프: epoch milliseconds 정수 (기준 host_epoch_ms)
- Raw는 원본 그대로, Feature만 5초 grid
- 경계: window 시작 시각, [start, end)
- 집계 단위: 5분
- 구역: zone_A / zone_B / zone_C, CSI는 link_id
- 접두사: csi_ / mm_ / ext_
- 결측: 빈칸
- 파일명: {소스}_{YYYYMMDD}_{HHMM}.csv

## 규칙

- main 직접 push 금지, fork 후 PR
- 데이터 파일은 git에 올리지 않음 (구글드라이브 공유)
- 커밋은 각자 이름으로
