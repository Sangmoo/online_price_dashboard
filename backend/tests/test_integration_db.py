"""통합 테스트: 실제 Oracle 조회 결과 검증 (조회만, 업무 데이터 변경 없음). Oracle 접속이 안 되면 건너뜀."""
import secrets
import time

import pytest

pytestmark = pytest.mark.db

COND = ("2026-07", "2026-08", "A11001,A31046", "2025,2026", "여름,여름기획")


@pytest.fixture(autouse=True)
def _need_oracle(oracle):
    from app import sale_monthly as sm

    sm._stats_cache.clear()


def test_paging_equals_single_global_query(oracle):
    from app import sale_monthly as sm

    where, p = sm._where(*COND)
    expected = [sm._row(r) for r in oracle.query(f"SELECT {sm.COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} {sm.ORDER_SQL}", p)[1]]
    assert expected, "테스트 조건에 데이터가 없습니다"
    got, page = [], 1
    while True:
        rows = sm.search(*COND, page=page, with_total=page == 1)["rows"]
        if not rows:
            break
        got += rows
        page += 1
    assert got == expected


def test_summary_totals_match_direct_sum(oracle):
    from app import sale_monthly as sm

    where, p = sm._where(*COND)
    qty, amt, dsct = oracle.query(f"SELECT SUM(QTY), SUM(REAL_SALE_AMT), SUM(DSCT_AMT) FROM T_CLOSE_SALE_BASE WHERE {where}", p)[1][0]
    for dim in ("month", "season"):
        r = sm.summary(*COND, dim)
        assert (r["total"]["qty"], r["total"]["amt"], r["total"]["dsct"]) == (int(qty), int(amt), int(dsct))
        assert sum(x["amt"] for x in r["rows"]) == int(amt)
    assert sm.dsct_total(*COND)["dsctAmt"] == int(dsct)


def test_shop_trend_last_12_months(oracle):
    from app import sale_monthly as sm

    t = sm.shop_trend("A11001")
    assert len(t["months"]) == 12 and t["months"][-1]["ym"] == t["to"]
    assert t["total"]["amt"] == sum(m["amt"] for m in t["months"])


def test_ai_sale_tool_matches_screen_summary(oracle):
    from app import chat_tools as ct
    from app import sale_monthly as sm

    out = ct.run_tool("aggregate_sales", {"ym_from": "202607", "ym_to": "202608", "shop_ids": ["A11001", "A31046"],
                                          "plan_yys": ["2025", "2026"], "seasons": ["여름", "여름기획"]},
                      {"pages": ["sale_monthly"]})
    row = out["result"]["rows"][0]
    s = sm.search(*COND, page=1, with_total=True)["summary"]
    assert (row["ROW_CNT"], row["QTY_SUM"], row["REAL_SALE_AMT_SUM"]) == (s["rows"], s["qty"], s["realSaleAmt"])


# ----------------------------------------------------------------------------
# API (FastAPI TestClient) — 최고 관리자 임시 세션으로 호출하고 끝나면 삭제
# ----------------------------------------------------------------------------
@pytest.fixture
def client(oracle):
    from fastapi.testclient import TestClient

    from app import auth, main, store

    token = secrets.token_urlsafe(24)
    now = time.time()
    store.execute("INSERT INTO sessions(token,sid,usr_id,created_at,last_seen,expires_at,ip,user_agent) VALUES(?,?,?,?,?,?,?,?)",
                  (token, secrets.token_hex(8), "250016", now, now, now + 600, "pytest", "pytest"))
    c = TestClient(main.app)
    try:
        yield c, token, auth.SESSION_COOKIE
    finally:
        store.execute("DELETE FROM sessions WHERE token=?", (token,))


def test_api_requires_login(client):
    c, _, _ = client
    c.cookies.clear()
    r = c.get("/api/sale-monthly/options")
    assert r.status_code == 401


def test_api_sale_endpoints(client):
    c, token, cookie = client
    c.cookies.set(cookie, token)
    assert c.get("/api/sale-monthly/options").json()["maxMonths"] == 36
    q = {"ymFrom": "2026-08", "ymTo": "2026-08", "shops": "A11001"}
    r = c.get("/api/sale-monthly", params={**q, "page": 1}).json()
    assert r["total"] == r["summary"]["rows"] and len(r["rows"]) <= 100
    assert c.get("/api/sale-monthly/summary", params={**q, "dim": "brand"}).status_code == 400
    assert c.get("/api/sale-monthly/summary", params={**q, "dim": "season"}).status_code == 200
    r = c.get("/api/admin/logs", params={"level": "WARNING"})
    assert r.status_code == 200 and "logs" in r.json()


def test_mv_tool_matches_base_table(oracle):
    """사전 집계 뷰 도구 결과 = 원본 테이블 직접 집계 (NO_REWRITE 로 뷰 자동 재작성 없이 계산)."""
    from app import chat_tools as ct
    from app import chat_tools_sale as cts

    if not cts.mv_state()["usable"]:
        pytest.skip("집계 뷰가 없거나 최신이 아님")
    out = ct.run_tool("sum_sales_shop_month", {"ym_from": "202601", "ym_to": "202608", "group_by": ["TEAM_CD"],
                                               "order_by": "TEAM_CD", "order_dir": "asc", "limit": 200},
                      {"pages": ["sale_monthly"]})
    assert out["result"]["source"].startswith("사전 집계 뷰")
    base = oracle.query(
        "SELECT /*+ NO_REWRITE */ TEAM_CD, COUNT(*), COUNT(DISTINCT SHOP_ID), SUM(QTY), SUM(REAL_SALE_AMT), SUM(DSCT_AMT) "
        "FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM BETWEEN '202601' AND '202608' GROUP BY TEAM_CD ORDER BY TEAM_CD")[1]
    assert [tuple(r.values()) for r in out["result"]["rows"]] == [tuple(int(x) if not isinstance(x, str) else x for x in r) for r in base]
