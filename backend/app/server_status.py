"""관리자 화면 > 서버 상태: 가동 시간 · 자동 재시작 · 요청/응답 · 느린 SQL · 오류 · DB 연결 · 디스크.

로그 파일(app.log, service.log)을 읽어 최근 N일(기본 7일)을 요약한다. DB 에는 묻지 않는다(연결 풀 상태만).
같은 기간 요청은 1분 캐시.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import logs

STARTED_AT = time.time()
CACHE_TTL = 60
BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"
SERVICE_LOG = logs.LOG_DIR / "service.log"

_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+)\s+(\S+)\s+(.*)$")
_REQ = re.compile(r"^user=(\S+) (\w+) (\S+) (\d{3}) (\d+)ms$")
_SLOW = re.compile(r"^느린 (\w+) ([\d.]+)s \| binds=.*? \| (.*)$")
_SQL_ERR = re.compile(r"^(\w+) 실패 ([\d.]+)s (.*?) \| binds=.*? \| (.*)$")
_SVC = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+)\s+(.*)$")
_cache: dict[int, tuple[float, dict]] = {}
_lock = threading.Lock()


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _supervisor(since: str) -> dict:
    """service.log: 감시 실행기의 서버 시작·재시작 기록"""
    events = []
    files = sorted(logs.LOG_DIR.glob("service.log*"), key=lambda p: p.stat().st_mtime) if logs.LOG_DIR.exists() else []
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _SVC.match(line.rstrip("\n"))
                if not m or m[1] < since:
                    continue
                msg = m[3]
                if msg.startswith("서버 재시작 예정"):
                    events.append({"ts": m[1], "kind": "crash", "message": msg})
                elif msg.startswith("재시작 요청"):
                    events.append({"ts": m[1], "kind": "deploy", "message": msg})
                elif msg.startswith("감시 시작") or msg.startswith("감시 종료") or msg.startswith("중지 요청"):
                    events.append({"ts": m[1], "kind": "service", "message": msg})
    return {
        "running": (DATA / "service.pid").exists(),
        "crashRestarts": sum(1 for e in events if e["kind"] == "crash"),
        "deployRestarts": sum(1 for e in events if e["kind"] == "deploy"),
        "events": events[-30:][::-1],
    }


def _pool() -> dict | None:
    from . import db

    p = db._pool
    if p is None:
        return None
    try:
        return {"opened": p.opened, "busy": p.busy, "max": p.max}
    except Exception:  # noqa: BLE001
        return None


def _parse_app_log(days: int, since: str) -> dict:
    req_n = err5 = slow_req = 0
    durations: list[int] = []
    per_day: dict[str, dict] = defaultdict(lambda: {"requests": 0, "errors": 0, "slowSql": 0})
    slow_sql: dict[str, dict] = {}
    sql_errors: list[dict] = []
    errors: list[dict] = []
    slow_paths: dict[str, list[int]] = defaultdict(list)
    for path in logs.app_log_files(days + 1):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LINE.match(line.rstrip("\n"))
                if not m or m[1] < since:
                    continue
                ts, level, cat, msg = m[1], m[2], m[3].removeprefix("erp."), m[4]
                day = ts[:10]
                if cat == "request":
                    r = _REQ.match(msg)
                    if r:
                        ms = int(r[5])
                        req_n += 1
                        per_day[day]["requests"] += 1
                        durations.append(ms)
                        if int(r[4]) >= 500:
                            err5 += 1
                        if ms >= logs.SLOW_REQUEST_SEC * 1000:
                            slow_req += 1
                            slow_paths[r[3].split("?")[0]].append(ms)
                elif cat == "sql":
                    s = _SLOW.match(msg)
                    if s:
                        per_day[day]["slowSql"] += 1
                        key = s[3][:200]
                        g = slow_sql.setdefault(key, {"sql": s[3], "count": 0, "maxSec": 0.0, "totalSec": 0.0, "last": ts})
                        g["count"] += 1
                        g["totalSec"] += float(s[2])
                        g["maxSec"] = max(g["maxSec"], float(s[2]))
                        g["last"] = max(g["last"], ts)
                    else:
                        e = _SQL_ERR.match(msg)
                        if e:
                            sql_errors.append({"ts": ts, "error": e[3], "sql": e[4][:300]})
                if level in ("ERROR", "CRITICAL"):
                    per_day[day]["errors"] += 1
                    errors.append({"ts": ts, "category": cat, "message": msg[:300]})
    durations.sort()
    pct = lambda q: durations[min(len(durations) - 1, int(len(durations) * q))] if durations else None  # noqa: E731
    top_sql = sorted(slow_sql.values(), key=lambda g: (g["count"] * g["totalSec"]), reverse=True)[:10]
    for g in top_sql:
        g["avgSec"] = round(g["totalSec"] / g["count"], 2)
        g["maxSec"] = round(g["maxSec"], 2)
        del g["totalSec"]
    return {
        "requests": {"count": req_n, "errors5xx": err5, "slow": slow_req, "avgMs": round(sum(durations) / len(durations)) if durations else None,
                     "p95Ms": pct(0.95), "slowSec": logs.SLOW_REQUEST_SEC,
                     "slowPaths": sorted(({"path": k, "count": len(v), "maxMs": max(v)} for k, v in slow_paths.items()),
                                         key=lambda x: x["count"], reverse=True)[:10]},
        "slowSql": {"count": sum(g["count"] for g in slow_sql.values()), "top": top_sql, "thresholdSec": logs.SLOW_SQL_SEC},
        "sqlErrors": {"count": len(sql_errors), "recent": sql_errors[-5:][::-1]},
        "errors": {"count": len(errors), "recent": errors[-10:][::-1]},
        "daily": [{"day": d, **v} for d, v in sorted(per_day.items())],
    }


def status(days: int = 7, keep_days: int | None = None) -> dict:
    days = max(1, min(int(days), 90))
    now = time.time()
    with _lock:
        hit = _cache.get(days)
    if hit and hit[0] > now:
        out = dict(hit[1])
    else:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        out = {"days": days, "since": since, **_parse_app_log(days, since), "supervisor": _supervisor(since)}
        with _lock:
            _cache[days] = (now + CACHE_TTL, out)
        out = dict(out)
    du = shutil.disk_usage(BASE)
    rotated = logs.rotated_files()
    out.update({
        "server": {"startedAt": datetime.fromtimestamp(STARTED_AT).strftime("%Y-%m-%d %H:%M:%S"), "uptimeSec": int(now - STARTED_AT),
                   "pid": os.getpid()},
        "pool": _pool(),
        "disk": {"logsBytes": _dir_size(logs.LOG_DIR), "exportsBytes": _dir_size(DATA / "exports"), "freeBytes": du.free,
                 "totalBytes": du.total, "logFiles": len(rotated) + sum(1 for p in logs.LOG_DIR.glob("*.log")),
                 "oldestLog": datetime.fromtimestamp(rotated[0].stat().st_mtime).strftime("%Y-%m-%d") if rotated else None},
        "keepDays": keep_days,
    })
    return out
