"""판매처 매장 연결: 판매자번호 있는 조합만, 판매자 단위 매장정보 예시, 매장정보 기준 후보, 브랜드별 조합, '*' 공통 매핑 적용, 같은 브랜드 매장 후보, 저장 검증·MERGE/DELETE. DB 는 가짜."""
import pytest

from app import mall_shop as ms
from app import shop_info

SHOPS = [
    {"shopId": "S51005", "shopNm": "하프클럽", "brand": "쉬즈미스", "brdCd": "S", "teamNm": "쉬즈5팀", "status": "정상"},
    {"shopId": "T51005", "shopNm": "하프클럽", "brand": "리스트", "brdCd": "T", "teamNm": "리스트5팀", "status": "정상"},
    {"shopId": "T32018", "shopNm": "롯데아울렛구리", "brand": "리스트", "brdCd": "T", "teamNm": "리스트3팀", "status": "정상"},
    {"shopId": "S32021", "shopNm": "롯데아울렛구리", "brand": "쉬즈미스", "brdCd": "S", "teamNm": "쉬즈3팀", "status": "정상"},
    {"shopId": "T15602", "shopNm": "신세계광주", "brand": "리스트", "brdCd": "T", "teamNm": "리스트1팀", "status": "정상"},
    {"shopId": "T15603", "shopNm": "(행)신세계광주", "brand": "리스트", "brdCd": "T", "teamNm": "리스트1팀", "status": "정상"},
]
# (사이트, 판매자번호, 브랜드, 행, 상품, 마지막, SHOP_ID 채움)
COMBOS = [("하프클럽(사이트)", "-", "S", 100, 10, "20261002", 0),   # 판매자번호 없음 → 목록에 없음 (쿼리에서 거름)
          ("네이버(사이트)", "510001", "T", 10, 3, "20261002", 0), ("네이버(사이트)", "510001", "S", 4, 1, "20261002", 0),
          ("네이버(사이트)롯데아울렛구리점 리스트", "510517044", "T", 50, 5, "20261001", 50),
          ("11번가(사이트)", "760001", "S", 10, 2, "20261002", 0)]


@pytest.fixture
def fake(monkeypatch):
    maps = {}
    executed = []

    def query(sql, params=None):
        if "WHERE 1 = 0" in sql:
            return [], []
        assert "NAVER_PAY_SELL_NO IS NOT NULL" in sql   # 판매자번호가 있는 행만 읽는다
        if "REGEXP_REPLACE" in sql:   # (사이트, 판매자번호, 모델번호 뗀 RMK, 행 수) — 판매자 단위 대표값
            return [], [("네이버(사이트)", "510001", "광주신세계 리스트", 9), ("네이버(사이트)", "510001", None, 1),
                        ("11번가(사이트)", "760001", "바이펀", 2), ("11번가(사이트)", "760001", None, 8)]   # 10행 중 2행 → 예시 아님
        return [], [c for c in COMBOS if c[1] != "-"]

    def query_dicts(sql, params=None):
        return [{"MALL_NM": m, "NAVER_PAY_SELL_NO": s, "BRD_CD": b, "SHOP_ID": v["shop"], "USE_YN": v["use"], "RMK": None,
                 "UPT_USERID": "u", "UPT_DAY": "20261003090000"} for (m, s, b), v in maps.items()]

    class Cur:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, p):
            executed.append((sql.split()[0], p))
            key = (p["m"], p["s"], p["b"])
            if sql.startswith("DELETE"):
                maps.pop(key, None)
            else:
                maps[key] = {"shop": p["shop"], "use": p["u"]}

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return Cur()

        def commit(self):
            pass

    class Pool:
        def acquire(self):
            return Conn()

    monkeypatch.setattr(ms.db, "query", query)
    monkeypatch.setattr(ms.db, "query_dicts", query_dicts)
    monkeypatch.setattr(ms.db, "get_pool", lambda: Pool())
    monkeypatch.setattr(shop_info, "search", lambda **k: SHOPS)
    monkeypatch.setattr(ms, "_shop_names", lambda ids: {s["shopId"]: s["shopNm"] for s in SHOPS if s["shopId"] in ids})
    monkeypatch.setattr(ms, "_ready", None)
    ms._cache.clear()
    return maps, executed


def test_listing_seller_only_rmk_and_suggestions(fake):
    d = ms.listing(7)
    assert d["ready"] and d["summary"]["combos"] == 4 and d["summary"]["sellers"] == 3
    assert [(r["mallNm"], r["sellNo"], r["brdCd"]) for r in d["rows"]] == [   # 사이트 → 판매자번호 → 브랜드
        ("11번가(사이트)", "760001", "S"), ("네이버(사이트)", "510001", "S"), ("네이버(사이트)", "510001", "T"),
        ("네이버(사이트)롯데아울렛구리점 리스트", "510517044", "T")]
    by = {(r["mallNm"], r["brdCd"]): r for r in d["rows"]}
    nv = by[("네이버(사이트)", "T")]
    assert (nv["rmk"], nv["rmkShare"]) == ("광주신세계 리스트", 90)   # 판매자 단위 대표값 (브랜드 행 모두 같은 예시)
    assert by[("네이버(사이트)", "S")]["rmk"] == "광주신세계 리스트"
    assert [s["shopId"] for s in nv["suggestions"]] == ["T15602"]   # 매장정보 기준, 순서 무관(광주신세계 ↔ 신세계광주), (행) 매장 제외
    assert by[("네이버(사이트)", "S")]["suggestions"] == []           # 같은 브랜드 매장만
    assert by[("11번가(사이트)", "S")]["rmk"] is None                  # 2/10 행뿐 → 대표 예시 아님
    assert [s["shopId"] for s in by[("네이버(사이트)롯데아울렛구리점 리스트", "T")]["suggestions"]] == ["T32018"]   # 예시 없으면 사이트명


def test_suggest_rules():
    shops = [{"shopId": "S22039", "shopNm": "의정부점", "brand": "쉬즈미스"}, {"shopId": "S12010", "shopNm": "신세계의정부", "brand": "쉬즈미스"},
             {"shopId": "S32043", "shopNm": "신세계프리미엄파주", "brand": "쉬즈미스"}, {"shopId": "S51007", "shopNm": "G마켓", "brand": "쉬즈미스"}]
    assert [s["shopId"] for s in ms._suggest("의정부점", shops)] == ["S22039"]          # 이름이 똑같은 매장이 우선
    assert [s["shopId"] for s in ms._suggest("신세계 파주 쉬즈미스", shops)] == ["S32043"]   # 체인 + 지역
    assert [s["shopId"] for s in ms._suggest("판매자 : G마켓", shops)] == ["S51007"]
    assert ms._suggest("인동FN", shops) == []


def test_save_brand_and_star_mapping(fake, audit_capture):
    maps, executed = fake
    me = {"id": "170046"}
    r = ms.save(me, [{"mallNm": "네이버(사이트)", "sellNo": "510001", "brdCd": "T", "shopId": "t15602"},
                     {"mallNm": "11번가(사이트)", "sellNo": "760001", "brdCd": "*", "shopId": "S51005", "rmk": "공통"}])
    assert r == {"saved": 2, "deleted": 0, "changed": 2}
    assert maps[("네이버(사이트)", "510001", "T")]["shop"] == "T15602" and ("11번가(사이트)", "760001", "*") in maps
    assert audit_capture[-1]["action"] == "MALL_SHOP_MAP" and "네이버(사이트)/510001/T: - → T15602" in audit_capture[-1]["summary"]
    ms._cache.clear()
    d = ms.listing(31)
    by = {(x["mallNm"], x["brdCd"]): x for x in d["rows"]}
    assert by[("11번가(사이트)", "S")]["effectiveShopId"] == "S51005"   # 브랜드 행이 없으면 '*' 공통 매핑
    assert by[("네이버(사이트)", "T")]["effectiveShopId"] == "T15602" and by[("네이버(사이트)", "S")]["effectiveShopId"] is None
    assert d["summary"]["rowsMapped"] == 10 + 10
    # 매장코드를 비우면 해제
    ms.save(me, [{"mallNm": "네이버(사이트)", "sellNo": "510001", "brdCd": "T", "shopId": ""}])
    assert ("네이버(사이트)", "510001", "T") not in maps and executed[-1][0] == "DELETE"


@pytest.mark.parametrize("item,msg", [
    ({"mallNm": "x", "brdCd": "Z", "shopId": "S51005"}, "브랜드"),
    ({"mallNm": "x", "brdCd": "S", "shopId": "ZZZ999"}, "없는 매장코드"),
    ({"mallNm": "", "brdCd": "S", "shopId": "S51005"}, "사이트명"),
    ({"mallNm": "x", "brdCd": "S", "shopId": "S5100512"}, "형식"),
])
def test_save_validation(fake, item, msg):
    with pytest.raises(Exception, match=msg):
        ms.save({"id": "1"}, [item])


def test_save_without_table(fake, monkeypatch):
    monkeypatch.setattr(ms, "table_ready", lambda: False)
    with pytest.raises(Exception, match="create_online_mall_shop.sql"):
        ms.save({"id": "1"}, [{"mallNm": "x", "brdCd": "S", "shopId": "S51005"}])
