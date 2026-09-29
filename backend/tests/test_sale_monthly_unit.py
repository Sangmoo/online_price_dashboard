"""월별 매장별 판매 집계: 조건 검증, 월 계산, 월 단위 페이징, 요약(전년 비교). DB 는 가짜로 대체."""
import re

import pytest
from fastapi import HTTPException

from app import sale_monthly as sm

N_COLS = len(sm.COLUMNS)


@pytest.fixture(autouse=True)
def _clear_cache():
    sm._stats_cache.clear()
    yield
    sm._stats_cache.clear()


# ----------------------------------------------------------------------------
# 조건 검증
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("f,t,msg", [
    ("2026-13", "2026-13", "YYYY-MM"),
    ("202608", "2026-0", "YYYY-MM"),
    ("2026-08", "2026-07", "늦습니다"),
    ("2023-08", "2026-08", "최대 36개월"),  # 37개월
])
def test_where_rejects_bad_period(f, t, msg):
    with pytest.raises(HTTPException) as e:
        sm._where(f, t, None, None, None)
    assert msg in e.value.detail["message"]


def test_where_allows_36_months_and_builds_binds():
    where, p = sm._where("2023-09", "2026-08", "A11001, S31019", "2025,2026", "여름,여름기획")
    assert p["ym_from"] == "202309" and p["ym_to"] == "202608"
    assert "SHOP_ID IN (:shop0, :shop1)" in where and p["shop1"] == "S31019"
    assert "PLAN_YY IN (:yy0, :yy1)" in where
    assert "SUBSTRB(SESS_NM, 1, 100) IN (:sess0, :sess1)" in where  # 인덱스 IX_04 와 같은 식
    # 값은 모두 바인드로만 들어가고 SQL 문자열에는 들어가지 않는다 (SQL 인젝션 방지)
    assert "A11001" not in where and "여름" not in where


@pytest.mark.parametrize("kw", [
    {"shops": "TOOLONG7"},
    {"plan_yys": "26"},
    {"seasons": "장마"},
    {"shops": ",".join(f"S{i:05d}" for i in range(501))},
])
def test_where_rejects_bad_filters(kw):
    args = {"shops": None, "plan_yys": None, "seasons": None, **kw}
    with pytest.raises(HTTPException):
        sm._where("2026-08", "2026-08", args["shops"], args["plan_yys"], args["seasons"])


def test_season_order():
    assert sm.SEASONS == ["봄", "봄기획", "여름", "여름기획", "가을", "가을기획", "겨울", "겨울기획"]


def test_month_helpers():
    assert sm._month_list("202511", "202602") == ["202511", "202512", "202601", "202602"]
    assert sm._months("202309", "202608") == 36
    assert sm._shift_ym("202601", -12) == "202501"
    assert sm._shift_ym("202601", -1) == "202512"
    assert sm._shift_ym("202512", 1) == "202601"


# ----------------------------------------------------------------------------
# 월 단위 페이징: 월별 건수로 위치를 찾아 해당 월만 조회해도 전체 정렬 결과와 같아야 한다
# ----------------------------------------------------------------------------
def _fake_db(monkeypatch, counts: dict[str, int]):
    data = {ym: [(ym, f"{ym}-{i:04d}") + (None,) * (N_COLS - 2) for i in range(n)] for ym, n in counts.items()}
    calls = []

    def query(sql, params=None, arraysize=5000):
        calls.append(sql)
        if "GROUP BY MAKE_YYMM ORDER BY MAKE_YYMM" in sql:
            return ["MAKE_YYMM"], [(ym, n, n * 2, n * 1000) for ym, n in sorted(counts.items())
                                   if params["ym_from"] <= ym <= params["ym_to"]]
        if "MAKE_YYMM = :cur_ym" in sql:
            rows = data[params["cur_ym"]]
            return [], rows[params["lo"]:params["hi"]]
        raise AssertionError(f"예상하지 못한 SQL: {sql}")

    monkeypatch.setattr(sm.db, "query", query)
    return data, calls


def test_paging_matches_global_order(monkeypatch):
    counts = {"202601": 150, "202602": 30, "202603": 0, "202604": 125}
    data, calls = _fake_db(monkeypatch, counts)
    expected = [r[1] for ym in sorted(data) for r in data[ym]]
    got, page = [], 1
    while True:
        r = sm.search("2026-01", "2026-04", None, None, None, page, page == 1)
        if page == 1:
            assert r["total"] == 305 and r["summary"] == {"rows": 305, "qty": 610, "realSaleAmt": 305000}
        if not r["rows"]:
            break
        assert len(r["rows"]) == (100 if page < 4 else 5)
        got += [x["TEAM_CD"] for x in r["rows"]]  # 두 번째 컬럼에 순번을 넣어 둠
        page += 1
    assert got == expected
    # 월별 건수 조회는 캐시되어 페이지마다 다시 하지 않는다
    assert sum("GROUP BY MAKE_YYMM ORDER BY" in c for c in calls) == 1


def test_page_spanning_two_months(monkeypatch):
    _fake_db(monkeypatch, {"202601": 150, "202602": 80})
    r = sm.search("2026-01", "2026-02", None, None, None, 2, False)
    months = [x["MAKE_YYMM"] for x in r["rows"]]
    assert months.count("202601") == 50 and months.count("202602") == 50
    assert "summary" not in r


def test_page_beyond_end_is_empty(monkeypatch):
    _fake_db(monkeypatch, {"202601": 10})
    assert sm.search("2026-01", "2026-01", None, None, None, 5, False)["rows"] == []


# ----------------------------------------------------------------------------
# 요약 · 전년 비교
# ----------------------------------------------------------------------------
def test_summary_month_matches_previous_year(monkeypatch):
    seen = []

    def group(where, p, col):
        seen.append((p["ym_from"], p["ym_to"], {k: v for k, v in p.items() if k.startswith("yy")}))
        if p["ym_from"] == "202601":  # 당해
            return {"202601": (10, 100, 1_000_000, 50, 300_000), "202602": (10, 120, 1_500_000, 60, 600_000)}
        return {"202501": (9, 90, 800_000, 40, 280_000)}  # 전년 (2월 없음)

    monkeypatch.setattr(sm, "_group", group)
    r = sm.summary("2026-01", "2026-02", None, "2026", None, "month")
    assert seen[1][:2] == ("202501", "202502") and seen[1][2] == {"yy0": "2025"}  # 기간·기획년도 1년 앞당김
    jan, feb = r["rows"]
    assert (jan["label"], jan["prevAmt"], jan["growth"]) == ("2026-01", 800_000, 25.0)
    assert (feb["prevAmt"], feb["growth"]) == (0, None)  # 전년 값 없으면 증감 없음
    assert r["total"]["amt"] == 2_500_000 and r["total"]["prevAmt"] == 800_000
    assert jan["share"] == 40.0
    # 원가율 = 원가 / 실판금액: 1월 30.0% (전년 35.0% → -5.0%p), 합계 36.0%
    assert (jan["cost"], jan["costRate"], jan["prevCostRate"], jan["costRateDiff"]) == (300_000, 30.0, 35.0, -5.0)
    assert (feb["costRate"], feb["prevCostRate"], feb["costRateDiff"]) == (40.0, None, None)
    assert (r["total"]["cost"], r["total"]["costRate"], r["total"]["prevCostRate"]) == (900_000, 36.0, 35.0)


def test_summary_plan_year_and_season_keys(monkeypatch):
    def group(where, p, col):
        if col == "PLAN_YY":
            return {"2026": (1, 1, 300, 0, 0)} if p["ym_from"] == "202601" else {"2025": (1, 1, 200, 0, 0)}
        return {"여름": (1, 1, 100, 0, 0), "봄": (1, 1, 50, 0, 0)} if p["ym_from"] == "202601" else {"봄": (1, 1, 100, 0, 0)}

    monkeypatch.setattr(sm, "_group", group)
    yy = sm.summary("2026-01", "2026-08", None, None, None, "plan_yy")["rows"]
    assert yy[0]["key"] == "2026" and yy[0]["prevKey"] == "2025" and yy[0]["growth"] == 50.0
    ss = sm.summary("2026-01", "2026-08", None, None, None, "season")["rows"]
    assert [x["key"] for x in ss] == ["봄", "여름"]  # 계절 순서
    assert ss[0]["growth"] == -50.0


def test_summary_rejects_unknown_dim():
    with pytest.raises(HTTPException):
        sm.summary("2026-01", "2026-02", None, None, None, "brand")


def test_shop_trend_validates_shop_id():
    with pytest.raises(HTTPException):
        sm.shop_trend("")
    with pytest.raises(HTTPException):
        sm.shop_trend("TOOLONG7")


def test_order_sql_keeps_requested_order():
    assert re.match(r"ORDER BY MAKE_YYMM, SHOP_ID\b", sm.ORDER_SQL)


def test_index_expressions_match_ddl():
    """시즌·품군 조건/그룹 식이 인덱스 DDL 의 식과 같아야 Oracle 이 인덱스를 쓴다 (한쪽만 바꾸면 느려짐)."""
    from pathlib import Path

    from app import chat_tools_sale as cts

    ddl = (Path(__file__).resolve().parents[2] / "db" / "create_ix_close_sale_base_04.sql").read_text(encoding="utf-8")
    assert sm.SESS_EXPR in ddl and sm.PRDT_GRP_EXPR in ddl
    assert sm.SUMMARY_DIMS["season"][0] == sm.SESS_EXPR and sm.SUMMARY_DIMS["prdt_grp"][0] == sm.PRDT_GRP_EXPR
    assert cts.GROUP_COLS["SESS_NM"] == sm.SESS_EXPR and cts.GROUP_COLS["PRDT_GRP_NM"] == sm.PRDT_GRP_EXPR


def test_shop_filter_adds_month_list_for_index_lookup():
    where, p = sm._where("2026-06", "2026-08", "A11001", None, None)
    assert "MAKE_YYMM IN (:ym0, :ym1, :ym2)" in where and [p["ym0"], p["ym2"]] == ["202606", "202608"]
    assert "MAKE_YYMM BETWEEN :ym_from AND :ym_to" in where  # 기간 값은 다른 계산(전년·월 목록)에서 계속 사용
    where2, _ = sm._where("2026-06", "2026-08", None, None, None)
    assert "MAKE_YYMM IN" not in where2  # 매장 조건이 없으면 기간 조건만


def test_shop_trend_uses_month_list(monkeypatch):
    seen = {}

    def query(sql, params=None, arraysize=5000):
        seen.setdefault("sql", sql)
        seen.setdefault("params", params)
        return [], []

    monkeypatch.setattr(sm.db, "query", query)
    monkeypatch.setattr(sm, "shop_names", lambda ids: {})
    t = sm.shop_trend("A11001")
    assert len(t["months"]) == 12 and "BETWEEN" not in seen["sql"]
    assert len([k for k in seen["params"] if k.startswith("m")]) == 24  # 최근 12개월 + 전년 같은 12개월
