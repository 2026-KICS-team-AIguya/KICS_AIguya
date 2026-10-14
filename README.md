# KICS_AIguya

Wi-Fi CSI 기반 층별 혼잡도와 키오스크 발권 흐름 안내 서비스
카메라 없이 전파 신호만으로 센싱 — 프라이버시 보호

---

## 프로젝트 개요

```
ESP32 CSI (TX1/RX1) → 5초 특징값 11개 → AI 혼잡도 분류 → 층별 표시
키오스크 API/로그   → 최근 5분·직전 5분 집계 → 별도 발권 흐름 표시 (준비 중)
```

- **수집 장소**: 테스트 공간 (파일럿)
- **서비스 대상**: 학식당 (확장 목표)

> ⚠️ 수집과 서비스 대상 공간이 다르다. 발표 시 **"소규모 파일럿으로 원리 검증, 확장은 향후 과제"**로 명확히 선을 그을 것.

---

## 팀원 및 담당

| 팀원 | 담당 | 폴더 |
|------|------|------|
| 이희수 | Wi-Fi CSI 수집·신호처리 | `csi/` |
| 장진호 | 기존 mmWave 담당 (현재 mmWave 미사용) | `mmwave/` |
| 이송주 | 통합·전처리·서버·프론트 | `pipeline/` `server/` `web/` |
| 김채은 | AI 학습·추론, 외부 데이터 | `ai/` `external/` |

---

## 폴더 구조

```
KICS_AIguya/
├─ docs/         # 규격 문서, 회의록
├─ csi/          # 희수 — ESP32 수집·신호처리
├─ mmwave/       # 기존 레이더 폴더, 현재 미사용
├─ external/     # 채은 — 외부 데이터
├─ pipeline/     # 송주 — 전처리 (오프라인·실시간 공용)
├─ ai/           # 모델 학습·평가
├─ server/       # 송주 — FastAPI
├─ web/          # 송주 — 대시보드
├─ tools/        # 더미 생성기 등
└─ data/         # ⚠️ .gitignore 대상
```

---

## 센서 배치

현재 CSI 송신기 1대와 수신기 1대(link_3)를 사용한다. mmWave는 사용하지 않는다.
시연에서는 테스트 공간의 결과를 상록원 2층에 매핑하고, 1·3층은 예시 데이터로 표시한다.
센서 한 쌍으로 여러 층이나 개별 좌석·구역을 측정했다고 표시하지 않는다.

희수 컴퓨터에서 센서 수집·백엔드를 실행하고, 같은 공유기의 송주 컴퓨터에서는 `http://희수컴퓨터IP:8000/dashboard/`에 접속한다. 터미널별 실행 명령은 [CSI 연결 문서](docs/CSI_INTEGRATION.md)에 있다. 식당 목록은 상록원·기숙사 식당·D-plex 세 곳이다.

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
| feature window | 현재 모델은 5초 특징값 11개 |

현재 CSI 수집 설정은 36 PPS이며, 실제 TX 설정과 expected-pps를 맞춘다.

**Raw에는 `device_time_us`와 `host_epoch_ms` 둘 다 기록** (버퍼링 지연 확인용)

### 식별자

| 소스 | 식별자 |
|------|--------|
| CSI | `link_id` (현재 `link_3` 한 개) |
| 키오스크 | `kiosk_id` + 식당 식별자 |

### 파일

| 항목 | 값 |
|------|-----|
| 필수 컬럼 | `timestamp` + 식별자 |
| 접두사 | `csi_` / `ext_` |
| 결측 | **빈칸** (`-1` 금지) |
| 파일명 | `{소스}_{YYYYMMDD}_{HHMM}.csv` |
| raw 보관 | **필수** (feature와 별도) |

AI 입력 특징값 11개는 `ai/scripts/config.py`의 `FEATURES`를 기준으로 맞춘다.
컬럼 추가·변경 시 송주에게 알릴 것.

**결측률 컬럼 (필수)**
```
CSI    : csi_packet_count, csi_missing_rate
```
> CSI는 패킷이 안 오면 행 자체가 안 생겨서 빈칸으로 결측을 판단할 수 없다.

### 파일 예시

```csv
# 기본 특징값 CSV 예시 (AI 입력 전체가 아님)
timestamp,link_id,csi_amp_var,csi_amp_mean,csi_packet_count,csi_missing_rate
1785397655000,link_3,0.31,12.4,175,0.027778

# label_20260812_1800.csv
start_timestamp,end_timestamp,zone,seats,occupied,status,level
1785397500000,1785397800000,zone_A,4,3,앉음,혼잡
```

### 라벨

| 항목 | 값 |
|------|-----|
| 기록 주기 | 5분 |
| 현장 기록 | `12:05~12:10` (종이) |
| CSV 저장 | epoch ms 변환 |
| 담당 | 4명 공동 |

**혼잡 등급 (점유율 기준)**
```
여유 : ≤ 30%
보통 : 30% < x < 70%
혼잡 : ≥ 70%
```
학습 라벨 기준이다. 현재 화면에는 혼잡 등급과 모델 신뢰도를 표시하며, 점유율로 환산하지 않는다.

### 동기화

| | 역할 |
|---|---|
| NTP | 주 동기화 |
| 손 흔들기 | 검증·보정 백업 |

세션 시작·끝 각 5초, TX-RX 경로를 가로막는 동작으로 동기화를 확인한다.

---

## 기술 스택

```
서버      : FastAPI
DB        : SQLite
전처리    : pandas
학습      : scikit-learn
프론트    : HTML/CSS/JavaScript + SVG
CSI 펌웨어 : ESP-IDF (C)
```

---

## 협업 규칙 (fork 방식)

```bash
# 최초 1회
git clone https://github.com/{본인}/KICS_AIguya.git
cd KICS_AIguya
git remote add upstream https://github.com/2026-KICS-team-AIguya/KICS_AIguya.git
git config user.name "본인 이름"
git config user.email "GitHub 등록 이메일"

# 작업할 때마다
git fetch upstream
git switch --no-track -c feat/작업이름 upstream/develop
# 작업 후
git add .
git commit -m "feat: 설명"
git push -u origin feat/작업이름
# GitHub에서 중앙 레포의 develop을 대상으로 PR
```

**커밋 메시지**: `feat:` `fix:` `docs:` `refactor:` `chore:`

**규칙**
- `main` 직접 push 금지 → 브랜치 + PR
- 데이터 파일은 git에 올리지 않음 → 구글드라이브 공유
- 커밋은 각자 이름으로
- AI 도구 자유롭게 쓰되 자기 파트는 설명할 수 있을 만큼 이해할 것

---

## 미결 사항

- [ ] 키오스크 데이터 제공 방식·범위 확인
- [ ] CSI 한 쌍과 AI의 현장 추론 검증
- [ ] 실측 혼잡 데이터와 운영 기준값 수집 조건 검증
- [x] 공유기 내 실행 구성: 희수 컴퓨터 수집·백엔드 / 송주 컴퓨터 웹 접속
- [ ] 외부 공개용 HTTPS 백엔드 주소 결정

---

## 상세 문서

현재 CSI·AI·백엔드 연결 규격과 실행은 `docs/CSI_INTEGRATION.md` 참고.
AI 툴 사용 시 해당 파일을 첨부하면 맥락이 이어진다.
