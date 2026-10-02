"""AI 도구 권한 · 판매 도구 입력 검증 · 실사계획 입력 검증 · 비용 계산 · 로그 조회."""
import pytest
from fastapi import HTTPException

from app import chat_tools as ct
from app import invt_plan as ip
from app import logs, usage


# ----------------------------------------------------------------------------
# AI 도구: 메뉴 권한에 따라 제공/실행
# ----------------------------------------------------------------------------
def _names(pages):
    return {t["name"] for t in ct.tools_for({"pages": pages})}


def test_tools_follow_menu_permissions():
    assert _names([]) == set()
    assert _names(["dashboard"]) == {"list_collection_dates", "aggregate_prices", "search_price_rows", "get_product_insight"}
    assert _names(["sale_monthly"]) == {"get_sales_dashboard", "sum_sales_shop_month", "aggregate_sales", "search_sales", "search_shops",
                                        "get_season_progress", "get_product_insight", "find_sale_heavy_shops"}
    assert _names(["sale_dashboard"]) == {"get_sales_dashboard", "sum_sales_shop_month", "search_shops",  # 판매 행 조회 도구는 없음
                                          "get_season_progress", "get_product_insight", "find_sale_heavy_shops"}
    assert _names(["invt_plan"]) == {"aggregate_invt_plans", "search_invt_plans", "search_shops"}
    assert len(_names(["detail", "sale_monthly", "invt_plan"])) == 14  # 판매 + 온라인 가격이면 온라인 할인 주의 도구까지


@pytest.mark.parametrize("name,inp", [
    ("aggregate_sales", {"ym_from": "202608", "ym_to": "202608"}),
    ("search_invt_plans", {}),
    ("aggregate_prices", {"date_from": "20260901", "date_to": "20260901"}),
])
def test_run_tool_rechecks_permission(name, inp):
    with pytest.raises(ct.ToolInputError, match="권한"):
        ct.run_tool(name, inp, {"pages": ["admin"]})


@pytest.mark.parametrize("inp,msg", [
    ({}, "YYYYMM"),
    ({"ym_from": "202608", "ym_to": "202607"}, "늦습니다"),
    ({"ym_from": "202308", "ym_to": "202608"}, "36개월"),
    ({"ym_from": "202608", "ym_to": "202608", "seasons": ["장마"]}, "seasons"),
    ({"ym_from": "202608", "ym_to": "202608", "group_by": ["BRAND"]}, "group_by"),
    ({"ym_from": "202608", "ym_to": "202608", "metrics": ["PROFIT"]}, "metrics"),
    ({"ym_from": "202608", "ym_to": "202608", "online_sale": "X"}, "online_sale"),
])
def test_sale_tool_validates_before_query(inp, msg, monkeypatch):
    monkeypatch.setattr(ct.sale.db, "query", lambda *a, **k: pytest.fail("검증 실패 입력으로 DB 를 조회하면 안 됨"))
    monkeypatch.setattr(ct.sale.db, "query_dicts", lambda *a, **k: pytest.fail("검증 실패 입력으로 DB 를 조회하면 안 됨"))
    with pytest.raises(ct.ToolInputError, match=msg):
        ct.run_tool("aggregate_sales", inp, {"pages": ["sale_monthly"]})


def test_sale_tool_default_metrics_use_index_columns_only(monkeypatch):
    captured = {}

    def query_dicts(sql, params=None):
        captured["sql"] = sql
        return [{"MAKE_YYMM": "202608", "ROW_CNT": 1, "SHOP_CNT": 1, "QTY_SUM": 2, "REAL_SALE_AMT_SUM": 3}]

    monkeypatch.setattr(ct.sale.db, "query_dicts", query_dicts)
    out = ct.run_tool("aggregate_sales", {"ym_from": "202608", "ym_to": "202608", "group_by": ["MAKE_YYMM"]},
                      {"pages": ["sale_monthly"]})
    sql = captured["sql"]
    for col in ("DSCT_AMT", "PRODUCT_COST2", "FIRST_PRICE", "SHOP_NM", "PRDT_CD"):
        assert col not in sql  # 기본 지표는 (MAKE_YYMM, SHOP_ID, REAL_SALE_AMT, QTY) 인덱스 컬럼만
    assert [c["key"] for c in out["table"]["columns"]] == ["MAKE_YYMM", "ROW_CNT", "SHOP_CNT", "QTY_SUM", "REAL_SALE_AMT_SUM"]


# ----------------------------------------------------------------------------
# 실사계획 입력 검증
# ----------------------------------------------------------------------------
@pytest.fixture
def utf8(monkeypatch):
    monkeypatch.setattr(ip, "_charset", "AL32UTF8")


def test_invt_clean_accepts_valid(utf8):
    v = ip._clean({"shopId": " S31019 ", "prevInvtType": "폐점", "invtPlanDt": "2026-10-01", "baseFee": "150,000",
                   "twiceYearYn": True, "rmk": "가" * 66}, partial=False)
    assert v["SHOP_ID"] == "S31019" and v["PREV_INVT_TYPE"] == "폐점" and v["INVT_PLAN_DT"] == "20261001"
    assert v["BASE_FEE"] == 150000 and v["TWICE_YEAR_YN"] == "Y"


@pytest.mark.parametrize("body", [
    {"shopId": "S1", "rmk": "가" * 67},            # 한글 67자 = 201바이트 > 200
    {"shopId": "S1", "prevInvtType": "기타"},
    {"shopId": "S1", "invtPlanDt": "2026-02-30"},
    {"shopId": "S1", "baseFee": "십만원"},
    {"shopId": "S1", "areaNm": "서울시"},
    {"prevInvtType": "정기"},                     # 신규 등록인데 매장코드 없음
])
def test_invt_clean_rejects(utf8, body):
    with pytest.raises(HTTPException):
        ip._clean(body, partial=False)


# ----------------------------------------------------------------------------
# AI 비용 계산
# ----------------------------------------------------------------------------
def test_cost_calculation():
    # opus-5: 입력 $5, 출력 $25, 캐시 읽기 $0.5, 캐시 쓰기 = 입력 × 1.25 (1M 토큰당)
    assert usage.cost_of("claude-opus-5", 1_000_000, 0, 0, 0) == pytest.approx(5.0)
    assert usage.cost_of("claude-opus-5", 0, 1_000_000, 0, 0) == pytest.approx(25.0)
    assert usage.cost_of("claude-opus-5", 0, 0, 1_000_000, 1_000_000) == pytest.approx(0.5 + 6.25)


def test_price_lookup_prefers_most_specific_model():
    assert usage.price_for("claude-opus-5-5") == usage.PRICES["claude-opus-5-5"]
    assert usage.price_for("claude-opus-5-20260101") == usage.PRICES["claude-opus-5"]
    assert usage.price_for("unknown-model") == usage.DEFAULT_PRICE
    assert usage.price_for(None) == usage.DEFAULT_PRICE


# ----------------------------------------------------------------------------
# 서버 로그 조회
# ----------------------------------------------------------------------------
def test_log_tail_groups_multiline_and_filters(tmp_path, monkeypatch):
    log = tmp_path / "app.log"
    log.write_text(
        "2026-09-29 10:00:00 INFO  erp.request  user=1 GET /api/a 200 5ms\n"
        "2026-09-29 10:00:01 WARNING erp.sql      느린 query 4.00s | binds=['f'] | SELECT 1\n"
        "2026-09-29 10:00:02 ERROR erp.request  처리 실패 user=2 GET /api/b\n"
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1\n"
        "ValueError: boom\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(logs, "APP_LOG", log)
    all_ = logs.tail()
    assert [e["category"] for e in all_] == ["request", "sql", "request"]  # 최신순
    assert "ValueError: boom" in all_[0]["message"]  # 스택이 한 항목으로 묶임
    assert [e["level"] for e in logs.tail("WARNING")] == ["ERROR", "WARNING"]
    assert len(logs.tail(category="sql")) == 1
    assert len(logs.tail(q="/api/a")) == 1


def test_sql_text_is_compact_and_truncated():
    assert logs.sql_text("SELECT  *\n  FROM   T") == "SELECT * FROM T"
    assert logs.sql_text("X" * 500, limit=10).endswith("…")


# ----------------------------------------------------------------------------
# 매장 매출 누계 구간 (월 목록으로 조회 — BETWEEN 대비 100배 이상 빠름)
# ----------------------------------------------------------------------------
def test_ytd_months():
    from datetime import date

    cur, prev = ip._ytd_months(date(2026, 9, 29))
    assert cur == [f"2026{m:02d}" for m in range(1, 9)] and prev == [f"2025{m:02d}" for m in range(1, 9)]
    assert ip._ytd_months(date(2026, 2, 3)) == (["202601"], ["202501"])
    assert ip._ytd_months(date(2026, 1, 15)) == ([], [])  # 1월에는 당년 누계 구간이 없음 (기존 SQL 과 동일)


def test_sales_ytd_uses_month_list(monkeypatch):
    seen = {}

    def query(sql, params=None, arraysize=5000):
        seen["sql"], seen["params"] = sql, params
        return [], [("202601", 100), ("202501", 40), ("202502", None)]

    monkeypatch.setattr(ip, "_ytd_months", lambda: (["202601", "202602"], ["202501", "202502"]))
    monkeypatch.setattr(ip.db, "query", query)
    assert ip._sales_ytd("A11001") == [{"CURR_SALE": 100, "PREV_SALE": 40}]
    assert "MAKE_YYMM IN (:m0, :m1, :m2, :m3)" in seen["sql"] and "BETWEEN" not in seen["sql"]


# ----------------------------------------------------------------------------
# 월×매장 사전 집계 뷰 도구: 뷰/원본 선택, 입력 검증
# ----------------------------------------------------------------------------
@pytest.fixture
def mv(monkeypatch):
    from app import chat_tools_sale as cts

    state = {"usable": True, "staleness": "FRESH", "last_refresh": None, "mv_max": "202608", "base_max": "202608"}
    seen = {}

    def query_dicts(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        return [{"MAKE_YYMM": "202608", "REAL_SALE_AMT_SUM": 10}]

    monkeypatch.setattr(cts, "mv_state", lambda: state)
    monkeypatch.setattr(cts.db, "query_dicts", query_dicts)
    return cts, state, seen


def _mv_run(inp):
    return ct.run_tool("sum_sales_shop_month", {"ym_from": "202601", "ym_to": "202608", **inp}, {"pages": ["sale_monthly"]})


def test_mv_tool_uses_view_when_fresh(mv):
    cts, _, seen = mv
    r = _mv_run({"group_by": ["MAKE_YYMM"], "metrics": ["REAL_SALE_AMT_SUM"]})
    assert cts.MV_NAME in seen["sql"] and "SUM(TOTAL_SALE_AMT)" in seen["sql"]
    assert r["result"]["source"].startswith("사전 집계 뷰")


@pytest.mark.parametrize("change", [{"usable": False}, {"mv_max": "202607"}])
def test_mv_tool_falls_back_to_base_table(mv, change):
    cts, state, seen = mv
    state.update(change)  # 뷰가 오래됐거나(STALE) 요청 기간의 최근 월이 아직 뷰에 없음
    r = _mv_run({"group_by": ["MAKE_YYMM"], "metrics": ["REAL_SALE_AMT_SUM"]})
    assert "FROM T_CLOSE_SALE_BASE" in seen["sql"] and "SUM(REAL_SALE_AMT)" in seen["sql"]
    assert r["result"]["source"].startswith("원본 테이블")


def test_mv_tool_period_before_view_max_still_uses_view(mv):
    cts, state, seen = mv
    state.update({"mv_max": "202607", "base_max": "202608"})
    ct.run_tool("sum_sales_shop_month", {"ym_from": "202601", "ym_to": "202606"}, {"pages": ["sale_monthly"]})
    assert cts.MV_NAME in seen["sql"]  # 요청 기간이 뷰 범위 안이면 뷰 사용


@pytest.mark.parametrize("inp,msg", [
    ({"group_by": ["SESS_NM"]}, "aggregate_sales"),
    ({"metrics": ["PRDT_CNT"]}, "metrics"),  # 상품 수는 뷰로 계산 불가 → aggregate_sales
    ({"ym_from": "201601"}, "120개월"),
    ({"order_by": "DSCT_AMT_SUM", "metrics": ["QTY_SUM"]}, "order_by"),
])
def test_mv_tool_validation(mv, inp, msg):
    with pytest.raises(ct.ToolInputError, match=msg):
        _mv_run(inp)


def test_mv_tool_listed_first_for_simple_totals():
    names = [t["name"] for t in ct.tools_for({"pages": ["sale_monthly"]})]
    assert names.index("get_sales_dashboard") < names.index("sum_sales_shop_month") < names.index("aggregate_sales")


def test_mv_cost_metric_uses_view_only_with_cost_column(mv):
    cts, state, seen = mv
    _mv_run({"metrics": ["COST_AMT_SUM"]})
    assert "FROM T_CLOSE_SALE_BASE" in seen["sql"] and "SUM(PRODUCT_COST2 * QTY)" in seen["sql"]  # 뷰에 컬럼 없음 → 원본
    state["columns"] = {"TOTAL_COST_AMT"}
    _mv_run({"metrics": ["COST_AMT_SUM"]})
    assert cts.MV_NAME in seen["sql"] and "SUM(TOTAL_COST_AMT)" in seen["sql"]
    assert "TOTAL_PRODUCT_COST2" not in seen["sql"]  # 단가 단순 합은 쓰지 않음
