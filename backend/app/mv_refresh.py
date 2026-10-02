"""사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM) 수동 갱신 — 관리자 화면 [지금 갱신] 버튼.

전월 마감 완료 시점이 매번 달라 자동 갱신 대신 관리자가 마감 후 직접 실행한다.
- 서버에서 백그라운드로 실행하고 화면은 진행 상태를 조회한다 (동시에 한 번만).
- 원자적 갱신(atomic_refresh): 끝나서 커밋될 때까지 화면·AI 는 이전 데이터를 그대로 본다.
- 끝나면 앱의 집계 캐시를 비워 판매 현황·요약·AI 가 바로 새 데이터를 쓰고, 기본 조건 판매 현황을 미리 계산한다(prewarm).
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

    from . import sale_mix, sale_products, sale_season

    cts._mv_state = None
    sale_dashboard.clear_cache()
    sale_products.clear_cache()
    sale_season.clear_cache()
    sale_mix.clear_cache()
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
    # 11g 는 PL/SQL BOOLEAN 바인드를 지원하지 않아(ORA-03115) callproc 로 True 를 넘기지 않고 리터럴 TRUE 로 쓴다
    with db.get_pool().acquire() as conn, conn.cursor() as cur:
        cur.execute("BEGIN DBMS_MVIEW.REFRESH(list => :l, method => 'C', atomic_refresh => TRUE); END;", {"l": _refresh_list()})


def _refresh_list() -> str:
    """함께 갱신할 뷰: 월×매장 뷰 + 상품 뷰(있으면). 한 번에 갱신해 두 뷰가 같은 시점의 데이터를 갖는다."""
    from . import sale_products

    names = [_mv_name()]
    if sale_products.mv_state()["exists"]:
        names.append(sale_products.MV_NAME)
    return ",".join(names)


def _run(admin: dict) -> None:
    before = None
    try:
        before = _snapshot()
        _log.info("사전 집계 뷰 갱신 시작 (by %s) %s", admin.get("id"), before)
        _refresh()
        after = _snapshot()
        _clear_caches()
        sec = int(time.time() - _state["started"])
        _log.info("사전 집계 뷰 갱신 완료 %s초 %s", sec, after)
        # 변경 이력을 먼저 남기고 상태를 바꾼다 (화면이 '완료'를 본 시점에는 이력에도 있도록)
        _audit(admin, before, after, f"사전 집계 뷰 갱신 {sec}초 · 행 {before['rows']:,} → {after['rows']:,} · 최신 월 "
                                     f"{before['maxMonth']} → {after['maxMonth']}")
        with _lock:
            _state.update({"status": "done", "finished": time.time(), "elapsedSec": sec})
        # 그날 첫 사용자도 기다리지 않게 기본 조건 판매 현황을 미리 계산 (완료 표시 뒤, 같은 스레드에서)
        from . import prewarm

        prewarm.after_refresh()
    except Exception as ex:  # noqa: BLE001 - 실패는 상태로 알리고, 원자적 갱신이라 뷰는 이전 데이터 그대로
        msg = str(ex).splitlines()[0]
        _log.exception("사전 집계 뷰 갱신 실패")
        _audit(admin, None, None, f"사전 집계 뷰 갱신 실패: {msg[:200]}")
        with _lock:
            _state.update({"status": "error", "finished": time.time(), "error": msg,
                           "elapsedSec": int(time.time() - (_state["started"] or time.time()))})


def _audit(admin: dict, before, after, summary: str) -> None:
    try:
        audit.record(admin, "MV_REFRESH", _mv_name(), before, after, summary=summary)
    except Exception:  # noqa: BLE001 - 이력 기록 실패가 갱신 결과를 바꾸지 않게
        _log.exception("사전 집계 뷰 갱신 이력 기록 실패")


def freshness() -> dict:
    """새 월 마감 알림 (관리자 화면 상단 배너).

    원본에 뷰보다 새로운 판매년월이 들어왔으면 behind=True. 뷰 상태 조회(chat_tools_sale.mv_state)의 60초 캐시를 그대로
    쓰므로 접속자 수와 관계없이 DB 조회는 1분에 한 번 이하다 (인덱스 최대값 조회 + 딕셔너리 1행, 수 ms).
    """
    from . import chat_tools_sale as cts

    st = cts.mv_state()
    return {
        "behind": bool(st["base_max"] and st["mv_max"] and st["base_max"] > st["mv_max"]),
        "mvMaxMonth": st["mv_max"], "baseMaxMonth": st["base_max"],
        "lastRefresh": st["last_refresh"].strftime("%Y-%m-%d %H:%M:%S") if st["last_refresh"] else None,
        "refreshing": _state["status"] == "running",
    }
