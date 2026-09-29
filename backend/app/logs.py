"""운영 로그: 요청 · 느린 쿼리 · SQL 오류 · 엑셀 작업 · 로그인 · AI 호출.

파일 (backend/logs/, git 제외, 매일 자정에 날짜 파일로 교체: app.log.2026-09-29):
- app.log    : 전체 (INFO 이상). 요청 1건 = 1줄, 느린 쿼리·작업 이력 포함
- error.log  : 오류만 (ERROR 이상, 스택 포함)
보관 기간(관리자 설정, 기본 7일)이 지난 교체 파일은 cleanup() 이 지운다. 전체 용량이 MAX_TOTAL_BYTES 를 넘으면 오래된 것부터 지운다.
관리자 화면 > 서버 로그 에서 최근 기록을, 서버 상태 에서 요약을 조회할 수 있다.

보안: 비밀번호·토큰·바인드 값은 남기지 않는다. SQL 은 문장과 바인드 이름만 기록한다.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
APP_LOG = LOG_DIR / "app.log"
ERROR_LOG = LOG_DIR / "error.log"
SLOW_SQL_SEC = float(os.getenv("SLOW_SQL_SEC", "3"))
SLOW_REQUEST_SEC = float(os.getenv("SLOW_REQUEST_SEC", "5"))
FMT = "%(asctime)s %(levelname)-5s %(name)-12s %(message)s"
DEFAULT_KEEP_DAYS = 7
MAX_TOTAL_BYTES = 1024 ** 3  # 로그 폴더 전체 상한 1GB

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
        # 매일 자정 날짜 파일로 교체. 지우기는 cleanup() 이 보관 일수로 한다 (backupCount=0: 핸들러는 지우지 않음)
        app_h = TimedRotatingFileHandler(APP_LOG, when="midnight", backupCount=0, encoding="utf-8")
        app_h.setFormatter(fmt)
        err_h = TimedRotatingFileHandler(ERROR_LOG, when="midnight", backupCount=0, encoding="utf-8")
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
# 보관 · 정리
# ----------------------------------------------------------------------------
def rotated_files() -> list[Path]:
    """교체된 로그 파일 (app.log.2026-09-28, error.log.1 같은 이전 방식 포함), 오래된 순"""
    if not LOG_DIR.exists():
        return []
    return sorted((p for p in LOG_DIR.glob("*.log.*") if p.is_file()), key=lambda p: p.stat().st_mtime)


def app_log_files(days: int) -> list[Path]:
    """최근 days 일의 app.log 파일들 (오래된 순, 마지막이 현재 파일)"""
    since = time.time() - days * 86400
    old = [p for p in rotated_files() if p.name.startswith("app.log.") and p.stat().st_mtime >= since]
    return old + ([APP_LOG] if APP_LOG.exists() else [])


def cleanup(keep_days: int = DEFAULT_KEEP_DAYS) -> dict:
    """보관 기간이 지난 교체 파일 삭제 + 전체 용량 상한. 현재 쓰는 파일(app.log 등)은 건드리지 않는다."""
    keep_days = max(1, int(keep_days))
    cutoff = time.time() - keep_days * 86400
    deleted, freed = [], 0
    files = rotated_files()
    for p in files:
        if p.stat().st_mtime < cutoff:
            size = p.stat().st_size
            try:
                p.unlink()
                deleted.append(p.name)
                freed += size
            except OSError:
                pass
    remaining = [p for p in rotated_files()]
    total = sum(p.stat().st_size for p in LOG_DIR.glob("*") if p.is_file()) if LOG_DIR.exists() else 0
    for p in remaining:  # 오래된 것부터
        if total <= MAX_TOTAL_BYTES:
            break
        size = p.stat().st_size
        try:
            p.unlink()
            deleted.append(p.name)
            freed += size
            total -= size
        except OSError:
            pass
    if deleted:
        get("app").info("로그 정리: %d개 파일 삭제 (%.1fMB, 보관 %d일)", len(deleted), freed / 1024 ** 2, keep_days)
    return {"deleted": deleted, "freedBytes": freed, "keepDays": keep_days}


# ----------------------------------------------------------------------------
# 관리자 화면 조회
# ----------------------------------------------------------------------------
_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+)\s+(\S+)\s+(.*)$")
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def tail(level: str = "INFO", q: str | None = None, category: str | None = None, limit: int = 300) -> list[dict]:
    """app.log(+직전 교체 파일)의 최근 기록. 스택 등 여러 줄 기록은 한 항목으로 묶는다."""
    limit = max(1, min(limit, 2000))
    min_lv = LEVELS.get(level.upper(), 20)
    files = app_log_files(1)[-2:]
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
