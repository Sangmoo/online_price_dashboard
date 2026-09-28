"""관리자 기능: 사용자 권한/페이지/AI 설정, 전역 설정, 사용 현황, 로그인 이력, 세션 관리."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

from fastapi import HTTPException

from . import auth, config, db, store, usage

MODELS = ["claude-opus-5", "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5-1"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


# ----------------------------------------------------------------------------
# 사용자
# ----------------------------------------------------------------------------
def list_users(q: str | None = None) -> list[dict]:
    settings = store.get_settings()
    today = usage.today()
    now = time.time()
    sql = """
        SELECT u.*,
               COALESCE(a.questions, 0) AS today_questions, COALESCE(a.cost, 0) AS today_cost,
               COALESCE(s.cnt, 0) AS session_cnt
          FROM users u
          LEFT JOIN (SELECT usr_id, SUM(kind='question') AS questions, SUM(cost_usd) AS cost
                       FROM ai_usage WHERE day=? GROUP BY usr_id) a ON a.usr_id = u.usr_id
          LEFT JOIN (SELECT usr_id, COUNT(*) AS cnt FROM sessions WHERE expires_at > ? GROUP BY usr_id) s
                 ON s.usr_id = u.usr_id
    """
    params: list = [today, now]
    if q:
        sql += " WHERE u.usr_id LIKE ? OR u.usr_nm LIKE ?"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY (u.role='ADMIN') DESC, u.last_login_at DESC"
    out = []
    for u in store.rows(sql, tuple(params)):
        me = auth.effective(u, settings)
        out.append({
            **{k: me[k] for k in ("id", "name", "role", "superAdmin", "active", "pages", "ai")},
            "rawAiEnabled": bool(u["ai_enabled"]),
            "rawDailyQuestions": u["daily_questions"],
            "rawDailyCostUsd": u["daily_cost_usd"],
            "lastLoginAt": u["last_login_at"],
            "createdAt": u["created_at"],
            "updatedAt": u["updated_at"],
            "updatedBy": u["updated_by"],
            "todayQuestions": int(u["today_questions"]),
            "todayCostUsd": round(float(u["today_cost"]), 4),
            "online": u["session_cnt"] > 0,
        })
    return out


def directory_search(q: str) -> list[dict]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    found = db.query_dicts(
        """
        SELECT * FROM (
            SELECT USR_ID, USR_NM FROM T_USR
             WHERE NVL(USE_YN, 'N') = 'Y' AND DEL_DAY IS NULL
               AND (USR_ID LIKE :q OR USR_NM LIKE :q)
             ORDER BY USR_ID
        ) WHERE ROWNUM <= 20
        """,
        {"q": f"%{q}%"},
    )
    registered = {r["usr_id"] for r in store.rows("SELECT usr_id FROM users")}
    return [{"id": r["USR_ID"], "name": r["USR_NM"], "registered": r["USR_ID"] in registered} for r in found]


def save_user(admin: dict, usr_id: str, body: dict) -> dict:
    u = store.row("SELECT * FROM users WHERE usr_id=?", (usr_id,))
    if u is None:
        found = db.query_dicts(
            "SELECT USR_ID, USR_NM FROM T_USR WHERE USR_ID=:id AND NVL(USE_YN,'N')='Y' AND DEL_DAY IS NULL",
            {"id": usr_id},
        )
        if not found:
            _bad("사용 중인 사용자(T_USR)에서 찾을 수 없는 ID 입니다.")
        u = auth.ensure_user(usr_id, found[0]["USR_NM"])

    super_admin = auth.is_super_admin(usr_id)
    updates: dict = {}

    if "role" in body:
        if body["role"] not in ("ADMIN", "USER"):
            _bad("권한은 ADMIN 또는 USER 입니다.")
        if super_admin and body["role"] != "ADMIN":
            _bad("최고 관리자의 권한은 변경할 수 없습니다.")
        updates["role"] = body["role"]
    if "pages" in body:
        pages = body["pages"]
        if not isinstance(pages, list) or any(p not in auth.PAGES for p in pages):
            _bad(f"페이지 권한은 {auth.PAGES} 중에서 선택합니다.")
        updates["pages"] = json.dumps(sorted(set(pages), key=auth.PAGES.index))
    if "aiEnabled" in body:
        updates["ai_enabled"] = int(bool(body["aiEnabled"]))
    if "dailyQuestions" in body:
        v = body["dailyQuestions"]
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 1000):
            _bad("일일 질문 한도는 0~1000 사이 정수(또는 기본값)입니다.")
        updates["daily_questions"] = v
    if "dailyCostUsd" in body:
        v = body["dailyCostUsd"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1000):
            _bad("일일 비용 한도는 0~1000 USD 사이(또는 기본값)입니다.")
        updates["daily_cost_usd"] = float(v) if v is not None else None
    if "active" in body:
        if super_admin and not body["active"]:
            _bad("최고 관리자는 비활성화할 수 없습니다.")
        updates["active"] = int(bool(body["active"]))

    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        store.execute(
            f"UPDATE users SET {sets}, updated_at=datetime('now','localtime'), updated_by=? WHERE usr_id=?",
            (*updates.values(), admin["id"], usr_id),
        )
        if updates.get("active") == 0:
            store.execute("DELETE FROM sessions WHERE usr_id=?", (usr_id,))  # 즉시 로그아웃
    return next(x for x in list_users() if x["id"] == usr_id)


# ----------------------------------------------------------------------------
# 전역 AI 설정
# ----------------------------------------------------------------------------
def get_settings() -> dict:
    s = store.get_settings()
    return {
        "aiEnabled": bool(s["ai_enabled"]),
        "defaultDailyQuestions": s["default_daily_questions"],
        "defaultDailyCostUsd": s["default_daily_cost_usd"],
        "model": s["model"] or config.ANTHROPIC_MODEL,
        "effort": s["effort"] or config.ANTHROPIC_EFFORT,
        "models": MODELS,
        "efforts": EFFORTS,
        "envModel": config.ANTHROPIC_MODEL,
        "envEffort": config.ANTHROPIC_EFFORT,
    }


def save_settings(body: dict) -> dict:
    values: dict = {}
    if "aiEnabled" in body:
        values["ai_enabled"] = bool(body["aiEnabled"])
    if "defaultDailyQuestions" in body:
        v = body["defaultDailyQuestions"]
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 1000:
            _bad("기본 일일 질문 한도는 0~1000 사이 정수입니다.")
        values["default_daily_questions"] = v
    if "defaultDailyCostUsd" in body:
        v = body["defaultDailyCostUsd"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1000:
            _bad("기본 일일 비용 한도는 0~1000 USD 입니다.")
        values["default_daily_cost_usd"] = float(v)
    if "model" in body:
        if body["model"] not in MODELS:
            _bad("지원하지 않는 모델입니다.")
        values["model"] = body["model"]
    if "effort" in body:
        if body["effort"] not in EFFORTS:
            _bad("지원하지 않는 effort 입니다.")
        values["effort"] = body["effort"]
    store.save_settings(values)
    return get_settings()


# ----------------------------------------------------------------------------
# 사용 현황
# ----------------------------------------------------------------------------
def usage_report(days: int = 30) -> dict:
    days = max(1, min(days, 180))
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    daily = store.rows(
        """SELECT day, SUM(kind='question') AS questions, SUM(kind='api_call') AS calls,
                  SUM(input_tokens + cache_read + cache_write) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  ROUND(SUM(cost_usd), 4) AS cost, COUNT(DISTINCT usr_id) AS users
             FROM ai_usage WHERE day >= ? GROUP BY day ORDER BY day""",
        (since,),
    )
    by_user = store.rows(
        """SELECT a.usr_id, u.usr_nm, SUM(kind='question') AS questions, SUM(kind='api_call') AS calls,
                  SUM(input_tokens + cache_read + cache_write) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  ROUND(SUM(cost_usd), 4) AS cost, MAX(a.ts) AS last_used
             FROM ai_usage a LEFT JOIN users u ON u.usr_id = a.usr_id
            WHERE day >= ? GROUP BY a.usr_id ORDER BY cost DESC""",
        (since,),
    )
    total = store.row(
        """SELECT COALESCE(SUM(kind='question'),0) AS questions, COALESCE(ROUND(SUM(cost_usd),4),0) AS cost,
                  COALESCE(SUM(input_tokens + cache_read + cache_write),0) AS input_tokens,
                  COALESCE(SUM(output_tokens),0) AS output_tokens, COUNT(DISTINCT usr_id) AS users
             FROM ai_usage WHERE day >= ?""",
        (since,),
    )
    return {"since": since, "days": days, "total": total, "daily": daily, "byUser": by_user}


# ----------------------------------------------------------------------------
# 로그인 이력 / 잠금 / 세션
# ----------------------------------------------------------------------------
def login_log(limit: int = 200, q: str | None = None) -> list[dict]:
    sql = """SELECT l.id, l.usr_id, u.usr_nm, l.ts, l.success, l.reason, l.ip
               FROM login_log l LEFT JOIN users u ON u.usr_id = l.usr_id"""
    params: tuple = ()
    if q:
        sql += " WHERE l.usr_id LIKE ?"
        params = (f"%{q}%",)
    sql += " ORDER BY l.id DESC LIMIT ?"
    return store.rows(sql, (*params, max(1, min(limit, 1000))))


def locks() -> list[dict]:
    now = time.time()
    return [
        {**r, "locked": r["locked_until"] > now, "remainSec": max(0, int(r["locked_until"] - now))}
        for r in store.rows("SELECT * FROM login_attempts WHERE fail_count > 0 OR locked_until > ? ORDER BY locked_until DESC",
                            (now,))
    ]


def unlock(usr_id: str) -> None:
    store.execute("DELETE FROM login_attempts WHERE usr_id=?", (usr_id,))


def sessions() -> list[dict]:
    return store.rows(
        """SELECT s.sid, s.usr_id, u.usr_nm, s.created_at, s.last_seen, s.expires_at, s.ip, s.user_agent
             FROM sessions s LEFT JOIN users u ON u.usr_id = s.usr_id
            WHERE s.expires_at > ? ORDER BY s.last_seen DESC""",
        (time.time(),),
    )


def kill_session(sid: str) -> None:
    store.execute("DELETE FROM sessions WHERE sid=?", (sid,))
