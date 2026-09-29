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
    assert _names(["dashboard"]) == {"list_collection_dates", "aggregate_prices", "search_price_rows"}
    assert _names(["sale_monthly"]) == {"aggregate_sales", "search_sales"}
    assert _names(["invt_plan"]) == {"aggregate_invt_plans", "search_invt_plans"}
    assert len(_names(["detail", "sale_monthly", "invt_plan"])) == 7


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
