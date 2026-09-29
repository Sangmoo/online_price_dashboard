@echo off
chcp 65001 > nul
cd /d %~dp0
set TASK=ERP_Sales_Web
REM 백그라운드 서비스 시작 (관리자 권한 필요)
net session >nul 2>&1
if errorlevel 1 (
  echo [오류] 관리자 권한이 필요합니다. 이 파일을 마우스 오른쪽 버튼 - [관리자 권한으로 실행] 하세요.
  pause
  exit /b 1
)
del /q backend\data\service.stop 2>nul
schtasks /Run /TN "%TASK%"
echo 시작 요청했습니다. 약 10초 뒤 접속해 보세요. (상태: service_status.bat)
pause
