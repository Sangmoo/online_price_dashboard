"""관리자 '사용 쿼리': 기능 목록의 함수가 실제로 있고 SQL 이 뽑히는지, 최근 실행 SQL 기록 · 바인드 값 채우기."""
from datetime import datetime

from app import roles, sql_catalog, sql_trace


def test_catalog_functions_exist_and_have_sql():
    for page, features in sql_catalog.CATALOG.items():
        for title, _, sources in features:
            for src in sources:
                if isinstance(src, dict):
                    assert src["title"] and src["sql"].strip()
                    continue
                t = sql_catalog.templates(src)
                assert not t.get("error"), f"{page} · {title}: {src} {t.get('error')}"
                assert t["sqls"], f"{page} · {title}: {src} 에서 SQL 을 찾지 못함"
                assert t["file"].startswith("backend/app/") and t["line"] > 0


def test_templates_resolve_constants_and_skip_sqlite():
    # 모듈 상수 · ', '.join(상수) 는 값으로 바뀌고, 같은 함수의 SQLite 문장은 빠진다
    sqls = sql_catalog.templates("downloads.report")["sqls"]
    assert any("DL_ID, DL_DAY, USR_ID" in s and "T_ERP_WEB_DOWNLOAD_LOG" in s for s in sqls)
    usage = sql_catalog.templates("usage.today_usage")["sqls"]
    assert usage and all("ai_usage" not in s and "?" not in s for s in usage)
    # 함수 안에서 import 한 모듈의 상수도 값으로
    assert "{cts.MV_NAME}" not in sql_catalog.templates("admin.data_status")["sqls"][0]


def test_fill_binds():
    sql = "SELECT * FROM T WHERE A = :a AND B = ':a' AND C = :dt AND D = :n -- :a\nAND E = :missing AND F = :s"
    out = sql_catalog.fill_binds(sql, {"a": "O'K", "dt": datetime(2026, 10, 7, 9, 5), "n": None, "s": 3})
    assert "A = 'O''K'" in out and "B = ':a'" in out and "-- :a" in out
    assert "TO_DATE('2026-10-07 09:05:00', 'YYYY-MM-DD HH24:MI:SS')" in out
    assert "D = NULL" in out and "E = :missing" in out and "F = 3" in out


def test_trace_records_by_caller(fake_oracle):
    sql_trace.clear()
    roles._rows()
    recent = sql_trace.recent("roles._rows")
    assert recent and "T_ERP_WEB_ROLE" in recent[0]["sql"] and recent[0]["count"] == 1
    roles._rows()
    assert sql_trace.recent("roles._rows")[0]["count"] == 2          # 같은 SQL 은 횟수만 늘림
    assert sql_trace._val("p_pw", "secret") == "****"

    page = sql_catalog.page("admin")
    item = next(i for f in page["features"] for i in f["items"] if i["fn"] == "roles._rows")
    assert item["recent"] and item["recent"][0]["filled"]
    assert sql_catalog.page("nope")["features"] == []
