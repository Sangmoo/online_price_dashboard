"""상품 순위 · 아이템/품군 · 판매형태: 원천 선택(뷰/원본 1개월), 기간·비교 기간 분리, 비중·할인율, 브랜드 팀 조건. DB 는 가짜."""
import pytest

from app import sale_dashboard as sd
from app import sale_products as sp

M = 1_000_000
PRODUCTS = [("P1", "자켓", "우븐", 100 * M, 50, 5 * M), ("P2", "팬츠", "우븐", 60 * M, 80, 1 * M), ("P3", "셔츠", "니트", 4 * M, 10, 2 * M)]
# (gid, ym, item, grp, type, amt, qty, dsct) — gid 3=아이템, 5=품군, 6=판매형태
GROUPS = [
    (3, "202608", "자켓", None, None, 100 * M, 50, 5 * M), (3, "202508", "자켓", None, None, 80 * M, 40, 4 * M),
    (5, "202608", None, "우븐", None, 160 * M, 130, 6 * M), (5, "202508", None, "우븐", None, 150 * M, 120, 6 * M),
    (6, "202608", None, None, "행사", 80 * M, 60, 4 * M), (6, "202608", None, None, "세일", 84 * M, 70, 4 * M),
    (6, "202508", None, None, "행사", 120 * M, 90, 5 * M), (6, "202508", None, None, "세일", 30 * M, 20, 1 * M),
]


@pytest.fixture
def fake(monkeypatch):
    seen = []
    state = {"mv": {"exists": True, "usable": True, "mv_max": "202608", "staleness": "FRESH"}}

    def query(sql, params=None):
        seen.append((sql, params or {}))
        if "GROUPING SETS" in sql:
            return [], GROUPS
        if "GROUP BY PRDT_CD" in sql:
            return [], PRODUCTS
        raise AssertionError(sql)

    monkeypatch.setattr(sp.db, "query", query)
    monkeypatch.setattr(sp, "mv_state", lambda: state["mv"])
    monkeypatch.setattr(sd, "available_months", lambda: ["202608", "202607", "202508"])
    monkeypatch.setattr(sd, "brand_teams", lambda: {"리스트": ["리스트1팀"], "쉬즈미스": ["쉬즈1팀"]})
    sp.clear_cache()
    yield seen, state
    sp.clear_cache()


def test_rankings_groups_and_sales_types(fake):
    seen, _ = fake
    d = sp.analyze("202608")
    assert d["source"] == "사전 집계 뷰" and sp.MV_NAME in seen[0][0]
    assert [p["prdtCd"] for p in d["rankings"]["amt"]] == ["P1", "P2", "P3"]
    assert [p["prdtCd"] for p in d["rankings"]["qty"]] == ["P2", "P1", "P3"]
    assert [p["prdtCd"] for p in d["rankings"]["dsctRate"]] == ["P1", "P2"]  # 500만원 미만(P3) 제외
    assert d["rankings"]["amt"][0]["dsctRate"] == 4.8  # 5 / (100 + 5)
    jacket = d["items"][0]
    assert (jacket["name"], jacket["change"], jacket["baseAmt"]) == ("자켓", 25.0, 80 * M)
    types = {t["name"]: t for t in d["salesTypes"]}
    assert (types["세일"]["share"], types["세일"]["baseShare"], types["세일"]["shareDiff"]) == (51.2, 20.0, 31.2)
    assert d["salesTypeTrend"] == [{"ym": "202608", "세일": 84 * M, "행사": 80 * M}]
    assert d["period"] == "2026-08" and d["base"] == "2025-08"


def test_without_view_only_one_month(fake):
    seen, state = fake
    state["mv"] = {"exists": False, "usable": False, "mv_max": None, "staleness": None}
    d = sp.analyze("202608")
    assert d["source"] == "원본(1개월)" and "T_CLOSE_SALE_BASE" in seen[0][0]
    long = sp.analyze("202608", "202607")
    assert "1개월" in long["unavailable"] and "rankings" not in long


def test_brand_scope_adds_team_condition(fake):
    seen, _ = fake
    sp.analyze("202608", brand="리스트")
    sql, params = seen[0]
    assert "TEAM_CD IN (:t0)" in sql and params["t0"] == "리스트1팀"
    with pytest.raises(Exception):
        sp.analyze("202608", brand="쉬즈미스", allowed=["리스트"])  # 권한 밖 브랜드
