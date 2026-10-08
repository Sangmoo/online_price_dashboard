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
    briefing._cache.clear()
    return calls


def test_weekly_sections_follow_pages_and_brands(parts):
    me = {"id": "U1", "brands": ["리스트"], "pages": ["stock_rt"]}
    d = briefing.weekly(me, today=date(2026, 10, 8))
    assert d["brands"] == ["리스트"] and "sales" not in d and parts["stock"] == ["T"] and d["errors"] == ["T short: 실패"]
    assert d["period"] == {"from": "2026-09-28", "to": "2026-10-04"} and d["ai"]["text"].startswith("### 핵심")
    # 같은 주 다시 열면 AI 를 다시 부르지 않는다 · [다시 만들기]는 다시
    again = briefing.weekly(me, today=date(2026, 10, 8))
    assert again["cached"] is True and parts["ai"] == 1
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

    monkeypatch.setattr(usage, "check_can_ask", lambda me: "오늘 질문 한도(10회)를 모두 사용했습니다.")
    out = briefing._ai({"id": "U1"}, {"period": {}})
    assert out["text"] is None and "한도" in out["blocked"]
