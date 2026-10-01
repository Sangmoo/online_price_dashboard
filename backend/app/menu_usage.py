"""메뉴별 이용 통계: 사용자가 메뉴를 열 때마다 (일자, 사용자, 메뉴) 횟수를 더하고, 관리자 화면에서 기간별로 요약한다.

저장소: Oracle T_ERP_WEB_MENU_USAGE (db/create_erp_web_menu_usage.sql). 테이블이 없으면 서버 로컬 SQLite 에 기록하고,
테이블이 생기면 1분 안에 Oracle 을 쓰며 SQLite 기록을 한 번 더해서 옮긴다. 기록 실패는 화면 사용을 막지 않는다.
AI 대화는 질문을 보낼 때 'ai' 로 함께 센다.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta

from . import auth, db, logs, store

_log = logs.get("app")
ORA_TABLE = "T_ERP_WEB_MENU_USAGE"
AI_PAGE = "ai"
PAGE_LABELS = {**auth.PAGE_LABELS, "admin": "관리자", AI_PAGE: "AI 어시스턴트"}

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_usage (
    use_ymd  TEXT NOT NULL,
    usr_id   TEXT NOT NULL,
    page_cd  TEXT NOT NULL,
    open_cnt INTEGER NOT NULL DEFAULT 0,
    last_day TEXT NOT NULL,
    PRIMARY KEY (use_ymd, usr_id, page_cd)
);
"""
_state: tuple[float, bool] | None = None
_lock = threading.Lock()


def _sqlite() -> None:
    store.conn().executescript(SQLITE_SCHEMA)


def use_oracle() -> bool:
    global _state
    now = time.time()
    with _lock:
        if _state and _state[0] > now:
            return _state[1]
    try:
        db.query(f"SELECT 1 FROM {ORA_TABLE} WHERE 1 = 0")
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    first = ok and not (_state and _state[1])
    with _lock:
        _state = (now + 60, ok)
    if first and os.getenv("ERP_NO_AUTO_MIGRATE") != "1":
        _migrate()
    return ok


def backend_name() -> str:
    return "oracle" if use_oracle() else "sqlite"


_MERGE = f"""MERGE INTO {ORA_TABLE} T
    USING (SELECT :ymd AS USE_YMD, :usr AS USR_ID, :pg AS PAGE_CD FROM DUAL) S
       ON (T.USE_YMD = S.USE_YMD AND T.USR_ID = S.USR_ID AND T.PAGE_CD = S.PAGE_CD)
    WHEN MATCHED THEN UPDATE SET OPEN_CNT = OPEN_CNT + :cnt, LAST_DAY = GREATEST(LAST_DAY, :last)
    WHEN NOT MATCHED THEN INSERT (USE_YMD, USR_ID, PAGE_CD, OPEN_CNT, LAST_DAY) VALUES (:ymd, :usr, :pg, :cnt, :last)"""


def record(usr_id: str, page: str, now: datetime | None = None) -> None:
    now = now or datetime.now()
    ymd, last = now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M%S")
    try:
        if use_oracle():
            db.execute(_MERGE, {"ymd": ymd, "usr": usr_id, "pg": page, "cnt": 1, "last": last})
        else:
            _sqlite()
            store.execute("""INSERT INTO menu_usage(use_ymd, usr_id, page_cd, open_cnt, last_day) VALUES (?, ?, ?, 1, ?)
                             ON CONFLICT(use_ymd, usr_id, page_cd) DO UPDATE SET open_cnt = open_cnt + 1,
                             last_day = MAX(last_day, excluded.last_day)""", (ymd, usr_id, page, last))
    except Exception:  # noqa: BLE001 - 통계 기록 실패가 화면 사용을 막지 않게
        _log.exception("메뉴 이용 기록 실패 user=%s page=%s", usr_id, page)


def _rows(since_ymd: str) -> list[tuple[str, str, str, int, str]]:
    if use_oracle():
        return [(d, u, p, int(c), last) for d, u, p, c, last in db.query(
            f"SELECT USE_YMD, USR_ID, PAGE_CD, OPEN_CNT, LAST_DAY FROM {ORA_TABLE} WHERE USE_YMD >= :s", {"s": since_ymd})[1]]
    _sqlite()
    return [(r["use_ymd"], r["usr_id"], r["page_cd"], int(r["open_cnt"]), r["last_day"])
            for r in store.rows("SELECT use_ymd, usr_id, page_cd, open_cnt, last_day FROM menu_usage WHERE use_ymd >= ?", (since_ymd,))]


def _fmt(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}" if v and len(v) >= 12 else v


def report(days: int, users: list[dict]) -> dict:
    """users: 관리자 사용자 목록 (id, name, pages, ai.enabled, active, lastLoginAt) — 권한은 있는데 안 쓰는 메뉴를 찾는 데 쓴다."""
    days = max(1, min(int(days), 365))
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y%m%d")
    rows = _rows(since)
    pages = [*auth.PAGES, "admin", AI_PAGE]
    by_cell: dict[tuple[str, str], dict] = {}
    by_page: dict[str, dict] = {p: {"page": p, "label": PAGE_LABELS.get(p, p), "opens": 0, "users": set(), "days": set(), "last": None}
                                for p in pages}
    daily: dict[str, int] = {}
    for d, u, p, c, last in rows:
        cell = by_cell.setdefault((u, p), {"opens": 0, "days": 0, "last": None})
        cell["opens"] += c
        cell["days"] += 1
        cell["last"] = max(cell["last"] or "", last)
        g = by_page.setdefault(p, {"page": p, "label": PAGE_LABELS.get(p, p), "opens": 0, "users": set(), "days": set(), "last": None})
        g["opens"] += c
        g["users"].add(u)
        g["days"].add(d)
        g["last"] = max(g["last"] or "", last)
        daily[d] = daily.get(d, 0) + c

    def granted(u: dict, p: str) -> bool:
        return u["ai"]["enabled"] if p == AI_PAGE else p in u["pages"]

    out_users, unused = [], 0
    for u in users:
        cells = {}
        for p in pages:
            c = by_cell.get((u["id"], p))
            g = granted(u, p)
            if c or g:
                cells[p] = {"granted": g, "opens": c["opens"] if c else 0, "days": c["days"] if c else 0,
                            "last": _fmt(c["last"]) if c else None}
                if g and not c:
                    unused += 1
        total = sum(c["opens"] for c in cells.values())
        out_users.append({"id": u["id"], "name": u["name"], "active": u["active"], "lastLoginAt": u.get("lastLoginAt"),
                          "opens": total, "cells": cells,
                          "unusedPages": [p for p, c in cells.items() if c["granted"] and not c["opens"]]})
    out_users.sort(key=lambda x: (-x["opens"], x["name"]))
    return {
        "days": days, "since": f"{since[:4]}-{since[4:6]}-{since[6:]}", "storage": backend_name(),
        "pages": [{**{k: v for k, v in g.items() if k not in ("users", "days", "last")}, "users": len(g["users"]),
                   "activeDays": len(g["days"]), "last": _fmt(g["last"]),
                   "grantedUsers": sum(1 for u in users if u["active"] and granted(u, g["page"]))}
                  for g in by_page.values()],
        "users": out_users,
        "daily": [{"day": f"{d[:4]}-{d[4:6]}-{d[6:]}", "opens": n} for d, n in sorted(daily.items())],
        "unusedGrants": unused,
    }


def _migrate() -> None:
    """SQLite 에 쌓인 기록을 Oracle 에 더하고(MERGE) 지운다."""
    try:
        _sqlite()
        rows = store.rows("SELECT use_ymd, usr_id, page_cd, open_cnt, last_day FROM menu_usage")
        if not rows:
            return
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(_MERGE, {"ymd": r["use_ymd"], "usr": r["usr_id"], "pg": r["page_cd"], "cnt": int(r["open_cnt"]),
                                     "last": r["last_day"]})
            conn.commit()
        store.execute("DELETE FROM menu_usage")
        _log.info("메뉴 이용 기록 %d건을 Oracle 로 옮겼습니다.", len(rows))
    except Exception:  # noqa: BLE001
        _log.exception("메뉴 이용 기록 Oracle 이전 실패 (SQLite 기록은 그대로)")
