@echo off
chcp 65001 > nul
cd /d %~dp0
set TASK=ERP_Sales_Web
REM 백그라운드 서비스 중지 (서버를 정상 종료 후 감시 실행기 종료)
net session >nul 2>&1
if errorlevel 1 (
  echo [오류] 관리자 권한이 필요합니다. 이 파일을 마우스 오른쪽 버튼 - [관리자 권한으로 실행] 하세요.
  pause
  exit /b 1
)
if not exist backend\data mkdir backend\data
echo stop> backend\data\service.stop
echo 서버를 끄는 중...
for /l %%i in (1,1,20) do (
  if not exist backend\data\service.pid goto :done
  timeout /t 1 /nobreak > nul
)
:done
schtasks /End /TN "%TASK%" > nul 2>&1
echo 중지했습니다. PC 를 다시 켜면 자동으로 다시 시작됩니다. (자동 시작을 없애려면 service_uninstall.bat)
pause
