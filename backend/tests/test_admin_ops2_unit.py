"""관리자 운영 2차: 공지 대상 · 상단 고정 · 필독 · 읽음 현황, 점검 예약, 대량 다운로드 알림, 권한 묶음, 계정 정리, 사용자 화면 미리보기.
Oracle 은 메모리 DB 로 흉내 낸다 (fake_oracle)."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app import admin, auth, cleanup, downloads, menu_usage, notices, roles, userdb

ADMIN = {"id": "900001", "name": "관리자", "role": "ADMIN", "pages": ["sale_dashboard", "invt_plan", "admin"], "brands": None, "ip": "1.1.1.1"}
SALE = {"id": "900002", "name": "판매", "role": "USER", "pages": ["sale_dashboard"], "brands": ["쉬즈미스"]}
INVT = {"id": "900003", "name": "실사", "role": "USER", "pages": ["invt_plan"], "brands": ["리스트"]}


def _day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _user_row(e: dict, last: str | None = "2026-10-01 09:00", active=True) -> dict:
    return {"usr_id": e["id"], "usr_nm": e["name"], "role": e["role"], "pages": json.dumps([p for p in e["pages"] if p != "admin"]),
            "ai_enabled": 1, "daily_questions": None, "daily_cost_usd": None, "active": 1 if active else 0, "last_login_at": last,
            "brands": json.dumps(e.get("brands") or []), "created_at": "2026-01-01 00:00", "updated_at": None, "updated_by": None}


@pytest.fixture
def users(monkeypatch):
    rows = [_user_row(ADMIN), _user_row(SALE), _user_row(INVT)]
    monkeypatch.setattr(userdb, "list_users", lambda q=None: rows)
    monkeypatch.setattr(userdb, "get_user", lambda uid, fresh=False: next((r for r in rows if r["usr_id"] == uid), None))
    monkeypatch.setattr(auth, "is_super_admin", lambda uid: False)
    return rows


# ---------------------------------------------------------------------------- 공지 대상 · 고정 · 필독 · 읽음
def test_notice_targets_pin_and_reads(fake_oracle, users):
    a = notices.save(ADMIN, {"title": "전체", "start": _day(0), "end": _day(1)})["notice"]
    s = notices.save(ADMIN, {"title": "판매 대상", "start": _day(0), "end": _day(1), "target": {"type": "pages", "values": ["sale_dashboard"]},
                             "mustAck": True})["notice"]
    b = notices.save(ADMIN, {"title": "리스트 담당", "start": _day(0), "end": _day(1), "target": {"type": "brands", "values": ["리스트"]},
                             "pin": True})["notice"]
    u = notices.save(ADMIN, {"title": "실사 개인", "start": _day(0), "end": _day(1), "target": {"type": "users", "values": ["900003"]}})["notice"]
    notices._clear()
    assert {n["title"] for n in notices.active_for(SALE)} == {"전체", "판매 대상"}
    assert {n["title"] for n in notices.active_for(INVT)} == {"전체", "리스트 담당", "실사 개인"}
    assert notices.board(INVT)["notices"][0]["title"] == "리스트 담당"                 # 상단 고정이 맨 위
    assert b["target"]["label"] == "브랜드: 리스트" and s["mustAck"] is True
    with pytest.raises(HTTPException):                                                  # 대상이 아닌 공지 상세는 못 본다
        notices.detail(SALE, u["id"])

    # 읽음 · 필독 확인
    assert notices.mark_read(SALE, [a["id"], s["id"], u["id"]]) == 2                    # 대상 아닌 공지는 건너뜀
    first = notices.active_for(SALE)
    assert all(n["read"] for n in first) and not next(n for n in first if n["id"] == s["id"])["acked"]
    with pytest.raises(HTTPException):
        notices.acknowledge(SALE, a["id"])                                              # 필독이 아닌 공지
    notices.acknowledge(SALE, s["id"])
    assert next(n for n in notices.active_for(SALE) if n["id"] == s["id"])["acked"] is True
    st = notices.read_status(s["id"])
    assert st["counts"] == {"target": 2, "read": 1, "ack": 1}                          # 관리자도 판매 메뉴가 있어 대상
    assert st["users"][0]["id"] == "900001" and st["users"][0]["readAt"] is None          # 안 읽은 대상자가 먼저
    assert notices.list_all()["notices"][0]["readCount"] >= 0
    assert notices.mark_read({**SALE, "viewAs": {"by": "900001"}}, [b["id"]]) == 0      # 미리보기 중에는 기록 안 함


def test_notice_target_validation(fake_oracle, users):
    with pytest.raises(HTTPException) as ex:
        notices.save(ADMIN, {"title": "a", "start": _day(0), "end": _day(0), "target": {"type": "pages", "values": []}})
    assert "하나 이상" in ex.value.detail["message"]


def test_notice_ext_missing_falls_back(fake_oracle, monkeypatch, users):
    monkeypatch.setattr(notices.ext, "missing", lambda: ["T_ERP_WEB_NOTICE_READ"])
    n = notices.save(ADMIN, {"title": "기본", "start": _day(0), "end": _day(0)})["notice"]
    assert n["target"]["type"] == "all" and n["pin"] is False                            # 2차 DDL 전: 전체 대상으로 동작
    with pytest.raises(HTTPException) as ex:
        notices.save(ADMIN, {"title": "x", "start": _day(0), "end": _day(0), "pin": True})
    assert "alter_erp_web_admin_ops_2.sql" in ex.value.detail["message"]
    assert notices.mark_read(SALE, [n["id"]]) == 0


# ---------------------------------------------------------------------------- 점검 예약
@pytest.fixture
def settings(monkeypatch):
    st = dict(userdb.DEFAULT_SETTINGS)
    monkeypatch.setattr(userdb, "get_settings", lambda: dict(st))
    monkeypatch.setattr(userdb, "save_settings", lambda values, by: st.update(values) or dict(st))
    return st


def test_maintenance_schedule(fake_oracle, settings, monkeypatch):
    fmt = "%Y-%m-%d %H:%M"
    now = datetime(2026, 10, 10, 12, 0)
    monkeypatch.setattr(notices, "_now_hm", lambda: now.strftime(fmt))
    monkeypatch.setattr(notices, "datetime", type("D", (), {"now": staticmethod(lambda: now), "strptime": datetime.strptime}))
    notices.set_maintenance(ADMIN, {"on": False, "start": "2026-10-10 12:30", "until": "2026-10-10 13:00", "message": "DB 작업"})
    assert notices.blocked_message() is None
    assert notices.upcoming_maintenance() == {"start": "2026-10-10 12:30", "until": "2026-10-10 13:00", "message": "DB 작업"}
    now = datetime(2026, 10, 10, 12, 40)                                                 # 예약 시간 안: 자동으로 막힘
    assert notices.maintenance()["scheduledNow"] is True and notices.blocked_message().startswith("DB 작업")
    with pytest.raises(HTTPException):
        auth._check_maintenance({"role": "USER"})
    now = datetime(2026, 10, 10, 13, 0)                                                  # 끝나면 자동으로 풀림
    assert notices.blocked_message() is None and notices.upcoming_maintenance() is None
    for bad in ({"start": "2026-10-10 14:00"}, {"start": "2026-10-10 15:00", "until": "2026-10-10 14:00"},
                {"start": "2026-10-10 09:00", "until": "2026-10-10 10:00"}):
        with pytest.raises(HTTPException):
            notices.set_maintenance(ADMIN, bad)


# ---------------------------------------------------------------------------- 대량 다운로드 알림
def test_download_alerts(real_records, monkeypatch):
    monkeypatch.setattr(userdb, "get_settings", lambda: {**userdb.DEFAULT_SETTINGS, "dl_alert_count": 3, "dl_alert_phone": 2, "dl_alert_rows": 5000})
    for _ in range(3):
        downloads.record(SALE, "online_detail", "x")
    downloads.record(INVT, "manager_phone", "p1")
    downloads.record(INVT, "manager_phone", "p2")
    downloads.record(INVT, "table", "큰 표", rows=6000)
    downloads.record({**SALE, "viewAs": {"by": "900001"}}, "manager_phone", "미리보기")   # 미리보기 중 조회는 관리자 이름으로
    al = downloads.alerts({"900002": "판매", "900003": "실사"})
    kinds = sorted((a["usrId"], a["kind"]) for a in al)
    assert kinds == [("900002", "count"), ("900003", "phone"), ("900003", "rows")]
    rows = downloads.report(1)["rows"]
    pv = next(r for r in rows if "미리보기" in (r["title"] or ""))
    assert pv["usrId"] == "900001" and pv["title"].startswith("[미리보기 900002]")
    with pytest.raises(HTTPException):
        downloads.save_alert_settings(ADMIN, {"count": 0, "phone": 1, "rows": 1000})


# ---------------------------------------------------------------------------- 권한 묶음
def test_roles_save_apply_and_reapply(fake_oracle, users, monkeypatch):
    saved = {}
    monkeypatch.setattr(admin, "save_user", lambda adm, uid, body: saved.setdefault(uid, []).append(body) or {})
    monkeypatch.setattr(auth, "is_super_admin", lambda uid: uid == "900009")
    r = roles.save(ADMIN, {"name": "영업 기본", "conf": {"pages": ["sale_dashboard", "sale_monthly"], "brands": None, "aiEnabled": True,
                                                       "dailyQuestions": 20}})
    with pytest.raises(HTTPException):
        roles.save(ADMIN, {"name": "영업 기본", "conf": {"pages": ["sale_dashboard"]}})          # 이름 중복
    with pytest.raises(HTTPException):
        roles.save(ADMIN, {"name": "빈 묶음", "conf": {"pages": []}})
    res = roles.apply(ADMIN, r["id"], ["900002", "900003", "900009"])
    assert res["applied"] == ["900002", "900003"] and res["skipped"][0]["id"] == "900009"
    assert saved["900002"][0] == {"pages": ["sale_dashboard", "sale_monthly"], "brands": None, "aiEnabled": True,
                                  "dailyQuestions": 20, "dailyCostUsd": None, "dailyBriefings": None}
    lst = roles.list_roles()["roles"][0]
    assert lst["name"] == "영업 기본" and {m["id"] for m in lst["members"]} == {"900002", "900003"}
    assert roles.role_of("900002")["name"] == "영업 기본"
    out = roles.save(ADMIN, {"name": "영업 기본", "conf": {"pages": ["sale_dashboard"]}, "reapply": True}, r["id"])
    assert out["reapplied"]["applied"] == ["900002", "900003"] and saved["900003"][-1]["pages"] == ["sale_dashboard"]
    roles.delete(ADMIN, r["id"])
    assert roles.list_roles()["roles"] == [] and roles.role_of("900002") is None


# ---------------------------------------------------------------------------- 계정 정리
def test_cleanup_report_and_apply(users, monkeypatch):
    old = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M")
    users[2]["last_login_at"] = old                                                     # 실사: 200일 미접속
    users[1]["last_login_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    monkeypatch.setattr(admin, "list_users", lambda q=None: [
        {"id": r["usr_id"], "name": r["usr_nm"], "role": r["role"], "superAdmin": False, "active": True,
         "pages": json.loads(r["pages"]), "ai": {"enabled": True}, "lastLoginAt": r["last_login_at"], "createdAt": None} for r in users])
    monkeypatch.setattr(menu_usage, "_rows", lambda since: [("20261001", "900002", "sale_dashboard", 3, "20261001100000")])
    rep = cleanup.report(ADMIN, 90)
    assert [x["id"] for x in rep["idle"]] == ["900003"]                                 # 관리자 본인 제외
    assert {x["id"]: [p["key"] for p in x["pages"]] for x in rep["unused"]} == {"900003": ["invt_plan"]}
    calls = []
    monkeypatch.setattr(admin, "save_user", lambda adm, uid, body: calls.append((uid, body)))
    done = cleanup.apply(ADMIN, {"deactivate": ["900003", "900001"], "revoke": [{"id": "900002", "pages": ["sale_dashboard"]}]})
    assert done["deactivated"] == ["900003"] and done["skipped"][0] == {"id": "900001", "reason": "본인 계정"}
    assert calls == [("900003", {"active": False}), ("900002", {"pages": []})]
    with pytest.raises(HTTPException):
        cleanup.apply(ADMIN, {})


# ---------------------------------------------------------------------------- 사용자 화면 미리보기
def test_view_as_rules():
    sup = {**ADMIN, "superAdmin": True}
    mid = {**ADMIN, "superAdmin": False, "pages": ["sale_dashboard", "admin"], "brands": ["쉬즈미스"]}
    assert auth.can_view_as(sup, {**INVT, "superAdmin": False}) is None
    assert "권한이 없는 메뉴" in auth.can_view_as(mid, {**INVT, "superAdmin": False})            # 관리자보다 넓은 메뉴
    assert auth.can_view_as(mid, {**SALE, "superAdmin": False}) is None
    assert "브랜드" in auth.can_view_as(mid, {**SALE, "brands": None, "superAdmin": False})      # 관리자보다 넓은 브랜드
    assert auth.can_view_as({**SALE, "superAdmin": False}, INVT) is not None                    # 일반 사용자는 불가
    assert auth._readonly_path("GET", "/api/sale-dashboard") and not auth._readonly_path("POST", "/api/chat")
    assert not auth._readonly_path("GET", "/api/rows/export") and not auth._readonly_path("GET", "/api/sale-monthly/exports/x/file")
