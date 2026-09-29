"""AI 판매 현황 도구: 권한(판매 현황 메뉴만 있는 사용자), 부분 조회, 기간·비교·브랜드 전달, 표, 입력 검증. 대시보드 계산은 가짜로 대체."""
import pytest
from fastapi import HTTPException

from app import chat_tools as ct
from app import chat_tools_dashboard as cd

DASH_ONLY = {"pages": ["sale_dashboard"]}

SHOP = {"shopId": "S1", "shopNm": "매장1", "brand": "쉬즈", "team": "쉬즈1팀", "amt": 400, "baseAmt": 300, "change": 33.3,
        "costRate": 29.0, "cost": 116, "goalAmt": 500, "achieve": 80.0, "closed": False}
FAKE = {
    "ym": "202608", "from": "202608", "months": ["202608", "202607"],
    "period": {"from": "202608", "to": "202608", "months": ["202608"], "label": "2026-08"},
    "base": {"from": "202508", "to": "202508", "months": ["202508"], "label": "2025-08", "kind": "yoy", "kindLabel": "전년 동기"},
    "extra": {"label": "전월", "period": "2026-07"}, "brand": None, "brandOptions": ["리스트", "쉬즈"],
    "kpi": {"amt": 1000, "baseAmt": 800, "change": 25.0, "extraAmt": 1250, "extraChange": -20.0, "qty": 10, "baseQty": 12,
            "qtyChange": -16.7, "dsct": 50, "baseDsct": 45, "dsctChange": 11.1, "cost": 300, "costRate": 30.0, "baseCostRate": 33.0,
            "costRateDiff": -3.0, "shops": 5, "baseShops": 6, "ytdAmt": 9000, "prevYtdAmt": 10000, "ytdYoy": -10.0,
            "avgPerShop": 200, "goalAmt": 1200, "goalSalesAmt": 960, "achieve": 80.0, "goalGap": -240, "goalShops": 4,
            "noGoalShops": 1, "noGoalAmt": 40},
    "trend": [{"ym": "202608", "amt": 1000, "prevAmt": 800, "yoy": 25.0, "costRate": 30.0, "shops": 5}],
    "brands": [{"brand": "쉬즈", "amt": 600, "baseAmt": 500, "change": 20.0, "costRate": 31.0, "shops": 3, "share": 60.0, "teams": 2,
                "goalAmt": 700, "achieve": 85.7}],
    "teams": [{"team": "쉬즈1팀", "brand": "쉬즈", "amt": 600, "baseAmt": 500, "change": 20.0, "costRate": 31.0, "shops": 3,
               "goalAmt": 700, "achieve": 85.7}],
    "topShops": [SHOP], "risers": [], "fallers": [], "laggards": [SHOP],
    "shopCounts": {"selling": 5, "new": 1, "comparable": 4, "closedExcluded": 1}, "minBaseForGrowth": 10_000_000, "hasGoals": True,
}


@pytest.fixture
def fake_dash(monkeypatch):
    seen = []

    def dashboard(ym=None, frm=None, cmp=None, cmp_from=None, cmp_to=None, brand=None, full=False):
        seen.append({"ym": ym, "frm": frm, "cmp": cmp, "cmp_from": cmp_from, "cmp_to": cmp_to, "brand": brand})
        if ym == "209912":
            raise HTTPException(400, {"message": "2099-12 판매 데이터가 없습니다.", "code": "BAD_REQUEST"})
        return FAKE

    monkeypatch.setattr(cd.sd, "dashboard", dashboard)
    return seen


def test_dashboard_only_user_gets_summary_tools_not_row_search(fake_dash):
    out = ct.run_tool("get_sales_dashboard", {}, DASH_ONLY)
    assert out["result"]["period"] == "2026-08" and set(out["result"]) >= {"kpi", "trend", "brands", "topShops"}
    assert "teams" not in out["result"] and "risers" not in out["result"]  # 기본은 요약만
    assert fake_dash[-1] == {"ym": None, "frm": None, "cmp": "yoy", "cmp_from": None, "cmp_to": None, "brand": None}
    with pytest.raises(ct.ToolInputError, match="권한"):
        ct.run_tool("search_sales", {"ym_from": "202608", "ym_to": "202608"}, DASH_ONLY)
    with pytest.raises(ct.ToolInputError, match="권한"):
        ct.run_tool("get_sales_dashboard", {}, {"pages": ["invt_plan"]})


def test_period_compare_brand_are_passed(fake_dash):
    ct.run_tool("get_sales_dashboard", {"ym": "2026-08", "ym_from": "202601", "compare": "custom", "compare_from": "2025-01",
                                        "compare_to": "202503", "brand": "쉬즈"}, DASH_ONLY)
    assert fake_dash[-1] == {"ym": "202608", "frm": "202601", "cmp": "custom", "cmp_from": "202501", "cmp_to": "202503", "brand": "쉬즈"}


def test_sections_and_table(fake_dash):
    out = ct.run_tool("get_sales_dashboard", {"ym": "2026-08", "sections": ["teams"]}, DASH_ONLY)
    assert out["result"]["teams"][0]["team"] == "쉬즈1팀" and "kpi" not in out["result"]
    assert [c["key"] for c in out["table"]["columns"]][:2] == ["brand", "team"]  # 한 부분만 요청 → 그 표
    assert "achieve" in [c["key"] for c in out["table"]["columns"]]
    kpi = ct.run_tool("get_sales_dashboard", {"sections": ["kpi", "risers"]}, DASH_ONLY)
    rows = {(r["ITEM"], r["BASE_LABEL"]): r for r in kpi["table"]["rows"]}
    assert rows[("실판금액(원)", "전년 동기 2025-08")]["CHANGE"] == "+25.0%"
    assert rows[("실판금액(원)", "전월 2026-07")]["CHANGE"] == "-20.0%"
    assert rows[("원가율(%)", "전년 동기 2025-08")]["CHANGE"] == "-3.0%p"
    assert rows[("판매 매장 수", "전년 동기 2025-08")]["CHANGE"] == "-1개"
    assert rows[("목표 달성률(%)", "목표금액(원)")]["CHANGE"] == "-240원"
    assert "폐점" in kpi["result"]["growthRule"]
    lag = ct.run_tool("get_sales_dashboard", {"sections": ["laggards"]}, DASH_ONLY)
    assert lag["table"]["rows"][0]["achieve"] == 80.0 and lag["result"]["laggards"][0]["rank"] == 1


@pytest.mark.parametrize("inp,msg", [
    ({"ym": "2026-13"}, "YYYYMM"),
    ({"ym_from": "abc"}, "ym_from"),
    ({"compare": "week"}, "compare"),
    ({"sections": ["profit"]}, "sections"),
    ({"ym": "209912"}, "2099-12"),
])
def test_validation(fake_dash, inp, msg):
    with pytest.raises(ct.ToolInputError, match=msg):
        ct.run_tool("get_sales_dashboard", inp, DASH_ONLY)


def test_sum_tool_available_to_dashboard_only_user():
    assert "sum_sales_shop_month" in [t["name"] for t in ct.tools_for(DASH_ONLY)]
