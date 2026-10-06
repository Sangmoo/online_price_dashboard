"""관리자 > 홈: 탭 여러 개에 흩어진 운영 상태를 카드 하나씩으로 모은다.

각 카드는 따로 계산하고, 하나가 실패해도 나머지는 보여준다 (실패한 카드는 error). 1분 캐시.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable

from . import appdb, logs

_log = logs.get("app")
CACHE_TTL = 60
_cache: tuple[float, dict] | None = None
_lock = threading.Lock()


def _feedback() -> dict:
    from . import feedback

    return {"open": feedback.open_count()}


def _users() -> dict:
    now = time.time()
    sess = appdb.sessions_active(now)
    today = datetime.now().strftime("%Y-%m-%d")
    log = [r for r in appdb.login_log_list(1000, None) if str(r["ts"] or "").startswith(today)]
    return {"online": len({s["usr_id"] for s in sess}), "sessions": len(sess),
            "loginsToday": len({r["usr_id"] for r in log if r["success"]}),
            "loginFailsToday": sum(1 for r in log if not r["success"]),
            "locked": len(appdb.locks_list(now))}


def _server() -> dict:
    from . import server_status

    s = server_status.status(1)
    return {"uptimeSec": s["server"]["uptimeSec"], "startedAt": s["server"]["startedAt"], "requests": s["requests"]["count"],
            "errors": s["errors"]["count"], "errors5xx": s["requests"]["errors5xx"], "slowRequests": s["requests"]["slow"],
            "slowSql": s["slowSql"]["count"], "sqlErrors": s["sqlErrors"]["count"],
            "recentErrors": s["errors"]["recent"][:3], "crashRestarts": s["supervisor"]["crashRestarts"],
            "diskFreeGb": round(s["disk"]["freeBytes"] / 1024 ** 3, 1),
            "diskFreePct": round(s["disk"]["freeBytes"] * 100 / s["disk"]["totalBytes"], 1) if s["disk"]["totalBytes"] else None}


def _data() -> dict:
    from . import data_service as ds
    from . import db, mv_refresh

    f = mv_refresh.freshness()
    dates = ds.available_dates(days_back=10)
    latest = dates[0] if dates else None
    y = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    n, s = db.query("SELECT COUNT(*), COUNT(SHOP_ID) FROM T_SELECT_ONLINE_MNG_R WHERE DT = :d", {"d": y})[1][0]
    n, s = int(n or 0), int(s or 0)
    return {"onlineLatest": latest["dt"] if latest else None, "onlineLatestRows": latest["count"] if latest else 0,
            "onlineToday": bool(latest and latest["dt"] == datetime.now().strftime("%Y%m%d")),
            "saleBaseMonth": f["baseMaxMonth"], "saleMvMonth": f["mvMaxMonth"], "mvBehind": f["behind"], "mvLastRefresh": f["lastRefresh"],
            "shopFill": {"dt": y, "rows": n, "filled": s, "pct": round(s * 100 / n, 1) if n else None}}


def _ai() -> dict:
    from . import usage, userdb

    by = usage.today_by_user()
    st = userdb.get_settings()
    return {"enabled": bool(st.get("ai_enabled")), "questions": sum(q for q, _ in by.values()),
            "costUsd": round(sum(c for _, c in by.values()), 2), "users": sum(1 for q, _ in by.values() if q)}


def _jobs() -> dict:
    from . import jobs

    return jobs.summary_for_home()


def _downloads() -> dict:
    from . import downloads

    return downloads.today_summary()


def _notices() -> dict:
    from . import notices

    act = notices.active()
    return {"active": len(act), "titles": [n["title"] for n in act[:3]], "endingSoon": len(notices.upcoming_end(3)),
            "maintenance": notices.maintenance(), "table": notices.tables.status()}


CARDS: dict[str, Callable[[], dict]] = {
    "feedback": _feedback, "users": _users, "server": _server, "data": _data, "ai": _ai, "jobs": _jobs,
    "downloads": _downloads, "notices": _notices,
}


def overview(fresh: bool = False) -> dict:
    global _cache
    now = time.time()
    with _lock:
        hit = _cache
    if hit and hit[0] > now and not fresh:
        return hit[1]

    def run(fn: Callable[[], dict]) -> dict[str, Any]:
        try:
            return fn()
        except Exception as ex:  # noqa: BLE001 - 카드 하나 실패가 홈 전체를 막지 않게
            _log.exception("관리자 홈 카드 계산 실패 %s", fn.__name__)
            return {"error": str(getattr(ex, "detail", ex)).splitlines()[0][:200]}

    with ThreadPoolExecutor(max_workers=len(CARDS)) as pool:
        futs = {k: pool.submit(run, fn) for k, fn in CARDS.items()}
        out: dict[str, Any] = {k: f.result() for k, f in futs.items()}
    out["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        _cache = (now + CACHE_TTL, out)
    return out
