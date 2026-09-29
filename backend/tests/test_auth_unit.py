"""로그인 · 잠금 · 등록 사용자만 허용 · 세션 · 페이지 권한 · 관리자 입력 검증. Oracle 은 가짜로 대체."""
import json

import pytest
from fastapi import HTTPException

from app import admin, appdb, auth

SETTINGS = {"ai_enabled": True, "default_daily_questions": 10, "default_daily_cost_usd": 2.0, "model": None, "effort": None}


def _user(usr_id, role="USER", pages=("dashboard",), active=1):
    return {"usr_id": usr_id, "usr_nm": f"이름{usr_id}", "role": role, "pages": json.dumps(list(pages)),
            "ai_enabled": 1, "daily_questions": None, "daily_cost_usd": None, "active": active,
            "last_login_at": None, "created_at": None, "updated_at": None, "updated_by": None}


@pytest.fixture
def env(temp_store, monkeypatch):
    """비밀번호 '1234' 가 맞는 사내 계정 + 서비스 등록 사용자 목록(users)."""
    users: dict[str, dict] = {"170046": _user("170046")}
    created = []

    monkeypatch.setattr(auth, "_verify_oracle", lambda uid, pw: {"USR_ID": uid, "USR_NM": f"이름{uid}"} if pw == "1234" else None)
    monkeypatch.setattr(auth.userdb, "get_user", lambda uid, fresh=False: users.get(uid))
    monkeypatch.setattr(auth.userdb, "get_settings", lambda: dict(SETTINGS))
    monkeypatch.setattr(auth.userdb, "update_name", lambda uid, nm: None)
    monkeypatch.setattr(auth.userdb, "touch_login", lambda uid: None)

    def create_user(uid, nm, role, pages, by, **kw):
        created.append((uid, role, by))
        users[uid] = _user(uid, role, pages)

    monkeypatch.setattr(auth.userdb, "create_user", create_user)
    return {"users": users, "created": created, "store": temp_store}


def _login(uid, pw="1234"):
    return auth.login(uid, pw, "127.0.0.1", "pytest")


def test_login_success_creates_session(env):
    token, me = _login("170046")
    assert me["id"] == "170046" and me["role"] == "USER" and me["pages"] == ["dashboard"]
    row = env["store"].row("SELECT * FROM sessions WHERE token=?", (appdb.token_hash(token),))
    assert row and row["expires_at"] - row["created_at"] == pytest.approx(auth.SESSION_TTL)


def test_wrong_password_message_and_lock_after_5(env):
    for i in range(4):
        with pytest.raises(HTTPException) as e:
            _login("170046", "bad")
        assert e.value.status_code == 401 and e.value.detail["message"] == auth.MSG_BAD_LOGIN
        assert e.value.detail["remaining"] == 4 - i
    with pytest.raises(HTTPException) as e:
        _login("170046", "bad")
    assert e.value.status_code == 429 and e.value.detail["code"] == "LOCKED"
    # 잠긴 동안에는 맞는 비밀번호도 거부
    with pytest.raises(HTTPException) as e:
        _login("170046")
    assert e.value.status_code == 429


def test_lock_expires(env, monkeypatch):
    for _ in range(5):
        with pytest.raises(HTTPException):
            _login("170046", "bad")
    real = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + auth.LOCK_SECONDS + 1)
    _, me = _login("170046")
    assert me["id"] == "170046"


def test_unregistered_user_is_rejected_and_not_created(env):
    with pytest.raises(HTTPException) as e:
        _login("110047")  # 사내 비밀번호는 맞지만 서비스 미등록
    assert e.value.status_code == 403 and e.value.detail["code"] == "NOT_REGISTERED"
    assert env["created"] == []
    log = env["store"].row("SELECT reason FROM login_log ORDER BY id DESC LIMIT 1")
    assert log["reason"] == "NOT_REGISTERED"


def test_super_admin_bootstrap(env):
    _, me = _login("250016")
    assert env["created"] == [("250016", "ADMIN", "SYSTEM")]
    assert me["role"] == "ADMIN" and me["superAdmin"] and "admin" in me["pages"]


def test_inactive_user_rejected(env):
    env["users"]["170046"]["active"] = 0
    with pytest.raises(HTTPException) as e:
        _login("170046")
    assert e.value.status_code == 403 and e.value.detail["code"] == "INACTIVE"


@pytest.mark.parametrize("uid,ok", [("250016", True), ("110047", True), ("12345", False), ("S31019", False),
                                    ("1234567", False), ("", False)])
def test_employee_number_rule(uid, ok):
    assert auth.is_emp_no(uid) is ok


# ----------------------------------------------------------------------------
# 요청 인증 · 페이지 권한
# ----------------------------------------------------------------------------
class _Req:
    def __init__(self, token):
        self.cookies = {auth.SESSION_COOKIE: token} if token else {}

        class S:
            pass

        self.state = S()


def test_current_user_slides_expiry_and_page_guard(env, monkeypatch):
    token, _ = _login("170046")
    before = env["store"].row("SELECT expires_at FROM sessions WHERE token=?", (appdb.token_hash(token),))["expires_at"]
    real = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + 600)
    me = auth.current_user(_Req(token))
    after = env["store"].row("SELECT expires_at FROM sessions WHERE token=?", (appdb.token_hash(token),))["expires_at"]
    assert after == pytest.approx(before + 600, abs=2) and me["id"] == "170046"
    assert auth.require_page("dashboard")(_Req(token))["id"] == "170046"
    with pytest.raises(HTTPException) as e:
        auth.require_page("sale_monthly")(_Req(token))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        auth.require_admin(_Req(token))
    assert e.value.status_code == 403


def test_expired_or_missing_session(env, monkeypatch):
    with pytest.raises(HTTPException) as e:
        auth.current_user(_Req(None))
    assert e.value.status_code == 401
    token, _ = _login("170046")
    real = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + auth.SESSION_TTL + 5)
    with pytest.raises(HTTPException) as e:
        auth.current_user(_Req(token))
    assert e.value.status_code == 401 and e.value.detail["code"] == "SESSION_EXPIRED"


# ----------------------------------------------------------------------------
# 관리자 입력 검증 (사용자 추가/수정)
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("body", [
    {"role": "OWNER"},
    {"pages": ["dashboard", "hack"]},
    {"dailyQuestions": 1001},
    {"dailyQuestions": True},
    {"dailyCostUsd": -1},
])
def test_admin_validate_rejects(body):
    with pytest.raises(HTTPException):
        admin._validate("170046", body)


def test_super_admin_cannot_be_demoted_or_disabled():
    with pytest.raises(HTTPException):
        admin._validate("250016", {"role": "USER"})
    with pytest.raises(HTTPException):
        admin._validate("250016", {"active": False})


def test_admin_validate_normalizes():
    v = admin._validate("170046", {"pages": ["invt_plan", "dashboard", "dashboard"], "aiEnabled": 0,
                                   "dailyQuestions": None, "dailyCostUsd": 3})
    assert v == {"pages": ["dashboard", "invt_plan"], "ai_enabled": False, "daily_questions": None, "daily_cost_usd": 3.0}


@pytest.mark.parametrize("uid", ["12345", "S31019", "abc123"])
def test_create_user_requires_6_digit_employee_number(uid):
    with pytest.raises(HTTPException) as e:
        admin.create_user({"id": "250016"}, {"id": uid, "pages": ["dashboard"]})
    assert "사번" in e.value.detail["message"]


def test_session_token_stored_as_hash_and_touch_throttled(env, monkeypatch):
    token, _ = _login("170046")
    assert env["store"].row("SELECT 1 FROM sessions WHERE token=?", (token,)) is None  # 원문 저장 안 함
    writes = []
    real_touch = appdb.session_touch
    monkeypatch.setattr(appdb, "session_touch", lambda *a: (writes.append(a), real_touch(*a)))
    auth.current_user(_Req(token))  # 로그인 직후: 1분이 안 지나 DB 쓰기 없음
    assert writes == []
    real = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + appdb.TOUCH_INTERVAL + 1)
    auth.current_user(_Req(token))
    assert len(writes) == 1
