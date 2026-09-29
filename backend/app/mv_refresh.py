"""사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM) 수동 갱신 — 관리자 화면 [지금 갱신] 버튼.

전월 마감 완료 시점이 매번 달라 자동 갱신 대신 관리자가 마감 후 직접 실행한다.
- 서버에서 백그라운드로 실행하고 화면은 진행 상태를 조회한다 (동시에 한 번만).
- 원자적 갱신(atomic_refresh): 끝나서 커밋될 때까지 화면·AI 는 이전 데이터를 그대로 본다.
- 끝나면 앱의 집계 캐시를 비워 판매 현황·요약·AI 가 바로 새 데이터를 쓴다.
- 앱 계정(SS10DEV)의 ALTER ANY MATERIALIZED VIEW 권한으로 DBMS_MVIEW.REFRESH 를 호출한다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import audit, db, logs

_log = logs.get("app")
_lock = threading.Lock()
_state: dict = {"status": "idle", "started": None, "finished": None, "by": None, "error": None, "elapsedSec": None}


def _mv_name() -> str:
    from . import chat_tools_sale as cts

    return cts.MV_NAME


def _snapshot() -> dict:
    """갱신 전후 비교용: 마지막 갱신 시각, 행 수, 최신 월, 신선도"""
    name = _mv_name()
    owner, mv = name.split(".")
    r = db.query("SELECT LAST_REFRESH_DATE, STALENESS FROM ALL_MVIEWS WHERE OWNER = :o AND MVIEW_NAME = :m", {"o": owner, "m": mv})[1]
    cnt, mx = db.query(f"SELECT COUNT(*), MAX(MAKE_YYMM) FROM {name}")[1][0]
    return {"lastRefresh": r[0][0].strftime("%Y-%m-%d %H:%M:%S") if r and r[0][0] else None,
            "staleness": r[0][1] if r else None, "rows": int(cnt), "maxMonth": mx}


def _clear_caches() -> None:
    from . import chat_tools_sale as cts
    from . import sale_dashboard, sale_monthly

    cts._mv_state = None
    sale_dashboard._cache.clear()
    with sale_monthly._stats_lock:
        sale_monthly._stats_cache.clear()


def state() -> dict:
    s = dict(_state)
    if s["status"] == "running" and s["started"]:
        s["elapsedSec"] = int(time.time() - s["started"])
    for k in ("started", "finished"):
        s[k] = datetime.fromtimestamp(s[k]).strftime("%Y-%m-%d %H:%M:%S") if s[k] else None
    return s


def start(admin: dict) -> dict:
    with _lock:
        if _state["status"] == "running":
            return state()
        _state.update({"status": "running", "started": time.time(), "finished": None, "by": admin.get("id"), "error": None,
                       "elapsedSec": None})
    threading.Thread(target=_run, args=(dict(admin),), daemon=True, name="mv-refresh").start()
    return state()


def _refresh() -> None:
    with db.get_pool().acquire() as conn, conn.cursor() as cur:
        cur.callproc("DBMS_MVIEW.REFRESH", keyword_parameters={"list": _mv_name(), "method": "C", "atomic_refresh": True})


def _run(admin: dict) -> None:
    before = None
    try:
        before = _snapshot()
        _log.info("사전 집계 뷰 갱신 시작 (by %s) %s", admin.get("id"), before)
        _refresh()
        after = _snapshot()
        _clear_caches()
        sec = int(time.time() - _state["started"])
        with _lock:
            _state.update({"status": "done", "finished": time.time(), "elapsedSec": sec})
        _log.info("사전 집계 뷰 갱신 완료 %s초 %s", sec, after)
        audit.record(admin, "MV_REFRESH", _mv_name(), before, after,
                     summary=f"사전 집계 뷰 갱신 {sec}초 · 행 {before['rows']:,} → {after['rows']:,} · 최신 월 "
                             f"{before['maxMonth']} → {after['maxMonth']}")
    except Exception as ex:  # noqa: BLE001 - 실패는 상태로 알리고, 원자적 갱신이라 뷰는 이전 데이터 그대로
        msg = str(ex).splitlines()[0]
        with _lock:
            _state.update({"status": "error", "finished": time.time(), "error": msg,
                           "elapsedSec": int(time.time() - (_state["started"] or time.time()))})
        _log.exception("사전 집계 뷰 갱신 실패")
        audit.record(admin, "MV_REFRESH", _mv_name(), summary=f"사전 집계 뷰 갱신 실패: {msg[:200]}")
