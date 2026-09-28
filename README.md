# 온라인 가격 모니터

`T_SELECT_ONLINE_MNG_R`(온라인몰 가격 수집 결과)를 조회하는 로컬 웹 서비스입니다. React와 FastAPI로 만들었고, 대화형 분석에는 Claude API를 씁니다.

## 기능
| 화면 | 내용 |
|---|---|
| 대시보드 | 최대 31일 기간 선택(최근 7/14/31일 버튼 제공). KPI 6종, 일자별 수집 추이, 할인율 분포, 사이트별 수집 건수 Top 15, 평균 할인율 높은 사이트 Top 10, 할인율 상위 상품 Top 20. 막대나 상품 행을 누르면 해당 일자 상세 화면으로 이동 |
| 일자별 상세 | 수집일을 하루씩 선택. 컬럼 제목을 누르면 오름차순 → 내림차순 → 해제 순으로 정렬. 통합 검색, 사이트 필터, 페이지 이동 지원. **엑셀 다운로드**는 현재 검색·정렬 조건을 적용한 전체 행을 내려받음 |
| AI 어시스턴트 | 우측 아래 💬 버튼을 누르면 대화 창이 열림. Claude가 이 테이블만 도구로 조회해서 답하고, 조회한 표는 엑셀로 내려받을 수 있음 |

## 실행 (로컬 배포)
1. `.env.example`을 복사해 `.env`를 만들고 DB 정보와 `ANTHROPIC_API_KEY`를 입력합니다.
2. 처음 한 번만 `setup.bat`를 실행합니다. Python 가상환경을 만들고 패키지를 설치한 뒤 프론트엔드를 빌드합니다.
3. `start.bat`를 실행하면 http://localhost:8000 에서 API와 화면이 함께 서비스됩니다.

개발 중에는 `dev.bat`를 실행합니다. 백엔드는 8000번(자동 재시작), 프론트는 5173번(HMR)에서 뜹니다.

## 구조
```
backend/app/
  config.py        .env 로드
  db.py            Oracle Thick 모드 커넥션 풀
  data_service.py  대시보드 집계(쿼리 병렬 실행, 캐시), 일자별 조회·정렬, 엑셀 생성
  chat_tools.py    Claude용 조회 도구(화이트리스트 기반 파라미터 쿼리, 바인드 변수 사용)
  chat_service.py  Claude 스트리밍, 도구 호출 루프, 대화 세션
  main.py          FastAPI 라우트와 dist 정적 파일 서비스
frontend/src/
  components/DashboardView.tsx, DetailView.tsx, ChatWidget.tsx
```

## 참고
- 모델은 `.env`의 `ANTHROPIC_MODEL`과 `ANTHROPIC_EFFORT`로 바꿀 수 있습니다.
- 안전 정책 때문에 요청이 거절되면 다른 모델로 자동 재시도하도록 `fallbacks: "default"` 옵션을 켜 두었습니다.
- Claude는 SQL을 직접 작성하지 않습니다. 정해진 컬럼·조건·집계만 쓸 수 있는 도구 3종으로만 조회합니다. 한 번에 조회할 수 있는 기간은 최대 31일, 결과는 최대 200행입니다.
- 캐시 유지 시간은 오늘 데이터가 5분, 지난 데이터가 60분입니다.
