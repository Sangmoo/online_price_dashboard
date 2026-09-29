"""AI 판매 도구의 매장명 검색 가속: 뷰가 최신일 때만 매장코드·월 목록 조건을 덧붙이고, 매장명 조건은 그대로 둔다."""
import pytest

from app import chat_tools_sale as cts

FRESH = {"usable": True, "mv_max": "202608", "base_max": "202608", "staleness": "FRESH", "last_refresh": None, "columns": set()}


@pytest.fixture
def fake(monkeypatch):
    state = {"st": dict(FRESH), "ids": ["S41004", "T51012"], "queries": []}
    monkeypatch.setattr(cts, "mv_state", lambda: state["st"])

    def query(sql, params=None):
        state["queries"].append((sql, params))
        return ["SHOP_ID"], [(i,) for i in state["ids"]]

    monkeypatch.setattr(cts.db, "query", query)
    return state


def test_adds_shop_and_month_lists_but_keeps_name_condition(fake):
    where, p = cts._where({"ym_from": "202607", "ym_to": "202608", "shop_nm": "롯데"})
    assert "INSTR(SHOP_NM, :shop_nm) > 0" in where and "MAKE_YYMM BETWEEN :ym_from AND :ym_to" in where
    assert "MAKE_YYMM IN (:nym0, :nym1)" in where and "SHOP_ID IN (:nshop0, :nshop1)" in where
    assert (p["nym0"], p["nym1"], p["nshop0"], p["shop_nm"]) == ("202607", "202608", "S41004", "롯데")
    assert "INSTR(SHOP_NM, :v)" in fake["queries"][0][0] and fake["queries"][0][1] == {"f": "202607", "t": "202608", "v": "롯데"}


def test_no_matching_shop_returns_nothing(fake):
    fake["ids"] = []
    where, _ = cts._where({"ym_from": "202607", "ym_to": "202608", "shop_nm": "없는매장"})
    assert "1 = 0" in where


@pytest.mark.parametrize("st", [
    {**FRESH, "usable": False, "staleness": "STALE"},   # 뷰가 오래됨 → 원본 방식 그대로
    {**FRESH, "mv_max": "202607"},                        # 요청 기간의 최근 월이 뷰에 없음
])
def test_falls_back_when_view_not_reliable(fake, st):
    fake["st"] = st
    where, p = cts._where({"ym_from": "202607", "ym_to": "202608", "shop_nm": "롯데"})
    assert "SHOP_ID IN" not in where and "nym0" not in p and fake["queries"] == []


def test_too_many_shops_falls_back(fake):
    fake["ids"] = [f"S{i:05d}" for i in range(cts.NARROW_MAX_SHOPS + 1)]
    where, _ = cts._where({"ym_from": "202607", "ym_to": "202608", "shop_nm": "매장"})
    assert "SHOP_ID IN" not in where


def test_without_shop_name_nothing_changes(fake):
    where, p = cts._where({"ym_from": "202607", "ym_to": "202608", "team_cd": "쉬즈"})
    assert where == "MAKE_YYMM BETWEEN :ym_from AND :ym_to AND INSTR(TEAM_CD, :team_cd) > 0" and fake["queries"] == []
