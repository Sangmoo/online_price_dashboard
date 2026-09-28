@echo off
chcp 65001 > nul
REM 개발 모드: 백엔드(8000, 자동 재시작) + Vite 개발 서버(5173, HMR)
cd /d %~dp0
start "backend" cmd /k backend\.venv\Scripts\python.exe backend\run.py --reload
start "frontend" cmd /k "cd frontend && npm run dev"
timeout /t 4 > nul
start "" http://localhost:5173
