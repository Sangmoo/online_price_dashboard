"""재고 재배치 추천: 조건 확인, 수불제어 규칙(ERP 함수와 같게), 매장 간 RT 짝 맞추기, 판매분 자동보충 배분, AI 도구. DB 는 가짜."""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app import chat_tools as ct
from app import chat_tools_stock as cts
from app import stock_ctl as sc
from app import stock_rt as rt
from app import wh_alloc as wa


# ---------------------------------------------------------------- 조건
def test_brand_and_period_rules():
    assert sc.brand_code(None, None) == "S"
    assert sc.brand_code("리스트", None) == sc.brand_code("t", None) == "T"
    assert sc.brand_code(None, ["시스티나"]) == "A"                       # 권한 있는 첫 브랜드
    with pytest.raises(HTTPException) as ex:
        sc.brand_code("쉬즈미스", ["리스트"])
    assert ex.value.status_code == 403
    with pytest.raises(HTTPException):
        sc.brand_code(None, [])
    today = date.today()
    f, t = sc.period(None, None, 7)
    assert t == today.strftime("%Y%m%d") and f == (today - timedelta(days=6)).strftime("%Y%m%d")
    f, t = sc.period(None, None, 1, end_yesterday=True)                  # 배분 기본 = 어제 하루
    assert f == t == (today - timedelta(days=1)).strftime("%Y%m%d")
    assert sc.period("2026-09-01", "2026-10-01", 7) == ("20260901", "20261001") if today >= date(2026, 10, 1) else True
    for frm, to, msg in (("20260901", "20261002", "최대 31일"), ("20261005", "20261001", "늦습니다"), ("2026-13-01", None, "올바르지")):
        with pytest.raises(HTTPException) as ex:
            sc.period(frm, to, 7)
        assert msg in ex.value.detail["message"]
    with pytest.raises(HTTPException):
        sc.period(None, (today + timedelta(days=1)).strftime("%Y%m%d"), 7)
    assert sc.code_list("C0073,C0074", "시즌", r"^C007[0-9A-Z]$") == ["C0073", "C0074"]
    with pytest.raises(HTTPException):
        sc.code_list(["C0073'; --"], "시즌", r"^C007[0-9A-Z]$")
    assert sc.default_seasons(date(2026, 10, 7))[:2] == ["C0073", "C0074"]
    assert sc.default_seasons(date(2026, 4, 1))[:2] == ["C0071", "C0072"]
    assert sc.default_plan_years(date(2027, 1, 5)) == ["2026", "2027"]


# ---------------------------------------------------------------- 수불제어 (F_GET_RNDS_CNTR_ID · F_GET_RNDS_CNTR_AUTO_RT 와 같은 규칙)
def _controls():
    c = sc.Controls()
    c.flags = {
        "SHOP": {"AUTO_DVID_CNTR_YN": "Y", "AUTO_RT_CNTR_YN": "N"},                       # 매장 지정 · 제품 없음 → 매장 전체
        "SHOPP": {"AUTO_DVID_CNTR_YN": "N", "DISTRB_DELV_CNTR_YN": "Y", "AUTO_RT_CNTR_YN": "Y"},  # 매장 + 제품 지정
        "PRDT": {"AUTO_RT_CNTR_STOR_YN": "Y", "INDC_RT_CNTR_YN": "Y", "AUTO_RT_CNTR_YN": "Y"},    # 제품만 지정 → 전 매장
    }
    c.shop_cntrs = {"S1": {"SHOP"}, "S2": {"SHOPP"}}
    c.has_shop = {"SHOP", "SHOPP"}
    c.has_prdt = {"SHOPP", "PRDT"}
    c.prdt_all = {("SHOPP", "P1"): {"BK"}, ("PRDT", "P2"): {"*"}}
    c.prdt_live = {"P2": [("PRDT", "*")]}
    c.xcld = [("C62010", "2026", "C0074", "*", "P9")]
    return c


def test_controls_match_erp_function_rules():
    c = _controls()
    assert c.controlled_id("S1", "ANY", "XX", "13")                        # 매장 전체 제어
    assert not c.controlled_id("S1", "ANY", "XX", "36")                     # 플래그 없음
    assert c.controlled_id("S2", "P1", "BK", "13") and not c.controlled_id("S2", "P1", "WH", "13")
    assert c.controlled_id("S3", "P2", "RD", "36")                          # 제품 지정 (칼라 '*'), 매장 행 없음
    assert not c.controlled_id("S3", "P2", "RD", "13")
    ok = {"team": "C62010", "rt": {"reqAbleYn": "Y"}}
    assert c.controlled_rt_out("S2", "P1", "BK", ok, None)                  # 자동RT 플래그
    assert c.controlled_rt_out("S3", "P2", "RD", ok, None)
    assert not c.controlled_rt_out("S4", "P5", "BK", ok, None)
    style = {"planYy": "2026", "sesn": "C0074", "item": "JK"}
    assert c.controlled_rt_out("S4", "P9", "BK", ok, style)                 # 자동RT 제외 스타일 (팀)
    assert not c.controlled_rt_out("S4", "P9", "BK", {**ok, "team": "C62020"}, style)
    assert c.controlled_rt_out("S4", "P5", "BK", {"team": "C62010", "rt": {"reqAbleYn": "N"}}, None)   # 요청가능여부 N
    assert c.controlled_rt_out("S4", "P5", "BK", {"team": "C62010", "rt": None}, None)                 # RT 그룹 없음


# ---------------------------------------------------------------- 매장 간 RT
def _cand(shop, sales=0, sendable=1, srate=0, mo="S", lsale=None):
    return {"shopId": shop, "sku": ("P1", "BK", "55"), "stock": sendable, "real": sendable, "sendable": sendable, "sales": sales,
            "moBrd": mo, "srate": srate, "lSaleDt": lsale, "fRndsDt": "20250101"}


def _recv(shop, sales=1, stock=0, fail=0, need=1):
    return {"shopId": shop, "prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "sales": sales, "stock": stock, "failCnt": fail,
            "need": need, "grp": "G1", "moOk": {"S"}, "supplyAny": True}


def test_match_orders_and_limits():
    key = (("P1", "BK", "55"), "G1")
    cands = {key: [_cand("A", sales=3, sendable=5), _cand("B", sales=0, sendable=1), _cand("C", sales=0, sendable=2, mo="T")]}
    # 안 팔리는 매장 우선: B(판매 0) 먼저, C 는 행낭 규칙(모매장 브랜드)으로 제외
    pairs, unfilled = rt.match([_recv("R1"), _recv("R2", fail=2)], cands, {}, {}, "slow")
    assert [(p["receiver"]["shopId"], p["sender"]["shopId"]) for p in pairs] == [("R2", "B"), ("R1", "A")]   # 자동RT 취소 요청 먼저
    assert not unfilled
    # 자동 RT 순서: 요청가능 재고 많은 A 먼저
    pairs, _ = rt.match([_recv("R1")], cands, {}, {}, "auto")
    assert pairs[0]["sender"]["shopId"] == "A"
    # 보내는 매장 한도 소진 → limit, 받는 매장 한도 → recv_limit, 재고 없는 그룹 → no_stock
    pairs, unfilled = rt.match([_recv("R1"), _recv("R2")], {key: [_cand("B")]}, {"B": 1}, {}, "slow")
    assert len(pairs) == 1 and unfilled[0]["reason"] in ("limit", "rules")
    pairs, unfilled = rt.match([_recv("R1", need=2)], cands, {}, {"R1": 1}, "slow")
    assert sum(p["qty"] for p in pairs) == 1 and unfilled[0]["reason"] == "recv_limit"
    pairs, unfilled = rt.match([{**_recv("R9"), "grp": "G2", "supplyAny": False}], cands, {}, {}, "slow")
    assert not pairs and unfilled[0]["reason"] == "no_stock"
    # 마이너스 재고(완불 대기) 2장: 한 매장에서 모자라면 다음 매장에서
    pairs, _ = rt.match([_recv("R1", stock=-1, need=2)], {key: [_cand("B"), _cand("D", sendable=1)]}, {}, {}, "slow")
    assert [(p["sender"]["shopId"], p["qty"]) for p in pairs] == [("B", 1), ("D", 1)]


def test_next_batch_extends_ties_and_mo_brands():
    cands = [_cand(s, sales=0, sendable=1) for s in "ABCDEFGHIJKL"] + [_cand("Z", sales=5)]
    assert rt.next_batch(cands, 0, 4, "slow") == 8          # 같은 순위는 4곳까지 더
    assert rt.next_batch(cands, 0, 20, "slow") == len(cands)
    assert rt._mo_brands("A11001", "A") == {"A", "S", "T"} and rt._mo_brands("A11001", "S") == {"S", "A"}
    assert rt._mo_brands("S11001", "A") == {"S"}


def test_rt_compute_end_to_end(monkeypatch):
    """판매 후 품절 매장 R1 ← 같은 그룹의 안 팔리는 S2 (S1 은 판매 중, S3 은 최소보유 · S4 는 출고 경과일 미달)"""
    shops = {sid: {"shopId": sid, "shopNm": sid + "점", "moBrd": "S", "normal": True, "team": "C62010", "type": "C0041", "attr2": None,
                   "rt": {"grp": "G1", "reqAble": None, "reqAbleYn": "Y", "asign": 5, "minRetain": 0, "fDays": 0, "lDays": 0}}
             for sid in ("R1", "S1", "S2", "S3", "S4", "X1")}
    shops["S3"]["rt"]["minRetain"] = 1
    shops["S4"]["rt"]["fDays"] = 30
    shops["X1"]["rt"] = None                                    # RT 그룹 없음 → 받는 매장에서 제외
    monkeypatch.setattr(sc, "shops", lambda: shops)
    monkeypatch.setattr(sc, "base_grade_group", lambda b: "GG")
    monkeypatch.setattr(sc, "grade_shops", lambda g: {s: {} for s in shops})
    monkeypatch.setattr(sc, "controls", lambda b, d=None: sc.Controls())
    monkeypatch.setattr(sc, "style_info", lambda p: {x: {"styleNm": "자켓", "planYy": "2026", "sesn": "C0074", "item": "JK"} for x in p})
    monkeypatch.setattr(sc, "team_names", lambda: {"C62010": "쉬즈1팀"})
    monkeypatch.setattr(rt, "_styles", lambda w, b: ["P1"])
    monkeypatch.setattr(rt, "_sales", lambda f, t, w, b, many: [("R1", "P1", "BK", "55", 2, "20261006"), ("S1", "P1", "BK", "55", 3, "20261006"),
                                                                ("X1", "P1", "BK", "55", 1, "20261006")])
    monkeypatch.setattr(rt, "_failed", lambda f, t, w, b: [])
    monkeypatch.setattr(rt, "_stock", lambda pcs, ym: [("S1", "P1", "BK", "55", 2), ("S2", "P1", "BK", "55", 1), ("S3", "P1", "BK", "55", 1),
                                                       ("S4", "P1", "BK", "55", 4)])
    monkeypatch.setattr(rt, "_reserved", lambda b, td: {"moving": {}, "pending": {}, "asigned": {}, "asignedSku": set(), "shopReq": {}, "requested": {}})
    recent = (date.today() - timedelta(days=3)).strftime("%Y%m%d")
    monkeypatch.setattr(rt, "_prdt_base", lambda b, keys: {k: (recent if k[0] == "S4" else "20250101", None, "20260901", 5, 0, 0, 2, 0) for k in keys})
    d = rt._compute("S", "20261001", "20261007", [], [], [], None, 1, False, "slow")
    assert [(r["fromShopId"], r["toShopId"], r["qty"]) for r in d["rows"]] == [("S2", "R1", 1)]
    s = d["summary"]
    assert s["receivers"] == 1 and s["skipped"]["noGroup"] == 1 and s["senderExcluded"]["moving"] == 1
    xl = rt.export_xlsx({**d, "cond": {"planYy": [], "seasons": [], "teams": [], "prdt": None}})
    assert xl[:2] == b"PK"


# ---------------------------------------------------------------- 창고 → 매장 배분 (SP_AUTO_DVID)
def _shop(sid, fq=0, sq=0, stk=0, ctl=False):
    return {"shopId": sid, "fq": fq, "sq": sq, "stk": stk, "ctl": ctl}


def test_allocate_fullpay_then_sales_with_caps():
    shops = [_shop("A", fq=1, sq=2, stk=1), _shop("B", sq=3, stk=0), _shop("C", fq=2, ctl=True)]
    # 상한 3: A 완불 1 → A 판매 min(2, 3-1-1=1)=1, B 판매 3 → 창고 4장이면 B 는 2장
    assert wa.allocate(4, shops, 3) == [{"shopId": "A", "fp": 1, "sale": 1}, {"shopId": "B", "fp": 0, "sale": 2}]
    assert wa.allocate(0, shops, 3) == []
    assert wa.allocate(10, [_shop("A", sq=5, stk=9)], 9) == []              # 이미 상한


def test_shop_key_and_oracle_round():
    base = {"typeRank": 1, "srate": 50.0, "prty": 3, "rank": 2, "sdt": None, "shopId": "X"}
    hi_grade = {**base, "prty": 5, "shopId": "Y"}
    assert sorted([base, hi_grade], key=lambda c: wa.shop_key(c, "S"))[0]["shopId"] == "Y"   # 쉬즈미스: 등급 높은 순
    assert sorted([base, hi_grade], key=lambda c: wa.shop_key(c, "T"))[0]["shopId"] == "X"   # 리스트: 반대
    assert sorted([base, {**base, "typeRank": 4, "srate": 99.0, "shopId": "Z"}], key=lambda c: wa.shop_key(c, "S"))[0]["shopId"] == "X"
    assert wa.oround(2.5) == 3 and wa.oround(0.125, 2) == 0.13 and wa.oround(-1.5) == -2


def test_alloc_compute_end_to_end(monkeypatch):
    shops = {sid: {"shopId": sid, "shopNm": sid, "moBrd": "S", "normal": True, "team": "C62010", "type": t, "attr2": None, "rt": None}
             for sid, t in (("A", "C0041"), ("B", "C0042"), ("C", "C0041"))}
    monkeypatch.setattr(sc, "shops", lambda: shops)
    monkeypatch.setattr(sc, "grade_shops", lambda g: {s: {"grd": "C09401", "grdNm": "1등급", "prty": 1, "rank": 1} for s in shops})
    monkeypatch.setattr(sc, "controls", lambda b, d=None: sc.Controls())
    monkeypatch.setattr(sc, "team_names", lambda: {})
    monkeypatch.setattr(wa, "_styles", lambda *a: {("P1", "BK", "55"): {"minRate": 0, "maxStock": 3, "minWh": 1, "brd": "S", "styleNm": "자켓",
                                                                        "planYy": "2026", "sesn": "C0074", "item": "JK"}})
    monkeypatch.setattr(wa, "_sales", lambda f, t, p: [("A", "P1", "BK", "55", 0, 1, 1), ("B", "P1", "BK", "55", 1, 0, 1), ("C", "P1", "BK", "55", 0, 1, 1)])
    monkeypatch.setattr(wa, "_stock", lambda pcs, ym: {("C", "P1", "BK", "55"): (3, 0)})           # C 는 상한 도달
    monkeypatch.setattr(wa, "_moves", lambda pcs, ms, f: {})
    monkeypatch.setattr(wa, "_first_sale", lambda b, k: {})
    monkeypatch.setattr(wa, "_wh_avail", lambda b, wh, p, td: {("P1", "BK", "55"): {"wh": 5, "indc": 1, "ask": 1}})
    d = wa._compute("S", "IN", "20261006", "20261006", "BASE", "GG", [], [], [], [], None, [], 1.0)
    # 창고 5 − 지시 1 − 의뢰 1 − 하한 1 = 2 → 완불 B 1장, 판매 A 1장 (C 는 상한)
    assert [(r["shopId"], r["askFp"], r["askSale"]) for r in d["rows"]] == [("A", 0, 1), ("B", 1, 0)]
    assert d["skus"][0]["avail"] == 2 and d["summary"]["allocQty"] == 2
    assert {r["shopId"]: r["ask"] for r in d["allRows"]} == {"A": 1, "B": 1, "C": 0}     # 현재고 = 상한이면 후보지만 0장


# ---------------------------------------------------------------- AI 도구
def test_stock_tools_need_menu_and_map_names(monkeypatch):
    assert {t["name"] for t in ct.tools_for({"pages": ["stock_rt"]})} >= cts.TOOL_NAMES
    assert not cts.TOOL_NAMES & {t["name"] for t in ct.tools_for({"pages": ["sale_dashboard"]})}
    with pytest.raises(ct.ToolInputError, match="재고 재배치 추천 메뉴 권한"):
        ct.run_tool("get_auto_rt_stats", {}, {"pages": ["sale_dashboard"]})
    seen = {}

    def fake(*a, **kw):
        seen["args"], seen["kw"] = a, kw
        return {"brand": "S", "brandNm": "쉬즈미스", "from": "2026-10-01", "to": "2026-10-07", "asOf": "x", "per": 1, "limits": False,
                "order": "slow", "orderNm": "안 팔리는 매장 우선", "senderMax": 0, "cond": {"planYy": [], "seasons": ["C0074"], "teams": [], "prdt": None},
                "summary": {"receivers": 1, "needQty": 1, "filledReceivers": 1, "recRows": 1, "recQty": 1, "senders": 1, "receivingShops": 1,
                            "failRequests": 0, "failFilled": 0, "unfilled": 0, "unfilledBy": {}, "senderExcluded": {}, "skipped": {"noGroup": 0, "recvCtl": 0}},
                "reasonNames": rt.REASONS, "ruleNames": rt.RULES, "rows": [{"fromShopId": "S2", "toShopId": "R1"}], "unfilled": [],
                "topSenders": [], "topReceivers": []}
    monkeypatch.setattr(rt, "recommend", fake)
    monkeypatch.setattr(sc, "code_names", lambda p: {"C0074": "겨울", "C0078": "겨울기획"})
    monkeypatch.setattr(sc, "team_names", lambda: {"C62010": "쉬즈1팀"})
    out = ct.run_tool("recommend_store_rt", {"brand": "쉬즈미스", "seasons": ["겨울", "C0078"], "teams": ["쉬즈1팀"], "shop_id": "r1"},
                      {"pages": ["stock_rt"], "brands": ["쉬즈미스"]})
    assert seen["args"][4] == ["C0074", "C0078"] and seen["args"][6] == ["C62010"] and seen["kw"]["allowed"] == ["쉬즈미스"]
    assert out["result"]["shopFilter"]["receiveRows"] == 1 and "ERP" in out["result"]["note"]
    with pytest.raises(ct.ToolInputError, match="시즌"):
        ct.run_tool("recommend_store_rt", {"seasons": ["한여름"]}, {"pages": ["stock_rt"]})
