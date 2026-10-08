"""AI 주간 브리핑: 기간 · 권한별 구성 · AI 한도 · 1시간 캐시 (DB · AI 없이)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app import briefing


def test_week_range_is_last_monday_to_sunday():
    assert briefing.week_range(date(2026, 10, 8)) == (date(2026, 9, 28), date(2026, 10, 4))     # 목요일 → 지난주
    assert briefing.week_range(date(2026, 10, 5)) == (date(2026, 9, 28), date(2026, 10, 4))     # 월요일 → 바로 전 주
    assert briefing.week_range(date(2026, 10, 4)) == (date(2026, 9, 21), date(2026, 9, 27))     # 일요일 → 그 전 주


@pytest.fixture
def parts(monkeypatch):
    calls = {"sales": 0, "stock": [], "ai": 0}

    def sales(brands, s, e):
        calls["sales"] += 1
        return {"brands": [{"brand": b} for b in brands], "ranges": {}}

    def stock(b, s, e, allowed):
        calls["stock"].append(b)
        return {"brand": b}, ([f"{b} short: 실패"] if b == "T" else [])

    def ai(me, data):
        calls["ai"] += 1
        assert "terms" in data and "note" in data                                  # 용어 · 기준 설명을 함께 넘긴다
        return {"text": "### 핵심 요약\n- 요약", "model": "m"}
    monkeypatch.setattr(briefing, "_sales", sales)
    monkeypatch.setattr(briefing, "_stock", stock)
    monkeypatch.setattr(briefing, "_ai", ai)
    monkeypatch.setattr(briefing, "_quota", lambda me: {"used": 1, "limit": 3})   # DB 없이
    briefing._cache.clear()
    return calls


def test_weekly_sections_follow_pages_and_brands(parts):
    me = {"id": "U1", "brands": ["리스트"], "pages": ["stock_rt"]}
    d = briefing.weekly(me, today=date(2026, 10, 8))
    assert d["brands"] == ["리스트"] and "sales" not in d and parts["stock"] == ["T"] and d["errors"] == ["T short: 실패"]
    assert d["period"] == {"from": "2026-09-28", "to": "2026-10-04"} and d["ai"]["text"].startswith("### 핵심")
    # 같은 주 다시 열면 AI 를 다시 부르지 않는다 · [다시 만들기]는 다시
    again = briefing.weekly(me, today=date(2026, 10, 8))
    assert again["cached"] is True and parts["ai"] == 1 and again["quota"] == {"used": 1, "limit": 3}
    briefing.weekly(me, refresh=True, today=date(2026, 10, 8))
    assert parts["ai"] == 2
    me2 = {"id": "U2", "brands": None, "pages": ["sale_dashboard"]}
    d = briefing.weekly(me2, today=date(2026, 10, 8))
    assert "stock" not in d and parts["sales"] == 1 and len(d["sales"]["brands"]) == 3


def test_weekly_needs_page_and_brand(parts):
    with pytest.raises(HTTPException):
        briefing.weekly({"id": "U3", "brands": None, "pages": ["invt_plan"]})
    with pytest.raises(HTTPException):
        briefing.weekly({"id": "U4", "brands": ["리스트"], "pages": ["stock_rt"]}, brand="S")    # 권한 없는 브랜드


def test_ai_blocked_returns_numbers_only(monkeypatch):
    from app import usage

    monkeypatch.setattr(usage, "check_can_brief", lambda me: "오늘 AI 주간 브리핑 횟수(3회)를 모두 사용했습니다.")
    out = briefing._ai({"id": "U1"}, {"period": {}})
    assert out["text"] is None and "3회" in out["blocked"]


def test_briefing_limit_is_separate_from_chat_limits(monkeypatch):
    """브리핑은 대화 질문 · 비용 한도와 따로 하루 N회 (사용자별, 기본 3회)"""
    from app import auth, usage

    ai = {"globalEnabled": True, "userEnabled": True, "dailyQuestions": 10, "dailyCostUsd": 2.0, "dailyBriefings": 3}
    used = {"questions": 10, "costUsd": 5.0, "inputTokens": 0, "outputTokens": 0, "briefings": 2}
    monkeypatch.setattr(usage, "today_usage", lambda uid: used)
    assert usage.check_can_brief({"id": "U1", "ai": ai}) is None                      # 대화 한도를 다 써도 브리핑은 된다
    assert usage.check_can_ask({"id": "U1", "ai": ai}) is not None
    used["briefings"] = 3
    assert usage.check_can_brief({"id": "U1", "ai": ai}) == usage.BRIEF_LIMIT_MSG == "AI 주간 브리핑 일일 사용량 한도 초과\n관리자에게 문의바랍니다."
    assert usage.check_can_brief({"id": "U1", "ai": {**ai, "dailyBriefings": 5}}) is None   # 사용자별 값이 우선
    row = {"usr_id": "U1", "usr_nm": "가", "role": "USER", "pages": "[]", "brands": "[]", "active": 1, "ai_enabled": 1,
           "daily_questions": None, "daily_cost_usd": None, "daily_briefings": None}
    s = {"ai_enabled": True, "default_daily_questions": 10, "default_daily_cost_usd": 2.0, "default_daily_briefings": 3}
    monkeypatch.setattr(auth, "is_super_admin", lambda uid: False)
    assert auth.effective(row, s)["ai"]["dailyBriefings"] == 3
    assert auth.effective({**row, "daily_briefings": 7}, s)["ai"]["dailyBriefings"] == 7


def test_scorecard_rt_sum_and_usage_kinds():
    from app import shop_scorecard as sc_, usage

    rows = [("C2951", "S1", " ", 8, 16.0, 8), ("C2952", "S1", "재고없음", 2, 10.0, 2), ("C2952", "ADMIN", "(자동거부) ", 3, 216.0, 3),
            ("C2954", None, " ", 1, None, 0)]
    r = sc_._rt_sum(rows)
    assert (r["accepted"], r["denied"], r["autoDenied"], r["pending"], r["requests"]) == (8, 2, 3, 1, 14)
    assert r["acceptRate"] == round(8 / 13 * 100, 1) and r["avgHours"] == round(26 / 10, 1)        # 자동거부 시간은 처리 시간에서 뺀다
    k = usage._kinds([{"kind": "briefing", "questions": 2, "calls": 2, "input_tokens": 5, "output_tokens": 1, "cost": 0.4, "users": 1}])
    assert [x["kind"] for x in k] == ["chat", "briefing"] and k[0]["cost"] == 0 and k[1]["name"] == "AI 주간 브리핑"


def test_ai_limit_flag(monkeypatch):
    from app import usage

    monkeypatch.setattr(usage, "check_can_brief", lambda me: usage.BRIEF_LIMIT_MSG)
    out = briefing._ai({"id": "U1"}, {"period": {}})
    assert out["limit"] is True and out["blocked"].startswith("AI 주간 브리핑 일일 사용량 한도 초과")


def test_backup_and_roles_carry_briefing_limit(monkeypatch):
    """설정 백업 · 권한 묶음에 사용자별 브리핑 횟수 — 예전 백업(값 없음)은 브리핑 횟수를 건드리지 않는다"""
    from app import admin, backup, roles, userdb

    monkeypatch.setattr(userdb, "has_brief_col", lambda: True)
    cur = {"id": "U1", "name": "가", "role": "USER", "pages": ["stock_rt"], "brands": None, "aiEnabled": True, "dailyQuestions": None,
           "dailyCostUsd": None, "dailyBriefings": 5, "active": True}
    monkeypatch.setattr(backup, "_users_now", lambda: {"U1": cur})
    monkeypatch.setattr(backup, "_settings_now", lambda: {})
    monkeypatch.setattr(backup, "_tools_now", lambda: {"builtin": {}, "custom": []})
    monkeypatch.setattr(backup.auth, "is_super_admin", lambda uid: False)
    old = {k: v for k, v in cur.items() if k != "dailyBriefings"}
    data = {"app": backup.APP_ID, "version": backup.VERSION, "users": [old]}
    assert backup.preview(data)["users"]["same"] == 1                                  # 예전 파일: 차이 없음
    assert "dailyBriefings" not in backup._user_body(old)
    data["users"] = [{**cur, "dailyBriefings": 2}]
    ch = backup.preview(data)["users"]["changed"][0]["diff"]
    assert ch == {"dailyBriefings": {"before": 5, "after": 2}} and backup._user_body(data["users"][0])["dailyBriefings"] == 2
    assert roles._conf({"pages": ["stock_rt"], "dailyBriefings": 4})["dailyBriefings"] == 4
    assert admin._validate("U1", {"dailyBriefings": 4}) == {"daily_briefings": 4}
