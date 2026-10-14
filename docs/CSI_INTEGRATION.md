# CSI → AI → 층별 대시보드

CSI 송신기 1대와 수신기 1대(`link_3`)를 사용한다. 테스트 공간의 실제 측정 결과를 상록원 1층에 연결하고, 2·3층 혼잡도는 예시 데이터로 구분한다. 키오스크 방문 도우미도 1층에서만 제공하고, 2·3층 키오스크는 준비 중으로 표시한다.

## 준비

모델은 Git에 포함하지 않는다. 백엔드 컴퓨터의 `data/ai/model_hgb_final.joblib`에 새 모델을 배치한다. 카카오톡 파일명이 `model_hgb_final (1).joblib`이면 실행 경로에서는 `(1)` 없는 이름으로 둔다.

백엔드 컴퓨터의 프로젝트 루트에서:

```powershell
.\venv\Scripts\python.exe -m pip install -r server/requirements.txt -r ai/requirements.txt -r pipeline/requirements.txt
```

가상환경이 없다면 Python 3.12에서 `python -m venv venv`로 먼저 만든다. 희수 수집 컴퓨터는 `pipeline/requirements.txt`의 numpy와 requests가 필요하며 AI 모델은 백엔드 컴퓨터에만 둔다.

## 두 컴퓨터에서 실행

두 컴퓨터를 같은 공유기에 연결한다. 희수 컴퓨터는 센서 수집·특징값 계산·전송을, 송주 컴퓨터는 백엔드·AI·웹을 실행한다. 최신 수집기에는 `/ingest` 전송이 포함되어 터미널은 각각 하나씩 연다.

```text
ESP32 RX → 희수 PC 수집기(:5001) → 5초 특징값 11개
                                      ↓ HTTP /ingest
송주 PC 브라우저 ← /dashboard/ ← 송주 PC FastAPI(:8000) → AI
```

**송주 컴퓨터 — 백엔드:**

```powershell
$env:CSI_LOCATION_ID = "sangnok"
$env:CSI_FLOOR = "1"
$env:CSI_LINK_ID = "link_3"
$env:CSI_MODE = "test"
.\venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --workers 1
```

`ipconfig`로 현재 공유기에 연결된 Wi-Fi/이더넷의 IPv4를 확인한다. 아래는 송주 컴퓨터 IP가 `192.168.0.10`인 예시다.

**희수 컴퓨터 — 가상환경을 활성화하고 수집·전송:**

```text
python csi/logger/tcp_receiver.py --links link_3 --expected-pps 36 --ingest-url http://192.168.0.10:8000/ingest
```

예시 IP를 실제 송주 컴퓨터 IP로 바꾼다. ESP32 수신기의 TCP 서버 주소는 계속 희수 컴퓨터 IP, 포트는 5001이다. 설정 방법은 `csi/firmware/README.md`를 따른다. 기본 4개 링크 설정을 쓰지 않고 `--links link_3`를 지정한다. TX PPS와 `--expected-pps 36`을 맞춘다.

송주 컴퓨터 브라우저: `http://127.0.0.1:8000/dashboard/`. 다른 기기는 `http://송주컴퓨터IP:8000/dashboard/`로 접속한다. 웹과 API가 같은 주소를 사용하므로 `web/runtime-config.js` 변경은 필요 없다. `0.0.0.0`은 서버 수신 설정이며 브라우저 주소가 아니다. 종료는 각 터미널에서 Ctrl+C.

한 컴퓨터에서 모두 실행하려면 수집기의 `--ingest-url`만 `http://127.0.0.1:8000/ingest`로 바꾼다. 서버 컴퓨터가 macOS라면 Python 경로를 `./venv/bin/python`으로 바꾸고 `export CSI_LOCATION_ID=sangnok CSI_FLOOR=1 CSI_LINK_ID=link_3 CSI_MODE=test`로 설정한다.

기존 `pipeline.stream_csi`를 수집기와 함께 켜면 중복 전송된다. 이전 연결 처리를 사용하는 경우에는 수집기에 `--no-ingest`를 지정하고 `python -m pipeline.stream_csi --server http://송주컴퓨터IP:8000 --floor 1`로 실행한다. 이 연결 처리는 현재 기록 중인 raw CSV만 자동으로 선택하며 과거 파일을 재생하지 않는다.

백엔드에 접속되지 않으면 현재 IP·공유기의 장치 간 통신·8000 포트 접근을 확인한다. 센서가 붙지 않으면 수신기에서 바라보는 희수 컴퓨터 IP와 5001 포트를 확인한다.

## 기준값과 실행 설정

센서를 먼저 켜서 안정화하고, 빈 방 또는 0~4명 상태에서 전송을 시작한다. 첫 24개 유효 구간(약 2분)이 기준값이다. 장소·가구 배치가 바뀌거나 모델을 교체하면 백엔드를 재시작하고 기준값을 다시 수집한다.

AI 기준값은 프로세스 메모리에 있으므로 worker는 1개로 실행한다. 모델이 없거나 로드에 실패해도 메뉴와 상태 조회는 제공하며 CSI 수신은 503으로 응답한다. 학습·추론은 `config.fit_baseline` / `apply_baseline`을 사용한다.

기본값은 `CSI_LOCATION_ID=sangnok`, `CSI_FLOOR=1`, `CSI_LINK_ID=link_3`, `CSI_MODE=test`다. 기존 터미널에 `CSI_FLOOR=2`가 남았다면 반드시 1로 변경한다. `test`는 테스트 공간을 상록원에 매핑하는 내부 설정이며 화면 명칭이 아니다. 실제 상록원 현장 운영에서는 `CSI_MODE=live`로 바꾼다. 이 모드는 재생·인공 입력을 거절한다.

DB는 `server/congestion.db`를 사용하며 `KICS_DATABASE_URL`로 별도 경로를 지정할 수 있다. 기존 `readings`·`results` 테이블은 보존하고 새 데이터는 `csi_measurements`·`kiosk_samples`에 저장한다. 이전 2층 기록을 1층 기록으로 덮어쓰지 않는다.

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
  "floor": 1,
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

현재 Vercel 배포는 정적 화면과 메뉴 API다. 센서·AI 백엔드는 지속 실행하는 별도 프로세스로 운영한다. 나중에 외부에서도 접속하려면 브라우저에서 접근 가능한 HTTPS 백엔드를 마련하고, 배포 빌드 환경변수 `CONGESTION_API_BASE`에 그 주소를 넣는다. 공유기의 내부 HTTP IP를 Vercel에 넣는 방식은 사용하지 않는다. 주소가 없으면 1층은 혼잡도 준비 중, 2·3층은 예시 데이터로 표시한다.

## 검증

```powershell
.\venv\Scripts\python.exe -m pip install -r tests/requirements.txt
.\venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/frontend_smoke.cjs
.\venv\Scripts\python.exe tools/build_vercel.py
```

테스트 DB는 메모리에 생성한다. 특징값은 학습용 오프라인 출력과 비교하고, 모델 파일이 있을 때에는 인공 raw 패킷 → 11개 특징값 → API → 실제 모델의 준비·추론 전환을 확인한다. 프론트 테스트는 mock DOM이므로 실제 브라우저 배치 확인과 현장 센서 검증을 대체하지 않는다.
