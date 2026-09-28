"""관리자 기능: 사용자 권한/페이지/AI 설정, 전역 설정, 사용 현황, 로그인 이력, 세션 관리."""
from __future__ import annotations

import time
from datetime import date, timedelta

from fastapi import HTTPException

from . import auth, config, db, store, usage, userdb

MODELS = ["claude-opus-5", "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5-1"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


# ----------------------------------------------------------------------------
# 사용자
# ----------------------------------------------------------------------------
def _names() -> dict[str, str]:
    return {u["usr_id"]: u["usr_nm"] for u in userdb.list_users()}


def list_users(q: str | None = None) -> list[dict]:
    settings = userdb.get_settings()
    today = usage.today_by_user()
    online = {r["usr_id"] for r in store.rows("SELECT DISTINCT usr_id FROM sessions WHERE expires_at > ?", (time.time(),))}
    out = []
    for u in userdb.list_users(q):
        me = auth.effective(u, settings)
        tq, tc = today.get(u["usr_id"], (0, 0.0))
        out.append({
            **{k: me[k] for k in ("id", "name", "role", "superAdmin", "active", "pages", "ai")},
            "rawAiEnabled": bool(u["ai_enabled"]),
            "rawDailyQuestions": u["daily_questions"],
            "rawDailyCostUsd": u["daily_cost_usd"],
            "lastLoginAt": u["last_login_at"],
            "createdAt": u["created_at"],
            "updatedAt": u["updated_at"],
            "updatedBy": u["updated_by"],
            "todayQuestions": tq,
            "todayCostUsd": tc,
            "online": u["usr_id"] in online,
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
    registered = userdb.user_ids()
    return [{"id": r["USR_ID"], "name": r["USR_NM"], "registered": r["USR_ID"] in registered}
            for r in found if auth.is_emp_no(r["USR_ID"])]


def _verify_emp(usr_id: str) -> dict:
    """사번 검증: 6자리 숫자 + 사내 계정(T_USR)에 사용 중으로 존재."""
    if not auth.is_emp_no(usr_id):
        _bad("사용자 ID 는 사번(6자리 숫자)이어야 합니다.")
    found = db.query_dicts(
        "SELECT USR_ID, USR_NM FROM T_USR WHERE USR_ID=:id AND NVL(USE_YN,'N')='Y' AND DEL_DAY IS NULL",
        {"id": usr_id},
    )
    if not found:
        _bad("사내 계정(T_USR)에 사용 중인 사번이 아닙니다.")
    return found[0]


def create_user(admin: dict, body: dict) -> dict:
    """관리자만 사용자를 등록한다. 권한·메뉴·AI 설정을 등록 시점에 함께 지정."""
    usr_id = str(body.get("id") or "").strip()
    emp = _verify_emp(usr_id)
    if userdb.get_user(usr_id, fresh=True):
        _bad("이미 등록된 사용자입니다.")
    v = _validate(usr_id, body)
    pages = v.get("pages", [])
    if not pages:
        _bad("메뉴 권한을 하나 이상 선택하세요.")
    userdb.create_user(
        usr_id, emp["USR_NM"], v.get("role", "USER"), pages, by=admin["id"],
        ai_enabled=v.get("ai_enabled", True), daily_questions=v.get("daily_questions"),
        daily_cost_usd=v.get("daily_cost_usd"), active=v.get("active", True),
    )
    return next(x for x in list_users() if x["id"] == usr_id)


def save_user(admin: dict, usr_id: str, body: dict) -> dict:
    if userdb.get_user(usr_id, fresh=True) is None:
        raise HTTPException(status_code=404, detail={"message": "등록되지 않은 사용자입니다. 사용자 추가로 먼저 등록하세요.",
                                                     "code": "NOT_FOUND"})
    updates = _validate(usr_id, body)
    if updates:
        userdb.update_user(usr_id, updates, by=admin["id"])
        if updates.get("active") is False:
            store.execute("DELETE FROM sessions WHERE usr_id=?", (usr_id,))  # 즉시 로그아웃
    return next(x for x in list_users() if x["id"] == usr_id)


def _validate(usr_id: str, body: dict) -> dict:
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
        updates["pages"] = sorted(set(pages), key=auth.PAGES.index)
    if "aiEnabled" in body:
        updates["ai_enabled"] = bool(body["aiEnabled"])
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
        updates["active"] = bool(body["active"])
    return updates


# ----------------------------------------------------------------------------
# 전역 AI 설정
# ----------------------------------------------------------------------------
def get_settings() -> dict:
    s = userdb.get_settings()
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


def save_settings(body: dict, by: str) -> dict:
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
    userdb.save_settings(values, by=by)
    return get_settings()


# ----------------------------------------------------------------------------
# 사용 현황
# ----------------------------------------------------------------------------
def usage_report(days: int = 30) -> dict:
    days = max(1, min(days, 180))
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    rep_ = usage.report(since)
    names = _names()
    by_user = [{**r, "usr_nm": names.get(r["usr_id"])} for r in rep_["byUser"]]
    return {"since": since, "days": days, "total": rep_["total"], "daily": rep_["daily"], "byUser": by_user,
            "storage": usage.backend_name()}


# ----------------------------------------------------------------------------
# 로그인 이력 / 잠금 / 세션
# ----------------------------------------------------------------------------
def login_log(limit: int = 200, q: str | None = None) -> list[dict]:
    sql = "SELECT l.id, l.usr_id, l.ts, l.success, l.reason, l.ip FROM login_log l"
    params: tuple = ()
    if q:
        sql += " WHERE l.usr_id LIKE ?"
        params = (f"%{q}%",)
    sql += " ORDER BY l.id DESC LIMIT ?"
    names = _names()
    return [{**r, "usr_nm": names.get(r["usr_id"])} for r in store.rows(sql, (*params, max(1, min(limit, 1000))))]


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
    names = _names()
    rows = store.rows(
        """SELECT sid, usr_id, created_at, last_seen, expires_at, ip, user_agent
             FROM sessions WHERE expires_at > ? ORDER BY last_seen DESC""",
        (time.time(),),
    )
    return [{**r, "usr_nm": names.get(r["usr_id"])} for r in rows]


def kill_session(sid: str) -> None:
    store.execute("DELETE FROM sessions WHERE sid=?", (sid,))
