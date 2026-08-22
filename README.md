# 📡 HLK-LD6004 mmWave Sensing & Feature Pipeline

2026 AI 스마트 캠퍼스 경진대회 — **HLK-LD6004 mmWave 레이더 기반 식당 좌석 혼잡도 감지 및 특징 추출 파이프라인**

---

## 🏗️ 시스템 아키텍처

```text
[ 천장/벽면 거치 ]
HLK-LD6004 레이더 (60GHz FMCW, 20Hz)
       │ (UART: 3V3, GND, TX2, RX2)
ESP32 개발 보드 (Bluetooth Serial 무선 송신)
       │
       │ Bluetooth 무선 링크 (LD6004_mmWave)
       ▼
[ 노트북 / 개발 PC ]
Python 실시간 파이프라인
  1. Raw 데이터 수집 및 host_epoch_ms 기록 (`raw/`)
  2. TinyFrame 프로토콜 파싱 (`parsed/`)
  3. 4개 Zone (`zone_A` ~ `zone_D`) 특징 추출
  4. 5초 Grid 단위 정렬 및 Feature CSV 생성 (`processed/`)
```

---

## 📁 디렉터리 구조

```text
mmwave/
├── config/              # Zone 설정(zone_A~D) 및 전역 세팅
├── docs/                # 프로토콜 및 하드웨어 핀아웃 기술 문서
├── firmware/            # ESP32용 아두이노 무선 블루투스 펌웨어 (.ino)
├── raw/                 # 원본 UART 패킷 바이너리/JSONL (영구 보존)
├── parsed/              # 프레임 단위 정형 파싱 데이터
├── processed/           # 팀 전달용 최종 5초 Grid Feature CSV (mm_YYYYMMDD_HHMM.csv)
├── src/                 # 핵심 파이썬 파이프라인 모듈
│   ├── collector.py
│   ├── parser.py
│   ├── feature_extractor.py
│   ├── aggregator.py
│   └── pipeline.py
└── tests/               # 단위 및 E2E 테스트 스위트
```

---

## 🔌 하드웨어 핀 연결 (ESP32 <-> LD6004)

```text
[ LD6004 센서 ]                 [ ESP32 보드 ]
1번 핀 (빨간색 선) ─── 3.3V ───►  [ 3V3 ] 핀
2번 핀 (검은색 선) ─── GND  ───►  [ GND ] 핀
3번 핀 (노란색 선) ─── RX   ───►  [ D17 ] 핀 (TX2)
4번 핀 (초록색 선) ─── TX   ───►  [ D16 ] 핀 (RX2)
5번 핀 (파란색 선) ────────────►  (연결 안 함)
```

---

## 🚀 빠른 시작 (Quick Start)

### 1. 의존성 설치
```bash
pip install pyserial esptool
```

### 2. 실시간 무선 데이터 수집 및 CSV 생성
```bash
# 블루투스 포트(COM7)로 5분(300초) 동안 수집
python src/pipeline.py --live --port COM7 --duration 300
```

### 3. 저장된 Raw 파일에서 Feature CSV 재생성
```bash
python src/pipeline.py --file raw/raw_20260822_213355.jsonl
```

### 4. 단위 테스트 실행
```bash
python -m unittest discover -s tests
```

---

## 📊 팀 공통 규격

* **시간 규격:** NTP 동기화된 `host_epoch_ms`
* **Grid 단위:** 5초 (`[start, end)` 구간 규칙)
* **Zone 명칭:** `zone_A`, `zone_B`, `zone_C`, `zone_D` (1개 타임스탬프당 4개 행 생성)
* **Feature 접두사:** `mm_presence`, `mm_target_count`, `mm_frame_count`, `mm_avg_velocity`, `mm_avg_distance`
* **결측값:** 빈칸 (`""`)
