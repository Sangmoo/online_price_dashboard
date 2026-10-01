"""AI 도구 관리: SQL 안전 검증, 정의 검증, 입력값 변환, 도구 목록/실행의 사용 여부·메뉴 권한 연동, 메뉴 권한 일괄 저장."""
import pytest
from fastapi import HTTPException

from app import admin, ai_tools
from app import chat_tools as ct

PAGES = ["dashboard", "detail", "sale_monthly", "invt_plan"]
BASE = {"name": "shop_top", "label": "매장 상위", "description": "판매년월의 매출 상위 매장을 조회합니다.", "page": "sale_monthly",
        "sql": "SELECT SHOP_ID, SUM(TOTAL_SALE_AMT) AMT FROM SS10.MV_CLOSE_SALE_SHOP_YM WHERE MAKE_YYMM = :ym GROUP BY SHOP_ID",
        "params": [{"name": "ym", "type": "yyyymm", "required": True}], "maxRows": 10}


@pytest.fixture
def local_store(temp_store, monkeypatch):
    """AI 도구 설정을 임시 SQLite 에 저장 (Oracle 테이블 없음 상태)."""
    monkeypatch.setattr(ai_tools, "_use_oracle", lambda: False)
    ai_tools.invalidate()
    yield
    ai_tools.invalidate()


# ----------------------------------------------------------------------------
# SQL 안전 검증
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("sql,msg", [
    ("UPDATE T_SHOP SET SHOP_NM = :ym", "조회"),
    ("DELETE FROM T_SHOP WHERE SHOP_ID = :ym", "조회"),
    ("SELECT * FROM T_SHOP WHERE SHOP_ID = :ym; DROP TABLE T_SHOP", "한 문장"),
    ("SELECT * FROM T_SHOP WHERE SHOP_ID = :ym -- 주석", "주석"),
    ("SELECT * FROM T_SHOP /* 주석 */ WHERE SHOP_ID = :ym", "주석"),
    ("SELECT CRYPTO_DECRYPT(PWD) FROM T_USR WHERE USR_ID = :ym", "CRYPTO_DECRYPT"),
    ("SELECT DBMS_RANDOM.VALUE FROM DUAL WHERE :ym IS NOT NULL", "DBMS_RANDOM"),
    ("SELECT * FROM T_SHOP WHERE SHOP_ID = :ym FOR UPDATE", "FOR UPDATE"),
    ("SELECT * FROM T_SHOP@OTHER_DB WHERE SHOP_ID = :ym", "@"),
    ("WITH X AS (SELECT 1 A FROM DUAL) SELECT * FROM X WHERE :ym IS NULL", None),       # WITH 허용
    ("SELECT /*+ INDEX(T) */ * FROM T_SHOP T WHERE SHOP_ID = :ym", None),               # 힌트 허용
    ("SELECT 'UPDATE; -- :x' AS TXT FROM DUAL WHERE :ym IS NOT NULL", None),            # 문자열 안은 검사 제외
])
def test_validate_sql(sql, msg):
    if msg is None:
        assert ai_tools.validate_sql(sql, ["ym"])
    else:
        with pytest.raises(ai_tools.ToolDefError, match=msg):
            ai_tools.validate_sql(sql, ["ym"])


def test_validate_sql_bind_consistency():
    with pytest.raises(ai_tools.ToolDefError, match=":shop"):
        ai_tools.validate_sql("SELECT * FROM T WHERE A = :ym AND B = :shop", ["ym"])
    with pytest.raises(ai_tools.ToolDefError, match="쓰이지 않습니다"):
        ai_tools.validate_sql("SELECT * FROM T WHERE A = :ym", ["ym", "shop"])
    assert ai_tools.validate_sql("SELECT * FROM T WHERE A = :ym;", ["ym"]).endswith(":ym")  # 끝 세미콜론 제거


@pytest.mark.parametrize("patch,msg", [
    ({"name": "Bad-Name"}, "도구 이름"),
    ({"name": "aggregate_sales"}, "기본 도구"),
    ({"label": ""}, "표시 이름"),
    ({"description": "짧음"}, "10자"),
    ({"page": "admin"}, "메뉴"),
    ({"maxRows": 9999}, "최대 행"),
    ({"params": [{"name": "ym", "type": "enum", "required": True}]}, "선택값"),
    ({"params": [{"name": "1ym", "type": "string"}]}, "파라미터 이름"),
    ({"params": [{"name": "ym", "type": "yyyymm", "default": "2026-13"}]}, "형식"),
])
def test_validate_def_rejects(local_store, patch, msg):
    with pytest.raises((ai_tools.ToolDefError, ai_tools.ToolArgError), match=msg):
        ai_tools.validate_def({**BASE, **patch}, ct.BUILTIN_NAMES, PAGES)


@pytest.mark.parametrize("typ,value,expected", [
    ("integer", "12", 12), ("number", "1.5", 1.5), ("date", "2026-08-01", "20260801"), ("yyyymm", "2026-08", "202608"),
])
def test_coerce(typ, value, expected):
    assert ai_tools.coerce({"name": "x", "type": typ}, value) == expected


@pytest.mark.parametrize("typ,value", [("integer", "1.5"), ("integer", True), ("date", "20260231"), ("yyyymm", "202613")])
def test_coerce_rejects(typ, value):
    with pytest.raises(ai_tools.ToolArgError):
        ai_tools.coerce({"name": "x", "type": typ}, value)


def test_run_custom_renames_binds_and_wraps(monkeypatch):
    """바인드는 :p_ 접두어로 바꿔 예약어 충돌을 피하고, 최대 행 수로 감싸며, 읽기 전용 트랜잭션에서 실행."""
    executed = []

    class Cur:
        description = [("SHOP_ID",), ("AMT",)]

        def execute(self, sql, binds=None):
            executed.append((sql, binds))

        def fetchmany(self, n):
            return [("S1", 10), ("S2", 5)]

    class Conn:
        call_timeout = 0

        def cursor(self):
            return Cur()

        def rollback(self):
            executed.append(("ROLLBACK", None))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return Conn()

    monkeypatch.setattr(ai_tools.db, "get_pool", lambda: Pool())
    spec = {**BASE, "sql": "SELECT * FROM T WHERE DT = :date AND X = ':date'", "params": [{"name": "date", "type": "date", "required": True}],
            "maxRows": 1}
    out = ai_tools.run_custom(spec, {"date": "2026-08-01"})
    assert executed[0][0] == "SET TRANSACTION READ ONLY"
    sql, binds = executed[1]
    assert ":p_date AND X = ':date'" in sql and binds == {"p_date": "20260801"}  # 리터럴 안은 그대로
    assert "ROWNUM <= 2" in sql
    assert out["result"]["returned"] == 1 and out["result"]["truncated"] is True
    assert executed[-1][0] == "ROLLBACK"
    with pytest.raises(ai_tools.ToolArgError, match="필수"):
        ai_tools.run_custom(spec, {})
    with pytest.raises(ai_tools.ToolArgError, match="정의되지 않은"):
        ai_tools.run_custom(spec, {"date": "20260801", "hack": 1})


# ----------------------------------------------------------------------------
# 도구 목록/실행: 사용 여부, 추가 안내, 메뉴 권한
# ----------------------------------------------------------------------------
def test_registry_respects_admin_settings(local_store, monkeypatch):
    adm = {"id": "250016"}
    admin.save_builtin_tool(adm, "search_sales", {"enabled": False})
    admin.save_builtin_tool(adm, "aggregate_sales", {"enabled": True, "extraDesc": "원가율은 소수 첫째 자리"})
    admin.save_custom_tool(adm, dict(BASE))
    sale_user = {"pages": ["sale_monthly"]}
    names = [t["name"] for t in ct.tools_for(sale_user)]
    assert "search_sales" not in names and "shop_top" in names
    agg = next(t for t in ct.tools_for(sale_user) if t["name"] == "aggregate_sales")
    assert agg["description"].endswith("[관리자 안내] 원가율은 소수 첫째 자리")
    assert "shop_top" not in [t["name"] for t in ct.tools_for({"pages": ["invt_plan"]})]  # 메뉴 권한 없음
    with pytest.raises(ct.ToolInputError, match="사용 중지"):
        ct.run_tool("search_sales", {"ym_from": "202608", "ym_to": "202608"}, sale_user)
    with pytest.raises(ct.ToolInputError, match="메뉴 권한"):
        ct.run_tool("shop_top", {"ym": "202608"}, {"pages": ["invt_plan"]})
    assert ct.tool_label("shop_top") == "매장 상위"
    # 수정: 이름 변경 불가, 삭제 후 목록에서 빠짐
    with pytest.raises(HTTPException):
        admin.save_custom_tool(adm, {**BASE, "name": "other_name"}, "shop_top")
    with pytest.raises(HTTPException):
        admin.save_custom_tool(adm, dict(BASE))  # 같은 이름 중복 추가
    with pytest.raises(HTTPException):
        admin.delete_custom_tool(adm, "aggregate_sales")  # 기본 도구 삭제 불가
    admin.delete_custom_tool(adm, "shop_top")
    assert "shop_top" not in [t["name"] for t in ct.tools_for(sale_user)]


def test_settings_error_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(ai_tools, "_load_all", lambda: (_ for _ in ()).throw(RuntimeError("DB down")))
    assert ai_tools.snapshot() == {"builtin": {}, "custom": []}
    assert len(ct.tools_for({"pages": ["sale_monthly"]})) == 5  # 설정 저장소 장애여도 기본 도구로 AI 동작


# ----------------------------------------------------------------------------
# 메뉴 권한 일괄 저장
# ----------------------------------------------------------------------------
def test_save_permissions_validates_all_before_saving(monkeypatch):
    users = {"170046": {"usr_id": "170046"}, "250016": {"usr_id": "250016"}}
    saved = []
    monkeypatch.setattr(admin.userdb, "get_user", lambda uid, fresh=False: users.get(uid))
    monkeypatch.setattr(admin.userdb, "update_user", lambda uid, values, by: saved.append((uid, values["pages"])))
    monkeypatch.setattr(admin, "list_users", lambda q=None: [{"id": u} for u in users])
    with pytest.raises(HTTPException):  # 두 번째가 잘못되면 첫 번째도 저장하지 않음
        admin.save_permissions({"id": "250016"}, [{"id": "170046", "pages": ["dashboard"]}, {"id": "170046", "pages": ["hack"]}])
    assert saved == []
    out = admin.save_permissions({"id": "250016"}, [{"id": "170046", "pages": ["invt_plan", "dashboard"]}, {"id": "250016", "pages": []}])
    assert saved == [("170046", ["dashboard", "invt_plan"])]  # 최고 관리자는 건너뜀
    assert [u["id"] for u in out] == ["170046"]


def test_builtin_description_override_and_reset(local_store):
    adm = {"id": "250016"}
    default = next(t for t in ct.sale.TOOLS if t["name"] == "search_sales")["description"]
    admin.save_builtin_tool(adm, "search_sales", {"enabled": True, "extraDesc": "", "description": "판매 행을 직접 보여 줄 때만 쓰는 도구입니다."})
    desc = next(t for t in ct.tools_for({"pages": ["sale_monthly"]}) if t["name"] == "search_sales")["description"]
    assert desc == "판매 행을 직접 보여 줄 때만 쓰는 도구입니다."
    ov = next(b for b in admin.ai_tools_overview()["builtin"] if b["name"] == "search_sales")
    assert ov["customized"] and ov["defaultDescription"] == default
    admin.save_builtin_tool(adm, "search_sales", {"enabled": False, "extraDesc": ""})  # 사용 여부만 바꿔도 바꾼 설명 유지
    assert next(b for b in admin.ai_tools_overview()["builtin"] if b["name"] == "search_sales")["customized"]
    admin.save_builtin_tool(adm, "search_sales", {"enabled": True, "extraDesc": "", "description": default})  # 기본값으로
    ov = next(b for b in admin.ai_tools_overview()["builtin"] if b["name"] == "search_sales")
    assert not ov["customized"] and ov["description"] == default
    with pytest.raises(HTTPException):
        admin.save_builtin_tool(adm, "search_sales", {"enabled": True, "extraDesc": "", "description": "짧음"})
