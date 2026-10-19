# 팀원 확인용 Vercel 데모

2026-10-19 기준 ‘식당 이용 추정’ 문구와 키오스크 `랜덤`·`실측 기반` 모드 전환을 반영한 팀 확인용 데모입니다.
실제 센서 수집 API, AI 모델과 SQLite 데이터는 Vercel에 업로드하지 않습니다.

공유 주소: https://kics-aiguya-demo.vercel.app

이번 배포: https://kics-aiguya-demo-24eacdf73-ai-guya.vercel.app

공유 주소에서 변경된 HTML·JavaScript·CSS와 `/api/kiosk-analysis` 정상 응답을 확인했습니다. 공개 센서 백엔드 환경변수는 아직 없으므로 배포 화면의 실측 기반 모드는 센서 연결 대기로 표시합니다. 랜덤 모드는 바로 이용할 수 있습니다. 실측 기반을 배포 화면에서 사용하려면 아래 `CONGESTION_API_BASE`를 설정하고 재배포합니다.

메뉴 함수는 서울(`icn1`)에서 실행합니다. 익명 페이지 접속, 세 공식 메뉴 소스 갱신,
D-plex·기숙사 메뉴 이미지 응답을 배포 주소에서 확인했습니다.

공유기 내부 시연은 센서 백엔드의 FastAPI가 웹과 API를 함께 제공합니다. 해당 컴퓨터에서 `http://127.0.0.1:8000/dashboard/`, 다른 컴퓨터에서 `http://백엔드컴퓨터IP:8000/dashboard/`로 접속하면 Vercel 재배포 없이 센서 연결을 확인할 수 있습니다. 실행 순서는 [CSI 연결 문서](CSI_INTEGRATION.md)에 있습니다.

## 구성

- `vercel.json`: 정적 출력 폴더 `public`, Python API 함수 설정
- `tools/build_vercel.py`: `web/`의 화면·이미지·글꼴을 정적 출력으로 복사
- `api/kiosk-analysis.py`: DB·AI 모델 없이 동작하는 가상 키오스크 분석 API (`server/kiosk_analysis.py` 공용)
- `api/menus.py`: `/api/menus`에서 공식 메뉴 조회
- `api/menu-image.py`: 공식 메뉴 이미지 전용 전달 경로
- `server/menu_cloud.py`: 파일 쓰기 없이 메뉴를 수집하고 메모리에 캐시
- `.vercelignore`: 센서 데이터, DB, 가상환경, 개인 환경변수 등 배포 제외

메뉴는 요청이 들어오면 캐시 만료를 확인하고 갱신합니다. 상시 실행 서버나 시간별 Cron에 의존하지 않습니다.
서버리스 인스턴스의 메모리 캐시는 영구 저장소가 아니며, 수집 실패 시 배포에 포함된 공식 메뉴가 백업으로 사용됩니다.
원문 수집 상태와 적용 기간을 화면에서 확인할 수 있습니다.

## 다음 배포

프로젝트 루트에서:

```powershell
vercel login
vercel link --yes --project kics-aiguya-demo --scope ai-guya
vercel deploy --prod --yes --scope ai-guya
```

`.vercel/project.json`은 로컬 연결 정보로 Git에 포함하지 않습니다.
GitHub에 아직 커밋하지 않은 파일도 CLI 배포에는 포함됩니다. 협업을 위해 소스 반영은 별도의 브랜치·PR로 진행해야 합니다.

## 실제 서비스로 확장할 때

외부에서 실시간 혼잡도를 확인하려면 지속 실행되는 HTTPS 백엔드가 필요합니다. 정적 빌드 시 `CONGESTION_API_BASE`를 그 주소로 설정하면 화면이 `/congestion`을 조회합니다. 공유기 내부 HTTP IP를 Vercel에 연결하지 않습니다.

센서 데이터 저장과 운영용 DB는 별도의 영구 저장소가 필요합니다.
메뉴 갱신 이력과 공유 캐시가 필요하면 영구 저장소를 붙이고, 실제 혼잡도 API를 연결합니다.
현재 데모에서는 유료 DB·키·별도 계정을 요구하지 않습니다.
