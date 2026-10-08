"""매장 재고 기준 집계(stock_base): 쓸 수 있는 집계 판단 · 재고 기준이 집계를 먼저 쓰는지 · 재집계 막기 (DB 없이)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app import stock_aging, stock_base


def _lg(ym: str, hours_ago: float, status: str = "OK") -> dict:
    return {"BRAND": "S", "MAKE_YYMM": ym, "BASE_DT": datetime(2026, 10, 8, 9) - timedelta(hours=hours_ago), "ROW_CNT": 3, "SEC": 1.2,
            "STATUS": status, "MSG": None, "UPD_DT": datetime(2026, 10, 8, 9)}


def test_usable_needs_this_month_and_recent():
    now = datetime(2026, 10, 8, 9)
    assert stock_base._usable(_lg("202610", 2.5), now)
    assert stock_base._usable(_lg("202610", 30, "ERROR"), now)          # 마지막 시도가 실패해도 이전 성공 집계가 36시간 안이면 쓴다
    assert not stock_base._usable(_lg("202610", 40), now)               # 스케줄이 하루 넘게 안 돎
    assert not stock_base._usable(_lg("202609", 2), now)                # 새 달 첫날 06:30 전
    assert not stock_base._usable(None, now)


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(stock_aging, "_styles", lambda b: {"S1": ("스타일", "2026", "C1")})
    stock_aging._cache.clear()
    yield
    stock_aging._cache.clear()


def test_aging_base_prefers_table(no_db, monkeypatch):
    rows = [("A001", "S1", 3, 30000, "20260901", "20260801", "20260701", 2)]
    monkeypatch.setattr(stock_base, "read", lambda b: {"rows": rows, "asOf": "2026-10-08 06:30", "ym": "202610", "source": "table"})

    def live(*a, **k):
        raise AssertionError("집계가 있으면 원장을 읽지 않는다")
    monkeypatch.setattr(stock_aging.db, "query", live)
    bs = stock_aging.base("S")
    assert bs["source"] == "table" and bs["rows"] == rows and bs["asOf"] == "2026-10-08 06:30"
    stock_aging.drop("S")
    assert "S" not in stock_aging._cache


def test_aging_base_falls_back_to_live(no_db, monkeypatch):
    monkeypatch.setattr(stock_base, "read", lambda b: None)
    monkeypatch.setattr(stock_aging.db, "query", lambda *a, **k: ([], [("A001", "S1", 1, 1000, None, None, "20260101", 1)]))
    bs = stock_aging.base("S")
    assert bs["source"] == "live" and len(bs["rows"]) == 1


def test_refresh_blocked_while_db_job_running(monkeypatch):
    monkeypatch.setattr(stock_base.tables, "ready", lambda: True)
    monkeypatch.setattr(stock_base, "_logs", lambda: {"S": {**_lg("202610", 0, "RUNNING"), "UPD_DT": datetime.now()}})
    with pytest.raises(HTTPException) as e:
        stock_base.start({"id": "ADM"})
    assert e.value.status_code == 409
    with pytest.raises(HTTPException):
        stock_base.start({"id": "ADM"}, "X")                                # 없는 브랜드
