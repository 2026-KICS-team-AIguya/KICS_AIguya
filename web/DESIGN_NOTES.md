# 동국식당 디자인

따뜻한 식당의 메뉴판과 영수증을 중심으로, 아이소메트릭 공간의 작은 장면을 더했습니다.
종이색·토마토색·버터색, 고운바탕 제목, 고운돋움 본문과 DM Serif Display 수치를 사용합니다.
기능은 기존 캠퍼스 → 식당 → 층 → 구역 흐름을 유지합니다.
식당 선택은 상록원·기숙사 식당·경영관 세 곳으로 구성합니다.
발권 정보는 메뉴판 아래에 넣고, 좌석 점유율과 함께 주문 증가 흐름을 볼 수 있게 합니다.
공식 주간 메뉴는 선택한 식당의 첫 정보로 배치합니다. 상록원은 날짜·층별 메뉴로,
기숙사·경영관은 원문 식단표 이미지로 표시하며 출처·적용 기간·확인 시각을 함께 제공합니다.

## 참고 자료

- 사용자 제공 [Habbo 형태 아이소메트릭 템플릿](https://v0.app/templates/habbo-hotel-like-multiplayer-chatroom-using-gpt-5-EYN85i0FdYV): 작은 공간과 캐릭터의 움직임.
- 사용자 제공 [Brutalist 레퍼런스](https://v0-design-brutalist-ai-saa-s.vercel.app/): 힘 있는 글자, 선과 구획.
- [Lulla / Isometric Studio](https://isometricstudio.com/lulla): 식당의 개성을 담는 글자와 일러스트의 조합.
- [Kawaii Sushi / Clever Quokka](https://cleverquokka.com/case-studies/kawaii-sushi): 음식 공간과 작은 상호작용을 연결하는 방식.
- [Si Roma / Brainbox](https://www.brainboxagency.com/work/siroma-restaurant-branding-website-design/): 음식점의 인상을 살리는 색과 시각적 비중.

레퍼런스의 코드, 사진, 일러스트는 복사하지 않았습니다.

## 일러스트

- 최종 자산: `assets/dining-room.png` (1536 × 1024, 알파 배경)
- 생성: 기본 제공 ImageGen 도구. CLI/API 직접 호출은 사용하지 않았습니다.
- 실제 상록원 사진이나 평면도가 아닌 가상의 식당입니다.
- 원본은 생성 도구의 기본 저장 경로에 보존하고 프로젝트에 복사했습니다.

최종 생성 프롬프트:

```text
Use case: stylized-concept. Asset type: original transparent hero illustration for a premium playful Korean university dining website. Primary request: a beautifully art-directed isometric miniature cafeteria cutaway, inspired by the charm of classic isometric social games but refined enough for a contemporary restaurant brand. Draw one compact rectangular two-wall dining room floating alone on a genuinely transparent background. Orthographic isometric camera, meticulous crisp pixel-informed forms, not chunky low-resolution pixels and not glossy AI clay. Warm ivory tiled floor with small oxblood-red checker accents, cream walls, a tomato-red and pale butter striped serving counter, three intimate dark walnut dining tables with thin bentwood chairs, carefully arranged pale green plants, ceramic bowls of rice and Korean side dishes, a cozy hanging light, a simple round wall clock. Include only three tiny elegant anonymous student figurines with warm neutral clothing. Premium architectural diorama with tasteful hand-painted details, fine edges, restrained vintage restaurant character, warm soft sunlight and subtle natural shadows. Color palette: parchment cream, tomato red, butter yellow, muted leaf green, cocoa brown. Composition: all parts visible with generous transparent padding, centered landscape-ish asset with room occupying most of canvas, view from above revealing the interior; no typography, no letters, no numbers, no logos, no watermarks, no interface, no stickers, no random floating food. This is a fictional dining room concept, not an accurate real building.
```

## 글꼴

글꼴은 Google Fonts 공식 배포본을 사용합니다.

- [고운바탕](https://github.com/google/fonts/tree/main/ofl/gowunbatang)
- [고운돋움](https://github.com/google/fonts/tree/main/ofl/gowundodum)
- [DM Serif Display](https://github.com/google/fonts/tree/main/ofl/dmserifdisplay)

SIL Open Font License 원문은 `assets/fonts/*-OFL.txt`에 포함되어 있습니다.
고운바탕과 고운돋움은 현재 화면의 문자만 포함한 웹용 서브셋입니다.
화면을 열 때 외부 폰트 서비스로 접속하지 않습니다.

## 움직임

처음 등장, 작은 식당의 부유와 포인터 기울기, 식당 이름 띠, 김과 캐릭터 움직임,
캠퍼스 시점 회전, 숫자 보간, 층·건물 전환, 새로고침과 버튼 반응을 적용했습니다.
오디오나 실제 사용자 위치 추적은 없습니다. 캐릭터는 장식입니다.
자동 데이터 갱신과 장식 애니메이션은 서로 독립적으로 정지할 수 있습니다.

## 검증의 범위

모의 DOM에서 선택·갱신·준비 중 상태·움직임 제어를 검증했습니다.
입체 식당의 투영 좌표는 모바일 포함 다섯 너비에서, 캠퍼스는 네 너비와 열두 회전각에서 확인했습니다.
제공된 환경에 연결된 브라우저가 없어 CSS의 실제 렌더링과 전체 화면 배치는 아직 확인하지 못했습니다.
