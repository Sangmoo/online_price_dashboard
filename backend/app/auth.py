"""로그인 / 세션 / 권한."""
from __future__ import annotations

import json
import re
import secrets
import time
from typing import Callable

from fastapi import HTTPException, Request

from . import appdb, config, db, logs, sql_trace, userdb

_log = logs.get("auth")

SESSION_COOKIE = "opd_session"
SESSION_TTL = 60 * 60          # 1시간 (사용 시마다 연장)
MAX_FAILS = 5
LOCK_SECONDS = 60

PAGES = ["dashboard", "detail", "mall_shop", "sale_dashboard", "sale_monthly", "invt_plan"]   # 권한 부여 가능한 일반 페이지
EMP_NO_RE = re.compile(r"^\d{6}$")             # 사번 형식 (6자리 숫자)
PAGE_GROUPS = {"dashboard": "온라인 가격", "detail": "온라인 가격", "mall_shop": "온라인 가격", "sale_dashboard": "판매 분석", "sale_monthly": "판매 분석",
               "invt_plan": "데이터 관리"}
PAGE_LABELS = {"dashboard": "대시보드", "detail": "일자별 상세", "mall_shop": "판매처 매장 연결", "sale_dashboard": "판매 현황", "sale_monthly": "월별 매장별 판매 집계", "invt_plan": "매장 재고 실사계획",
               "admin": "관리자"}

MSG_BAD_LOGIN = "아이디 또는 패스워드가 일치하지 않습니다."
MSG_NOT_REGISTERED = "이 서비스에 등록되지 않은 사용자입니다. 관리자에게 사용자 등록을 요청하세요."


class AuthError(HTTPException):
    def __init__(self, status: int, message: str, code: str, **extra):
        super().__init__(status_code=status, detail={"message": message, "code": code, **extra})


# ----------------------------------------------------------------------------
# 사용자 권한
# ----------------------------------------------------------------------------
def is_super_admin(usr_id: str) -> bool:
    return usr_id == config.SUPER_ADMIN_ID


def is_emp_no(usr_id: str) -> bool:
    return bool(EMP_NO_RE.match(usr_id or ""))


def registered_user(usr_id: str, usr_nm: str | None) -> dict | None:
    """서비스 사용자 테이블(T_ERP_WEB_USER)에 등록된 사용자만 반환. 자동 등록하지 않는다.
    예외: 최고 관리자는 테이블이 비어 있어도 들어올 수 있도록 없으면 ADMIN 으로 등록한다."""
    u = userdb.get_user(usr_id, fresh=True)
    if u is None:
        if not is_super_admin(usr_id):
            return None
        userdb.create_user(usr_id, usr_nm, "ADMIN", PAGES, by="SYSTEM")
    elif usr_nm and u["usr_nm"] != usr_nm:
        userdb.update_name(usr_id, usr_nm)
    return userdb.get_user(usr_id, fresh=True)


def effective(u: dict, settings: dict | None = None) -> dict:
    """users 행 + 전역 설정 → 실제 적용 권한."""
    s = settings or userdb.get_settings()
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
        # 브랜드 데이터 권한: None = 모든 브랜드 (최고 관리자, 브랜드 미지정 사용자)
        "brands": None if super_admin else (json.loads(u.get("brands") or "[]") or None),
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
    return appdb.lock_get(usr_id)


def _record(usr_id: str, success: bool, reason: str, ip: str | None):
    appdb.login_log_add(usr_id, success, reason, ip)
    (_log.info if success else _log.warning)("로그인 %s user=%s ip=%s", reason, usr_id, ip)


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
        appdb.lock_set(usr_id, 0 if locked_until else fails, locked_until)
        _record(usr_id, False, "LOCKED" if locked_until else "BAD_CREDENTIALS", ip)
        if locked_until:
            raise AuthError(429, f"{MSG_BAD_LOGIN} 로그인 {MAX_FAILS}회 실패로 1분간 로그인할 수 없습니다.",
                            "LOCKED", retryAfter=LOCK_SECONDS)
        raise AuthError(401, MSG_BAD_LOGIN, "BAD_CREDENTIALS", remaining=MAX_FAILS - fails)

    appdb.lock_clear(usr_id)
    u = registered_user(found["USR_ID"], found["USR_NM"])
    if u is None:
        _record(usr_id, False, "NOT_REGISTERED", ip)
        raise AuthError(403, MSG_NOT_REGISTERED, "NOT_REGISTERED")
    me = effective(u)
    if not me["active"]:
        _record(usr_id, False, "INACTIVE", ip)
        raise AuthError(403, "사용이 중지된 계정입니다. 관리자에게 문의하세요.", "INACTIVE")
    _check_maintenance(me, lambda: _record(usr_id, False, "MAINTENANCE", ip))

    token = secrets.token_urlsafe(32)
    appdb.session_purge(now)
    appdb.session_create(token, secrets.token_hex(8), usr_id, now, now + SESSION_TTL, ip, user_agent)
    userdb.touch_login(usr_id)
    _record(usr_id, True, "OK", ip)
    return token, me


def logout(token: str | None):
    if token:
        appdb.session_delete(token)


# ----------------------------------------------------------------------------
# 요청 인증 (FastAPI 의존성)
# ----------------------------------------------------------------------------
BACKGROUND_HEADER = "X-Background"


def is_background(request: Request) -> bool:
    headers = getattr(request, "headers", None) or {}
    return headers.get(BACKGROUND_HEADER) == "1"


def _check_maintenance(me: dict, on_block=None) -> None:
    """점검 모드면 관리자 외 사용자는 막는다 (503 MAINTENANCE). 세션은 지우지 않아 점검이 끝나면 그대로 이어서 쓴다."""
    if me["role"] == "ADMIN":
        return
    from . import notices

    msg = notices.blocked_message()
    if msg:
        if on_block:
            on_block()
        raise AuthError(503, msg, "MAINTENANCE")


# ----------------------------------------------------------------------------
# 사용자 화면 미리보기 (관리자 · 읽기 전용)
# ----------------------------------------------------------------------------
VIEW_AS_HEADER = "X-View-As"
# 미리보기 중에도 관리자 본인으로 처리하는 경로 (세션 · 미리보기 시작/확인)
VIEW_AS_EXEMPT = ("/api/auth/", "/api/admin/view-as")


def can_view_as(admin_me: dict, target: dict) -> str | None:
    """관리자가 대상 사용자 화면을 미리볼 수 있는지. 볼 수 없으면 이유. 관리자가 가진 것보다 넓은 권한은 볼 수 없다."""
    if admin_me["role"] != "ADMIN":
        return "관리자만 사용자 화면을 미리볼 수 있습니다."
    if target["id"] == admin_me["id"]:
        return "본인 화면은 미리볼 필요가 없습니다."
    if admin_me.get("superAdmin"):
        return None
    if target.get("superAdmin"):
        return "최고 관리자 화면은 미리볼 수 없습니다."
    extra = [p for p in target["pages"] if p != "admin" and p not in admin_me["pages"]]
    if extra:
        return f"내가 권한이 없는 메뉴가 있는 사용자입니다: {', '.join(PAGE_LABELS.get(p, p) for p in extra)}"
    if admin_me.get("brands") is not None and (target.get("brands") is None or set(target["brands"]) - set(admin_me["brands"])):
        return "내 브랜드 권한보다 넓은 브랜드 권한을 가진 사용자입니다."
    return None


def view_as_user(admin_me: dict, target_id: str) -> dict:
    u = userdb.get_user(target_id)
    if not u:
        raise AuthError(404, "등록되지 않은 사용자입니다.", "NOT_FOUND")
    target = effective(u)
    why = can_view_as(admin_me, target)
    if why:
        raise AuthError(403, why, "FORBIDDEN")
    return target


def _readonly_path(method: str, path: str) -> bool:
    """미리보기 중 허용: 조회(GET)만. 엑셀 · 파일 내려받기는 막는다 (본인 권한으로 받도록)."""
    return method == "GET" and "/export" not in path and not path.endswith("/file")


def _apply_view_as(request: Request, me: dict) -> dict:
    target_id = (getattr(request, "headers", None) or {}).get(VIEW_AS_HEADER)
    path = request.url.path if getattr(request, "url", None) else ""
    if not target_id or any(path.startswith(x) for x in VIEW_AS_EXEMPT):
        return me
    target = view_as_user(me, target_id)
    if not _readonly_path(request.method, path):
        raise AuthError(403, "사용자 화면 미리보기 중에는 조회만 할 수 있습니다 (저장 · 엑셀 · AI 질문 불가).", "VIEW_AS_READONLY")
    target["viewAs"] = {"by": me["id"], "byName": me["name"]}
    target["ip"] = me.get("ip")
    target["sessionExpiresAt"] = me["sessionExpiresAt"]
    request.state.usr_id = f"{me['id']}>{target['id']}"
    return target


def current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    now = time.time()
    sess = appdb.session_get(token) if token else None
    if not sess or sess["expires_at"] <= now:
        if sess:
            appdb.session_delete(token)
        raise AuthError(401, "로그인이 필요합니다." if not sess else "1시간 동안 사용하지 않아 로그아웃되었습니다.",
                        "SESSION_EXPIRED")
    u = userdb.get_user(sess["usr_id"])
    me = effective(u) if u else None
    if not me or not me["active"]:
        appdb.session_delete(token)
        raise AuthError(401, "사용이 중지된 계정입니다. 관리자에게 문의하세요.", "INACTIVE")

    # 서비스 이용 시 세션 만료시간 연장 (슬라이딩 1시간). DB 쓰기는 1분에 한 번만.
    # 화면이 사람 조작 없이 스스로 보내는 요청(주기 확인 등, 헤더 X-Background: 1)은 연장하지 않는다
    # → 화면을 열어만 두고 1시간 쓰지 않으면 정상적으로 로그아웃된다.
    if is_background(request):
        expires = sess["expires_at"]
    elif now - sess["last_seen"] >= appdb.TOUCH_INTERVAL:
        expires = now + SESSION_TTL
        appdb.session_touch(token, now, expires)
    else:
        expires = sess["expires_at"]
    request.state.usr_id = me["id"]
    sql_trace.set_user(me["id"])   # 사용 쿼리: 미리보기 중이어도 실제로 조회한 관리자 기준
    _check_maintenance(me)
    request.state.session_expires = int(expires)
    me["ip"] = request.client.host if getattr(request, "client", None) else None  # 관리자 변경 이력용
    me["sessionExpiresAt"] = int(expires)
    return _apply_view_as(request, me)


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
