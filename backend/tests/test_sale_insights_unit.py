"""시즌 판매 진척 · 온라인 할인 주의 상품 · 판매 현황 미리 계산 · 문의·신고. DB 는 가짜."""
from datetime import datetime

import pytest

from app import feedback as fb
from app import online_alerts as oa
from app import prewarm
from app import sale_dashboard as sd
from app import sale_products as sp
from app import sale_season as ss

M = 1_000_000


@pytest.fixture
def months(monkeypatch):
    monkeypatch.setattr(sd, "available_months", lambda: ["202609", "202608", "202607"])
    monkeypatch.setattr(sd, "brand_teams", lambda: {"리스트": ["리스트1팀"], "쉬즈미스": ["쉬즈1팀"]})
    ss.clear_cache()
    yield
    ss.clear_cache()


# (기획년도, 시즌, 월, 금액, 수량, 할인)
SEASON_ROWS = [
    ("2026", "가을", "202606", 1 * M, 1, 0), ("2026", "가을", "202607", 10 * M, 10, 0), ("2026", "가을", "202608", 40 * M, 40, 0),
    ("2026", "가을", "202609", 70 * M, 70, 10 * M),
    ("2025", "가을", "202507", 10 * M, 10, 0), ("2025", "가을", "202508", 30 * M, 30, 0), ("2025", "가을", "202509", 60 * M, 60, 0),
    ("2025", "가을", "202510", 100 * M, 100, 0),
    ("2026", "여름", "202609", 5 * M, 5, 0),
    (None, None, "202609", 999 * M, 1, 0),  # 기획년도 없는 행은 무시
]


def test_season_progress_default_and_curve(months, monkeypatch):
    seen = []
    monkeypatch.setattr(sp, "mv_state", lambda: {"exists": True, "usable": True, "mv_max": "202609", "staleness": "FRESH"})

    def query(sql, params=None):
        seen.append(sql)
        return [], SEASON_ROWS
    monkeypatch.setattr(ss.db, "query", query)
    d = ss.progress()
    assert sp.MV_NAME in seen[0] and d["source"] == "사전 집계 뷰"
    assert (d["planYy"], d["season"]) == ("2026", "가을")  # 기준 월에 가장 많이 팔린 시즌
    assert d["startLabel"] == "2026-06" and d["step"] == 4
    k = d["kpi"]
    assert k["amt"] == 121 * M and k["prevSameAmt"] == 100 * M and k["change"] == 21.0
    assert k["prevFinalAmt"] == 200 * M and k["progress"] == 60.5 and k["prevProgressSame"] == 50.0
    assert k["dsctRate"] == 7.6  # 10 / (121 + 10)
    last = d["months"][-1]
    assert last["ym"] == "202610" and last["cum"] is None and last["prevCum"] == 200 * M  # 전년 선은 끝까지
    assert [o["season"] for o in d["options"]][:2] == ["여름", "가을"]  # 계절 순서
    assert ss.progress(plan_yy="2026", season="여름")["kpi"]["amt"] == 5 * M  # 캐시 재사용
    assert len(seen) == 1
    with pytest.raises(Exception, match="선택할 수 있는 시즌: 2026 여름, 2026 가을"):
        ss.progress(plan_yy="2019", season="봄")


def test_season_falls_back_to_base_with_team_filter(months, monkeypatch):
    seen = []
    monkeypatch.setattr(sp, "mv_state", lambda: {"exists": False, "usable": False, "mv_max": None, "staleness": None})
    monkeypatch.setattr(ss.db, "query", lambda sql, params=None: seen.append((sql, params)) or ([], SEASON_ROWS))
    d = ss.progress(brand="리스트")
    assert d["source"] == "원본" and "T_CLOSE_SALE_BASE" in seen[0][0] and "TEAM_CD IN" in seen[0][0]
    assert "리스트1팀" in seen[0][1].values()


def test_online_alerts_flags_rises(monkeypatch):
    top = [{"prdtCd": c, "itemNm": "자켓", "prdtGrpNm": "우븐", "amt": a, "qty": 1, "dsctRate": 1.0}
           for c, a in (("A", 300 * M), ("B", 200 * M), ("C", 100 * M), ("D", 50 * M))]
    monkeypatch.setattr(sp, "analyze", lambda *a, **k: {"period": "2026-09", "brand": None, "_top": top})
    # (품번, 최근7일, 이전4주, 최저가, 사이트, 건수7, 건수28, 마지막일)
    rows = [("A", 12.0, 11.0, 1000, 5, 10, 40, "20261001"), ("B", 15.0, 10.0, 900, 3, 10, 40, "20261001"),
            ("C", 20.0, None, 800, 2, 5, 0, "20261001")]
    monkeypatch.setattr(oa.db, "query", lambda sql, params=None: ([], rows))
    oa.clear_cache()
    d = oa.alerts(today=datetime(2026, 10, 2))
    assert d["alertCount"] == 2 and d["withOnline"] == 3 and d["total"] == 4
    assert [(r["prdtCd"], r["flag"]) for r in d["rows"][:2]] == [("B", "rise"), ("C", "new")]
    b = d["rows"][0]
    assert b["rank"] == 2 and b["diff"] == 5.0
    assert d["recentFrom"] == "2026-09-26" and d["baseFrom"] == "2026-08-29"
    assert next(r for r in d["rows"] if r["prdtCd"] == "D")["online"] is None


def test_prewarm_scopes_and_tick(monkeypatch):
    from app import auth, userdb

    users = [{"id": "a", "active": True, "pages": ["sale_dashboard"], "brands": None},
             {"id": "b", "active": True, "pages": ["sale_dashboard"], "brands": ["리스트"]},
             {"id": "c", "active": True, "pages": ["sale_dashboard"], "brands": ["리스트"]},
             {"id": "d", "active": True, "pages": ["detail"], "brands": ["쉬즈미스"]},
             {"id": "e", "active": False, "pages": ["sale_dashboard"], "brands": ["시스티나"]}]
    monkeypatch.setattr(userdb, "list_users", lambda: users)
    monkeypatch.setattr(userdb, "get_settings", lambda: {})
    monkeypatch.setattr(auth, "effective", lambda u, s=None: u)
    assert prewarm.scopes() == [None, ["리스트"]]

    calls = []
    monkeypatch.setattr(sd, "dashboard", lambda **k: calls.append(("d", k["allowed"], k["ttl"])))
    monkeypatch.setattr(sp, "analyze", lambda **k: calls.append(("p", k["allowed"], k["ttl"])))
    monkeypatch.setattr(ss, "progress", lambda **k: calls.append(("s", k["allowed"], k["ttl"])))
    from app import sale_mix

    monkeypatch.setattr(sale_mix, "heavy_shops", lambda **k: calls.append(("m", k["allowed"], k["ttl"])))
    from app import stock_aging

    aging = []
    monkeypatch.setattr(stock_aging, "warm_async", lambda: aging.append(1))   # 실제 재고 기준 읽기(운영 DB 수 분) 대신
    sig = {"v": ("FRESH", "t1")}
    monkeypatch.setattr(prewarm, "signature", lambda: sig["v"])
    prewarm._state.update({"signature": None, "day": None})
    assert prewarm.tick(datetime(2026, 10, 2, 6, 0)) == "서버 시작"
    assert len(calls) == 8 and calls[0] == ("d", None, prewarm.WARM_TTL)
    assert prewarm.tick(datetime(2026, 10, 2, 6, 30)) is None  # 7시 전 · 변경 없음
    assert prewarm.tick(datetime(2026, 10, 2, 7, 5)) == "아침 계산" and aging == [1]
    assert prewarm.tick(datetime(2026, 10, 2, 9, 0)) is None  # 그날은 한 번
    cleared = []
    monkeypatch.setattr(sd, "clear_cache", lambda: cleared.append("d"))
    sig["v"] = ("STALE", "t1")
    assert prewarm.tick(datetime(2026, 10, 2, 9, 30)) == "데이터 변경" and cleared == ["d"]
    assert prewarm.state()["running"] is False


@pytest.fixture
def local_fb(temp_store, monkeypatch):
    monkeypatch.setattr(fb, "use_oracle", lambda: False)
    return temp_store


def test_feedback_create_mine_answer(local_fb):
    me = {"id": "170046", "name": "홍길동"}
    f = fb.create(me, {"type": "bug", "content": "판매 현황 숫자가 이상해요", "page": "sale_dashboard",
                       "context": {"conditions": {"ym": "202609"}, "errors": [{"message": "x" * 5000}]}})
    assert f["status"] == "NEW" and f["typeLabel"] == "오류" and f["userName"] == "홍길동"
    assert f["context"]["conditions"] == {"ym": "202609"} and f["context"].get("_trimmed")  # 큰 항목은 잘라냄
    fb.create({"id": "250016", "name": "나"}, {"type": "REQ", "content": "요청입니다"})
    assert [x["id"] for x in fb.mine("170046")] == [f["id"]]
    r = fb.answer({"id": "admin"}, f["id"], {"status": "DONE", "answer": "확인했습니다"})
    assert (r["status"], r["answer"], r["answerBy"]) == ("DONE", "확인했습니다", "admin") and r["answeredAt"]
    r2 = fb.answer({"id": "admin2"}, f["id"], {"status": "DOING"})  # 답변 그대로면 답변자 유지
    assert r2["answerBy"] == "admin" and r2["status"] == "DOING"
    lst = fb.list_all("DOING")
    assert [x["id"] for x in lst["rows"]] == [f["id"]] and lst["counts"] == {"NEW": 1, "DOING": 1, "DONE": 0}
    assert fb.open_count() == 2
    with pytest.raises(Exception):
        fb.create(me, {"type": "XX", "content": "내용"})
    with pytest.raises(Exception):
        fb.create(me, {"type": "ASK", "content": " "})


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20



def test_feedback_images(local_fb, monkeypatch):
    import base64

    me = {"id": "170046", "name": "홍길동", "role": "USER"}
    data = "data:image/png;base64," + base64.b64encode(PNG).decode()
    f = fb.create(me, {"type": "BUG", "content": "캡처 첨부", "images": [{"name": "../../a.png", "data": data},
                                                                    {"name": "b.png", "data": base64.b64encode(PNG).decode()}]})
    assert [(x["no"], x["name"], x["type"], x["size"]) for x in f["files"]] == [(1, "a.png", "image/png", 28), (2, "b.png", "image/png", 28)]
    assert fb.get_file(f["id"], 2, me) == (PNG, "image/png", "b.png")
    assert fb.get_file(f["id"], 1, {"id": "admin", "role": "ADMIN"})[0] == PNG
    with pytest.raises(Exception):  # 다른 사용자
        fb.get_file(f["id"], 1, {"id": "250016", "role": "USER"})
    with pytest.raises(Exception, match="최대 3개"):
        fb.create(me, {"type": "BUG", "content": "내용", "images": [{"data": data}] * 4})
    with pytest.raises(Exception, match="이미지만"):  # 확장자가 아니라 내용으로 확인
        fb.create(me, {"type": "BUG", "content": "내용", "images": [{"name": "x.png", "data": base64.b64encode(b"MZ\x90\x00evil").decode()}]})
    monkeypatch.setattr(fb, "MAX_FILE_BYTES", 10)
    with pytest.raises(Exception, match="까지입니다"):
        fb.create(me, {"type": "BUG", "content": "내용", "images": [{"data": data}]})
    assert len(fb.mine("170046")) == 1  # 실패한 접수는 남지 않음


def test_feedback_long_text_limit(local_fb, monkeypatch):
    me = {"id": "1", "name": "가"}
    assert len(fb.create(me, {"type": "ASK", "content": "가" * 5000})["content"]) == 5000  # 한글 4000바이트 넘어도 됨
    monkeypatch.setattr(fb, "_status", lambda: (True, False))  # Oracle 이지만 아직 VARCHAR2 면 짧게 제한
    assert fb.max_text() == fb.MAX_TEXT_VARCHAR


def test_insight_tools_registry_and_permissions(monkeypatch):
    from app import chat_tools as ct
    from app import chat_tools_insight as ins
    from app import ai_tools

    monkeypatch.setattr(ai_tools, "snapshot", lambda: {"builtin": {}, "custom": []})
    names = lambda me: sorted(t["name"] for t in ct.tools_for(me) if t["name"] in ct._INSIGHT_TOOL_NAMES)  # noqa: E731
    assert names({"pages": ["sale_dashboard", "dashboard"]}) == ["find_online_discount_alerts", "find_sale_heavy_shops", "get_product_insight", "get_season_progress"]
    assert names({"pages": ["sale_dashboard"]}) == ["find_sale_heavy_shops", "get_product_insight", "get_season_progress"]
    assert names({"pages": ["detail"]}) == ["get_product_insight"]
    assert names({"pages": ["invt_plan"]}) == []
    with pytest.raises(ct.ToolInputError, match="모두 있어야"):
        ct.run_tool("find_online_discount_alerts", {}, {"pages": ["sale_dashboard"]})
    seen = {}
    monkeypatch.setattr(ins.ds, "product_online", lambda cd: seen.setdefault("online", cd) and {"title": "t", "lastDt": "20261001", "daily": [], "malls": []})
    out = ct.run_tool("get_product_insight", {"prdt_cd": "twwjkq72020"}, {"pages": ["detail"]})
    assert seen["online"] == "TWWJKQ72020" and "sales" not in out["result"]
    assert any("판매 메뉴 권한이 없어" in n for n in out["result"]["notes"])
    with pytest.raises(ct.ToolInputError, match="함께"):
        ct.run_tool("get_season_progress", {"plan_yy": "2026"}, {"pages": ["sale_dashboard"]})
    captured = {}
    monkeypatch.setattr(ins.sale_season, "progress", lambda *a: captured.setdefault("a", a) and {"planYy": None, "toLabel": "2026-09"})
    ct.run_tool("get_season_progress", {"season": "가을", "plan_yy": "2026", "brand": "리스트"}, {"pages": ["sale_dashboard"], "brands": ["리스트"]})
    assert captured["a"] == (None, "리스트", ["리스트"], "2026", "가을")
