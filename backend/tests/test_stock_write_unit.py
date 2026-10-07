"""재고 재배치 추천 > ERP 등록 · 삭제 (본사지시 RT 지시 · 배분의뢰) — DB 없이 흐름 · 안전장치 확인."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import stock_ctl as sc
from app import stock_write as w

TODAY = sc.today()


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, binds=None):
        self.conn.log.append((" ".join(sql.split()), binds))
        for key, rows in self.conn.answers.items():
            if key in sql:
                self._rows = list(rows)
                break
        else:
            self._rows = []
        self.rowcount = self.conn.rowcount if sql.lstrip().upper().startswith("DELETE") else 0

    def executemany(self, sql, rows):
        self.conn.many.append((" ".join(sql.split()), rows))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, answers=None, rowcount=0):
        self.answers = answers or {}
        self.rowcount = rowcount
        self.log: list = []
        self.many: list = []
        self.committed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn

    def release(self, c):
        pass


ME = {"id": "ADM1", "role": "ADMIN", "ip": "127.0.0.1"}


def _rt_rows():
    base = {"styleNm": "자켓", "fromSendable": 1, "fromStock": 2, "toIncoming": 0}
    return [{**base, "no": 1, "prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "qty": 1, "fromShopId": "S1", "toShopId": "R1"},
            {**base, "no": 2, "prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "qty": 1, "fromShopId": "S1", "toShopId": "R2"},
            {**base, "no": 3, "prdtCd": "P2", "colorCd": "WH", "sizeCd": "66", "qty": 2, "fromShopId": "S2", "toShopId": "R3"}]


@pytest.fixture
def rt_env(monkeypatch):
    from app import stock_rt

    monkeypatch.setattr(stock_rt, "recommend", lambda **k: {"brand": "S", "brandNm": "쉬즈미스", "asOf": "2026-10-07 10:00", "rows": _rt_rows()})
    live = {("S1", "P1", "BK", "55"): 1, ("S2", "P2", "WH", "66"): 5}
    incoming: dict = {}
    monkeypatch.setattr(w, "_sender_live", lambda keys, td, b: (live, incoming))
    return incoming


def test_writer_is_admin_only(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "stock_page", lambda req: {"id": "U1", "role": "USER"})
    with pytest.raises(HTTPException) as e:
        main.stock_writer(None)
    assert e.value.status_code == 403
    monkeypatch.setattr(main, "stock_page", lambda req: ME)
    assert main.stock_writer(None) is ME
    from types import SimpleNamespace

    with pytest.raises(HTTPException) as e:          # 사용자 화면 미리보기 중 (관리자>대상) → 대상 사번으로 들어가므로 막음
        main.stock_writer(SimpleNamespace(state=SimpleNamespace(usr_id="ADM1>U2")))
    assert "미리보기" in e.value.detail["message"]
    assert main.stock_writer(SimpleNamespace(state=SimpleNamespace(usr_id="ADM1"))) is ME


def test_rt_plan_rechecks_live_stock_and_incoming(rt_env):
    keys = [["P1", "BK", "55", "S1", "R1"], ["P1", "BK", "55", "S1", "R2"], ["P2", "WH", "66", "S2", "R3"], ["X", "Y", "Z", "S9", "R9"]]
    p = w.rt_preview({}, keys, None)
    # S1 은 지금 1장만 보낼 수 있어 두 번째 행은 빠진다 · 추천에 없는 행도 빠진다
    assert [(r["fromShopId"], r["toShopId"]) for r in p["rows"]] == [("S1", "R1"), ("S2", "R3")]
    assert p["qty"] == 3 and len(p["skipped"]) == 2
    assert any("재고 부족" in s["reason"] for s in p["skipped"]) and any("추천 결과에 없음" in s["reason"] for s in p["skipped"])
    # 추천 뒤 받는 매장에 새 지시가 들어오면 뺀다
    rt_env[("R3", "P2", "WH", "66")] = 1
    p = w.rt_preview({}, keys[2:3], None)
    assert p["count"] == 0 and "새로 들어감" in p["skipped"][0]["reason"]
    with pytest.raises(HTTPException):
        w.rt_preview({}, [["P1", "BK"]], None)          # 키 모양이 틀림


def test_rt_register_inserts_unconfirmed_instructions_only(rt_env, monkeypatch, audit_capture):
    from app import db

    conn = FakeConn({"FROM T_INDC_RT WHERE INDC_ID LIKE": [(41, f"{TODAY}00041")], "S_SHOP_REQ_SEQ.NEXTVAL": [(901,), (902,), (903,)]})
    monkeypatch.setattr(db, "get_pool", lambda: FakePool(conn))
    r = w.rt_register(ME, {}, [["P1", "BK", "55", "S1", "R1"], ["P2", "WH", "66", "S2", "R3"]], None, None)
    assert conn.committed and r["qty"] == 3 and r["firstId"] == f"{TODAY}00042" and r["lastId"] == f"{TODAY}00044"
    (sql, rows), (req_sql, reqs) = conn.many
    # 지시: 1장에 1행, 로그인 사번으로 확정 (CNFM_YN Y · CNFM_USERID · 요청 연결)
    assert "INSERT INTO T_INDC_RT" in sql and "1, :dt, 'Y', :td, :u, 'C6811', :dt, :rs" in sql
    assert [x["st"] for x in rows] == ["R1", "R3", "R3"] and [x["rs"] for x in rows] == [901, 902, 903]
    assert all(x["m"] == sc.WEB_MARK and x["u"] == "ADM1" for x in rows)
    # 매장 이동요청: 본사지시 · 미처리, 요청일 = 지시일, 같은 순번
    assert "INSERT INTO T_SHOP_REQ" in req_sql and "'C2954', 'N', :cp, 'C6811'" in req_sql
    assert [(x["rs"], x["id"], x["u"]) for x in reqs] == [(901, f"{TODAY}00042", "ADM1"), (902, f"{TODAY}00043", "ADM1"), (903, f"{TODAY}00044", "ADM1")]
    assert audit_capture[-1]["action"] == "STOCK_RT_INDC"
    with pytest.raises(HTTPException):
        w.rt_register(ME, {}, [["P1", "BK", "55", "S1", "R1"]], "2020-01-01", None)          # 지난 날짜


def test_rt_delete_only_web_unconfirmed(monkeypatch, audit_capture):
    from app import db

    conn = FakeConn({"SELECT INDC_ID": [("x",)]}, rowcount=1)
    monkeypatch.setattr(db, "get_pool", lambda: FakePool(conn))
    r = w.rt_delete(ME, "S", [f"{TODAY}00042", f"{TODAY}00043"], None)
    assert r["deleted"] == 1 and r["removed"] == 1 and r["canceled"] == 0 and r["notDeleted"] == 1
    dele = [s for s, _ in conn.log if s.startswith("DELETE")][0]
    assert "ATTR1 = :m" in dele and "NVL(CNFM_YN, 'N') = 'N'" in dele and "SHOP_REQ_SEQ IS NULL" in dele
    # 확정된 지시는 매장 미처리 요청만 ERP 본사지시 취소처럼 소프트 삭제
    upd = [s for s, _ in conn.log if s.startswith("UPDATE T_SHOP_REQ")][0]
    assert "RESN = '본사지시취소 ' || RESN" in upd and "DEL_DAY = :now" in upd and "PRCS_CLSBY = 'C2954'" in upd and "SHOP_MOVE_SEQ IS NULL" in upd
    with pytest.raises(HTTPException):
        w.rt_delete(ME, "S", ["abc"], None)


@pytest.fixture
def alloc_env(monkeypatch):
    from app import wh_alloc

    row = {"prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "rank": 1, "askFp": 1, "askSale": 1, "ask": 2}
    rows = [{**row, "shopId": "A"}, {**row, "shopId": "B", "rank": 2}, {**row, "shopId": "C", "rank": 3}]
    monkeypatch.setattr(wh_alloc, "recommend", lambda **k: {"brand": "S", "brandNm": "쉬즈미스", "wh": "IN", "grdGrp": "GG", "asOf": "x",
                                                            "rows": rows, "skus": [{"prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "minWh": 1}]})
    monkeypatch.setattr(wh_alloc, "_wh_avail", lambda b, wh, p, td: {("P1", "BK", "55"): {"wh": 7, "indc": 1, "ask": 0}})   # 가용 5
    asked: dict = {}
    monkeypatch.setattr(wh_alloc, "web_asked", lambda b, td: asked)
    return asked


def test_alloc_plan_caps_by_live_warehouse(alloc_env):
    keys = [["A", "P1", "BK", "55"], ["B", "P1", "BK", "55"], ["C", "P1", "BK", "55"]]
    p = w.alloc_preview({}, keys, None)
    assert [r["shopId"] for r in p["rows"]] == ["A", "B"] and "창고 가용 부족" in p["skipped"][0]["reason"]     # 5장 → 2 + 2, C 는 순위 뒤라 뺌
    alloc_env[("A", "P1", "BK", "55")] = 2
    p = w.alloc_preview({}, keys, None)
    assert [r["shopId"] for r in p["rows"]] == ["B", "C"] and "이미" in p["skipped"][0]["reason"]


def test_alloc_register_like_sp_and_rejects_confirmed_seq(alloc_env, monkeypatch, audit_capture):
    from app import db

    conn = FakeConn({"WHERE ASK_DT = :d AND ASK_SEQN = :n FOR UPDATE": [("T", "N", "Z", "P", "C", "S"), ("S", "N", "A", "P1", "BK", "55")],
                     "SELECT NVL(MAX(SEQ), 0)": [(7,)]})
    monkeypatch.setattr(db, "get_pool", lambda: FakePool(conn))
    r = w.alloc_register(ME, {}, [["A", "P1", "BK", "55"], ["B", "P1", "BK", "55"]], None, 12, None, None)
    (sql, rows), = conn.many
    assert "INSERT INTO T_DELV_ASK" in sql and "'C0633', :q, :pre, 'N'" in sql
    assert [(x["sh"], x["seq"], x["q"], x["m"]) for x in rows] == [("B", 8, 2, sc.WEB_MARK)]        # A 는 이 차수에 이미 있어 뺌
    assert r["count"] == 1 and r["askSeqn"] == 12 and audit_capture[-1]["action"] == "STOCK_ALLOC_ASK"
    conn.answers["WHERE ASK_DT = :d AND ASK_SEQN = :n FOR UPDATE"] = [("S", "Y", "Q", "P", "C", "S")]
    with pytest.raises(HTTPException) as e:
        w.alloc_register(ME, {}, [["B", "P1", "BK", "55"]], None, 12, None, None)
    assert "확정된 차수" in e.value.detail["message"]
    for bad in (0, "x", 10000):
        with pytest.raises(HTTPException):
            w.alloc_register(ME, {}, [["B", "P1", "BK", "55"]], None, bad, None, None)


def test_alloc_delete_only_web_unconfirmed(monkeypatch):
    from app import db

    conn = FakeConn({"SELECT ASK_DT": [("r",)]}, rowcount=2)
    monkeypatch.setattr(db, "get_pool", lambda: FakePool(conn))
    r = w.alloc_delete(ME, "S", [["2026-10-07", 12, 1], ["2026-10-07", 12, 2]], None)
    assert r["deleted"] == 2
    dele = [s for s, _ in conn.log if s.startswith("DELETE")][0]
    assert "ATTR1 = :m" in dele and "NVL(CNFM_YN, 'N') = 'N'" in dele and "DELV_INDC_SEQ IS NULL" in dele


def test_fill_shortage_and_setting_check(monkeypatch):
    """창고 부족 → RT 채우기 · 자동 RT 설정 점검 (DB 없이)"""
    from app import stock_rt as rt
    from app import wh_alloc

    shops = {sid: {"shopId": sid, "shopNm": sid, "team": "C62010", "normal": True, "attr2": None, "type": "C0041", "moBrd": "S",
                   "rt": {"grp": "G1", "reqAble": None, "reqAbleYn": "Y", "asign": 0 if sid == "S1" else 2, "minRetain": 0, "fDays": 0, "lDays": 0}}
             for sid in ("R1", "S1", "S2")}
    monkeypatch.setattr(sc, "shops", lambda: shops)
    monkeypatch.setattr(sc, "base_grade_group", lambda b: "GG")
    monkeypatch.setattr(sc, "grade_shops", lambda g: {s: {} for s in shops})
    monkeypatch.setattr(sc, "controls", lambda b, d=None: sc.Controls())
    monkeypatch.setattr(sc, "style_info", lambda p: {x: {"styleNm": "자켓"} for x in p})
    monkeypatch.setattr(sc, "team_names", lambda: {"C62010": "쉬즈1팀"})
    short = {"shopId": "R1", "prdtCd": "P1", "colorCd": "BK", "sizeCd": "55", "fq": 1, "sq": 1, "ask": 0, "need": 2, "short": 2, "ctl": False}
    monkeypatch.setattr(wh_alloc, "recommend", lambda **k: {"brand": "S", "asOf": "x", "wh": "IN", "from": "a", "to": "b", "shortRows": [short]})
    monkeypatch.setattr(rt, "_stock", lambda pcs, ym: [("S1", "P1", "BK", "55", 3), ("S2", "P1", "BK", "55", 1)])
    res = {"moving": {}, "pending": {}, "asigned": {}, "asignedSku": set(), "shopReq": {}, "requested": {}, "instrOut": {}, "instrIn": {}}
    monkeypatch.setattr(rt, "_reserved", lambda b, td: res)
    monkeypatch.setattr(rt, "_prdt_base", lambda b, keys: {k: ("20250101", None, "20260901", 5, 0, 0, 2, 0) for k in keys})
    d = rt.fill_shortage({"brand": "S"}, refresh=True)
    assert d["summary"]["recQty"] == 2 and all(r["why"] == "창고 부족" and r["toShopId"] == "R1" for r in d["rows"])
    res["instrIn"] = {("R1", "P1", "BK", "55"): 2}          # 이미 2장 들어올 예정이면 채울 게 없음
    d = rt.fill_shortage({"brand": "S"}, refresh=True)
    assert d["rows"] == [] and d["summary"]["skipped"]["incoming"] == 1

    from app import db

    rows = [{"no": 1, "fromShopId": "S1", "toShopId": "R1", "qty": 2, "toFailCnt": 1}, {"no": 2, "fromShopId": "S2", "toShopId": "R2", "qty": 1, "toFailCnt": 0}]
    monkeypatch.setattr(rt, "recommend", lambda **k: {"brand": "S", "brandNm": "쉬즈미스", "from": "2026-10-01", "to": "2026-10-07", "asOf": "x",
                                                      "rows": rows, "summary": {"recQty": 3, "failRequests": 1, "failFilled": 1}})
    monkeypatch.setattr(db, "query", lambda sql, b=None, arraysize=0: ([], [("S2", 7)]))
    c = rt.setting_check({"brand": "S", "limits": True})
    by = {r["shopId"]: r for r in c["rows"]}
    assert by["S1"]["blocked"] and by["S1"]["suggest"] == 1 and by["S2"]["suggest"] == 2 and by["S2"]["status"] == "적정"
    assert c["rows"][0]["shopId"] == "S1" and c["summary"]["blockedShops"] == 1 and c["summary"]["blockedQty"] == 2 and c["days"] == 7


def test_open_screen_tool_makes_card_not_navigation(monkeypatch):
    from app import chat_tools_stock as ts

    monkeypatch.setattr(sc, "code_names", lambda p: {"C0074": "겨울"})
    monkeypatch.setattr(sc, "team_names", lambda: {"C62030": "리스트3팀"})
    out = ts.run("open_stock_rt_screen", {"brand": "리스트", "seasons": ["겨울"], "date_from": TODAY, "date_to": TODAY, "prdt_cd": "twk",
                                          "teams": ["리스트3팀"], "view": "unfilled"}, allowed=None)
    a = out["action"]
    assert a["actionKind"] == "open_stock" and out["result"]["opened"] is False
    p = a["items"][0]
    assert p["tab"] == "rt" and p["brand"] == "T" and p["view"] == "unfilled"
    assert p["cond"] == {"dateFrom": f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:]}", "dateTo": f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:]}",
                         "seasons": ["C0074"], "teams": ["C62030"], "prdt": "TWK"}
    assert any("겨울" in x for x in a["lines"])
    with pytest.raises(ts.StockToolError):
        ts.run("open_stock_rt_screen", {"tab": "alloc", "view": "unfilled"}, allowed=None)     # 배분 탭에 없는 보기
    with pytest.raises(ts.StockToolError):
        ts.run("open_stock_rt_screen", {"brand": "쉬즈미스"}, allowed=["리스트"])                # 브랜드 권한
