"""로그인 / 세션 / 권한."""
from __future__ import annotations

import json
import secrets
import time
from typing import Callable

from fastapi import HTTPException, Request

from . import config, db, store

SESSION_COOKIE = "opd_session"
SESSION_TTL = 60 * 60          # 1시간 (사용 시마다 연장)
MAX_FAILS = 5
LOCK_SECONDS = 60

PAGES = ["dashboard", "detail", "invt_plan"]   # 권한 부여 가능한 일반 페이지
DEFAULT_PAGES = PAGES                          # 신규 사용자 기본 권한 (현재 전 페이지)
PAGE_LABELS = {"dashboard": "대시보드", "detail": "일자별 상세", "invt_plan": "매장 재고 실사계획", "admin": "관리자"}

MSG_BAD_LOGIN = "아이디 또는 패스워드가 일치하지 않습니다."


class AuthError(HTTPException):
    def __init__(self, status: int, message: str, code: str, **extra):
        super().__init__(status_code=status, detail={"message": message, "code": code, **extra})


# ----------------------------------------------------------------------------
# 사용자 권한
# ----------------------------------------------------------------------------
def is_super_admin(usr_id: str) -> bool:
    return usr_id == config.SUPER_ADMIN_ID


def ensure_user(usr_id: str, usr_nm: str | None) -> dict:
    u = store.row("SELECT * FROM users WHERE usr_id=?", (usr_id,))
    if u is None:
        role = "ADMIN" if is_super_admin(usr_id) else "USER"
        store.execute("INSERT INTO users(usr_id, usr_nm, role, pages) VALUES(?,?,?,?)",
                      (usr_id, usr_nm, role, json.dumps(DEFAULT_PAGES)))
    elif usr_nm and u["usr_nm"] != usr_nm:
        store.execute("UPDATE users SET usr_nm=? WHERE usr_id=?", (usr_nm, usr_id))
    return store.row("SELECT * FROM users WHERE usr_id=?", (usr_id,))


def effective(u: dict, settings: dict | None = None) -> dict:
    """users 행 + 전역 설정 → 실제 적용 권한."""
    s = settings or store.get_settings()
    super_admin = is_super_admin(u["usr_id"])
    role = "ADMIN" if super_admin else u["role"]
    pages = PAGES[:] if super_admin else [p for p in json.loads(u["pages"] or "[]") if p in PAGES]
    if role == "ADMIN":
        pages.append("admin")
    return {
        "id": u["usr_id"],
        "name": u["usr_nm"] or u["usr_id"],
        "role": role,
        "superAdmin": super_admin,
        "active": bool(u["active"]) or super_admin,
        "pages": pages,
        "ai": {
            "enabled": bool(s["ai_enabled"]) and bool(u["ai_enabled"]),
            "globalEnabled": bool(s["ai_enabled"]),
            "userEnabled": bool(u["ai_enabled"]),
            "dailyQuestions": u["daily_questions"] if u["daily_questions"] is not None else s["default_daily_questions"],
            "dailyCostUsd": u["daily_cost_usd"] if u["daily_cost_usd"] is not None else s["default_daily_cost_usd"],
            "customLimits": u["daily_questions"] is not None or u["daily_cost_usd"] is not None,
        },
    }


# ----------------------------------------------------------------------------
# 로그인 / 잠금
# ----------------------------------------------------------------------------
def _lock_state(usr_id: str) -> dict:
    return store.row("SELECT * FROM login_attempts WHERE usr_id=?", (usr_id,)) or {"fail_count": 0, "locked_until": 0}


def _log(usr_id: str, success: bool, reason: str, ip: str | None):
    store.execute("INSERT INTO login_log(usr_id, success, reason, ip) VALUES(?,?,?,?)", (usr_id, int(success), reason, ip))


def _verify_oracle(usr_id: str, password: str) -> dict | None:
    # 복호화한 비밀번호를 앱으로 가져오지 않고 DB 안에서 비교한다.
    found = db.query_dicts(
        """
        SELECT USR_ID, USR_NM
          FROM T_USR
         WHERE USR_ID = :id
           AND CRYPTO_DECRYPT(PWD) = :pwd
           AND NVL(USE_YN, 'N') = 'Y'
           AND DEL_DAY IS NULL
        """,
        {"id": usr_id, "pwd": password},
    )
    return found[0] if found else None


def login(usr_id: str, password: str, ip: str | None, user_agent: str | None) -> tuple[str, dict]:
    usr_id = (usr_id or "").strip()
    if not usr_id or not password or len(usr_id) > 20 or len(password) > 100:
        raise AuthError(401, MSG_BAD_LOGIN, "BAD_CREDENTIALS")

    now = time.time()
    st = _lock_state(usr_id)
    if st["locked_until"] > now:
        remain = int(st["locked_until"] - now) + 1
        raise AuthError(429, f"로그인 {MAX_FAILS}회 실패로 1분간 로그인할 수 없습니다. {remain}초 후 다시 시도하세요.",
                        "LOCKED", retryAfter=remain)

    found = _verify_oracle(usr_id, password)
    if not found:
        fails = st["fail_count"] + 1
        locked_until = now + LOCK_SECONDS if fails >= MAX_FAILS else 0
        store.execute(
            """INSERT INTO login_attempts(usr_id, fail_count, locked_until) VALUES(?,?,?)
               ON CONFLICT(usr_id) DO UPDATE SET fail_count=excluded.fail_count, locked_until=excluded.locked_until""",
            (usr_id, 0 if locked_until else fails, locked_until),
        )
        _log(usr_id, False, "LOCKED" if locked_until else "BAD_CREDENTIALS", ip)
        if locked_until:
            raise AuthError(429, f"{MSG_BAD_LOGIN} 로그인 {MAX_FAILS}회 실패로 1분간 로그인할 수 없습니다.",
                            "LOCKED", retryAfter=LOCK_SECONDS)
        raise AuthError(401, MSG_BAD_LOGIN, "BAD_CREDENTIALS", remaining=MAX_FAILS - fails)

    store.execute("DELETE FROM login_attempts WHERE usr_id=?", (usr_id,))
    u = ensure_user(found["USR_ID"], found["USR_NM"])
    me = effective(u)
    if not me["active"]:
        _log(usr_id, False, "INACTIVE", ip)
        raise AuthError(403, "사용이 중지된 계정입니다. 관리자에게 문의하세요.", "INACTIVE")

    token = secrets.token_urlsafe(32)
    store.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    store.execute(
        "INSERT INTO sessions(token, sid, usr_id, created_at, last_seen, expires_at, ip, user_agent) VALUES(?,?,?,?,?,?,?,?)",
        (token, secrets.token_hex(8), usr_id, now, now, now + SESSION_TTL, ip, (user_agent or "")[:200]),
    )
    store.execute("UPDATE users SET last_login_at=datetime('now','localtime') WHERE usr_id=?", (usr_id,))
    _log(usr_id, True, "OK", ip)
    return token, me


def logout(token: str | None):
    if token:
        store.execute("DELETE FROM sessions WHERE token=?", (token,))


# ----------------------------------------------------------------------------
# 요청 인증 (FastAPI 의존성)
# ----------------------------------------------------------------------------
def current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    now = time.time()
    sess = store.row("SELECT * FROM sessions WHERE token=?", (token,)) if token else None
    if not sess or sess["expires_at"] <= now:
        if sess:
            store.execute("DELETE FROM sessions WHERE token=?", (token,))
        raise AuthError(401, "로그인이 필요합니다." if not sess else "1시간 동안 사용하지 않아 로그아웃되었습니다.",
                        "SESSION_EXPIRED")
    u = store.row("SELECT * FROM users WHERE usr_id=?", (sess["usr_id"],))
    me = effective(u) if u else None
    if not me or not me["active"]:
        store.execute("DELETE FROM sessions WHERE token=?", (token,))
        raise AuthError(401, "사용이 중지된 계정입니다. 관리자에게 문의하세요.", "INACTIVE")

    # 서비스 이용 시 세션 만료시간 연장 (슬라이딩 1시간)
    expires = now + SESSION_TTL
    store.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE token=?", (now, expires, token))
    request.state.session_expires = int(expires)
    me["sessionExpiresAt"] = int(expires)
    return me


def require_page(page: str) -> Callable[[Request], dict]:
    def dep(request: Request) -> dict:
        me = current_user(request)
        if page not in me["pages"]:
            raise AuthError(403, f"'{PAGE_LABELS.get(page, page)}' 페이지 권한이 없습니다.", "FORBIDDEN")
        return me
    return dep


def require_admin(request: Request) -> dict:
    me = current_user(request)
    if me["role"] != "ADMIN":
        raise AuthError(403, "관리자 권한이 필요합니다.", "FORBIDDEN")
    return me
