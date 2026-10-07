"""최근 실행 SQL 기록 (관리자 '사용 쿼리' 화면용, 메모리에만 보관).

db.timed 를 거치는 쿼리마다 호출 스택의 앱 함수(모듈.함수)별로 최근 SQL 과 바인드 값을 남긴다.
요청마다 번호(req)와 로그인 사용자(usr)를 함께 남겨 '내가 방금 조회한 화면의 쿼리'만 골라 볼 수 있다.
서버를 다시 시작하면 비워진다. 비밀번호 · 토큰처럼 보이는 바인드 값은 가린다.
"""
from __future__ import annotations

import itertools
import sys
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from datetime import date, datetime

PER_KEY = 20         # 함수마다 (사용자, SQL) 최근 20개 — 한 번 조회에 SQL 여러 개를 쓰는 기능이 있어서
MAX_KEYS = 300
MAX_SQL = 20_000
MAX_STR = 4000       # 값 채운 SQL 이 그대로 실행되도록 넉넉히
SKIP_MODULES = {"db", "main", "sql_trace", "sql_catalog", "sql_perf", "tables"}   # sql_perf: 실행 계획 조회는 기록하지 않음
SECRET_HINTS = ("pw", "pass", "token", "hash", "secret")

MAX_STATS = 800      # 느린 쿼리 현황: SQL 문장별 실행 통계
SLOW_SEC = float(__import__("os").getenv("SLOW_SQL_SEC", "3"))   # logs.SLOW_SQL_SEC 와 같은 기준 (순환 import 피함)

_lock = threading.Lock()
_store: "OrderedDict[str, OrderedDict[int, dict]]" = OrderedDict()
_stats: "OrderedDict[int, dict]" = OrderedDict()
started = time.strftime("%Y-%m-%d %H:%M:%S")
stats_since = started
_seq = itertools.count(1)
# 요청 단위 정보 {req, usr}: 미들웨어가 만들고 로그인 확인(current_user)이 usr 를 채운다.
# 같은 dict 를 공유하므로 스레드풀에서 실행되는 엔드포인트에서도 보인다.
_req: ContextVar[dict | None] = ContextVar("sql_trace_req", default=None)


def begin():
    return _req.set({"req": next(_seq), "usr": None})


def end(token) -> None:
    _req.reset(token)


def set_user(usr_id: str) -> None:
    h = _req.get()
    if h is not None:
        h["usr"] = usr_id


def _keys() -> list[str]:
    """호출 스택에서 앱 함수 이름(모듈.최상위 함수)을 가까운 순으로"""
    out: list[str] = []
    f = sys._getframe(2)
    pkg = __package__ or "app"
    while f is not None and len(out) < 8:
        mod = f.f_globals.get("__name__", "")
        if mod.startswith(pkg + "."):
            short = mod.rsplit(".", 1)[-1]
            if short not in SKIP_MODULES:
                key = f"{short}.{f.f_code.co_qualname.split('.')[0]}"
                if key not in out:
                    out.append(key)
        f = f.f_back
    return out


def _val(k: str, v):
    if any(h in k.lower() for h in SECRET_HINTS):
        return "****"
    if v is None or isinstance(v, (int, float, datetime, date)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return f"<binary {len(v)} bytes>"
    s = str(v)
    return s if len(s) <= MAX_STR else s[:MAX_STR] + "…"


def record(sql: str, params: dict | None, sec: float) -> None:
    try:
        keys = _keys()
        if not keys:
            return
        text = sql if len(sql) <= MAX_SQL else sql[:MAX_SQL] + "\n-- (이하 생략)"
        binds = {k: _val(k, v) for k, v in (params or {}).items()} if isinstance(params, dict) else {}
        ctx = _req.get() or {}
        usr, req = ctx.get("usr"), ctx.get("req")
        h = hash((usr, text))
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        ms = round(sec * 1000)
        with _lock:
            st = _stats.pop(hash(text), None) or {"sql": text, "keys": keys, "count": 0, "total_ms": 0, "max_ms": -1, "slow": 0}
            st["count"] += 1
            st["total_ms"] += ms
            st["last_at"] = now
            if sec >= SLOW_SEC:
                st["slow"] += 1
            if ms > st["max_ms"]:   # 가장 오래 걸린 실행의 값 · 시각 · 사용자 (실행 계획 · 재현용)
                st.update(max_ms=ms, max_at=now, max_binds=binds, max_usr=usr)
            _stats[hash(text)] = st
            while len(_stats) > MAX_STATS:
                _stats.popitem(last=False)
            for key in keys:
                per = _store.get(key)
                if per is None:
                    per = _store[key] = OrderedDict()
                    while len(_store) > MAX_KEYS:
                        _store.popitem(last=False)
                else:
                    _store.move_to_end(key)
                e = per.pop(h, None) or {"sql": text, "count": 0, "usr": usr}
                e.update(binds=binds, at=now, ms=ms, count=e["count"] + 1, req=req)
                per[h] = e
                while len(per) > PER_KEY:
                    per.popitem(last=False)
    except Exception:  # noqa: BLE001 - 기록 실패가 조회를 막지 않게
        pass


def recent(key: str) -> list[dict]:
    """최근 순"""
    with _lock:
        per = _store.get(key)
        return [dict(e) for e in reversed(per.values())] if per else []


def stats() -> list[dict]:
    with _lock:
        return [dict(e) for e in _stats.values()]


def clear_stats() -> None:
    """느린 쿼리 현황 초기화 (배포 · 인덱스 변경 뒤 새로 재기 위해). 사용 쿼리 기록은 그대로 둔다."""
    global stats_since
    with _lock:
        _stats.clear()
        stats_since = time.strftime("%Y-%m-%d %H:%M:%S")


def clear() -> None:
    with _lock:
        _store.clear()
        _stats.clear()
