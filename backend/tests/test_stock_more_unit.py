"""재고 재배치 추천 > 행사 · 가상 매장 제외 · 미처리 RT 현황 · 창고 회수 추천 · 장기 미판매 재고 (DB 없이)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app import stock_ctl as sc


def test_virtual_reason_rules():
    assert sc.virtual_reason("C708070", "C00209", "C3872", "C3772", "N") == "오픈매장"            # 가상매장구분이 가장 구체적
    assert sc.virtual_reason(None, "C00209", "C3873", "C3773", "Y") == "기타 유통"                # 사내행사(롯데아울렛동부산) 같은 기타 유통
    assert sc.virtual_reason(None, "C00204", "C3881", "C3779", "Y") == "사내행사"
    assert sc.virtual_reason(None, "C00204", "C3874", "C3774", "N") == "실매장 아님"
    assert sc.virtual_reason(None, "C00202", "C3871", "C3771", "Y") is None                      # 일반 백화점
    assert sc.virtual_reason(None, "C00205", "C3872", "C3772", None) is None                     # 대리점 (실매장 값 없음)
    assert sc.virtual_reason(None, "C00204", "C3874", "C3774", None, "(행)스타필드하남") == "행사(매장명)"   # 코드는 정상, 이름에만 표시
    assert sc.virtual_reason(None, "C00202", "C3871", "C3771", "Y", "(폐)롯데강남") == "폐점(매장명)"
    assert sc.virtual_reason(None, "C00202", "C3871", "C3771", "Y", "롯데(행사)") is None


def _shops():
    base = {"moBrd": "S", "normal": True, "type": "C0041", "attr2": None, "rt": None, "virtual": False, "virtualWhy": None}
    return {"S1": {**base, "shopId": "S1", "shopNm": "롯데잠실", "team": "C62010"},
            "S2": {**base, "shopId": "S2", "shopNm": "천호점", "team": "C62020"},
            "V1": {**base, "shopId": "V1", "shopNm": "오픈매장1", "team": "C62010", "virtual": True, "virtualWhy": "오픈매장"},
            "C1": {**base, "shopId": "C1", "shopNm": "(폐)강남", "team": "C62010", "normal": False}}


def test_pending_board_ages_urgent_and_virtual(monkeypatch):
    from app import db, stock_pending as sp

    now = datetime.now()
    ago = lambda h: (now - timedelta(hours=h)).strftime("%Y%m%d%H%M%S")   # noqa: E731
    rows = [("20261005", 1, "S1", "S2", "P1", "BK", "55", 1, "C6811", ago(50), "230112", "2026100500001", None),
            ("20261006", 2, "S1", "S2", "P1", "BK", "66", 1, "C6812", ago(10), "S2", None, "A1"),
            ("20261006", 3, "S2", "S1", "P2", "IV", "77", 2, "C6811", ago(80), "230112", "2026100600002", None),
            ("20261006", 4, "V1", "S1", "P2", "IV", "77", 1, "C6811", ago(5), "230112", None, None)]
    monkeypatch.setattr(db, "query", lambda sql, b=None, arraysize=0: ([], rows))
    monkeypatch.setattr(sc, "shops", _shops)
    monkeypatch.setattr(sc, "team_names", lambda: {"C62010": "쉬즈1팀", "C62020": "쉬즈2팀"})
    monkeypatch.setattr(sc, "style_info", lambda p: {})
    d = sp.board("S", refresh=True)
    s = d["summary"]
    assert s["rows"] == 3 and d["virtualRows"] == 1 and s["urgent"] == 2                          # 본사지시 50 · 80시간 → 임박
    assert s["byAge"] == {"d0": 1, "d1": 0, "d2": 1, "d3": 1} and s["byType"]["C6812"] == 1
    assert d["rows"][0]["hours"] >= 80 and d["rows"][0]["fromShopId"] == "S2"                     # 오래된 순
    by = {g["key"]: g for g in d["shops"]}
    assert by["S1"]["rows"] == 2 and by["S1"]["urgent"] == 1 and by["S2"]["d3"] == 1
    assert sp.board("S", include_virtual=True, refresh=True)["summary"]["rows"] == 4
    assert sp.export_xlsx(d)[:2] == b"PK"


def test_return_recommend_orders_and_fills(monkeypatch):
    from app import stock_return as sr
    from app import stock_rt, wh_alloc

    sku = {"prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "styleNm": "자켓", "whStock": 1, "avail": 0, "demand": 3, "short": 3, "minWh": 0}
    alloc = {"brand": "S", "brandNm": "쉬즈미스", "wh": "IN", "from": "2026-10-06", "to": "2026-10-06", "asOf": "x", "skus": [sku],
             "shortRows": [{"shopId": "S2", "prdtCd": "P1", "colorCd": "BK", "sizeCd": "55"}]}
    monkeypatch.setattr(wh_alloc, "recommend", lambda **k: alloc)
    stock = [("S1", "P1", "BK", "55", 2), ("S2", "P1", "BK", "55", 1), ("V1", "P1", "BK", "55", 5), ("C1", "P1", "BK", "55", 1), ("S3", "P1", "BK", "55", 4)]
    monkeypatch.setattr(stock_rt, "_stock", lambda pcs, ym: stock)
    monkeypatch.setattr(sr, "_sales", lambda pcs, f, t: {("S3", "P1", "BK", "55"): 1})            # S3 은 최근 판매 → 제외
    res = {"moving": {}, "pending": {}, "asigned": {}, "asignedSku": set(), "shopReq": {}, "requested": {}, "instrOut": {}, "instrIn": {}}
    monkeypatch.setattr(stock_rt, "_reserved", lambda b, td: res)
    monkeypatch.setattr(stock_rt, "_prdt_base", lambda b, keys: {("S1", "P1", "BK", "55"): ("20250101", "20260101", "20260301", 0, 0, 0, 0, 0)})
    shops = _shops()
    shops["S3"] = {**shops["S1"], "shopId": "S3", "shopNm": "S3"}
    monkeypatch.setattr(sc, "shops", lambda: shops)
    monkeypatch.setattr(sc, "team_names", lambda: {})
    d = sr.recommend({"brand": "S"}, 14, "need", refresh=True)
    # 폐점 C1 먼저 1장 → 판매 이력 있는 S1 에서 2장 (S2 는 받을 매장, V1 가상, S3 최근 판매)
    assert [(r["shopId"], r["qty"]) for r in d["rows"]] == [("C1", 1), ("S1", 2)]
    s = d["summary"]
    assert s["returnQty"] == 3 and s["coveredSkus"] == 1 and s["excluded"] == {"sold": 1, "needs": 1, "virtual": 1, "reserved": 0}
    res["instrOut"] = {("S1", "P1", "BK", "55"): 2}                                               # 이미 지시로 나가는 재고는 회수 못 함
    d = sr.recommend({"brand": "S"}, 14, "all", refresh=True)
    assert [(r["shopId"], r["qty"]) for r in d["rows"]] == [("C1", 1)] and d["skus"][0]["left"] == 2
    assert sr.export_xlsx(d)[:2] == b"PK"


def test_aging_report_buckets_filters_and_virtual(monkeypatch):
    from app import stock_aging as sa

    today = date.today()
    d8 = lambda n: (today - timedelta(days=n)).strftime("%Y%m%d")   # noqa: E731
    base = {"rows": [("S1", "P1", 5, 500000, d8(10), d8(20), d8(200), 3),         # 10일 전 판매 → 30일 이하
                     ("S1", "P2", 2, 100000, d8(400), d8(400), d8(500), 1),       # 1년 넘음
                     ("S2", "P2", 3, 150000, None, d8(120), d8(120), 2),          # 판매 이력 없음 → 최초출고 120일
                     ("V1", "P2", 9, 900000, d8(300), None, None, 1),             # 가상 매장
                     ("S2", "P3", 1, 10000, None, None, None, 1)],                # 기준 없음
            "styles": {"P1": ("자켓", "2026", "C0074"), "P2": ("코트", "2025", "C0074"), "P3": ("니트", "2024", "C0073")},
            "asOf": "2026-10-07 07:00", "sec": 60.0, "ym": "202610"}
    monkeypatch.setattr(sa, "base", lambda b, refresh=False: base)
    monkeypatch.setattr(sc, "shops", _shops)
    monkeypatch.setattr(sc, "team_names", lambda: {"C62010": "쉬즈1팀", "C62020": "쉬즈2팀"})
    monkeypatch.setattr(sc, "code_names", lambda p: {"C0074": "겨울", "C0073": "가을"})
    d = sa.report("S", 90)
    s = d["summary"]
    assert s["qty"] == 11 and s["agedQty"] == 5 and s["agedShops"] == 2 and d["virtualQty"] == 9
    bk = {b["key"]: b["qty"] for b in d["buckets"]}
    assert bk["b30"] == 5 and bk["b180"] == 3 and bk["bOld"] == 2 and bk["none"] == 1
    assert [(x["shopId"], x["prdtCd"], x["neverSold"]) for x in d["detail"]] == [("S2", "P2", True), ("S1", "P2", False)]
    assert d["styles"][0]["prdtCd"] == "P2" and d["styles"][0]["agedShops"] == 2
    d = sa.report("S", 180, seasons="C0074", include_virtual=True)
    assert d["summary"]["agedQty"] == 2 + 9 and d["virtualQty"] == 0
    assert sa.report("S", 30, teams="C62020")["summary"]["agedQty"] == 3
    assert sa.export_xlsx(d)[:2] == b"PK"


def test_rt_excludes_virtual_shops(monkeypatch):
    """행사 · 가상 매장은 받는 매장 · 보내는 매장 모두에서 빠진다"""
    from app import stock_rt as rt

    shops = {sid: {"shopId": sid, "shopNm": sid, "moBrd": "S", "normal": True, "team": "C62010", "type": "C0041", "attr2": None,
                   "virtual": sid.startswith("V"), "rt": {"grp": "G1", "reqAble": None, "reqAbleYn": "Y", "asign": 5, "minRetain": 0, "fDays": 0, "lDays": 0}}
             for sid in ("R1", "V2", "S2", "V9")}
    monkeypatch.setattr(sc, "shops", lambda: shops)
    monkeypatch.setattr(sc, "base_grade_group", lambda b: "GG")
    monkeypatch.setattr(sc, "grade_shops", lambda g: {s: {} for s in shops})
    monkeypatch.setattr(sc, "controls", lambda b, d=None: sc.Controls())
    monkeypatch.setattr(sc, "style_info", lambda p: {x: {"styleNm": "자켓"} for x in p})
    monkeypatch.setattr(sc, "team_names", lambda: {})
    monkeypatch.setattr(rt, "_styles", lambda w, b: ["P1"])
    monkeypatch.setattr(rt, "_sales", lambda f, t, w, b, many: [("R1", "P1", "BK", "55", 2, "20261006"), ("V2", "P1", "BK", "55", 1, "20261006")])
    monkeypatch.setattr(rt, "_failed", lambda f, t, w, b: [])
    monkeypatch.setattr(rt, "_stock", lambda pcs, ym: [("S2", "P1", "BK", "55", 1), ("V9", "P1", "BK", "55", 5)])
    monkeypatch.setattr(rt, "_reserved", lambda b, td: {"moving": {}, "pending": {}, "asigned": {}, "asignedSku": set(), "shopReq": {}, "requested": {},
                                                        "instrOut": {}, "instrIn": {}})
    monkeypatch.setattr(rt, "_prdt_base", lambda b, keys: {k: ("20250101", None, "20260901", 5, 0, 0, 2, 0) for k in keys})
    d = rt._compute("S", "20261001", "20261007", [], [], [], None, 1, False, "slow")
    assert [(r["fromShopId"], r["toShopId"]) for r in d["rows"]] == [("S2", "R1")]
    assert d["summary"]["skipped"]["virtual"] == 1 and d["summary"]["senderExcluded"]["virtual"] == 1


def test_turnover_classes_and_aggregates(monkeypatch):
    from app import stock_aging, stock_turnover as tv

    base = {"rows": [("S1", "P1", 10, 100000, None, None, None, 1),    # 판매 28 → 일 1 → 10일
                     ("S1", "P2", 40, 400000, None, None, None, 1),    # 판매 0 → 판매 없음
                     ("S2", "P1", 1, 10000, None, None, None, 1),      # 판매 14 → 일 0.5 → 2일 (품절 위험)
                     ("V1", "P1", 9, 90000, None, None, None, 1)],     # 가상 매장
            "styles": {"P1": ("자켓", "2026", "C0074"), "P2": ("코트", "2025", "C0074"), "P3": ("니트", "2026", "C0073")},
            "asOf": "x", "sec": 1, "ym": "202610"}
    monkeypatch.setattr(stock_aging, "base", lambda b, refresh=False: base)
    monkeypatch.setattr(sc, "cached", lambda key, ttl, fn, force=False: fn())
    monkeypatch.setattr(tv, "_sales", lambda b, d: {("S1", "P1"): 28, ("S2", "P1"): 14, ("S2", "P3"): 5, ("V1", "P1"): 3})
    monkeypatch.setattr(sc, "shops", _shops)
    monkeypatch.setattr(sc, "team_names", lambda: {"C62010": "쉬즈1팀", "C62020": "쉬즈2팀"})
    monkeypatch.setattr(sc, "code_names", lambda p: {"C0074": "겨울", "C0073": "가을"})
    d = tv.report("S", 28)
    cls = {c["key"]: c["rows"] for c in d["classes"]}
    assert cls["c30"] == 1 and cls["nosale"] == 1 and cls["c7"] == 1 and cls["out"] == 1 and d["virtualRows"] == 1   # S2·P3 = 재고 0 · 판매 5 → 품절
    s = d["summary"]
    assert s["stock"] == 51 and s["sales"] == 47 and s["shortRows"] == 2 and s["overRows"] == 1 and s["overStock"] == 40
    by = {g["shopId"]: g for g in d["shops"]}
    assert by["S1"]["cover"] == round(50 / (28 / 28), 1) and by["S2"]["short"] == 2
    assert d["detail"][0]["cls"] in ("out", "c7") and d["detail"][-1]["cls"] == "nosale"
    assert tv.report("S", 28, seasons="C0073")["summary"]["sales"] == 5
    assert tv.export_xlsx(d)[:2] == b"PK"


def test_initial_overlap_and_maturity(monkeypatch):
    from app import stock_initial as si

    today = date.today()
    old = (today - timedelta(days=40)).strftime("%Y%m%d")
    new = (today - timedelta(days=3)).strftime("%Y%m%d")
    items = [{"shopId": "S1", "prdtCd": "P1", "colorCd": "BK", "alloc": 10, "sold": 12, "start": old, "matured": True},
             {"shopId": "S2", "prdtCd": "P1", "colorCd": "BK", "alloc": 10, "sold": 0, "start": old, "matured": True},
             {"shopId": "V1", "prdtCd": "P1", "colorCd": "BK", "alloc": 5, "sold": 5, "start": old, "matured": True},
             {"shopId": "S1", "prdtCd": "P2", "colorCd": "IV", "alloc": 4, "sold": 1, "start": new, "matured": False}]
    base = {"brand": "S", "from": old, "to": new, "window": 14, "items": items, "asOf": "x", "sec": 1,
            "styles": {"P1": {"planYy": "2026", "sesn": "C0074"}, "P2": {"planYy": "2026", "sesn": "C0074"}}}
    monkeypatch.setattr(si, "_load", lambda b, f, t, w: base)
    monkeypatch.setattr(sc, "cached", lambda key, ttl, fn, force=False: fn())
    monkeypatch.setattr(sc, "shops", _shops)
    monkeypatch.setattr(sc, "team_names", lambda: {})
    monkeypatch.setattr(sc, "code_names", lambda p: {"C0074": "겨울"})
    d = si.analyze("S", old, new, 14)
    s = d["summary"]
    # P1: 배분 비중 50/50, 판매 비중 100/0 → 적중률 50
    assert d["products"][0]["overlap"] == 50.0 and s["overlap"] == 50.0 and d["immature"] == 1 and d["virtualRows"] == 1
    assert s["alloc"] == 20 and s["sold"] == 12 and s["zero"] == 1 and s["soldOut"] == 1
    d = si.analyze("S", old, new, 14, matured_only=False)
    p2 = next(p for p in d["products"] if p["prdtCd"] == "P2")
    assert p2["overlap"] is None                                   # 판매 10장 미만은 판단 보류
    try:
        si.analyze("S", "20260101", "20260601", 14)
        raise AssertionError("기간 제한")
    except Exception as ex:                                        # noqa: BLE001
        assert "최대" in str(getattr(ex, "detail", ex))
    assert si.export_xlsx(d)[:2] == b"PK"
