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
├─ docs/         # 규격 문서, 회의록
├─ csi/          # 희수 — ESP32 수집·신호처리
├─ mmwave/       # 진호 — 레이더 수집·파싱
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

```
        ✳1 ┌─────────────────────┐ ✳2
           │  ┌────┐   ┌────┐    │
           │  │ A  │   │ B  │    │
           │  └────┘   └────┘    │
           │   ●1    △    ●2     │
           │  ┌────┐   ┌────┐    │
           │  │ C  │   │ D  │    │
           │  └────┘   └────┘    │
        ✳3 └─────────────────────┘ ✳4

△ CSI 송신기(TX) 1대 — 중앙
✳ CSI 수신기(RX) 4대 — 모서리, 각 링크가 대각선으로 테이블 관통
● mmWave 2대 — 좌(A/C) · 우(B/D)
```

| 센서 | 필요 | 보유 | 추가 |
|------|:---:|:---:|:---:|
| ESP32 | 5 (TX1+RX4) | 2 | **3** |
| mmWave (HLK-LD6001A) | 2 | 1 | **1** |

**CSI 링크 매핑 (검증 전)**
```
link_1 → zone_A     link_2 → zone_B
link_3 → zone_C     link_4 → zone_D
```

> ⚠️ 네 링크가 TX를 공유하므로 경로가 중앙에서 겹친다.
> **"link_1 = zone_A"를 확정하지 말 것.** 배치 후 한 구역에만 사람을 두고
> 네 링크 반응을 비교하는 **분리도 검증 실험**이 필요하다.
> 분리가 약하면 네 링크 값을 전부 feature로 쓰는 방식으로 전환.

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

특징값 목록은 자유. 접두사·필수 컬럼만 지키면 각자 결정.
컬럼 추가·변경 시 송주에게 알릴 것.

**결측률 컬럼 (필수)**
```
CSI    : csi_packet_count, csi_missing_rate
mmWave : mm_frame_count
```
> CSI는 패킷이 안 오면 행 자체가 안 생겨서 빈칸으로 결측을 판단할 수 없다.

### 파일 예시

```csv
# csi_20260812_1800.csv
timestamp,link_id,csi_amp_var,csi_amp_mean,csi_packet_count,csi_missing_rate
1785397655000,link_1,0.31,12.4,493,0.014
1785397655000,link_2,0.22,11.8,491,0.018

# mm_20260812_1800.csv
timestamp,zone,mm_presence,mm_static_energy,mm_moving_energy,mm_frame_count
1785397655000,zone_A,1,0.91,0.12,98
1785397655000,zone_B,0,0.05,0.02,98

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
구역별 좌석 수를 미리 세어둘 것.

### 동기화

| | 역할 |
|---|---|
| NTP | 주 동기화 |
| 손 흔들기 | 검증·보정 백업 |

세션 시작·끝 각 5초. **TX-RX 경로를 가로막으면서 레이더 시야에도 들어가는 위치**에서.

---

## 기술 스택

```
서버      : FastAPI
DB        : SQLite
전처리    : pandas
학습      : scikit-learn
프론트    : HTML + Chart.js
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
git checkout main
git pull upstream main
git push origin main
git checkout -b feat/작업이름
# 작업 후
git add .
git commit -m "feat: 설명"
git push origin feat/작업이름
# GitHub에서 중앙 레포로 PR
```

**커밋 메시지**: `feat:` `fix:` `docs:` `refactor:` `chore:`

**규칙**
- `main` 직접 push 금지 → 브랜치 + PR
- 데이터 파일은 git에 올리지 않음 → 구글드라이브 공유
- 커밋은 각자 이름으로
- AI 도구 자유롭게 쓰되 자기 파트는 설명할 수 있을 만큼 이해할 것

---

## 미결 사항

- [ ] **대기시간: 실측 vs 휴리스틱** — 결정 안 하면 자동으로 휴리스틱.
      실측하려면 수집 시 스톱워치로 같이 재야 함 (수집 시작 전 결정 필요)
- [ ] CSI 링크 분리도 검증 실험 (센서 도착 후)
- [ ] 구역별 좌석 수 실측

---

## 상세 문서

프로젝트 전체 맥락은 `docs/PROJECT_CONTEXT.md` 참고.
AI 툴 사용 시 해당 파일을 첨부하면 맥락이 이어진다.
