@echo off
chcp 65001 > nul
rem 자동 테스트 실행
rem   test.bat              서버(백엔드) 테스트 전체
rem   test.bat -m "not db"  DB 없이 서버 단위 테스트만
rem   test.bat e2e          화면 테스트 (Edge 로 가짜 데이터 확인, 실제 서버·DB 접속 없음)
if /i "%~1"=="e2e" (
  cd /d "%~dp0frontend"
  call npx playwright test
  exit /b %errorlevel%
)
cd /d "%~dp0backend"
.venv\Scripts\python -m pytest %*
