# CSI 연결 작업을 나눠 올리기

현재 작업 브랜치는 `feat/csi-ai-integration`이다. 아래는 송주가 직접 실행할 명령이다. 실행 전에 `git status --short`와 `git branch --show-current`로 확인한다. 기존에 따로 stage한 파일이 있다면 각 커밋 전에 `git diff --cached --stat`에서 함께 포함되지 않았는지 확인한다.

## 1. 센서 수집 → AI → 서버

```powershell
git add -- pipeline/features.py pipeline/stream_csi.py pipeline/requirements.txt pipeline/replay.py server/congestion_service.py server/main.py server/models.py server/database.py server/predict.py tools/mock_send.py tools/replay_send.py tests/test_csi_integration.py tests/test_replay.py tests/requirements.txt README.md docs/CSI_INTEGRATION.md
git diff --cached --stat
git commit -m "feat(server): 실제 CSI 특징값과 AI 혼잡도 연결"
```

## 2. 층별 화면과 D-plex

```powershell
git add -- web/ tests/frontend_smoke.cjs server/menu_service.py
git diff --cached --stat
git commit -m "feat(web): 층별 실시간 혼잡도와 발권 흐름 표시"
```

`web/`에는 로컬 글꼴과 공식 주간 메뉴 캐시·이미지도 포함된다. 이 단계까지 함께 적용해야 새 서버 응답에 맞는 화면을 사용할 수 있다.

## 3. 배포 설정과 문서

```powershell
git add -- .vercelignore vercel.json tools/build_vercel.py docs/VERCEL_DEPLOY.md docs/REFACTOR_NOTES.md docs/GIT_UPLOAD.md
git diff --cached --stat
git commit -m "chore(deploy): 혼잡도 API 연결 설정과 실행 문서 정리"
git status --short
git push -u origin feat/csi-ai-integration
```

GitHub PR은 팀 레포의 **`develop`**을 base로, 개인 fork의 **`feat/csi-ai-integration`**을 compare로 만든다. `main`은 사용하지 않는다. 세 커밋을 한 PR에서 검토할 수 있다. 파트별 PR이 필요하면 첫 PR을 병합한 뒤 다음 브랜치를 나눠 진행한다.

2026-10-14 기준 팀 `develop`의 AI 정규화 수정까지 현재 작업 브랜치에 fast-forward로 반영했다(`929aa2b`). AI 업데이트를 다시 별도 커밋할 필요는 없다. 새 `tools/replay_send.py`의 로컬 변경은 서버가 파일 재생 입력을 구분하도록 하는 `input_kind` 표시다.

커밋 작성자는 실행하는 Git의 `user.name`, `user.email`을 사용한다. 모델(`*.joblib`), 원본 CSV, DB, 가상환경은 `.gitignore` 대상으로 포함되지 않는다. 모델은 희수 컴퓨터에도 별도로 전달해야 한다.

PR 설명 예시:

> CSI 송수신기 한 쌍의 원본 패킷에서 학습 규격과 동일한 11개 특징값을 계산하고, AI 추론 결과를 상록원 2층 혼잡도에 연결했습니다. 1·3층은 예시 데이터로 구분하고 식당 명칭을 D-plex로 변경했습니다. 키오스크는 5초 구간 발권 수신과 최근·직전 5분 비교 API를 준비했습니다. 희수 컴퓨터에서 센서 수집·백엔드를 실행하고 같은 공유기의 다른 컴퓨터에서 웹을 확인할 수 있습니다.
>
> 검증: Python 테스트 29개, 프론트 상태·LAN 주소 처리 검사, 정적 빌드 통과. 실제 센서·공유기 연결과 브라우저 배치는 현장 확인이 필요합니다.
