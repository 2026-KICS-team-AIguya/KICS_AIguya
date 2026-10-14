# CSI → AI → 층별 대시보드

CSI 송신기 1대와 수신기 1대(`link_3`)를 사용한다. 실제 수집 장소는 테스트 공간이고, 결과는 상록원 2층에 연결한다. 화면에는 개발용 테스트 문구 없이 혼잡도·측정 상태를 표시한다. 상록원 1·3층은 `예시 데이터`로 구분한다. 키오스크는 실데이터 확보 전이며 수신 API만 준비했다.

희수 컴퓨터에서 센서 수집·특징값 전송·백엔드를 실행하고, 송주 컴퓨터에서는 브라우저만 사용한다. 두 컴퓨터는 같은 공유기에 연결한다.

```text
ESP32 RX → 희수 PC TCP 수집기(:5001) → raw CSV → stream_csi
                                                    ↓
송주 PC 브라우저 ← /dashboard/ · /congestion ← 희수 PC FastAPI(:8000) → AI
```

## 준비와 실행

모델은 Git에 포함하지 않는다. `data/ai/model_hgb_final.joblib`에 배치한다.

희수 컴퓨터의 프로젝트 루트에서 준비한다. 이 컴퓨터에도 모델 파일이 필요하다. 아래 명령은 Windows PowerShell 기준이며, 기존 가상환경 이름이 다르면 `venv` 경로를 맞춘다.

```powershell
.\venv\Scripts\python.exe -m pip install -r server/requirements.txt -r ai/requirements.txt -r pipeline/requirements.txt
```

가상환경이 없다면 Python 3.12에서 `python -m venv venv`로 먼저 만든다.

## 공유기 안에서 실행

희수 컴퓨터에서 터미널 3개를 열고 각각 프로젝트 루트에서 실행한다. 기존 재생 전송기는 Ctrl+C로 종료한다. 인공 입력을 사용한 서버도 종료한 뒤 다시 실행해 기준값을 초기화한다.

**터미널 1 — 백엔드와 웹:**

```powershell
$env:CSI_LOCATION_ID = "sangnok"
$env:CSI_FLOOR = "2"
$env:CSI_LINK_ID = "link_3"
$env:CSI_MODE = "test"
.\venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --workers 1
```

**터미널 2 — 실제 수집기:**

```powershell
.\venv\Scripts\python.exe csi/logger/tcp_receiver.py --links link_3 --expected-pps 36
```

**터미널 3 — 실제 패킷에서 특징값을 계산해 전송:**

```powershell
.\venv\Scripts\python.exe -m pipeline.stream_csi --server http://127.0.0.1:8000
```

`stream_csi`는 `data/csi/raw/`에서 최근 30초 내 기록된 `csi_*.csv`를 기다렸다가 한 파일에 연결한다. 보관된 과거 파일은 자동 재생하지 않는다. 연결 시점 이후 추가된 완전한 CSV 행만 읽으며, 5초 구간이 끝난 후 2초를 기다려 전송한다. 수집기를 다시 실행해 파일이 바뀌면 `stream_csi`와 백엔드도 다시 실행해 새 기준값을 수집한다. 사용자 지정 파일이 필요하면 `--raw-file "실제 Raw Output 경로.csv"`를 사용한다.

수집기의 출력 경로와 연결된 파일이 같은지 확인한다. ESP32 수신기의 서버 주소는 **희수 컴퓨터의 공유기 IPv4 주소**, 포트는 **5001**로 설정한다. 설정 방법은 `csi/firmware/README.md`를 따른다. 기존 4개 수신기 설정을 사용하지 않고 `--links link_3`를 유지한다. TX 설정과 `--expected-pps 36`도 일치해야 한다.

희수 컴퓨터에서 `ipconfig`를 실행하고 현재 공유기에 연결된 Wi-Fi/이더넷의 IPv4 주소를 확인한다. 예를 들어 `192.168.0.23`이라면:

- 희수 컴퓨터 자체 확인: `http://127.0.0.1:8000/dashboard/`
- 송주 컴퓨터 브라우저: `http://192.168.0.23:8000/dashboard/`

예시 IP는 실제 희수 컴퓨터 IP로 바꾼다. `0.0.0.0`은 서버의 수신 설정이고 브라우저 접속 주소가 아니다. 송주 컴퓨터에서는 서버·Python·센서 코드를 실행할 필요가 없다. 화면과 API가 같은 희수 컴퓨터 주소를 사용하므로 `web/runtime-config.js` 변경도 필요 없다. 종료는 각 터미널에서 Ctrl+C.

희수 컴퓨터가 macOS라면 설치·실행 명령의 `.\venv\Scripts\python.exe`를 `./venv/bin/python`으로 바꾸고, 환경변수는 `export CSI_LOCATION_ID=sangnok CSI_FLOOR=2 CSI_LINK_ID=link_3 CSI_MODE=test`로 설정한다. IPv4 주소는 시스템 설정의 네트워크 정보에서 확인한다.

희수 컴퓨터에서는 열리고 다른 컴퓨터에서는 열리지 않으면 공유기의 장치 간 통신 제한과 Windows의 해당 Python/8000 포트 허용 여부를 확인한다. 센서가 붙지 않으면 수신기에서 바라보는 희수 컴퓨터 IP와 5001 포트도 확인한다.

AI 기준값은 프로세스 메모리에 있다. worker는 1개로 실행하며, 재시작하면 기준값을 다시 수집한다. 모델이 없거나 로드에 실패하면 메뉴와 상태 조회는 계속 제공하고 CSI 수신은 503으로 응답한다.

**기준값 수집 조건:** 센서를 먼저 켜서 신호를 안정화하고, 빈 방 또는 0~4명 상태에서 `stream_csi` 전송을 시작한다. 첫 24개 유효 구간(약 2분)이 기준값이므로 사람이 많은 상태에서 시작하면 그 상태가 기준으로 잡힌다. 장소·가구 배치가 바뀌면 백엔드를 재시작하고 같은 조건으로 다시 수집한다.

2026-10-14에 팀 `develop`의 정규화 수정(`929aa2b`)과 새 모델을 함께 반영했다. 학습과 추론 모두 `config.fit_baseline` / `apply_baseline`을 사용한다. 모델 교체 후에는 파일명만 바꾸는 것으로 끝나지 않고 백엔드를 재시작해야 한다. 카카오톡에서 받은 `model_hgb_final (1).joblib`은 실행 경로에서 `data/ai/model_hgb_final.joblib`이라는 이름으로 둔다. 희수 컴퓨터에도 동일한 새 모델을 별도로 전달한다.

기본값: `CSI_LOCATION_ID=sangnok`, `CSI_FLOOR=2`, `CSI_LINK_ID=link_3`, `CSI_MODE=test`. `test`는 실제 수집 장소를 상록원 2층에 매핑하는 내부 설정이며 화면의 명칭이 아니다. 실제 상록원 현장 운영에서는 `CSI_MODE=live`로 바꾼다. 이 모드는 재생·인공 입력을 거절한다.

DB는 `server/congestion.db`를 기본으로 사용한다. `KICS_DATABASE_URL`로 별도 SQLite 경로를 지정할 수 있다. 기존 `readings`·`results` 테이블은 보존하고, 새 데이터는 `csi_measurements`·`kiosk_samples`에 저장한다. 예전 루트 `congestion.db`의 데이터는 자동으로 이동하지 않는다.

## 특징값 계산

계산은 `offline_feature.feature_row()`와 `candidate_features.window_features()`를 재사용한다. 기본 5개와 후보 6개를 결합하며, 중복 패킷·null 서브캐리어·연속 패킷 쌍 처리도 학습용 코드와 맞춘다. 두 계산의 유효 패킷 집합이 다르면 후보 특징값을 결측으로 전송한다. 특징값 누락은 정상값이나 0으로 채우지 않는다.

## 센서 없이 실행 확인

실측 CSV가 있으면 아래를 실행한다. 특징값 11개가 포함된 한 세션의 CSV를 사용한다. 수집 시각은 현재 시각으로 바꾸어 5초마다 전송한다:

```powershell
python -m pipeline.replay --feature-file data/ai/labeled_real_final.csv --count 30
```

실측 파일이 없을 때 연결 동작만 확인하려면:

```powershell
python -m pipeline.replay --synthetic --count 30
```

이 명령은 30개 행 전송 뒤 종료하므로, 이후 30초가 지나면 화면이 수신 끊김으로 바뀐다. 시연 동안 계속 전송하려면 다음을 실행하고, 종료할 때 전송기 터미널에서 Ctrl+C를 누른다:

```powershell
python -m pipeline.replay --synthetic --continuous
```

전송기는 한 개만 실행한다. `--continuous`는 인공 입력 전용이며 실측 CSV를 반복 전송하지 않는다. 실제 수집 경로는 `input_kind=sensor`, 파일 재생은 `replay`, 인공 입력은 `synthetic`으로 전송한다. 서버는 한 세션에서 입력 종류가 바뀌면 409를 반환한다. 화면은 인공 입력을 `예시 데이터`, 파일 재생을 `기록 데이터`로 구분한다.

인공 입력은 정확도 검증용 데이터가 아니다. 24개의 유효 행을 받으면 기준값 수집을 마치고 추론한다(정상적인 5초 간격에서 약 2분). 인공 입력·다른 세션에서 실제 센서로 전환할 때는 서버를 재시작해 기준값을 다시 잡는다. 모델의 실측 성능 한계는 `ai/docs/02_inference_interface.md`를 참고한다.

## API

`POST /ingest`:

```json
{
  "source": "csi",
  "input_kind": "sensor",
  "identifier": "link_3",
  "location_id": "sangnok",
  "floor": 2,
  "timestamp": 1791817200000,
  "features": {"csi_rssi_mean": -50, "...": "FEATURES의 11개 특징값"}
}
```

`features` 예시는 구조 설명용이며 그대로 전송할 수 없다. 실제 목록은 `ai/scripts/config.py`의 `FEATURES`가 기준이다. `identifier` 대신 `link_id`도 지원한다. 식당·층을 생략하면 서버의 설치 설정을 사용한다. 다른 링크·층은 422로 거절한다. timestamp는 epoch ms, 5초 구간 시작 시각이다.

- 유효 CSI 행마다 `update()` 호출. `calibrating`, `ok`, `skipped`를 저장한다.
- 동일 링크·시각·내용 재전송은 기존 응답을 반환하고 AI를 다시 호출하지 않는다. 내용 충돌이나 역순 전송은 409.
- 숫자 NaN/Infinity는 거절한다. 결측은 `null` 또는 빈 문자열로 전송한다.
- 유효 패킷 0개는 추론하지 않는다. 마지막 실제 수신 또는 특징값 시각이 30초 넘게 오래되면 `stale`로 표시한다.

`GET /congestion?location_id=sangnok`은 버전 2 응답으로 `sensor_scope`, `floors`, `kiosk`를 제공한다. 층별 결과에는 `status`, `level`, `confidence`, `timestamp`, `received_at`, `history`가 있다. 신뢰도는 좌석 점유율이 아니다. `/aggregate`는 새 확률 기반 5분 요약을 조회하는 호환 경로이고, 예전 밀도·좌석 점유율·대기시간 응답은 제공하지 않는다.

## 키오스크 수신 규격

`POST /kiosk/ingest`는 **한 키오스크의 5초 구간 신규 발권 건수**를 받는다. 누적값을 그대로 보내지 않는다. timestamp는 해당 구간의 시작 시각이다. 데이터 형식이 확보되면 원본 로그/API를 이 규격으로 변환한다.

```json
{"location_id":"sangnok","kiosk_id":"main","timestamp":1791817200000,"count":3}
```

0건 구간도 전송해야 한다. 같은 구간 재전송은 중복 집계하지 않는다. 등록된 각 키오스크의 60개 구간이 있어야 최근 5분 총계를 제공하고, 직전 5분도 확보된 뒤 증감을 계산한다. 수신 누락은 0건이 아니다. 조회 시각은 마지막 완성된 5초 경계로 맞추고 `[시작, 종료)` 구간을 사용한다. 등록된 키오스크가 더는 사용되지 않으면 장치 목록 관리가 추가로 필요하다.

발권량은 층별 센서 결과와 분리된 식당 전체 정보다. 현재 대기 인원·대기시간으로 환산하거나 AI 입력에 섞지 않는다.

## Vercel 화면 연결

공유기 안에서 확인할 때는 위의 희수 컴퓨터 `/dashboard/` 주소로 접속한다. Vercel 재배포나 외부 서버는 필요 없다.

현재 Vercel 배포는 정적 화면과 메뉴 API다. 센서·AI 백엔드는 지속 실행하는 별도 프로세스로 운영한다. 나중에 외부에서도 접속하려면 브라우저에서 접근 가능한 HTTPS 백엔드를 마련하고, 배포 빌드 환경변수 `CONGESTION_API_BASE`에 그 주소를 넣는다. 공유기의 내부 HTTP IP를 Vercel에 넣는 방식은 사용하지 않는다. 주소가 없으면 2층은 혼잡도 준비 중, 1·3층은 예시 데이터로 표시한다.

## 검증

```powershell
.\venv\Scripts\python.exe -m pip install -r tests/requirements.txt
.\venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/frontend_smoke.cjs
.\venv\Scripts\python.exe tools/build_vercel.py
```

테스트 DB는 메모리에 생성한다. 특징값은 학습용 오프라인 출력과 비교하고, 모델 파일이 있을 때에는 인공 raw 패킷 → 11개 특징값 → API → 실제 모델의 준비·추론 전환을 확인한다. 프론트 테스트는 mock DOM이므로 실제 브라우저 배치 확인과 현장 센서 검증을 대체하지 않는다.
