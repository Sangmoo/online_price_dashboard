"""매장 정보: 담당 영업직원 검색·집계(AI 도구), 브랜드 권한, 매장 정보 팝업 API. 매장 마스터는 가짜로 대체."""
import pytest
from fastapi import HTTPException

from app import chat_tools as ct
from app import shop_info

ROWS = [
    {"shopId": "S41004", "shopNm": "타임스퀘어", "brdCd": "S", "brand": "쉬즈미스", "teamNm": "쉬즈4팀", "repId": "230038", "repNm": "양성규",
     "status": "정상", "openDt": "2014-09-05", "closeDt": None},
    {"shopId": "T51012", "shopNm": "자사몰", "brdCd": "T", "brand": "리스트", "teamNm": "리스트5팀", "repId": "200058", "repNm": "이혜연",
     "status": "정상", "openDt": "2017-03-07", "closeDt": None},
    {"shopId": "S21021", "shopNm": "(폐)상암", "brdCd": "S", "brand": "쉬즈미스", "teamNm": "쉬즈2팀", "repId": "230038", "repNm": "양성규",
     "status": "폐점", "openDt": "2026-05-12", "closeDt": "2026-07-09"},
    {"shopId": "S21021", "shopNm": "(폐)상암", "brdCd": "T", "brand": "리스트", "teamNm": "쉬즈2팀", "repId": "230038", "repNm": "양성규",
     "status": "폐점", "openDt": "2026-05-12", "closeDt": "2026-07-09"},
]
ME = {"pages": ["sale_dashboard"], "brands": None}


@pytest.fixture(autouse=True)
def fake_master(monkeypatch):
    monkeypatch.setattr(shop_info, "all_rows", lambda: ROWS)


def test_search_by_rep_open_only_by_default():
    out = ct.run_tool("search_shops", {"rep": "양성규"}, ME)
    assert [r["SHOP_ID"] for r in out["result"]["rows"]] == ["S41004"]  # 폐점 매장은 기본 제외
    out = ct.run_tool("search_shops", {"rep": "230038", "include_closed": True}, ME)
    assert {r["SHOP_ID"] for r in out["result"]["rows"]} == {"S41004", "S21021"}


def test_group_by_rep_counts_distinct_shops():
    out = ct.run_tool("search_shops", {"group_by": "REP", "include_closed": True}, ME)
    assert out["result"]["groups"] == [{"GROUP": "양성규", "SHOP_CNT": 2}, {"GROUP": "이혜연", "SHOP_CNT": 1}]
    assert out["table"]["columns"][0]["label"] == "담당 영업직원"


def test_brand_scope_and_permission():
    limited = {"pages": ["sale_monthly"], "brands": ["리스트"]}
    out = ct.run_tool("search_shops", {"include_closed": True}, limited)
    assert {r["BRAND"] for r in out["result"]["rows"]} == {"리스트"}
    with pytest.raises(ct.ToolInputError, match="권한"):
        ct.run_tool("search_shops", {"brand": "쉬즈미스"}, limited)
    with pytest.raises(ct.ToolInputError, match="권한"):
        ct.run_tool("search_shops", {}, {"pages": ["dashboard"]})  # 온라인 가격 메뉴만으로는 매장 정보 없음
    with pytest.raises(ct.ToolInputError, match="group_by"):
        ct.run_tool("search_shops", {"group_by": "CITY"}, ME)


def test_profile_brand_scope(monkeypatch):
    monkeypatch.setattr(shop_info.db, "query_dicts", lambda sql, p=None: [{"SHOP_ADDR1": "서울", "SHOP_ADDR2": "1층", "SHOP_TEL_NO1": "02",
                                                                         "SHOP_TEL_NO2": "123", "SHOP_TEL_NO3": "4567"}])
    p = shop_info.profile("s21021")
    assert (p["shopId"], p["repNm"], p["tel"], p["addr"]) == ("S21021", "양성규", "02-123-4567", "서울 1층")
    assert [b["brand"] for b in p["brands"]] == ["쉬즈미스", "리스트"]
    assert [b["brand"] for b in shop_info.profile("S21021", ["리스트"])["brands"]] == ["리스트"]
    with pytest.raises(HTTPException) as e:
        shop_info.profile("S41004", ["리스트"])
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        shop_info.profile("TOOLONG1")
