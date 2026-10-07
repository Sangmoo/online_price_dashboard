"""최근 실행 SQL 기록 (관리자 '사용 쿼리' 화면용, 메모리에만 보관).

db.timed 를 거치는 쿼리마다 호출 스택의 앱 함수(모듈.함수)별로 최근 SQL 몇 개와 바인드 값을 남긴다.
서버를 다시 시작하면 비워진다. 비밀번호 · 토큰처럼 보이는 바인드 값은 가린다.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import OrderedDict
from datetime import date, datetime

PER_KEY = 5          # 함수마다 서로 다른 SQL 최근 5개
MAX_KEYS = 600
MAX_SQL = 30_000
MAX_STR = 300
SKIP_MODULES = {"db", "main", "sql_trace", "sql_catalog", "tables"}
SECRET_HINTS = ("pw", "pass", "token", "hash", "secret")

_lock = threading.Lock()
_store: "OrderedDict[str, OrderedDict[int, dict]]" = OrderedDict()
started = time.strftime("%Y-%m-%d %H:%M:%S")


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
        h = hash(text)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with _lock:
            for key in keys:
                per = _store.get(key)
                if per is None:
                    per = _store[key] = OrderedDict()
                    while len(_store) > MAX_KEYS:
                        _store.popitem(last=False)
                else:
                    _store.move_to_end(key)
                e = per.pop(h, None) or {"sql": text, "count": 0}
                e.update(binds=binds, at=now, ms=round(sec * 1000), count=e["count"] + 1)
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


def clear() -> None:
    with _lock:
        _store.clear()
