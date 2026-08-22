# KICS_AIguya

무선 신호(Wi-Fi CSI + mmWave) 기반 실시간 혼잡도·예상 대기시간 예측 서비스  
카메라 없이 전파 신호만으로 센싱 — 프라이버시 보호

---

## 프로젝트 개요

```
ESP32 Wi-Fi CSI  → 동적 움직임 감지 (사람이 오가는 정도)
mmWave 레이더    → 정적 좌석 점유 감지 (앉아 있는 사람)
외부 데이터       → 보조 feature
        ↓
   5초 정렬 → 5분 슬롯 집계
        ↓
   AI 모델 (혼잡도 분류)
        ↓
   웹 대시보드 (구역별 실시간 표시)
```

- **수집 장소**: 고깃집 (4테이블 규모, 파일럿)
- **서비스 대상**: 학식당 (확장 목표)

> ⚠️ 수집과 서비스 대상 공간이 다르다. 발표 시 **"소규모 파일럿으로 원리 검증, 확장은 향후 과제"**로 명확히 선을 그을 것.

---

## 팀원 및 담당

| 팀원 | 담당 | 폴더 |
|------|------|------|
| 이희수 | Wi-Fi CSI 수집·신호처리 | `csi/` |
| 장진호 | mmWave 수집·파싱 | `mmwave/` |
| 이송주 | 통합·전처리·서버·프론트 | `pipeline/` `server/` `web/` |
| 김채은 | 외부 데이터 | `external/` |

---

## 폴더 구조

```
KICS_AIguya/
├─ docs/         # 규격 문서, 회의록, 레이더 프로토콜
├─ csi/          # 희수 — ESP32 수집·신호처리
├─ mmwave/       # 진호 — HLK-LD6004 레이더 수집·파싱·Feature 추출
├─ config/       # 진호 — Zone 및 시스템 설정
├─ firmware/     # 진호 — ESP32 무선(Bluetooth) 펌웨어
├─ src/          # 진호 — mmWave 파이프라인 모듈
├─ external/     # 채은 — 외부 데이터
├─ pipeline/     # 송주 — 전처리 (오프라인·실시간 공용)
├─ ai/           # 모델 학습·평가
├─ server/       # 송주 — FastAPI
├─ web/          # 송주 — 대시보드
├─ tools/        # 더미 생성기 등
└─ data/         # ⚠️ .gitignore 대상
```

---

## 데이터 규격

### 시간

| 항목 | 값 |
|------|-----|
| 타임스탬프 | epoch **milliseconds 정수** |
| 공통 기준 | **`host_epoch_ms`** (호스트가 찍은 시각) |
| Raw | **원본 그대로, 반올림 금지** |
| Feature | **5초 grid** |
| 경계 | window **시작 시각**, `[start, end)` |
| 집계 단위 | 5분 (송주 처리) |
| feature window | 센서 담당자 재량 |

> mmWave 20Hz → 5초에 약 100프레임. 5초 grid로 충분.

**Raw에는 `device_time_us`와 `host_epoch_ms` 둘 다 기록** (버퍼링 지연 확인용)

### 식별자

| 소스 | 식별자 |
|------|--------|
| CSI | `link_id` (link_1 ~ link_4) |
| mmWave | `zone` (zone_A ~ zone_D) |
| 외부 | 없음 (timestamp만) |

### 파일

| 항목 | 값 |
|------|-----|
| 필수 컬럼 | `timestamp` + 식별자 |
| 접두사 | `csi_` / `mm_` / `ext_` |
| 결측 | **빈칸** (`-1` 금지) |
| 파일명 | `{소스}_{YYYYMMDD}_{HHMM}.csv` |
| raw 보관 | **필수** (feature와 별도) |

---

## 📡 mmWave 레이더 모듈 가이드 (장진호)

### 1. 하드웨어 핀 연결 (ESP32 <-> HLK-LD6004)
```text
[ LD6004 센서 ]                 [ ESP32 보드 ]
1번 핀 (빨간색 선) ─── 3.3V ───►  [ 3V3 ] 핀
2번 핀 (검은색 선) ─── GND  ───►  [ GND ] 핀
3번 핀 (노란색 선) ─── RX   ───►  [ D17 ] 핀 (TX2)
4번 핀 (초록색 선) ─── TX   ───►  [ D16 ] 핀 (RX2)
5번 핀 (파란색 선) ────────────►  (연결 안 함)
```

### 2. 실시간 무선 데이터 수집
```bash
# 블루투스 포트(COM7)로 실시간 수집 및 mm_YYYYMMDD_HHMM.csv 자동 생성
python src/pipeline.py --live --port COM7 --duration 300
```
