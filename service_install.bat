@echo off
chcp 65001 > nul
cd /d %~dp0
set TASK=ERP_Sales_Web
REM ============================================================
REM  ERP 영업 관리 - 백그라운드 서비스 설치 (PC 시작 시 자동 실행, 창 없음)
REM  작업 스케줄러에 '%TASK%' 작업을 SYSTEM 계정으로 등록합니다. 관리자 권한 필요.
REM  감시 실행기(backend\service.py)가 서버 멈춤/종료 시 자동으로 다시 띄웁니다.
REM ============================================================
net session >nul 2>&1
if errorlevel 1 (
  echo [오류] 관리자 권한이 필요합니다. 이 파일을 마우스 오른쪽 버튼 - [관리자 권한으로 실행] 하세요.
  pause
  exit /b 1
)
if not exist backend\.venv\Scripts\pythonw.exe (
  echo [오류] 먼저 setup.bat 을 실행하세요.
  pause
  exit /b 1
)
if not exist frontend\dist\index.html (
  echo 프론트엔드 빌드 중...
  pushd frontend && call npm run build && popd
)
set PYW=%~dp0backend\.venv\Scripts\pythonw.exe
set SVC=%~dp0backend\service.py
set WD=%~dp0backend
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute '%PYW%' -Argument '%SVC%' -WorkingDirectory '%WD%';" ^
  "$t = New-ScheduledTaskTrigger -AtStartup;" ^
  "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew;" ^
  "$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;" ^
  "Register-ScheduledTask -TaskName '%TASK%' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null;" ^
  "Start-ScheduledTask -TaskName '%TASK%'"
if errorlevel 1 (
  echo [오류] 작업 등록에 실패했습니다.
  pause
  exit /b 1
)
echo.
echo 설치했습니다. 약 10초 뒤 http://localhost:8000 에서 접속할 수 있습니다.
echo  - PC 를 켜면 로그인하지 않아도 자동으로 실행됩니다.
echo  - 기존 start.bat 창이 열려 있으면 먼저 닫으세요 (같은 포트를 씁니다).
echo  - 상태 확인: service_status.bat / 중지: service_stop.bat / 제거: service_uninstall.bat
pause
