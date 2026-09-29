"""운영 로그: 요청 · 느린 쿼리 · SQL 오류 · 엑셀 작업 · 로그인 · AI 호출.

파일 (backend/logs/, git 제외, 크기 기준 자동 교체):
- app.log    : 전체 (INFO 이상). 요청 1건 = 1줄, 느린 쿼리·작업 이력 포함
- error.log  : 오류만 (ERROR 이상, 스택 포함)
관리자 화면 > 서버 로그 에서 최근 기록을 조회할 수 있다.

보안: 비밀번호·토큰·바인드 값은 남기지 않는다. SQL 은 문장과 바인드 이름만 기록한다.
"""
from __future__ import annotations

import logging
import os
import re
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
APP_LOG = LOG_DIR / "app.log"
ERROR_LOG = LOG_DIR / "error.log"
SLOW_SQL_SEC = float(os.getenv("SLOW_SQL_SEC", "3"))
SLOW_REQUEST_SEC = float(os.getenv("SLOW_REQUEST_SEC", "5"))
FMT = "%(asctime)s %(levelname)-5s %(name)-12s %(message)s"

_configured = False


def setup() -> None:
    """앱 시작 시 1회. uvicorn 재시작(reload)으로 중복 호출돼도 핸들러를 두 번 달지 않는다."""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("erp")
    root.setLevel(logging.INFO)
    root.propagate = False
    if not root.handlers:
        fmt = logging.Formatter(FMT, "%Y-%m-%d %H:%M:%S")
        app_h = RotatingFileHandler(APP_LOG, maxBytes=20 * 1024 * 1024, backupCount=10, encoding="utf-8")
        app_h.setFormatter(fmt)
        err_h = RotatingFileHandler(ERROR_LOG, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
        err_h.setLevel(logging.ERROR)
        err_h.setFormatter(fmt)
        con_h = logging.StreamHandler()
        con_h.setLevel(logging.WARNING)
        con_h.setFormatter(fmt)
        for h in (app_h, err_h, con_h):
            root.addHandler(h)
    _configured = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"erp.{name}")


_WS = re.compile(r"\s+")


def sql_text(sql: str, limit: int = 400) -> str:
    s = _WS.sub(" ", sql).strip()
    return s if len(s) <= limit else s[:limit] + " …"


# ----------------------------------------------------------------------------
# 관리자 화면 조회
# ----------------------------------------------------------------------------
_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+)\s+(\S+)\s+(.*)$")
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def tail(level: str = "INFO", q: str | None = None, category: str | None = None, limit: int = 300) -> list[dict]:
    """app.log(+직전 교체 파일)의 최근 기록. 스택 등 여러 줄 기록은 한 항목으로 묶는다."""
    limit = max(1, min(limit, 2000))
    min_lv = LEVELS.get(level.upper(), 20)
    files = [p for p in (Path(f"{APP_LOG}.1"), APP_LOG) if p.exists()]
    entries: deque[dict] = deque(maxlen=20000)
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                m = _LINE.match(line)
                if m:
                    entries.append({"ts": m[1], "level": m[2], "category": m[3].removeprefix("erp."), "message": m[4]})
                elif entries:
                    entries[-1]["message"] += "\n" + line
    out = []
    for e in reversed(entries):
        if LEVELS.get(e["level"], 20) < min_lv:
            continue
        if category and e["category"] != category:
            continue
        if q and q.lower() not in e["message"].lower():
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out
