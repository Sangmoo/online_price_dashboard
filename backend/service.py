"""서버 감시 실행기 (창 없이 백그라운드 실행 · 자동 재시작 · 멈춤 감지).

service_install.bat 이 Windows 작업 스케줄러에 'PC 시작 시 실행'으로 등록한다.
- 서버(run.py)를 창 없이 띄우고, 종료되면 자동으로 다시 띄운다 (연속 실패 시 대기 시간을 늘림).
- 30초마다 /api/health 를 확인해 3번 연속 응답이 없으면(약 1분 30초) 멈춘 것으로 보고 강제 종료 후 다시 띄운다.
- backend/data/service.stop 파일이 생기면(service_stop.bat) 서버를 끄고 종료한다.
- 기록: backend/logs/service.log (감시 기록), backend/logs/server-console.log (서버 출력)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
LOGS = BASE / "logs"
STOP_FILE = DATA / "service.stop"
PID_FILE = DATA / "service.pid"
CHILD_PID_FILE = DATA / "server.pid"

HEALTH_EVERY = 30        # 초
HEALTH_TIMEOUT = 10      # 초
HEALTH_FAILS = 3         # 연속 실패 횟수 → 재시작
STARTUP_GRACE = 60       # 서버 시작 직후 확인 유예(초)
CREATE_NO_WINDOW = 0x08000000


def _port() -> int:
    sys.path.insert(0, str(BASE))
    from app import config  # .env 의 API_PORT

    return config.API_PORT


def _setup_log() -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("service")
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(LOGS / "service.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(h)
    return log


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _python() -> str:
    """창이 뜨지 않도록 python.exe 를 CREATE_NO_WINDOW 로 실행 (pythonw 로 실행된 경우에도 같은 폴더의 python.exe 사용)."""
    exe = Path(sys.executable)
    cand = exe.with_name("python.exe")
    return str(cand if cand.exists() else exe)


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    log = _setup_log()
    STOP_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    port = _port()
    log.info("감시 시작 (pid=%s, port=%s)", os.getpid(), port)
    if _healthy(port):
        log.warning("이미 %s 번 포트에서 서버가 응답합니다 (start.bat 등으로 실행 중?). 그 서버가 꺼질 때까지 기다립니다.", port)

    backoff = 5
    while not STOP_FILE.exists():
        if _healthy(port):  # 다른 방식으로 이미 떠 있는 서버가 있으면 건드리지 않고 기다린다
            time.sleep(HEALTH_EVERY)
            continue
        console = open(LOGS / "server-console.log", "a", encoding="utf-8", errors="replace")
        console.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 서버 시작 =====\n")
        console.flush()
        child = subprocess.Popen([_python(), str(BASE / "run.py")], cwd=str(BASE), stdout=console, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        CHILD_PID_FILE.write_text(str(child.pid))
        started = time.time()
        log.info("서버 시작 (pid=%s)", child.pid)
        fails, next_check, reason = 0, started + STARTUP_GRACE, None
        while True:
            if STOP_FILE.exists():
                reason = "stop"
                break
            code = child.poll()
            if code is not None:
                reason = f"종료됨(code={code})"
                break
            if time.time() >= next_check:
                if _healthy(port):
                    fails = 0
                else:
                    fails += 1
                    log.warning("응답 없음 %d/%d", fails, HEALTH_FAILS)
                    if fails >= HEALTH_FAILS:
                        reason = "응답 없음(멈춤)"
                        break
                next_check = time.time() + HEALTH_EVERY
            time.sleep(2)
        if child.poll() is None:
            _kill_tree(child.pid)
        console.close()
        CHILD_PID_FILE.unlink(missing_ok=True)
        if reason == "stop":
            log.info("중지 요청으로 서버를 종료했습니다.")
            break
        ran = time.time() - started
        backoff = 5 if ran > 300 else min(backoff * 2, 120)  # 5분 이상 잘 돌았으면 대기 초기화, 계속 죽으면 늘림
        log.error("서버 재시작 예정: %s, %s초 실행, %s초 후 다시 시작 (server-console.log 확인)", reason, int(ran), backoff)
        for _ in range(backoff):
            if STOP_FILE.exists():
                break
            time.sleep(1)

    STOP_FILE.unlink(missing_ok=True)
    PID_FILE.unlink(missing_ok=True)
    log.info("감시 종료")


if __name__ == "__main__":
    main()
