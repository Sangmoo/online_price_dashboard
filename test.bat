@echo off
rem 자동 테스트 실행. DB 없이 단위 테스트만: test.bat -m "not db"
cd /d "%~dp0backend"
.venv\Scripts\python -m pytest %*
