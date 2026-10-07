"""관리자 '사용 쿼리': 메뉴(화면)마다 기능별로 쓰는 SQL.

- 코드 기준: 각 기능 함수의 소스에서 SQL 문자열을 뽑는다(코드가 바뀌면 자동으로 따라감).
  { } 로 남는 부분은 조회 조건에 따라 코드가 채우는 부분, :이름 은 바인드 변수.
- 실제 실행: sql_trace 가 메모리에 남긴 SQL 에 바인드 값을 채운 실제 쿼리. 요청한 관리자가 가장 최근에 조회한 1회분을 먼저
  (서버 재시작 후 화면에서 그 기능을 한 번 조회해야 보임).
기능 목록(CATALOG)의 함수 이름은 tests/test_sql_catalog_unit.py 가 존재 여부를 확인한다.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
import textwrap
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from . import sql_trace

SQL_START = re.compile(r"^\s*\(?\s*(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|BEGIN)\b", re.I)
_PKG = __package__ or "app"
_ROOT = Path(__file__).resolve().parents[2]

# 페이지 → [(기능, 설명, [모듈.함수 또는 {"title", "sql"}])]
CATALOG: dict[str, list[tuple[str, str, list]]] = {
    "dashboard": [
        ("수집 일자 목록", "날짜 선택에 쓰는 최근 120일 수집 건수", ["data_service.available_dates"]),
        ("기간 수집 현황", "요약 카드 · 일자별 추이 · 사이트별 · 할인율 분포 · 매장별 수집", ["data_service.dashboard"]),
        ("상품 팝업 · 온라인 가격", "품번을 누르면 뜨는 팝업의 최근 31일 온라인 가격", ["data_service.product_online"]),
    ],
    "detail": [
        ("수집 일자 목록", "날짜 선택에 쓰는 최근 120일 수집 건수", ["data_service.available_dates"]),
        ("일자별 원본 조회 · 엑셀", "선택한 날짜 전체를 읽어 서버에서 검색 · 사이트 · 할인율 · 매장코드 조건과 정렬을 적용 (엑셀도 같은 데이터)",
         ["data_service.load_day"]),
        ("매장코드 채우기", "최근 7일 수집 행의 SHOP_ID 를 판매처 매장 연결로 채움 (db/create_job_online_shop_id.sql)", [
            {"title": "프로시저 직접 실행 (SQL*Plus · SQL Developer)", "sql":
             "VARIABLE n NUMBER\nEXEC P_FILL_ONLINE_SHOP_ID(TO_CHAR(SYSDATE - 6, 'YYYYMMDD'), TO_CHAR(SYSDATE, 'YYYYMMDD'), :n)\nPRINT n"},
        ]),
        ("상품 팝업 · 온라인 가격", "품번을 누르면 뜨는 팝업의 최근 31일 온라인 가격", ["data_service.product_online"]),
    ],
    "mall_shop": [
        ("사이트 · 판매자 조합", "최근 수집에 나온 사이트 · 판매자번호 · 브랜드 조합과 건수", ["mall_shop._combos"]),
        ("저장된 매장 연결", "T_SELECT_ONLINE_MALL_SHOP 매핑", ["mall_shop._maps"]),
        ("매장 선택 목록", "영업 중 매장 · 브랜드", ["shop_info.all_rows"]),
        ("매핑 저장 · 해제", "MERGE 로 저장, 매장코드를 비우면 삭제", ["mall_shop.save"]),
        ("엑셀 업로드", "기존 연결과 비교(미리보기) 후 매핑 저장과 같은 MERGE", ["mall_shop._maps", "sale_monthly.shop_names", "mall_shop.save"]),
        ("매장코드 채우기", "최근 7일 수집 행 SHOP_ID 채우기 프로시저", [
            {"title": "프로시저 직접 실행 (SQL*Plus · SQL Developer)", "sql":
             "VARIABLE n NUMBER\nEXEC P_FILL_ONLINE_SHOP_ID(TO_CHAR(SYSDATE - 6, 'YYYYMMDD'), TO_CHAR(SYSDATE, 'YYYYMMDD'), :n)\nPRINT n"},
        ]),
    ],
    "sale_dashboard": [
        ("기준 월 · 브랜드 목록", "선택할 수 있는 판매년월과 브랜드별 팀", ["sale_dashboard.available_months", "sale_dashboard.brand_teams"]),
        ("판매 현황 집계", "요약 카드 · 월 추이 · 브랜드 · 팀 · 매장 순위 (사전 집계 뷰가 있으면 뷰에서)", ["sale_dashboard._compute"]),
        ("매장 목표", "목표 대비 달성률", ["sale_dashboard._goals"]),
        ("상품 순위 · 아이템 비교", "상품 순위 · 아이템/품군 비교 · 판매형태 구성", ["sale_products._compute", "sale_products.mv_state"]),
        ("시즌 판매 진척", "시즌 누적 판매와 전년 같은 시점 · 아이템별", ["sale_season._load", "sale_season.items"]),
        ("세일 비중 높은 매장", "판매형태(정상 · 세일 · 행사) 구성", ["sale_mix._compute"]),
        ("온라인 할인 주의 상품", "매장 상위 상품의 최근 온라인 할인율", ["online_alerts._online"]),
        ("매장 판매 추이", "매장을 누르면 뜨는 월별 추이", ["sale_monthly.shop_trend"]),
        ("상품 팝업 · 매장 판매", "품번 팝업의 월별 판매 · 많이 팔린 매장 · 같은 아이템 순위",
         ["sale_products.product_sales", "sale_products.product_shops", "sale_products.product_siblings"]),
        ("매장 정보 팝업", "매장 기본 정보 · 월별 목표 · 판매 구성", ["shop_info.all_rows", "shop_info.profile", "shop_info.goals_by_month", "sale_monthly.shop_mix"]),
    ],
    "sale_monthly": [
        ("브랜드 권한 조건", "브랜드 권한이 있는 사용자의 매장 조건", ["sale_monthly.brand_filter", "sale_monthly.brand_shop_ids"]),
        ("목록 조회 · 건수", "조건(기간 · 매장 · 기획년도 · 시즌)으로 페이지 조회와 월별 건수", ["sale_monthly.search", "sale_monthly._month_stats"]),
        ("할인 금액 합계", "", ["sale_monthly.dsct_total"]),
        ("요약 (월 · 매장 · 시즌 등)", "선택한 기준으로 묶은 합계", ["sale_monthly._group", "sale_monthly.shop_names"]),
        ("매장 판매 추이", "", ["sale_monthly.shop_trend"]),
        ("엑셀 내보내기", "월 단위로 나눠 읽어 파일을 만든다", ["sale_monthly._run_export"]),
        ("매장 검색", "매장 조건 입력창", ["invt_plan.search_shops"]),
    ],
    "invt_plan": [
        ("실사계획 목록", "삭제되지 않은 계획 (엑셀도 같은 목록)", ["invt_plan.list_plans"]),
        ("등록 · 수정 · 삭제", "삭제는 DEL_DAY 를 채우는 방식", ["invt_plan.create_plan", "invt_plan.update_plan", "invt_plan.delete_plans", "invt_plan.get_plan"]),
        ("매장 검색", "", ["invt_plan.search_shops"]),
        ("매장 상세", "매장 정보 · 직전 실사 · 재고 수량 · 실사 등급 · 올해 매출", ["invt_plan.shop_detail", "invt_plan.invt_rank", "invt_plan._sales_ytd"]),
        ("매장 매니저", "현재 · 과거 매니저와 연락처", ["invt_plan.shop_managers"]),
        ("매장 판매 추이", "", ["sale_monthly.shop_trend"]),
        ("엑셀 업로드", "매장 확인 · 기존 계획 수 (미리보기), 한 번에 등록 (매장 정보 자동 입력은 '매장 상세' 쿼리)",
         ["uploads._invt_rows", "uploads.invt_apply"]),
    ],
    "stock_rt": [
        ("선택지 · 최근 판매분 자동보충 실행 조건", "창고 · 판매보충기준 · 등급 그룹 · SS10DEV.T_AUTO_DVID_MASTER_HIST",
         ["wh_alloc.options", "wh_alloc.recent_runs", "stock_ctl.team_names", "stock_ctl.code_names"]),
        ("매장 기준 · 수불제어", "매장 · RT 그룹 설정 · 매장등급 · 유효 수불제어(F_GET_RNDS_CNTR 와 같은 규칙) · 자동RT 제외 스타일",
         ["stock_ctl.shops", "stock_ctl.base_grade_group", "stock_ctl.grade_shops", "stock_ctl.controls", "stock_ctl.style_info"]),
        ("매장 간 RT · 판매 · 자동 RT 취소", "기간 판매(매장 × 상품)와 '지시가능매장없음' 취소 요청",
         ["stock_rt._styles", "stock_rt._sales", "stock_rt._failed"]),
        ("매장 간 RT · 재고", "판매가 있던 품번 · 칼라의 이번 달 매장 재고", ["stock_rt._stock"]),
        ("매장 간 RT · 이동중 · 요청중 · 오늘 지정", "", ["stock_rt._moving", "stock_rt._reserved"]),
        ("매장 간 RT · 매장 상품 기준", "보내는 후보의 최초 · 최종 출고일, 최종판매일, 판매율용 수량", ["stock_rt._prdt_base"]),
        ("자동 RT 현황", "", ["stock_rt.auto_rt_stats"]),
        ("창고 배분 · 상품 · 판매", "판매보충기준에 맞는 상품, 기간 판매(완불 · 일반)", ["wh_alloc._styles", "wh_alloc._sales"]),
        ("창고 배분 · 매장 재고 · 시점재고 · 최초판매일", "", ["wh_alloc._stock", "wh_alloc._moves", "wh_alloc._first_sale"]),
        ("창고 배분 · 창고 가용", "창고 재고 · 출고지시 미명세 · 미확정 배분의뢰", ["wh_alloc._wh_avail"]),
    ],
    "notice": [
        ("공지 목록", "게시판 · 로그인 팝업 (첨부 · 댓글 수 · 내 읽음)", ["notices._all", "notices._file_meta", "notices._comment_counts", "notices._my_reads"]),
        ("공지 상세 · 첨부", "", ["notices._get", "notices.get_file"]),
        ("읽음 · 필독 확인", "", ["notices._save_read"]),
        ("댓글", "목록 · 등록 · 수정 · 삭제", ["notices._comment_rows", "notices._ins_sql", "notices.edit_comment", "notices.delete_comment"]),
    ],
    "mypage": [
        ("내 정보", "사용자 · 메뉴 권한 · 브랜드 권한", ["userdb.get_user", "userdb._pages_of", "userdb._brands_of"]),
        ("화면 설정 (다크 모드 · 강조 색)", "사용자별로 서버에 저장", ["appdb.pref_get", "appdb.pref_set"]),
        ("적용된 권한 묶음", "", ["roles.role_of"]),
        ("오늘 AI 사용", "", ["usage.today_usage"]),
        ("최근 내 다운로드", "", ["downloads.report"]),
    ],
    "admin": [
        ("관리자 홈", "카드 요약 (어제 매장코드 채움 등)", ["admin_home._data"]),
        ("사용자 목록 · 등록 · 수정", "", ["userdb.list_users", "userdb._pages_of", "userdb._brands_of", "userdb.create_user", "userdb.update_user", "userdb._sync_brands"]),
        ("사원 검색 (사용자 추가)", "", ["admin.directory_search", "admin._verify_emp"]),
        ("권한 묶음", "", ["roles._rows", "roles._members", "roles.save", "roles.delete", "roles._remember"]),
        ("변경 이력", "", ["audit.search"]),
        ("다운로드 이력 · 알림", "", ["downloads.report", "downloads.alerts"]),
        ("공지 · 점검", "목록 · 읽음 현황 · 저장 · 삭제", ["notices._all", "notices._read_counts", "notices.read_status", "notices.save", "notices._save_files", "notices.delete"]),
        ("스케줄 · 배치", "DB 스케줄 (함수가 커서를 돌려줌) · 서버 작업 기록", [
            {"title": "DB 스케줄 목록 · 실행 이력", "sql":
             "SELECT F_ERP_WEB_SCHED_JOBS('JOB_FILL_ONLINE_SHOP_ID,JOB_LOAD_CLOSE_SALE_BASE') FROM DUAL;\n"
             "SELECT F_ERP_WEB_SCHED_RUNS('JOB_FILL_ONLINE_SHOP_ID,JOB_LOAD_CLOSE_SALE_BASE', 14) FROM DUAL;"},
            "jobs._app_jobs", "jobs.record", "jobs._check_result",
        ]),
        ("데이터 현황 · 사전 집계 뷰", "", ["admin.data_status", "mv_refresh._snapshot"]),
        ("AI 사용량 · 메뉴 사용", "", ["usage.report", "usage.today_by_user", "menu_usage._rows"]),
        ("문의 · 신고", "", ["feedback._select", "feedback._file_meta", "feedback.answer"]),
        ("로그인 · 세션", "", ["appdb.login_log_list", "appdb.locks_list", "appdb.sessions_active"]),
        ("시스템 설정", "", ["userdb.get_settings", "userdb.save_settings"]),
    ],
}

_SAFE_TYPES = (str, int, float, tuple, list, frozenset)


def _mod(name: str):
    return importlib.import_module(f"{_PKG}.{name}")


def _global(node: ast.AST, g: dict):
    """Name · 점 이름(모듈.상수)을 모듈 전역 값으로 (함수 · 객체는 제외)"""
    if isinstance(node, ast.Name):
        if node.id not in g:
            return None
        v = g[node.id]
    elif isinstance(node, ast.Attribute):
        base = _global(node.value, g) if not isinstance(node.value, ast.Name) else g.get(node.value.id)
        if base is None:
            return None
        v = getattr(base, node.attr, None)
    else:
        return None
    return v if isinstance(v, _SAFE_TYPES) or inspect.ismodule(v) else None


def _const_expr(node: ast.AST, g: dict) -> str | None:
    """{ } 안의 식이 상수만 쓰면 값으로 바꾼다: 이름 · 모듈.상수 · ', '.join(상수)"""
    v = _global(node, g)
    if isinstance(v, (str, int, float)):
        return str(v)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join"
            and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)
            and len(node.args) == 1 and not node.keywords):
        seq = _global(node.args[0], g)
        if isinstance(seq, (tuple, list)) and all(isinstance(x, str) for x in seq):
            return node.func.value.value.join(seq)
    return None


def _render(node: ast.AST, g: dict, local: set[str]) -> str | None:
    """문자열 식을 SQL 텍스트로 (알 수 없는 부분은 {식})"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(str(part.value))
            else:
                val = _const_expr(part.value, g)
                out.append(val if val is not None else "{" + ast.unparse(part.value) + "}")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _render(node.left, g, local), _render(node.right, g, local)
        if left is None and right is None:
            return None
        return (left if left is not None else "{" + ast.unparse(node.left) + "}") + (
            right if right is not None else "{" + ast.unparse(node.right) + "}")
    if isinstance(node, (ast.Name, ast.Attribute)) and not (isinstance(node, ast.Name) and node.id in local):
        v = _global(node, g)
        return v if isinstance(v, str) else None
    return None


_SQLITE_TABLE = re.compile(r"\b(?:FROM|INTO|UPDATE)\s+([A-Za-z_]\w*)", re.I)


def _is_sqlite(sql: str) -> bool:
    """같은 함수 안의 SQLite(로컬 보관용) 문장은 빼고 Oracle 문장만"""
    if re.search(r"\?|\bLIMIT\s+\d|\bINSERT\s+OR\b|\bON\s+CONFLICT\b", sql, re.I):
        return True
    m = _SQLITE_TABLE.search(sql)
    return bool(m and m.group(1).islower() and not m.group(1).startswith(("nls_", "all_", "user_", "dba_", "dual")))


def tidy(sql: str) -> str:
    lines = sql.strip("\n").splitlines()
    if not lines:
        return ""
    first, rest = lines[0].strip(), textwrap.dedent("\n".join(lines[1:]))
    return "\n".join([first, *[ln.rstrip() for ln in rest.splitlines()]]).strip()


@lru_cache(maxsize=512)
def templates(key: str) -> dict:
    """함수 소스의 SQL 문장 (코드 기준)"""
    mod_name, fn_name = key.split(".", 1)
    mod = _mod(mod_name)
    file = Path(inspect.getsourcefile(mod) or "")
    # 모듈 소스에서 최상위 함수를 찾는다 (실행 중 다른 함수로 바뀌어 있어도 코드 기준으로)
    tree = next((n for n in ast.parse(file.read_text(encoding="utf-8")).body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name), None)
    if tree is None:
        return {"error": "함수를 찾을 수 없습니다.", "sqls": []}
    line = tree.lineno
    g = dict(vars(mod))
    for imp in ast.walk(tree):   # 함수 안의 from . import x as y
        if isinstance(imp, ast.ImportFrom) and imp.level >= 1 and not imp.module:
            for a in imp.names:
                try:
                    g[a.asname or a.name] = _mod(a.name)
                except ImportError:
                    pass
    local = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    local |= {a.arg for n in ast.walk(tree) if isinstance(n, ast.arguments) for a in (*n.args, *n.kwonlyargs)}
    found: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            return   # 독스트링
        txt = _render(node, g, local)
        if txt is not None and SQL_START.match(txt):
            t = tidy(txt)
            if not _is_sqlite(t) and t not in found:
                found.append(t)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    try:
        rel = file.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        rel = file.name
    return {"file": rel, "line": line, "sqls": found}


def _literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return f"TO_DATE('{v:%Y-%m-%d %H:%M:%S}', 'YYYY-MM-DD HH24:MI:SS')"
    if isinstance(v, date):
        return f"TO_DATE('{v:%Y-%m-%d}', 'YYYY-MM-DD')"
    return "'" + str(v).replace("'", "''") + "'"


_TOKEN = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"|--[^\n]*|/\*.*?\*/|:([A-Za-z_]\w*)", re.S)


def fill_binds(sql: str, binds: dict) -> str:
    """:이름 을 값으로 바꾼 SQL (문자열 · 주석 안은 그대로). 값이 없는 바인드는 남긴다."""
    upper = {k.upper(): v for k, v in binds.items()}

    def rep(m: re.Match) -> str:
        name = m.group(1)
        if name is None or name.upper() not in upper:
            return m.group(0)
        return _literal(upper[name.upper()])

    return _TOKEN.sub(rep, sql)


def _json(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _run(r: dict) -> dict:
    sql = tidy(r["sql"])
    return {"sql": sql, "raw": r["sql"], "filled": fill_binds(sql, r["binds"]), "binds": {k: _json(v) for k, v in r["binds"].items()},
            "at": r["at"], "ms": r["ms"], "count": r["count"], "usr": r.get("usr")}


def _item(src, usr: str | None = None) -> dict:
    """runs: 가장 최근 조회 1회(같은 요청)에서 실행된 SQL — 값이 채워진 실제 쿼리, 실행 순서대로.
    내가 실행한 기록이 있으면 내 것, 없으면 다른 사용자의 최근 조회. older: 그 이전 실행."""
    if isinstance(src, dict):
        return {"fn": None, "title": src["title"], "file": None, "line": None, "sqls": [tidy(src["sql"])], "runs": [], "older": []}
    try:
        t = templates(src)
    except Exception as ex:  # noqa: BLE001 - 한 함수가 실패해도 나머지는 보여준다
        t = {"error": f"소스를 읽지 못했습니다: {ex}", "sqls": []}
    all_runs = sql_trace.recent(src)                       # 최근 순
    mine = [r for r in all_runs if usr and r.get("usr") == usr]
    pool = mine or all_runs
    runs, older = [], []
    if pool:
        last = pool[0].get("req")
        runs = [_run(r) for r in reversed(pool) if r.get("req") == last]
        older = [_run(r) for r in pool if r.get("req") != last]
    return {"fn": src, "title": None, "file": t.get("file"), "line": t.get("line"), "sqls": t["sqls"],
            "error": t.get("error"), "runs": runs, "older": older, "mine": bool(mine)}


def page_label(key: str) -> str:
    from . import auth

    return {"notice": "공지사항", "mypage": "마이페이지", "admin": "관리자"}.get(key) or auth.PAGE_LABELS.get(key, key)


def page(key: str, usr: str | None = None) -> dict:
    if key not in CATALOG:
        return {"page": key, "features": [], "since": sql_trace.started}
    label = page_label(key)
    features = [{"title": t, "desc": d, "items": [_item(s, usr) for s in srcs]} for t, d, srcs in CATALOG[key]]
    return {"page": key, "label": label, "features": features, "since": sql_trace.started}
