"""관리자 기능: 사용자 권한/페이지/AI 설정, 전역 설정, 사용 현황, 로그인 이력, 세션 관리."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

from fastapi import HTTPException

from . import ai_tools, appdb, audit, auth, config, db, logs, model_router, mv_refresh, prewarm, usage, userdb

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
    online = appdb.online_user_ids(time.time())
    out = []
    for u in userdb.list_users(q):
        me = auth.effective(u, settings)
        tq, tc = today.get(u["usr_id"], (0, 0.0))
        out.append({
            **{k: me[k] for k in ("id", "name", "role", "superAdmin", "active", "pages", "ai", "brands")},
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


def _snap(usr_id: str) -> dict | None:
    """변경 이력용 사용자 설정 스냅샷"""
    u = userdb.get_user(usr_id, fresh=True)
    if not u:
        return None
    return {"role": u.get("role"), "pages": list(json.loads(u.get("pages") or "[]")),
            "brands": json.loads(u.get("brands") or "[]") or "모든 브랜드", "ai_enabled": bool(u.get("ai_enabled", 1)),
            "daily_questions": u.get("daily_questions"), "daily_cost_usd": u.get("daily_cost_usd"), "active": bool(u.get("active", 1))}


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
    if "brands" not in body:
        _bad("브랜드 권한(모든 브랜드 또는 브랜드 선택)을 지정하세요.")
    userdb.create_user(
        usr_id, emp["USR_NM"], v.get("role", "USER"), pages, by=admin["id"],
        ai_enabled=v.get("ai_enabled", True), daily_questions=v.get("daily_questions"),
        daily_cost_usd=v.get("daily_cost_usd"), active=v.get("active", True), brands=v.get("brands") or None,
    )
    after = _snap(usr_id)
    audit.record(admin, "USER_CREATE", usr_id, None, after,
                 summary=f"{emp['USR_NM']}({usr_id}) 추가 · " + audit.diff_summary({}, after))
    return next(x for x in list_users() if x["id"] == usr_id)


def save_user(admin: dict, usr_id: str, body: dict) -> dict:
    if userdb.get_user(usr_id, fresh=True) is None:
        raise HTTPException(status_code=404, detail={"message": "등록되지 않은 사용자입니다. 사용자 추가로 먼저 등록하세요.",
                                                     "code": "NOT_FOUND"})
    updates = _validate(usr_id, body)
    if updates:
        before = _snap(usr_id)
        userdb.update_user(usr_id, updates, by=admin["id"])
        if updates.get("active") is False:
            appdb.session_delete_user(usr_id)  # 즉시 로그아웃
        audit.record(admin, "USER_UPDATE", usr_id, before, _snap(usr_id))
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
    if "brands" in body:
        updates["brands"] = _validate_brands(body["brands"], super_admin)
    return updates


def brand_options() -> list[str]:
    from . import sale_dashboard as sd

    try:
        return list(sd.brand_teams())
    except Exception:  # noqa: BLE001 - 판매 데이터에 접근할 수 없으면 선택지 없음
        return []


def _validate_brands(v, super_admin: bool) -> list[str]:
    """None = 모든 브랜드(저장 시 빈 목록). 목록 = 그 브랜드만."""
    if v is None:
        return []
    if not isinstance(v, list) or not v or any(not isinstance(x, str) for x in v):
        _bad("브랜드 권한은 '모든 브랜드' 이거나 브랜드를 하나 이상 선택해야 합니다.")
    if super_admin:
        _bad("최고 관리자는 항상 모든 브랜드를 봅니다.")
    if not userdb.brand_table_ready():
        _bad("브랜드 권한 테이블이 없습니다. db/create_erp_web_user_brand.sql 을 먼저 실행하세요.")
    options = brand_options()
    bad = [x for x in v if x not in options]
    if bad:
        _bad(f"없는 브랜드입니다: {', '.join(bad)} (선택지: {', '.join(options)})")
    return sorted(set(v), key=options.index)


def page_meta() -> list[dict]:
    return [{"key": p, "label": auth.PAGE_LABELS[p], "group": auth.PAGE_GROUPS.get(p, "기타")} for p in auth.PAGES]


def save_permissions(admin: dict, changes: list) -> list[dict]:
    """메뉴 권한 일괄 저장. changes = [{id, pages}]. 하나라도 검증에 실패하면 아무것도 저장하지 않는다."""
    if not isinstance(changes, list) or not changes:
        _bad("변경할 사용자가 없습니다.")
    if len(changes) > 500:
        _bad("한 번에 500명까지 저장할 수 있습니다.")
    plan = []
    for ch in changes:
        usr_id = str((ch or {}).get("id") or "")
        if userdb.get_user(usr_id, fresh=True) is None:
            _bad(f"등록되지 않은 사용자입니다: {usr_id}")
        if auth.is_super_admin(usr_id):
            continue  # 최고 관리자는 항상 전체 메뉴
        plan.append((usr_id, _validate(usr_id, {"pages": ch.get("pages")})))
    for usr_id, updates in plan:
        before = _snap(usr_id)
        userdb.update_user(usr_id, updates, by=admin["id"])
        audit.record(admin, "PERM_UPDATE", usr_id, {"pages": before["pages"]} if before else None, {"pages": updates["pages"]})
    changed = {u for u, _ in plan}
    return [x for x in list_users() if x["id"] in changed]


# ----------------------------------------------------------------------------
# AI 도구 관리
# ----------------------------------------------------------------------------
def _tool_bad(ex: Exception):
    _bad(str(ex))


def ai_tools_overview() -> dict:
    from . import chat_tools as ct

    cfg = ai_tools.snapshot()
    builtin = []
    for tools, group, pages in ct.BUILTIN_GROUPS:
        for t in tools:
            c = cfg["builtin"].get(t["name"], {})
            builtin.append({
                "name": t["name"], "label": ct.TOOL_LABELS.get(t["name"], t["name"]), "group": group,
                "pages": [{"key": p, "label": auth.PAGE_LABELS[p]} for p in pages],
                "description": c.get("description") or t["description"], "defaultDescription": t["description"],
                "customized": bool(c.get("description")), "params": list(t["input_schema"].get("properties", {})),
                "enabled": c.get("enabled", True), "extraDesc": c.get("extraDesc", ""),
                "updatedAt": c.get("updatedAt"), "updatedBy": c.get("updatedBy"),
            })
    return {"storage": ai_tools.backend_name(), "builtin": builtin, "custom": cfg["custom"], "pages": page_meta(),
            "paramTypes": [{"key": k, "label": v} for k, v in ai_tools.PARAM_TYPES.items()],
            "maxRowsLimit": ai_tools.MAX_ROWS_LIMIT}


def data_status() -> dict:
    """사전 집계 뷰 상태 (관리자 화면). 캐시를 비우고 지금 상태를 읽는다."""
    from . import chat_tools_sale as cts

    cts._mv_state = None
    st = cts.mv_state()
    rows = None
    if st["mv_max"]:
        try:
            rows = int(db.query(f"SELECT COUNT(*) FROM {cts.MV_NAME}")[1][0][0])
        except Exception:  # noqa: BLE001
            rows = None
    return {
        "name": cts.MV_NAME, "usable": st["usable"], "staleness": st["staleness"],
        "lastRefresh": st["last_refresh"].strftime("%Y-%m-%d %H:%M:%S") if st["last_refresh"] else None,
        "mvMaxMonth": st["mv_max"], "baseMaxMonth": st["base_max"], "rows": rows,
        "hasCostColumn": "TOTAL_COST_AMT" in st.get("columns", set()),
        "behind": bool(st["base_max"] and st["mv_max"] and st["base_max"] > st["mv_max"]),
        "refresh": mv_refresh.state(),
        "productMv": _product_mv(),
        "prewarm": prewarm.state(),
    }


def _product_mv() -> dict:
    from . import sale_products

    sale_products.clear_state()
    ps = sale_products.mv_state()
    return {"exists": ps["exists"], "staleness": ps["staleness"], "mvMaxMonth": ps["mv_max"]}


def refresh_mv(admin: dict) -> dict:
    """[지금 갱신]: 백그라운드로 시작하고 현재 상태를 돌려준다 (이미 진행 중이면 그 상태)."""
    return {"refresh": mv_refresh.start(admin)}


def save_builtin_tool(admin: dict, name: str, body: dict) -> dict:
    from . import chat_tools as ct

    if name not in ct.BUILTIN_NAMES:
        _bad("기본 도구가 아닙니다.")
    old = ai_tools.snapshot()["builtin"].get(name, {})
    before = {"enabled": old.get("enabled", True), "description": old.get("description") or "(기본)", "extraDesc": old.get("extraDesc", "")}
    try:
        desc = body.get("description")
        default = next(t["description"] for tools, _, _ in ct.BUILTIN_GROUPS for t in tools if t["name"] == name)
        if desc is not None and str(desc).strip() == default.strip():
            desc = None  # 기본 설명과 같으면 저장하지 않음 (프로그램이 설명을 개선하면 자동 반영되도록)
        elif desc is None:
            desc = ai_tools.snapshot()["builtin"].get(name, {}).get("description")  # 사용 여부만 바꿀 때는 기존 설명 유지
        ai_tools.save_builtin(name, bool(body.get("enabled", True)), str(body.get("extraDesc") or ""), admin["id"],
                              description=desc)
    except ai_tools.ToolDefError as ex:
        _tool_bad(ex)
    audit.record(admin, "TOOL_BUILTIN", name, before,
                 {"enabled": bool(body.get("enabled", True)), "description": desc or "(기본)", "extraDesc": str(body.get("extraDesc") or "")})
    return ai_tools_overview()


def save_custom_tool(admin: dict, body: dict, name: str | None = None) -> dict:
    from . import chat_tools as ct

    if name is not None and str(body.get("name") or "").lower() != name:
        _bad("도구 이름은 바꿀 수 없습니다. 새 이름으로 추가한 뒤 기존 도구를 삭제하세요.")
    keys = ("label", "description", "page", "sql", "params", "maxRows", "enabled")
    old = next((c for c in ai_tools.snapshot()["custom"] if c["name"] == name), None) if name else None
    try:
        spec = ai_tools.validate_def(body, ct.BUILTIN_NAMES, auth.PAGES, existing=name)
        ai_tools.save_custom(spec, admin["id"], is_new=name is None)
    except ai_tools.ToolDefError as ex:
        _tool_bad(ex)
    after = {k: spec[k] for k in keys}
    if name is None:
        audit.record(admin, "TOOL_CREATE", spec["name"], None, after,
                     summary=f"{spec['label']}({spec['name']}) 추가 · 연결 메뉴 {auth.PAGE_LABELS.get(spec['page'], spec['page'])}"
                             f" · 입력값 {len(spec['params'])}개")
    else:
        audit.record(admin, "TOOL_UPDATE", name, {k: old[k] for k in keys} if old else None, after)
    return ai_tools_overview()


def delete_custom_tool(admin: dict, name: str) -> dict:
    old = next((c for c in ai_tools.snapshot()["custom"] if c["name"] == name), None)
    try:
        ai_tools.delete_custom(name, admin["id"])
    except ai_tools.ToolDefError as ex:
        _tool_bad(ex)
    audit.record(admin, "TOOL_DELETE", name, old, None, summary=f"{old['label'] if old else name}({name}) 삭제")
    return ai_tools_overview()


def test_custom_tool(body: dict) -> dict:
    """저장 전 시험 실행 (최대 20행). 정의 검증과 실행 오류를 그대로 돌려준다."""
    from . import chat_tools as ct

    spec_in = body.get("tool") or {}
    try:
        spec = ai_tools.validate_def(spec_in, ct.BUILTIN_NAMES, auth.PAGES, existing=str(spec_in.get("name") or "").lower())
    except ai_tools.ToolDefError as ex:
        return {"ok": False, "stage": "definition", "message": str(ex)}
    try:
        out = ai_tools.run_custom(spec, body.get("args") or {}, max_rows=20)
        return {"ok": True, "elapsedMs": out["elapsedMs"], "columns": out["table"]["columns"], "rows": out["table"]["rows"],
                "truncated": out["result"]["truncated"], "schema": ai_tools.tool_schema(spec)}
    except ai_tools.ToolArgError as ex:
        return {"ok": False, "stage": "args", "message": str(ex)}
    except Exception as ex:  # noqa: BLE001 - SQL 오류 메시지를 관리자에게 보여 준다
        return {"ok": False, "stage": "sql", "message": str(ex).splitlines()[0]}


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
        "logKeepDays": s.get("log_keep_days") or logs.DEFAULT_KEEP_DAYS,
        "autoModel": bool(s.get("auto_model")),
        "simpleModel": s.get("simple_model") or model_router.DEFAULT_SIMPLE_MODEL,
    }


def save_settings(body: dict, admin: dict) -> dict:
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
    if "autoModel" in body:
        values["auto_model"] = bool(body["autoModel"])
    if "simpleModel" in body:
        if body["simpleModel"] not in MODELS:
            _bad("지원하지 않는 모델입니다.")
        values["simple_model"] = body["simpleModel"]
    if "logKeepDays" in body:
        v = body["logKeepDays"]
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 365:
            _bad("로그 보관 기간은 1~365일입니다.")
        values["log_keep_days"] = v
    before = userdb.get_settings()
    userdb.save_settings(values, by=admin["id"])
    if "log_keep_days" in values:
        logs.cleanup(values["log_keep_days"])
    after = userdb.get_settings()
    rename = {"ai_enabled": "ai_enabled_global"}
    audit.record(admin, "SETTING_UPDATE", "운영 설정" if set(values) == {"log_keep_days"} else "AI 설정", {rename.get(k, k): before.get(k) for k in values},
                 {rename.get(k, k): after.get(k) for k in values})
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
            "byModel": rep_.get("byModel", []), "storage": usage.backend_name()}


# ----------------------------------------------------------------------------
# 로그인 이력 / 잠금 / 세션
# ----------------------------------------------------------------------------
def login_log(limit: int = 200, q: str | None = None) -> list[dict]:
    names = _names()
    return [{**r, "usr_nm": names.get(r["usr_id"])} for r in appdb.login_log_list(limit, q)]


def locks() -> list[dict]:
    now = time.time()
    return [{**r, "locked": r["locked_until"] > now, "remainSec": max(0, int(r["locked_until"] - now))} for r in appdb.locks_list(now)]


def unlock(admin: dict, usr_id: str) -> None:
    appdb.lock_clear(usr_id)
    audit.record(admin, "LOCK_RELEASE", usr_id, summary=f"{usr_id} 로그인 잠금 해제")


def sessions() -> list[dict]:
    names = _names()
    return [{**r, "usr_nm": names.get(r["usr_id"])} for r in appdb.sessions_active(time.time())]


def kill_session(admin: dict, sid: str) -> None:
    target = next((s for s in appdb.sessions_active(time.time()) if s["sid"] == sid), None)
    appdb.session_delete_sid(sid)
    who = target["usr_id"] if target else "-"
    audit.record(admin, "SESSION_KILL", who, summary=f"{who} 세션 강제 로그아웃 (IP {target['ip'] if target else '-'})")


def audit_log(action: str | None, q: str | None, days: int) -> dict:
    return {"logs": audit.search(action or None, q or None, days),
            "actions": [{"key": k, "label": v} for k, v in audit.ACTIONS.items()], "storage": audit.backend_name()}
