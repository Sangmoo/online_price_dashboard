"""일자별 상세 매장코드: SHOP_ID IN 조건('-' = 매장코드 없음), 매장명 붙이기, 매장 선택 목록, AI 도구 shop_ids. DB 는 가짜."""
import pandas as pd
import pytest

from app import chat_tools as ct
from app import data_service as ds
from app import sale_monthly


def _df():
    return pd.DataFrame([
        {"ONLINE_ID": 1, "DT": "20261007", "PRDT_CD": "TA1", "PRICE": 100, "DC_PRICE": 90, "DC_RATE": 10, "MALL_NM": "SSG(사이트)",
         "TITLE": "a", "RMK": None, "INS_DAY": "20261007010101", "NAVER_PAY_SELL_NO": "0623601366", "SHOP_ID": "T15602", "URL": "u"},
        {"ONLINE_ID": 2, "DT": "20261007", "PRDT_CD": "AB1", "PRICE": 100, "DC_PRICE": 80, "DC_RATE": 20, "MALL_NM": "SSG(사이트)",
         "TITLE": "b", "RMK": None, "INS_DAY": "20261007010101", "NAVER_PAY_SELL_NO": "0623601403", "SHOP_ID": "A15602", "URL": "u"},
        {"ONLINE_ID": 3, "DT": "20261007", "PRDT_CD": "SC1", "PRICE": 100, "DC_PRICE": 70, "DC_RATE": 30, "MALL_NM": "쿠팡",
         "TITLE": "c", "RMK": None, "INS_DAY": "20261007010101", "NAVER_PAY_SELL_NO": None, "SHOP_ID": None, "URL": "u"},
        {"ONLINE_ID": 4, "DT": "20261007", "PRDT_CD": "TA2", "PRICE": 100, "DC_PRICE": 95, "DC_RATE": 5, "MALL_NM": "SSG(사이트)",
         "TITLE": "d", "RMK": None, "INS_DAY": "20261007010101", "NAVER_PAY_SELL_NO": "0623601366", "SHOP_ID": "T15602", "URL": "u"},
    ])


@pytest.fixture
def day(monkeypatch):
    ds._day_cache._data.clear()
    df = _df()
    monkeypatch.setattr(ds.db, "query", lambda sql, p=None: (list(df.columns), df.values.tolist()))
    monkeypatch.setattr(sale_monthly, "shop_names", lambda ids: {"T15602": "신세계광주", "A15602": "신세계광주"})
    yield
    ds._day_cache._data.clear()


def test_parse_shops():
    assert ds.parse_shops(" t15602, A15602;T15602\n- ") == ["T15602", "A15602", "-"]
    assert ds.parse_shops(None) == [] and ds.parse_shops("") == []
    with pytest.raises(ValueError):
        ds.parse_shops("T156021")              # 7자리
    with pytest.raises(ValueError):
        ds.parse_shops(",".join(f"T{i:05d}" for i in range(ds.MAX_SHOP_IDS + 1)))


def test_day_rows_shop_column_and_in_filter(day):
    r = ds.day_rows("20261007", 1, 50, None, "asc", None, None)
    assert [c["key"] for c in r["columns"]][-3:] == ["SHOP_ID", "SHOP_NM", "URL"]
    assert r["rows"][0]["SHOP_NM"] == "신세계광주" and r["rows"][2]["SHOP_NM"] is None
    assert r["summary"]["shops"] == 2 and r["summary"]["shopRows"] == 3
    assert r["shops"][0] == {"shopId": "T15602", "shopNm": "신세계광주", "rows": 2}   # 건수 많은 순

    r = ds.day_rows("20261007", 1, 50, None, "asc", None, None, shops="t15602,A15602")
    assert sorted(x["ONLINE_ID"] for x in r["rows"]) == [1, 2, 4] and r["totalAll"] == 4
    assert r["summary"]["shopRows"] == 3
    r = ds.day_rows("20261007", 1, 50, None, "asc", None, None, shops="-")
    assert [x["ONLINE_ID"] for x in r["rows"]] == [3]
    r = ds.day_rows("20261007", 1, 50, None, "asc", None, None, shops="A15602 -")
    assert sorted(x["ONLINE_ID"] for x in r["rows"]) == [2, 3]
    r = ds.day_rows("20261007", 1, 50, None, "asc", "신세계광주", None)   # 통합 검색은 매장명도 본다
    assert r["total"] == 3


def test_export_with_shop_filter(day):
    assert ds.export_day("20261007", None, "asc", None, None, shops="T15602", cols=["SHOP_ID", "SHOP_NM"])[:2] == b"PK"


def test_ai_tool_shop_ids(monkeypatch):
    seen = {}

    def fake(sql, p=None):
        seen["sql"], seen["p"] = sql, p
        return [] if "SELECT *" in sql else [{"ROW_CNT": 0}]
    monkeypatch.setattr(ct.db, "query_dicts", fake)
    monkeypatch.setattr(ct.db, "query", lambda sql, p=None: (["C"], [[0]]))
    ct._run_price_tool("search_price_rows", {"date_from": "20261007", "date_to": "20261007", "shop_ids": ["t15602", "-"]})
    assert "(SHOP_ID IN (:shop0) OR SHOP_ID IS NULL)" in seen["sql"] and seen["p"]["shop0"] == "T15602"
    assert "SHOP_ID, URL" in seen["sql"]
    assert "SHOP_NM" not in ct.ROW_COLS and "SHOP_ID" in ct.GROUP_COLS
    with pytest.raises(ct.ToolInputError):
        ct._run_price_tool("search_price_rows", {"date_from": "20261007", "date_to": "20261007", "shop_ids": "T15602"})


class _Var:
    def __init__(self, v):
        self.v = v

    def getvalue(self):
        return self.v


class _Cur:
    def __init__(self, log, err=None):
        self.log, self.err = log, err

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def var(self, _type):
        return _Var(1234)

    def callproc(self, name, args):
        if self.err:
            raise self.err
        self.log.append((name, args[:2]))


class _Pool:
    def __init__(self, log, err=None):
        self.log, self.err = log, err

    def acquire(self):
        pool = self

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cursor(self):
                return _Cur(pool.log, pool.err)
        return _Conn()


def test_fill_shop_ids_calls_proc_for_last_7_days(monkeypatch):
    from datetime import datetime, timedelta

    from app import audit, mall_shop as ms

    log, audits = [], []
    monkeypatch.setattr(ms.db, "get_pool", lambda: _Pool(log))
    monkeypatch.setattr(audit, "record", lambda *a, **k: audits.append(a))
    ds._day_cache.set("20261007", "x", 60)
    r = ms.fill_shop_ids({"id": "900001"})
    today = datetime.now()
    assert log == [("P_FILL_ONLINE_SHOP_ID", [(today - timedelta(days=6)).strftime("%Y%m%d"), today.strftime("%Y%m%d")])]
    assert r["updated"] == 1234 and r["from"] == log[0][1][0]
    assert ds._day_cache.get("20261007") is None          # 화면 캐시 비움
    assert audits and audits[0][1] == "ONLINE_SHOP_FILL"


def test_fill_shop_ids_missing_proc(monkeypatch):
    import oracledb
    from fastapi import HTTPException

    from app import mall_shop as ms

    monkeypatch.setattr(ms.db, "get_pool", lambda: _Pool([], oracledb.DatabaseError("ORA-06550: PLS-00201: identifier 'P_FILL_ONLINE_SHOP_ID' must be declared")))
    with pytest.raises(HTTPException) as ex:
        ms.fill_shop_ids({"id": "900001"})
    assert "create_job_online_shop_id.sql" in ex.value.detail["message"]
    assert not ms._fill_lock.locked()
