@echo off
chcp 65001 > nul
REM 최초 설치: Python 가상환경 + 패키지, 프론트엔드 패키지 설치 및 빌드
cd /d %~dp0
echo [1/3] Python 가상환경 생성 및 패키지 설치
if not exist backend\.venv\Scripts\python.exe python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || goto :err
echo [2/3] 프론트엔드 패키지 설치
pushd frontend
call npm install || (popd & goto :err)
echo [3/3] 프론트엔드 빌드
call npm run build || (popd & goto :err)
popd
echo.
echo 설치 완료. start.bat 으로 실행하세요.
pause
exit /b 0
:err
echo 설치 중 오류가 발생했습니다.
pause
exit /b 1
