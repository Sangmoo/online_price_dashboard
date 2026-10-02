"""판매처 매장 연결 AI 도구: 조회 필터, 변경안(사이트 부분 일치·판매자번호 추론·브랜드 이름), 저장하지 않음, 브랜드 경고, 권한."""
import pytest

from app import chat_tools as ct
from app import chat_tools_mall as cm
from app import mall_shop as ms
from app import shop_info


def _row(mall, sell, brd, shop=None, star=None, rows=10):
    return {"mallNm": mall, "sellNo": sell, "brdCd": brd, "brand": {"S": "쉬즈미스", "T": "리스트", "A": "시스티나", "*": "모든 브랜드"}[brd],
            "rows": rows, "products": 1, "lastDt": "20261002", "shopFilled": 0, "rmk": None, "seen": True, "shopId": shop,
            "shopNm": None, "useYn": "Y" if shop else None, "mapRmk": None, "updatedBy": None, "updatedAt": None,
            "starShopId": star, "starShopNm": None, "effectiveShopId": shop or star, "suggestions": []}


ROWS = [_row("하프클럽(사이트)", "-", "S"), _row("하프클럽(사이트)", "-", "T", shop="T51005"),
        _row("네이버(사이트)롯데아울렛구리점 리스트", "510517044", "T"),
        _row("SSG(사이트)인동FN", "143555", "S"), _row("SSG(사이트)신세계 사우스시티", "0316952259", "T")]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(ms, "listing", lambda days=31: {"ready": True, "days": days, "rows": ROWS,
                                                         "summary": {"combos": len(ROWS)}})
    monkeypatch.setattr(ms, "table_ready", lambda: True)
    monkeypatch.setattr(ms, "_maps", lambda: {("하프클럽(사이트)", "-", "T"): {"SHOP_ID": "T51005", "USE_YN": "Y", "RMK": None}})
    monkeypatch.setattr(ms, "_shop_names", lambda ids: {i: {"S51005": "하프클럽", "T51005": "하프클럽", "T32018": "롯데아울렛구리"}[i]
                                                         for i in ids if i in ("S51005", "T51005", "T32018")})
    monkeypatch.setattr(shop_info, "search", lambda **k: [{"shopId": "S51005", "brdCd": "S"}, {"shopId": "T51005", "brdCd": "T"},
                                                          {"shopId": "T32018", "brdCd": "T"}])
    writes = []
    monkeypatch.setattr(ms.db, "get_pool", lambda: writes.append(1))   # 쓰면 기록됨 (호출되면 안 됨)
    return writes


def test_search_filters(fake):
    out = cm.run("search_mall_shop_mappings", {"mall_nm": "하프클럽", "status": "unmapped"})
    assert [(r["mallNm"], r["brand"]) for r in out["result"]["rows"]] == [("하프클럽(사이트)", "쉬즈미스")]
    assert cm.run("search_mall_shop_mappings", {"brand": "리스트"})["result"]["total_matched"] == 3


def test_propose_builds_action_without_writing(fake):
    out = cm.run("propose_mall_shop_mappings", {"items": [
        {"mall_nm": "하프클럽", "brand": "쉬즈미스", "shop_id": "s51005"},          # 부분 일치 + 판매자번호 하나 → 추론
        {"mall_nm": "구리점", "brand": "T", "shop_id": "T32018"},
        {"mall_nm": "하프클럽(사이트)", "sell_no": "-", "brand": "리스트", "shop_id": "T51005"},   # 이미 같음 → 변경 없음
    ]})
    assert fake == []   # DB 에 쓰지 않는다
    r = out["result"]
    assert r["saved"] is False and r["applicableCount"] == 2 and "[적용]" in r["instruction"]
    assert [c["action"] for c in r["changes"]] == ["등록", "등록", "변경 없음"]
    a = out["action"]
    assert a["actionKind"] == "mall_shop_save" and [i["shopId"] for i in a["items"]] == ["S51005", "T32018"]
    assert a["items"][0] == {"mallNm": "하프클럽(사이트)", "sellNo": "-", "brdCd": "S", "shopId": "S51005", "useYn": "Y", "rmk": ""}
    assert any("하프클럽' → '하프클럽(사이트)'" in n for n in r["notes"])


def test_propose_warns_brand_mismatch_and_unmap(fake):
    out = cm.run("propose_mall_shop_mappings", {"items": [
        {"mall_nm": "SSG(사이트)인동FN", "brand": "S", "shop_id": "T51005"},   # 쉬즈미스 행에 리스트 매장
        {"mall_nm": "하프클럽(사이트)", "brand": "T", "shop_id": ""},           # 해제
    ]})
    assert out["action"]["warnings"] and "리스트 매장인데 쉬즈미스 행" in out["action"]["warnings"][0]
    assert [c["action"] for c in out["result"]["changes"]] == ["등록", "해제"]
    assert out["action"]["items"][1]["shopId"] == ""


@pytest.mark.parametrize("item,msg", [
    ({"mall_nm": "SSG", "brand": "S", "shop_id": "S51005"}, "2개입니다"),       # 사이트 여러 개
    ({"mall_nm": "없는몰", "brand": "S", "shop_id": "S51005"}, "찾지 못했습니다"),
    ({"mall_nm": "하프클럽", "brand": "X", "shop_id": "S51005"}, "알 수 없습니다"),
    ({"mall_nm": "하프클럽", "brand": "S", "shop_id": "ZZ1"}, "없는 매장코드"),
])
def test_propose_errors(fake, item, msg):
    with pytest.raises(cm.MallToolError, match=msg):
        cm.run("propose_mall_shop_mappings", {"items": [item]})


def test_permission(fake, monkeypatch):
    from app import ai_tools

    monkeypatch.setattr(ai_tools, "snapshot", lambda: {"builtin": {}, "custom": []})
    assert {"search_mall_shop_mappings", "propose_mall_shop_mappings"} <= {t["name"] for t in ct.tools_for({"pages": ["mall_shop"]})}
    assert not {"search_mall_shop_mappings"} & {t["name"] for t in ct.tools_for({"pages": ["dashboard"]})}
    with pytest.raises(ct.ToolInputError, match="판매처 매장 연결 메뉴 권한"):
        ct.run_tool("propose_mall_shop_mappings", {"items": []}, {"pages": ["dashboard"]})
