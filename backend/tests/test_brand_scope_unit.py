"""브랜드 데이터 권한: 사용자 권한 값, 관리자 입력 검증, 판매 집계 조건(매장코드로 바꾸기/팀 조건), 판매 현황 범위, AI 관리자 정의 도구 차단."""
import json

import pytest
from fastapi import HTTPException

from app import admin, auth, brand_scope, chat_tools, sale_monthly as sm, userdb

BT = {"리스트": ["리스트1팀", "리스트2팀"], "쉬즈미스": ["쉬즈1팀"], "시스티나": ["시스티나1팀"]}
FRESH = {"usable": True, "mv_max": "202608", "base_max": "202608", "staleness": "FRESH", "last_refresh": None, "columns": set()}


def _u(brands, uid="170046"):
    return {"usr_id": uid, "usr_nm": "이름", "role": "USER", "pages": json.dumps(["sale_monthly"]), "ai_enabled": 1,
            "daily_questions": None, "daily_cost_usd": None, "active": 1, "brands": json.dumps(brands)}


SETTINGS = {"ai_enabled": True, "default_daily_questions": 10, "default_daily_cost_usd": 2.0, "model": None, "effort": None}


def test_effective_brands():
    assert auth.effective(_u([]), SETTINGS)["brands"] is None            # 기존 사용자: 모든 브랜드
    assert auth.effective(_u(["리스트"]), SETTINGS)["brands"] == ["리스트"]
    assert auth.effective(_u(["리스트"], "250016"), SETTINGS)["brands"] is None  # 최고 관리자는 항상 전체
    legacy = _u([])
    del legacy["brands"]
    assert auth.effective(legacy, SETTINGS)["brands"] is None


def test_teams_of(monkeypatch):
    from app import sale_dashboard as sd

    monkeypatch.setattr(sd, "brand_teams", lambda: BT)
    assert brand_scope.teams_of({"brands": None}) is None
    assert brand_scope.teams_of({"brands": ["리스트", "시스티나"]}) == ["리스트1팀", "리스트2팀", "시스티나1팀"]
    assert brand_scope.teams_of({"brands": ["없어진브랜드"]}) == []


@pytest.fixture
def brand_admin(monkeypatch):
    monkeypatch.setattr(admin, "brand_options", lambda: list(BT))
    monkeypatch.setattr(userdb, "brand_table_ready", lambda: True)


def test_validate_brands(brand_admin, monkeypatch):
    assert admin._validate("170046", {"brands": None}) == {"brands": []}           # 모든 브랜드 = 빈 목록으로 저장
    assert admin._validate("170046", {"brands": ["시스티나", "리스트", "리스트"]}) == {"brands": ["리스트", "시스티나"]}
    for bad in ([], ["없는브랜드"], "리스트", [1]):
        with pytest.raises(HTTPException):
            admin._validate("170046", {"brands": bad})
    with pytest.raises(HTTPException) as e:
        admin._validate("250016", {"brands": ["리스트"]})
    assert "최고 관리자" in e.value.detail["message"]
    monkeypatch.setattr(userdb, "brand_table_ready", lambda: False)
    with pytest.raises(HTTPException) as e:
        admin._validate("170046", {"brands": ["리스트"]})
    assert "create_erp_web_user_brand.sql" in e.value.detail["message"]


def test_create_user_requires_brand_choice(brand_admin, monkeypatch):
    monkeypatch.setattr(admin, "_verify_emp", lambda uid: {"USR_ID": uid, "USR_NM": "새사용자"})
    monkeypatch.setattr(userdb, "get_user", lambda uid, fresh=False: None)
    with pytest.raises(HTTPException) as e:
        admin.create_user({"id": "250016"}, {"id": "170099", "pages": ["sale_monthly"]})
    assert "브랜드" in e.value.detail["message"]


@pytest.fixture
def mv(monkeypatch):
    from app import chat_tools_sale as cts

    state = {"st": dict(FRESH), "rows": [("S1", 1), ("S2", 1)], "queries": []}
    monkeypatch.setattr(cts, "mv_state", lambda: state["st"])

    def query(sql, params=None):
        state["queries"].append(sql)
        return [], state["rows"]

    monkeypatch.setattr(sm.db, "query", query)
    return state


def test_brand_filter_uses_shop_codes_when_exact(mv):
    conds, b = sm.brand_filter(["리스트1팀"], "202607", "202608")
    assert conds == ["MAKE_YYMM IN (:bfm0, :bfm1)", "SHOP_ID IN (:bfs0, :bfs1)"]  # 팀 조건 없이 인덱스만으로
    assert (b["bfs0"], b["bfs1"], b["bfm1"]) == ("S1", "S2", "202608")


def test_brand_filter_keeps_team_condition_for_mixed_shops(mv):
    mv["rows"] = [("S1", 1), ("S9", 0)]  # S9 는 다른 팀으로도 팔림
    conds, b = sm.brand_filter(["리스트1팀"], "202607", "202608")
    assert conds[-1] == "TEAM_CD IN (:bft0)" and b["bft0"] == "리스트1팀" and "SHOP_ID IN (:bfs0, :bfs1)" in conds


@pytest.mark.parametrize("st", [{**FRESH, "usable": False}, {**FRESH, "mv_max": "202607"}])
def test_brand_filter_falls_back_to_team_condition(mv, st):
    mv["st"] = st
    assert sm.brand_filter(["리스트1팀"], "202607", "202608") == (["TEAM_CD IN (:bft0)"], {"bft0": "리스트1팀"})
    assert mv["queries"] == []


def test_brand_filter_edges(mv):
    assert sm.brand_filter(None, "202607", "202608") == ([], {})
    assert sm.brand_filter([], "202607", "202608") == (["1 = 0"], {})
    mv["rows"] = []
    assert sm.brand_filter(["리스트1팀"], "202607", "202608") == (["1 = 0"], {})
    mv["rows"] = [(f"S{i}", 1) for i in range(sm.MAX_IN + 1)]
    assert sm.brand_filter(["리스트1팀"], "202607", "202608")[0] == ["TEAM_CD IN (:bft0)"]


def test_custom_sales_tool_blocked_for_brand_limited_user(monkeypatch):
    from app import ai_tools

    custom = {"name": "my_sales", "enabled": True, "page": "sale_monthly", "label": "x"}
    monkeypatch.setattr(ai_tools, "snapshot", lambda: {"builtin": {}, "custom": [custom]})
    monkeypatch.setattr(ai_tools, "tool_schema", lambda c: {"name": c["name"]})
    monkeypatch.setattr(ai_tools, "run_custom", lambda c, inp: {"result": {}, "table": None})
    limited = {"pages": ["sale_monthly"], "brands": ["리스트"]}
    everyone = {"pages": ["sale_monthly"], "brands": None}
    assert "my_sales" not in [t["name"] for t in chat_tools.tools_for(limited)]
    assert "my_sales" in [t["name"] for t in chat_tools.tools_for(everyone)]
    with pytest.raises(chat_tools.ToolInputError, match="브랜드"):
        chat_tools.run_tool("my_sales", {}, limited)
    assert chat_tools.run_tool("my_sales", {}, everyone)["result"] == {}
