@echo off
chcp 65001 > nul
cd /d %~dp0
set TASK=ERP_Sales_Web
REM 백그라운드 서비스 제거 (자동 시작 해제)
net session >nul 2>&1
if errorlevel 1 (
  echo [오류] 관리자 권한이 필요합니다. 이 파일을 마우스 오른쪽 버튼 - [관리자 권한으로 실행] 하세요.
  pause
  exit /b 1
)
if not exist backend\data mkdir backend\data
echo stop> backend\data\service.stop
for /l %%i in (1,1,20) do (
  if not exist backend\data\service.pid goto :done
  timeout /t 1 /nobreak > nul
)
:done
schtasks /End /TN "%TASK%" > nul 2>&1
schtasks /Delete /TN "%TASK%" /F
echo 제거했습니다. 이제 start.bat 으로 직접 실행하면 됩니다.
pause
