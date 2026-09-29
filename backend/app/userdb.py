"""사용자 권한 · 페이지 권한 · 전역 설정 저장소 (Oracle).

T_ERP_WEB_USER / T_ERP_WEB_USER_PAGE / T_ERP_WEB_SETTING
반환 형태는 기존 SQLite users 행과 같은 dict 로 맞춰 호출부 변경을 최소화한다.
요청마다 조회되므로 짧은 캐시를 두고, 쓰기 시 즉시 무효화한다.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any

from . import db

CACHE_TTL = 20  # 초. 다른 서버 인스턴스에서 바뀐 권한도 이 시간 안에 반영

# 설정 키 매핑: 앱 키 → (DB SET_KEY, 형)
SETTING_KEYS: dict[str, tuple[str, str]] = {
    "ai_enabled": ("AI_ENABLED", "yn"),
    "default_daily_questions": ("DEFAULT_DAY_QSTN_LMT", "int"),
    "default_daily_cost_usd": ("DEFAULT_DAY_COST_LMT", "float"),
    "model": ("AI_MODEL", "str"),
    "effort": ("AI_EFFORT", "str"),
}
DEFAULT_SETTINGS: dict[str, Any] = {
    "ai_enabled": True,
    "default_daily_questions": 10,
    "default_daily_cost_usd": 2.0,
    "model": None,
    "effort": None,
}

_lock = threading.Lock()
_user_cache: dict[str, tuple[float, dict | None]] = {}
_settings_cache: tuple[float, dict] | None = None


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _fmt14(v: str | None) -> str | None:
    """YYYYMMDDHH24MISS → 'YYYY-MM-DD HH:MM:SS' (화면 표시용, 기존 SQLite 형식과 동일)."""
    if not v or len(v) < 14:
        return v
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}"


def invalidate(usr_id: str | None = None) -> None:
    global _settings_cache
    with _lock:
        if usr_id is None:
            _user_cache.clear()
            _settings_cache = None
        else:
            _user_cache.pop(usr_id, None)


# ----------------------------------------------------------------------------
# 사용자
# ----------------------------------------------------------------------------
USER_SQL = """
    SELECT U.USR_ID, U.USR_NM, U.ROLE_CD, U.AI_USE_YN, U.DAY_QSTN_LMT, U.DAY_COST_LMT, U.USE_YN,
           U.LAST_LOGIN_DAY, U.INS_DAY, U.UPT_DAY, U.UPT_USERID
      FROM T_ERP_WEB_USER U
"""


def _pages_of(ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {i: [] for i in ids}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        binds = {f"u{j}": v for j, v in enumerate(chunk)}
        rows = db.query(
            f"SELECT USR_ID, PAGE_CD FROM T_ERP_WEB_USER_PAGE WHERE USR_ID IN ({', '.join(':' + k for k in binds)})",
            binds,
        )[1]
        for uid, page in rows:
            out.setdefault(uid, []).append(page)
    return out


def _to_row(r: dict, pages: list[str]) -> dict:
    """기존 SQLite users 행과 같은 키."""
    return {
        "usr_id": r["USR_ID"],
        "usr_nm": r["USR_NM"],
        "role": r["ROLE_CD"],
        "pages": json.dumps(pages),
        "ai_enabled": 1 if r["AI_USE_YN"] == "Y" else 0,
        "daily_questions": int(r["DAY_QSTN_LMT"]) if r["DAY_QSTN_LMT"] is not None else None,
        "daily_cost_usd": float(r["DAY_COST_LMT"]) if r["DAY_COST_LMT"] is not None else None,
        "active": 1 if r["USE_YN"] == "Y" else 0,
        "last_login_at": _fmt14(r["LAST_LOGIN_DAY"]),
        "created_at": _fmt14(r["INS_DAY"]),
        "updated_at": _fmt14(r["UPT_DAY"]),
        "updated_by": r["UPT_USERID"],
    }


def get_user(usr_id: str, fresh: bool = False) -> dict | None:
    now = time.time()
    if not fresh:
        with _lock:
            hit = _user_cache.get(usr_id)
        if hit and hit[0] > now:
            return hit[1]
    rows = db.query_dicts(USER_SQL + " WHERE U.USR_ID = :id", {"id": usr_id})
    row = _to_row(rows[0], _pages_of([usr_id])[usr_id]) if rows else None
    with _lock:
        _user_cache[usr_id] = (now + CACHE_TTL, row)
    return row


def list_users(q: str | None = None) -> list[dict]:
    sql, p = USER_SQL, {}
    if q:
        sql += " WHERE U.USR_ID LIKE :q OR U.USR_NM LIKE :q"
        p["q"] = f"%{q}%"
    rows = db.query_dicts(sql + " ORDER BY DECODE(U.ROLE_CD, 'ADMIN', 0, 1), U.LAST_LOGIN_DAY DESC NULLS LAST", p)
    pages = _pages_of([r["USR_ID"] for r in rows]) if rows else {}
    return [_to_row(r, pages.get(r["USR_ID"], [])) for r in rows]


def user_ids() -> set[str]:
    return {r[0] for r in db.query("SELECT USR_ID FROM T_ERP_WEB_USER")[1]}


def create_user(usr_id: str, usr_nm: str | None, role: str, pages: list[str], by: str, *,
                ai_enabled: bool = True, daily_questions: int | None = None,
                daily_cost_usd: float | None = None, active: bool = True) -> None:
    now = _now14()
    with db.get_pool().acquire() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO T_ERP_WEB_USER (USR_ID, USR_NM, ROLE_CD, AI_USE_YN, DAY_QSTN_LMT, DAY_COST_LMT, USE_YN,
                                              INS_DAY, INS_USERID)
                   VALUES (:id, :nm, :role_cd, :ai_yn, :q_lmt, :c_lmt, :use_yn, :d, :usr_by)""",
                {"id": usr_id, "nm": usr_nm, "role_cd": role, "ai_yn": "Y" if ai_enabled else "N",
                 "q_lmt": daily_questions, "c_lmt": daily_cost_usd, "use_yn": "Y" if active else "N",
                 "d": now, "usr_by": by},
            )
            for page in pages:
                cur.execute(
                    "INSERT INTO T_ERP_WEB_USER_PAGE (USR_ID, PAGE_CD, INS_DAY, INS_USERID) VALUES (:id, :p, :d, :usr_by)",
                    {"id": usr_id, "p": page, "d": now, "usr_by": by},
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    invalidate(usr_id)


def update_user(usr_id: str, values: dict[str, Any], by: str) -> None:
    """values 키: role, pages(list), ai_enabled(bool), daily_questions, daily_cost_usd, active(bool), usr_nm."""
    col_map = {"role": "ROLE_CD", "usr_nm": "USR_NM", "daily_questions": "DAY_QSTN_LMT",
               "daily_cost_usd": "DAY_COST_LMT"}
    sets, p = [], {"id": usr_id}
    for k, col in col_map.items():
        if k in values:
            sets.append(f"{col} = :v_{k}")
            p[f"v_{k}"] = values[k]
    for k, col in (("ai_enabled", "AI_USE_YN"), ("active", "USE_YN")):
        if k in values:
            sets.append(f"{col} = :v_{k}")
            p[f"v_{k}"] = "Y" if values[k] else "N"
    now = _now14()
    with db.get_pool().acquire() as conn:
        cur = conn.cursor()
        try:
            if sets or "pages" in values:
                sets += ["UPT_DAY = :upt_d", "UPT_USERID = :upt_u"]
                p.update({"upt_d": now, "upt_u": by})
                cur.execute(f"UPDATE T_ERP_WEB_USER SET {', '.join(sets)} WHERE USR_ID = :id", p)
            if "pages" in values:
                cur.execute("SELECT PAGE_CD FROM T_ERP_WEB_USER_PAGE WHERE USR_ID = :id", {"id": usr_id})
                current = {r[0] for r in cur.fetchall()}
                target = set(values["pages"])
                for page in current - target:
                    cur.execute("DELETE FROM T_ERP_WEB_USER_PAGE WHERE USR_ID = :id AND PAGE_CD = :p",
                                {"id": usr_id, "p": page})
                for page in target - current:
                    cur.execute(
                        "INSERT INTO T_ERP_WEB_USER_PAGE (USR_ID, PAGE_CD, INS_DAY, INS_USERID) VALUES (:id, :p, :d, :usr_by)",
                        {"id": usr_id, "p": page, "d": now, "usr_by": by},
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    invalidate(usr_id)


def update_name(usr_id: str, usr_nm: str) -> None:
    db.execute("UPDATE T_ERP_WEB_USER SET USR_NM = :nm WHERE USR_ID = :id", {"nm": usr_nm, "id": usr_id})
    invalidate(usr_id)


def touch_login(usr_id: str) -> None:
    db.execute("UPDATE T_ERP_WEB_USER SET LAST_LOGIN_DAY = :d WHERE USR_ID = :id", {"d": _now14(), "id": usr_id})
    invalidate(usr_id)


# ----------------------------------------------------------------------------
# 전역 설정
# ----------------------------------------------------------------------------
def _parse(val: str | None, typ: str):
    if val is None or val == "":
        return None
    if typ == "yn":
        return val == "Y"
    if typ == "int":
        return int(float(val))
    if typ == "float":
        return float(val)
    return val


def get_settings() -> dict[str, Any]:
    global _settings_cache
    now = time.time()
    with _lock:
        if _settings_cache and _settings_cache[0] > now:
            return dict(_settings_cache[1])
    rows = dict(db.query("SELECT SET_KEY, SET_VAL FROM T_ERP_WEB_SETTING")[1])
    out = dict(DEFAULT_SETTINGS)
    for key, (db_key, typ) in SETTING_KEYS.items():
        if db_key in rows:
            v = _parse(rows[db_key], typ)
            if v is not None or typ == "str":  # 모델/effort 는 NULL = .env 기본값
                out[key] = v
    with _lock:
        _settings_cache = (now + CACHE_TTL, out)
    return dict(out)


def save_settings(values: dict[str, Any], by: str) -> dict[str, Any]:
    now = _now14()
    with db.get_pool().acquire() as conn:
        cur = conn.cursor()
        try:
            for key, v in values.items():
                if key not in SETTING_KEYS:
                    continue
                db_key, typ = SETTING_KEYS[key]
                sval = None if v is None else ("Y" if v else "N") if typ == "yn" else str(v)
                cur.execute(
                    """MERGE INTO T_ERP_WEB_SETTING T
                       USING (SELECT :k AS SET_KEY FROM DUAL) S ON (T.SET_KEY = S.SET_KEY)
                       WHEN MATCHED THEN UPDATE SET SET_VAL = :v, UPT_DAY = :d, UPT_USERID = :usr_by
                       WHEN NOT MATCHED THEN INSERT (SET_KEY, SET_VAL, UPT_DAY, UPT_USERID) VALUES (:k, :v, :d, :usr_by)""",
                    {"k": db_key, "v": sval, "d": now, "usr_by": by},
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    invalidate()
    return get_settings()


def grant_page_once(flag: str, page: str, if_has: str) -> list[str]:
    """새 메뉴를 기존 사용자에게 1회 부여: if_has 메뉴 권한이 있는 사용자에게 page 를 더한다.
    실행 여부는 T_ERP_WEB_SETTING 의 flag 키로 기록해 한 번만 한다(이후 관리자가 회수해도 다시 주지 않음)."""
    if db.query("SELECT COUNT(*) FROM T_ERP_WEB_SETTING WHERE SET_KEY = :k", {"k": flag})[1][0][0]:
        return []
    now = _now14()
    granted = []
    for u in list_users():
        pages = json.loads(u["pages"] or "[]")
        if if_has in pages and page not in pages:
            db.execute("INSERT INTO T_ERP_WEB_USER_PAGE (USR_ID, PAGE_CD, INS_DAY, INS_USERID) VALUES (:id, :p, :d, 'MIGRATION')",
                       {"id": u["usr_id"], "p": page, "d": now})
            granted.append(u["usr_id"])
    db.execute("INSERT INTO T_ERP_WEB_SETTING (SET_KEY, SET_VAL, SET_DESC, UPT_DAY, UPT_USERID) VALUES (:k, 'Y', :d, :t, 'MIGRATION')",
               {"k": flag, "d": f"1회 메뉴 부여 완료: {page}", "t": now})
    invalidate()
    return granted


# ----------------------------------------------------------------------------
# 1회성: SQLite(이전 저장소) → Oracle 이전
# ----------------------------------------------------------------------------
def migrate_from_sqlite(store) -> list[str]:
    """Oracle 에 사용자가 한 명도 없을 때만 SQLite users/settings 를 옮긴다. 옮긴 사용자 ID 반환."""
    if db.query("SELECT COUNT(*) FROM T_ERP_WEB_USER")[1][0][0] > 0:
        return []
    legacy = store.rows("SELECT * FROM users")
    moved = []
    for u in legacy:
        create_user(u["usr_id"], u["usr_nm"], u["role"], json.loads(u["pages"] or "[]"), by="MIGRATION")
        update_user(u["usr_id"], {
            "ai_enabled": bool(u["ai_enabled"]),
            "daily_questions": u["daily_questions"],
            "daily_cost_usd": u["daily_cost_usd"],
            "active": bool(u["active"]),
        }, by="MIGRATION")
        if u.get("last_login_at"):
            ts = u["last_login_at"].replace("-", "").replace(":", "").replace(" ", "")[:14]
            db.execute("UPDATE T_ERP_WEB_USER SET LAST_LOGIN_DAY = :d, UPT_DAY = NULL, UPT_USERID = NULL WHERE USR_ID = :id",
                       {"d": ts, "id": u["usr_id"]})
        moved.append(u["usr_id"])
    legacy_settings = {r["key"]: json.loads(r["value"]) for r in store.rows("SELECT key, value FROM settings")
                       if not r["key"].startswith("_")}
    if legacy_settings:
        save_settings(legacy_settings, by="MIGRATION")
    invalidate()
    return moved
