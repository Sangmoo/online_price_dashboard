@echo off
chcp 65001 > nul
cd /d %~dp0
set TASK=ERP_Sales_Web
REM 백그라운드 서비스 상태 확인
echo [작업 스케줄러]
schtasks /Query /TN "%TASK%" /FO LIST 2>nul | findstr /i "상태 Status 작업이름 TaskName"
if errorlevel 1 echo   등록되어 있지 않습니다. (service_install.bat 으로 설치)
echo.
echo [서버 응답]
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://127.0.0.1:8000/api/health; '  정상 (' + $r.StatusCode + ')' } catch { '  응답 없음' }"
echo.
echo [최근 감시 기록] backend\logs\service.log
powershell -NoProfile -Command "if (Test-Path backend\logs\service.log) { Get-Content backend\logs\service.log -Tail 10 -Encoding UTF8 } else { '  (기록 없음)' }"
pause
