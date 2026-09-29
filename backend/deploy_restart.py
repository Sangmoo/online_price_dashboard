"""deploy.bat 마지막 단계: 실행 중인 서버를 새 코드로 다시 띄우고 정상 기동을 확인한다.

- 백그라운드 서비스(service.py)로 실행 중이면 backend/data/service.restart 파일로 재시작을 요청한다 (관리자 권한 불필요).
- start.bat 창으로 실행 중이면 그 창을 다시 실행하라고 안내한다 (창을 대신 닫지 않는다).
- 새 서버가 /api/health 에 응답하고, 그 시작 시각이 요청 이후인지 확인한다.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESTART_FILE = DATA / "service.restart"
PID_FILE = DATA / "service.pid"
ACK_WAIT = 20        # 감시 실행기가 요청 파일을 가져가기까지 (초, 감시 주기 2초)
START_WAIT = 120     # 새 서버가 응답하기까지 (초)

sys.path.insert(0, str(BASE))
from app import config  # noqa: E402

URL = f"http://127.0.0.1:{config.API_PORT}/api/health"


def health() -> dict | None:
    try:
        with urllib.request.urlopen(URL, timeout=5) as r:
            return json.load(r)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    requested = time.time()
    if not PID_FILE.exists():
        if health():
            print("서버가 start.bat 창으로 실행 중입니다. 그 창을 닫고 start.bat 을 다시 실행하면 반영됩니다.")
        else:
            print("서버가 실행 중이 아닙니다. service_start.bat(관리자 권한) 또는 start.bat 으로 시작하세요.")
        return 0

    DATA.mkdir(parents=True, exist_ok=True)
    RESTART_FILE.write_text("deploy", encoding="utf-8")
    print("서버 재시작을 요청했습니다...")
    for _ in range(ACK_WAIT):
        if not RESTART_FILE.exists():
            break
        time.sleep(1)
    else:
        RESTART_FILE.unlink(missing_ok=True)
        print("[주의] 감시 실행기가 재시작 요청을 처리하지 않았습니다 (이전 버전이거나 멈춤).")
        print("       이번 한 번만 service_stop.bat → service_start.bat 을 관리자 권한으로 실행해 주세요.")
        return 1

    for _ in range(START_WAIT):
        h = health()
        if h and float(h.get("started") or 0) >= requested:
            started = time.strftime("%H:%M:%S", time.localtime(h["started"]))
            print(f"반영 완료: 새 서버가 {started} 에 시작되어 정상 응답합니다.")
            return 0
        time.sleep(1)
    print("[주의] 새 서버가 제시간에 응답하지 않았습니다. service_status.bat 과 backend\\logs\\server-console.log 를 확인하세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
