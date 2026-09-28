@echo off
chcp 65001 > nul
REM ============================================================
REM  ERP 영업 관리 - 로컬 배포 실행 (http://localhost:8000)
REM  1) 최초 1회: setup.bat 실행
REM  2) 이후: start.bat 실행
REM ============================================================
cd /d %~dp0
if not exist backend\.venv\Scripts\python.exe (
  echo [오류] 먼저 setup.bat 을 실행하세요.
  pause
  exit /b 1
)
if not exist frontend\dist\index.html (
  echo 프론트엔드 빌드 중...
  pushd frontend && call npm run build && popd
)
start "" http://localhost:8000
backend\.venv\Scripts\python.exe backend\run.py
