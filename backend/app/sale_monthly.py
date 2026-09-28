"""월별 매장별 판매 집계: T_CLOSE_SALE_BASE(마감 매출 기초 데이터) 조회 · 페이징 · 전체 엑셀."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date

import xlsxwriter
from fastapi import HTTPException

from . import db

PAGE_SIZE = 100
MAX_MONTHS = 36                  # 조회 기간 최대 개월 수
SHEET_ROWS = 1_000_000           # 엑셀 시트당 최대 행 (엑셀 한도 1,048,576)
MAX_EXPORT_ROWS = 2_000_000      # 엑셀 한 번에 내려받을 수 있는 최대 행

# 시즌: 계절 순서 (봄 → 여름 → 가을 → 겨울, 각 계절은 기본 → 기획)
SEASONS = ["봄", "봄기획", "여름", "여름기획", "가을", "가을기획", "겨울", "겨울기획"]

# (컬럼, 한글명, 형식) — 테이블 컬럼 순서
COLUMNS: list[tuple[str, str, str]] = [
    ("MAKE_YYMM", "판매년월", "text"),
    ("TEAM_CD", "팀", "text"),
    ("SHOP_ID", "매장코드", "text"),
    ("SHOP_NM", "매장명", "text"),
    ("PLAN_YY", "기획년도", "text"),
    ("SESS_NM", "시즌", "text"),
    ("PRDT_GRP_NM", "품군", "text"),
    ("ITEM_NM", "아이템", "text"),
    ("CHARGE_CLSBY_NM", "수수료구분", "text"),
    ("DSCT_CLSBY_NM", "판매형태", "text"),
    ("PRDT_CD", "상품", "text"),
    ("COLOR_CD", "색상", "text"),
    ("SIZE_CD", "사이즈", "text"),
    ("QTY", "수량", "int"),
    ("FIRST_PRICE", "최초가", "int"),
    ("REAL_SALE_PRICE", "판매단가", "int"),
    ("REAL_SALE_AMT_PRICE", "실판단가", "int"),
    ("REAL_SALE_AMT", "실판금액", "int"),
    ("DSCT_AMT", "할인금액", "int"),
    ("PRDT_CLSBY_NM", "생산형태", "text"),
    ("ACC_YN", "악세사리 구분", "text"),
    ("ONLINE_SALE", "온라인 판매 구분", "text"),
    ("GOODS_CLSBY_NM", "상품구분", "text"),
    ("PRODUCT_COST2", "제조원가(V+)", "int"),
]
COL_SQL = ", ".join(c for c, _, _ in COLUMNS)
# 요청 정렬은 판매년월, 매장코드. 페이지 간 순서가 흔들리지 않도록 뒤에 고유 순서를 덧붙인다.
ORDER_SQL = "ORDER BY MAKE_YYMM, SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, ROWID"

_YYMM = re.compile(r"^\d{6}$")


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


def _months(f: str, t: str) -> int:
    return (int(t[:4]) - int(f[:4])) * 12 + int(t[4:]) - int(f[4:]) + 1


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _where(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None) -> tuple[str, dict]:
    ym_from, ym_to = (ym_from or "").replace("-", ""), (ym_to or "").replace("-", "")
    if not (_YYMM.match(ym_from) and _YYMM.match(ym_to)) or not (1 <= int(ym_from[4:]) <= 12 and 1 <= int(ym_to[4:]) <= 12):
        _bad("판매년월은 YYYY-MM 형식으로 입력하세요.")
    if ym_from > ym_to:
        _bad("판매년월 시작이 종료보다 늦습니다.")
    if _months(ym_from, ym_to) > MAX_MONTHS:
        _bad(f"판매년월은 최대 {MAX_MONTHS}개월까지 조회할 수 있습니다.")

    conds, p = ["MAKE_YYMM BETWEEN :ym_from AND :ym_to"], {"ym_from": ym_from, "ym_to": ym_to}

    def _in(col: str, prefix: str, values: list[str], limit: int):
        if len(values) > limit:
            _bad(f"선택 가능한 개수({limit}개)를 넘었습니다.")
        binds = {f"{prefix}{i}": v for i, v in enumerate(values)}
        conds.append(f"{col} IN ({', '.join(':' + k for k in binds)})")
        p.update(binds)

    shop_list = _split(shops)
    if shop_list:
        if any(len(s) > 6 for s in shop_list):
            _bad("매장코드가 올바르지 않습니다.")
        _in("SHOP_ID", "shop", shop_list, 500)
    yy_list = _split(plan_yys)
    if yy_list:
        if any(not re.match(r"^\d{4}$", y) for y in yy_list):
            _bad("기획년도가 올바르지 않습니다.")
        _in("PLAN_YY", "yy", yy_list, 30)
    sess_list = _split(seasons)
    if sess_list:
        if any(s not in SEASONS for s in sess_list):
            _bad("시즌이 올바르지 않습니다.")
        _in("SESS_NM", "sess", sess_list, len(SEASONS))
    return " AND ".join(conds), p


def _row(r: tuple) -> dict:
    return {c: (int(v) if kind == "int" and v is not None and float(v).is_integer() else v)
            for (c, _, kind), v in zip(COLUMNS, r)}


def search(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None,
           page: int = 1, with_total: bool = True) -> dict:
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons)
    page = max(1, int(page))
    out: dict = {"page": page, "pageSize": PAGE_SIZE}
    if with_total:
        cnt, qty, amt, dsct = db.query(
            f"SELECT COUNT(*), NVL(SUM(QTY), 0), NVL(SUM(REAL_SALE_AMT), 0), NVL(SUM(DSCT_AMT), 0) "
            f"FROM T_CLOSE_SALE_BASE WHERE {where}", p)[1][0]
        out["summary"] = {"rows": int(cnt), "qty": int(qty), "realSaleAmt": int(amt), "dsctAmt": int(dsct)}
        out["total"] = int(cnt)
    rows = db.query(
        f"""SELECT {COL_SQL} FROM (
               SELECT A.*, ROWNUM RN FROM (
                   SELECT {COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} {ORDER_SQL}
               ) A WHERE ROWNUM <= :hi
            ) WHERE RN > :lo""",
        {**p, "hi": page * PAGE_SIZE, "lo": (page - 1) * PAGE_SIZE},
    )[1]
    out["rows"] = [_row(r) for r in rows]
    return out


def export_xlsx(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None) -> tuple[str, str]:
    """조회 조건 전체 결과를 엑셀 파일로 만든다. (임시 파일 경로, 파일명) 반환 — 호출부에서 전송 후 삭제."""
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons)
    total = db.query(f"SELECT COUNT(*) FROM T_CLOSE_SALE_BASE WHERE {where}", p)[1][0][0]
    if total == 0:
        _bad("조회된 데이터가 없습니다.")
    if total > MAX_EXPORT_ROWS:
        _bad(f"결과가 {total:,}건으로 엑셀 최대 {MAX_EXPORT_ROWS:,}건을 넘습니다. 기간·매장·시즌 조건을 좁혀 주세요.")

    fd, path = tempfile.mkstemp(suffix=".xlsx", prefix="sale_monthly_")
    os.close(fd)
    try:
        wb = xlsxwriter.Workbook(path, {"constant_memory": True})
        head = wb.add_format({"bold": True, "bg_color": "#E8ECF7", "border": 1, "align": "center", "valign": "vcenter"})
        num = wb.add_format({"num_format": "#,##0"})
        widths = [10, 8, 10, 22, 8, 9, 10, 12, 10, 10, 14, 7, 7, 8, 11, 11, 11, 13, 11, 10, 8, 10, 10, 12]
        ws, n_sheet, r_idx = None, 0, 0

        def new_sheet():
            nonlocal ws, n_sheet, r_idx
            n_sheet += 1
            ws = wb.add_worksheet("판매집계" if n_sheet == 1 else f"판매집계_{n_sheet}")
            for i, (_, label, _) in enumerate(COLUMNS):
                ws.write(0, i, label, head)
                ws.set_column(i, i, widths[i], num if COLUMNS[i][2] == "int" else None)
            ws.freeze_panes(1, 0)
            r_idx = 1

        new_sheet()
        with db.get_pool().acquire() as conn:
            cur = conn.cursor()
            cur.arraysize = 5000
            cur.prefetchrows = 5000
            cur.execute(f"SELECT {COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} {ORDER_SQL}", p)
            while True:
                batch = cur.fetchmany()
                if not batch:
                    break
                for r in batch:
                    if r_idx > SHEET_ROWS:
                        new_sheet()
                    ws.write_row(r_idx, 0, r)
                    r_idx += 1
        wb.close()
    except Exception:
        os.remove(path)
        raise
    ym = f"{ym_from.replace('-', '')}-{ym_to.replace('-', '')}"
    return path, f"월별매장별판매집계_{ym}_{date.today():%Y%m%d}.xlsx"


def options() -> dict:
    this_year = date.today().year
    return {
        "seasons": SEASONS,
        "planYears": [str(y) for y in range(this_year + 1, 2019, -1)],
        "columns": [{"key": c, "label": label, "type": kind} for c, label, kind in COLUMNS],
        "pageSize": PAGE_SIZE,
        "maxMonths": MAX_MONTHS,
        "maxExportRows": MAX_EXPORT_ROWS,
    }
