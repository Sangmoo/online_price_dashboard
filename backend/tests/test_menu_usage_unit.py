"""메뉴 이용 통계: SQLite 기록(Oracle 테이블 없을 때), 같은 날 횟수 누적, 기간 요약, 권한은 있지만 안 쓰는 메뉴."""
from datetime import datetime, timedelta

import pytest

from app import menu_usage as mu


@pytest.fixture
def local(temp_store, monkeypatch):
    monkeypatch.setattr(mu, "use_oracle", lambda: False)
    return temp_store


def _user(uid, name, pages, ai=True, active=True):
    return {"id": uid, "name": name, "pages": pages, "ai": {"enabled": ai}, "active": active, "lastLoginAt": None}


def test_record_and_report(local):
    now = datetime.now()
    for _ in range(3):
        mu.record("170046", "sale_dashboard", now)
    mu.record("170046", "sale_dashboard", now - timedelta(days=1))
    mu.record("170046", "ai", now)
    mu.record("250016", "admin", now)
    mu.record("170046", "invt_plan", now - timedelta(days=60))  # 기간 밖
    users = [_user("170046", "가", ["sale_dashboard", "sale_monthly", "invt_plan"]), _user("250016", "나", ["admin"], ai=False)]
    r = mu.report(30, users)
    pages = {p["page"]: p for p in r["pages"]}
    assert (pages["sale_dashboard"]["opens"], pages["sale_dashboard"]["users"], pages["sale_dashboard"]["activeDays"]) == (4, 1, 2)
    assert pages["sale_dashboard"]["grantedUsers"] == 1 and pages["ai"]["opens"] == 1 and pages["invt_plan"]["opens"] == 0
    u = next(x for x in r["users"] if x["id"] == "170046")
    assert u["opens"] == 5 and u["cells"]["sale_dashboard"]["days"] == 2
    assert sorted(u["unusedPages"]) == ["invt_plan", "sale_monthly"]  # 권한은 있는데 30일간 안 연 메뉴
    assert r["unusedGrants"] == 2 and r["storage"] == "sqlite" and sum(d["opens"] for d in r["daily"]) == 6
    assert r["users"][0]["id"] == "170046"  # 많이 쓴 사용자 먼저
