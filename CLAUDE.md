# realestate-dashboard 작업 안내

세 대시보드가 함께 따르는 규칙은 아래 파일에 있습니다. 먼저 읽고 따릅니다.

@DASHBOARD-RULES.md

## 이 저장소

- 이름: **부동산 시장 Dashboard**(화면 제목, 보내는 사람). 서울·부산 아파트 시장 흐름을 보는 참고 화면입니다.
  메일 머리('부동산 시장 주간 요약')와 메일 제목('[부동산 주간] …')은 아직 이 이름과 다릅니다. 메일을 고칠 때 공통 규칙 7에 맞춥니다.
- 페이지: https://jhkim0603.github.io/realestate-dashboard/ , 기본 가지는 `main` 입니다.
- 주요 파일
  - `Update-RealEstateDashboard.ps1`: 한국부동산원 R-ONE, 한국은행 ECOS, 구글 뉴스를 받아 `data-history.json` 에 쌓고 `dashboard.html` 을 만듭니다. pwsh 7 전용입니다.
  - `template.html`: 화면. 변동률, 시장 온도, 지도 색 같은 계산은 이 안의 스크립트가 합니다. 자리표시자는 `__DATA_JSON__`, `__GEO_JSON__` 입니다.
  - `config.json`: 통계표 ID, 지역 코드, 정책 발표일, 일정, 뉴스 검색어.
  - `tools/weekly-mail.py`: 주간 메일(목요일 발표가 반영된 첫 실행에서 한 주에 한 번).
  - `certs/`: R-ONE 서버가 보내지 않는 중간 인증서. 인증서 검증은 끄지 않습니다.

## 실행과 확인

- 화면 미리보기(수집 없이 배포된 자료로): `python tools/preview.py` → `preview.html`
- 메일 미리보기: `python tools/weekly-mail.py preview.html <폴더>`
- 밝은·어두운 화면 대비 점검: `python tools/contrast-audit.py preview.html <결과 폴더> [화면 폭]`
- 시험 실행: `gh workflow run update-dashboard.yml -R JHKim0603/realestate-dashboard -f send_email=false`
  (보내지 않고 메일만 받아 보려면 `-f send_email=false -f mail_preview=true`)
- 봇이 관리하는 파일: `data-history.json`, `news-history.json`, `.last-weekly-mail`

## 이 저장소의 색과 표현

- 빨강은 상승(또는 집값을 올리는 요인), 파랑은 하락(내리는 요인)입니다. 선 색은 서울 보라, 부산 청록, 전국 회색입니다.
- 용어는 통계 이름과 같게 씁니다: 상승·보합·하락, 매수우위지수, 전세수급지수.
- 구별 개수는 4주 평균 기준(흐름 정리)과 3개월 변동률 기준(구별 지도)이 다를 수 있어, 문장에 기준을 밝힙니다.
- 메일의 흐름 정리 상자는 안쪽에 제목을 둡니다. 공통 규칙의 메일 모양(상자 밖 구역 제목)과 아직 다르므로, 메일을 고칠 때 맞춥니다.

## 남은 일(사용자 조치 필요)

- 주간 메일 Gmail 비밀값(`GMAIL_USERNAME`, `GMAIL_APP_PASSWORD`)이 없으면 메일 단계만 건너뜁니다. 사용자가 `gh secret set` 으로 넣습니다.
- 착공, 입주 예정, 구별 실거래가는 인증키(data.go.kr 활용신청)가 있어야 합니다. 매물 수는 공개 API 가 없습니다.
