@echo off
chcp 65001 > nul
cd /d %~dp0
REM ============================================================
REM  ERP 영업 관리 - 변경 반영 (자동 테스트 → 화면 빌드 → 서버 재시작 → 기동 확인)
REM  코드를 받은(pull) 뒤 이 파일만 실행하면 됩니다. 관리자 권한 불필요.
REM  테스트를 건너뛰려면: deploy.bat quick
REM  중간 단계가 실패하면 서버는 그대로 두고 멈춥니다.
REM ============================================================
if not exist backend\.venv\Scripts\python.exe (
  echo [오류] 먼저 setup.bat 을 실행하세요.
  pause
  exit /b 1
)
if /i "%~1"=="quick" (
  echo [1/3] 자동 테스트 - 건너뜀
  goto :build
)
echo [1/3] 자동 테스트 - 서버
pushd backend
.venv\Scripts\python -m pytest -q
if errorlevel 1 (
  popd
  echo [중단] 서버 테스트 실패 - 반영하지 않았습니다. 위 오류를 확인하세요.
  pause
  exit /b 1
)
popd
echo [1/3] 자동 테스트 - 화면 (Edge 로 가짜 데이터 확인, 약 30초)
pushd frontend
call npx playwright test
if errorlevel 1 (
  popd
  echo [중단] 화면 테스트 실패 - 반영하지 않았습니다. 위 오류를 확인하세요.
  pause
  exit /b 1
)
popd
:build
echo [2/3] 화면 빌드
pushd frontend
call npm run build
if errorlevel 1 (
  popd
  echo [중단] 화면 빌드 실패 - 서버는 이전 상태 그대로입니다.
  pause
  exit /b 1
)
popd
echo [3/3] 서버 재시작
backend\.venv\Scripts\python.exe backend\deploy_restart.py
pause
