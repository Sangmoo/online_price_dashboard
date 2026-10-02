"""월별 매장별 판매 집계: T_CLOSE_SALE_BASE(마감 매출 기초 데이터) 조회 · 페이징 · 전체 엑셀."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from . import db, logs
from .xlsx_stream import XlsxStreamWriter

_log = logs.get("export")

PAGE_SIZE = 100
MAX_MONTHS = 36                  # 조회 기간 최대 개월 수
SHEET_ROWS = 1_000_000           # 엑셀 시트당 행 수. 넘으면 다음 시트에 이어서 쓴다 (엑셀 한도 1,048,576)
EXPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "exports"   # git 제외 폴더
EXPORT_KEEP_SEC = 2 * 60 * 60    # 완료된 엑셀 파일 보관 시간 (다시 받기 가능)
MAX_RUNNING_JOBS = 2             # 서버 전체 동시 생성 작업 수
WIDTHS = [10, 12, 10, 22, 8, 9, 10, 12, 10, 10, 14, 7, 7, 8, 11, 11, 11, 13, 11, 10, 8, 10, 10, 12]

# 시즌·품군 컬럼은 VARCHAR2(4000) 으로 선언돼 있어 그대로는 복합 인덱스에 넣을 수 없다(ORA-01450, 키 최대 6398바이트).
# 인덱스 IX_T_CLOSE_SALE_BASE_04 는 아래 식(앞 100바이트)으로 만들어져 있고, Oracle 은 쿼리에 같은 식이 있어야
# 그 인덱스를 쓰므로 조건·그룹핑에는 반드시 이 식을 사용한다. 실제 값은 최대 20바이트 수준이라 결과는 원래 컬럼과 같다.
SESS_EXPR = "SUBSTRB(SESS_NM, 1, 100)"
PRDT_GRP_EXPR = "SUBSTRB(PRDT_GRP_NM, 1, 100)"

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


MAX_IN = 1000  # Oracle IN 목록 최대 개수


def brand_filter(teams: list[str] | None, ym_from: str, ym_to: str, prefix: str = "bf") -> tuple[list[str], dict]:
    """브랜드 권한(허용 팀) 조건. teams=None 이면 조건 없음, [] 이면 아무 행도 없음.

    TEAM_CD 조건만 걸면 인덱스(판매년월, 매장코드…)만으로 끝나던 건수·합계가 테이블을 읽게 되어 느려진다.
    그래서 사전 집계 뷰가 최신이고 기간을 모두 담고 있으면, 허용 팀에서 팔린 매장코드를 먼저 찾아
    (판매년월 목록, 매장코드 목록) 조건으로 바꾼다. 결과가 같도록:
    - 기간 안에 허용 팀으로만 팔린 매장만 있으면 매장코드 조건만 쓴다 (팀 조건과 같은 행).
    - 다른 팀으로도 팔린 매장이 하나라도 있으면 팀 조건을 함께 건다.
    - 뷰를 쓸 수 없으면 팀 조건만 건다."""
    if teams is None:
        return [], {}
    if not teams:
        return ["1 = 0"], {}
    tb = {f"{prefix}t{i}": t for i, t in enumerate(teams)}
    team_cond = f"TEAM_CD IN ({', '.join(':' + k for k in tb)})"
    from . import chat_tools_sale as cts  # 순환 import 방지

    st = cts.mv_state()
    if not (st["usable"] and st["mv_max"] and ym_to <= st["mv_max"]):
        return [team_cond], tb
    rows = db.query(
        f"""SELECT SHOP_ID, MIN(CASE WHEN TEAM_CD IN ({', '.join(':' + k for k in tb)}) THEN 1 ELSE 0 END)
              FROM {cts.MV_NAME} WHERE MAKE_YYMM BETWEEN :{prefix}f AND :{prefix}t
             GROUP BY SHOP_ID HAVING MAX(CASE WHEN TEAM_CD IN ({', '.join(':' + k for k in tb)}) THEN 1 ELSE 0 END) = 1""",
        {**tb, f"{prefix}f": ym_from, f"{prefix}t": ym_to})[1]
    if not rows:
        return ["1 = 0"], {}
    shop_ids = sorted(r[0] for r in rows)
    mixed = any(int(r[1]) == 0 for r in rows)
    if len(shop_ids) > MAX_IN:
        return [team_cond], tb
    mb = {f"{prefix}m{i}": m for i, m in enumerate(_month_list(ym_from, ym_to))}
    sb = {f"{prefix}s{i}": v for i, v in enumerate(shop_ids)}
    conds = [f"MAKE_YYMM IN ({', '.join(':' + k for k in mb)})", f"SHOP_ID IN ({', '.join(':' + k for k in sb)})"]
    binds = {**mb, **sb}
    if mixed:
        conds.append(team_cond)
        binds.update(tb)
    return conds, binds


_brand_shops_cache: dict[tuple, tuple[float, set[str]]] = {}


def brand_shop_ids(teams: list[str]) -> set[str]:
    """허용 팀에서 판매 기록이 있는 매장코드 (매장 선택 팝업 거르기용, 사전 집계 뷰 전체 기간, 10분 캐시)"""
    key = tuple(sorted(teams))
    hit = _brand_shops_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    from . import chat_tools_sale as cts

    if not teams:
        out: set[str] = set()
    else:
        tb = {f"t{i}": t for i, t in enumerate(teams)}
        out = {r[0] for r in db.query(f"SELECT DISTINCT SHOP_ID FROM {cts.MV_NAME} WHERE TEAM_CD IN ({', '.join(':' + k for k in tb)})",
                                      tb)[1]}
    if len(_brand_shops_cache) > 50:
        _brand_shops_cache.clear()
    _brand_shops_cache[key] = (time.time() + 600, out)
    return out


def _where(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None,
           teams: list[str] | None = None) -> tuple[str, dict]:
    """teams: 브랜드 권한으로 허용된 팀 (None = 모든 브랜드)"""
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
        # 기간(BETWEEN)만 있으면 기간 안의 모든 매장 인덱스를 훑은 뒤 매장을 거른다(수 초).
        # 월 목록(IN)을 함께 주면 (판매년월, 매장코드) 조합을 인덱스에서 바로 찾는다(수십 ms). 결과는 같다.
        _in("MAKE_YYMM", "ym", _month_list(ym_from, ym_to), MAX_MONTHS)
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
        _in(SESS_EXPR, "sess", sess_list, len(SEASONS))
    bconds, bbinds = brand_filter(teams, ym_from, ym_to)
    conds += bconds
    p.update(bbinds)
    return " AND ".join(conds), p


def _row(r: tuple) -> dict:
    return {c: (int(v) if kind == "int" and v is not None and float(v).is_integer() else v)
            for (c, _, kind), v in zip(COLUMNS, r)}


# 조회 결과 월별 건수/합계 캐시. 마감 데이터라 자주 바뀌지 않으므로 같은 조건의 페이지 이동은 캐시로 위치를 계산한다.
STATS_TTL = 10 * 60
_stats_cache: dict[tuple, tuple[float, object]] = {}
_stats_lock = threading.Lock()


def _cached(kind: str, where: str, p: dict, fn):
    key = (kind, where, tuple(sorted(p.items())))
    now = time.time()
    with _stats_lock:
        hit = _stats_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    val = fn()
    with _stats_lock:
        if len(_stats_cache) > 500:
            _stats_cache.clear()
        _stats_cache[key] = (now + STATS_TTL, val)
    return val


def _month_stats(where: str, p: dict) -> list[tuple[str, int, int, int]]:
    """(판매년월, 건수, 수량, 실판금액). 매장 조건까지는 인덱스(IX_03)만으로 계산되어 36개월도 수 초 안에 끝난다."""
    return _cached("months", where, p, lambda: [
        (ym, int(c), int(q or 0), int(a or 0))
        for ym, c, q, a in db.query(
            f"SELECT MAKE_YYMM, COUNT(*), SUM(QTY), SUM(REAL_SALE_AMT) FROM T_CLOSE_SALE_BASE WHERE {where} "
            "GROUP BY MAKE_YYMM ORDER BY MAKE_YYMM", p)[1]
    ])


def search(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None,
           page: int = 1, with_total: bool = True, teams: list[str] | None = None) -> dict:
    """정렬(판매년월 → 매장코드 …)의 첫 키가 판매년월이므로, 월별 건수로 페이지가 걸친 월을 찾아 그 월만 정렬해 가져온다.
    전체 기간을 한 번에 정렬하면 36개월(1,400만 행)에서 페이지마다 수십 초가 걸린다."""
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons, teams)
    page = max(1, int(page))
    months = _month_stats(where, p)
    total = sum(m[1] for m in months)
    out: dict = {"page": page, "pageSize": PAGE_SIZE, "total": total}
    if with_total:
        out["summary"] = {"rows": total, "qty": sum(m[2] for m in months), "realSaleAmt": sum(m[3] for m in months)}

    lo, need, acc, rows = (page - 1) * PAGE_SIZE, PAGE_SIZE, 0, []
    for ym, cnt, _, _ in months:
        if need <= 0:
            break
        if lo >= acc + cnt:
            acc += cnt
            continue
        local_lo = lo - acc
        got = db.query(
            f"""SELECT {COL_SQL} FROM (
                   SELECT A.*, ROWNUM RN FROM (
                       SELECT {COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} AND MAKE_YYMM = :cur_ym {ORDER_SQL}
                   ) A WHERE ROWNUM <= :hi
                ) WHERE RN > :lo""",
            {**p, "cur_ym": ym, "hi": local_lo + need, "lo": local_lo},
        )[1]
        rows += got
        need -= len(got)
        acc += cnt
        lo = acc  # 다음 월은 처음부터
    out["rows"] = [_row(r) for r in rows]
    return out


def dsct_total(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None,
               teams: list[str] | None = None) -> dict:
    """할인금액 합계는 인덱스에 없어 테이블을 읽어야 하므로(36개월 약 40초) 화면에서 따로 요청한다."""
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons, teams)
    val = _cached("dsct", where, p, lambda: int(db.query(
        f"SELECT NVL(SUM(DSCT_AMT), 0) FROM T_CLOSE_SALE_BASE WHERE {where}", p)[1][0][0] or 0))
    return {"dsctAmt": val}


# ----------------------------------------------------------------------------
# 요약: 월·매장·기획년도·시즌·품군별 합계 + 전년 동기 비교
# ----------------------------------------------------------------------------
SUMMARY_DIMS = {
    "month": ("MAKE_YYMM", "판매년월"),
    "shop": ("SHOP_ID", "매장"),
    "plan_yy": ("PLAN_YY", "기획년도"),
    "season": (SESS_EXPR, "시즌"),
    "prdt_grp": (PRDT_GRP_EXPR, "품군"),
}


def _shift_ym(ym: str, months: int) -> str:
    y, m = divmod(int(ym[:4]) * 12 + int(ym[4:6]) - 1 + months, 12)
    return f"{y:04d}{m + 1:02d}"


def shop_names(ids: list[str]) -> dict[str, str]:
    ids = [i for i in dict.fromkeys(ids) if i]
    out: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        binds = {f"s{j}": v for j, v in enumerate(ids[i:i + 500])}
        out.update(db.query(f"SELECT SHOP_ID, SHOP_NM FROM T_SHOP WHERE SHOP_ID IN ({', '.join(':' + k for k in binds)})",
                            binds)[1])
    return out


def _group(where: str, p: dict, col: str) -> dict:
    # 원가 금액 = 제조원가(V+) × 수량. 월·매장 묶음은 Oracle 이 사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM)로 자동 재작성해 즉시 계산된다.
    sql = (f"SELECT {col} AS K, COUNT(DISTINCT SHOP_ID), NVL(SUM(QTY), 0), NVL(SUM(REAL_SALE_AMT), 0), NVL(SUM(DSCT_AMT), 0), "
           f"NVL(SUM(PRODUCT_COST2 * QTY), 0) FROM T_CLOSE_SALE_BASE WHERE {where} GROUP BY {col}")
    return _cached(f"group2:{col}", where, p, lambda: {
        k: (int(s), int(q), int(a), int(d), int(c)) for k, s, q, a, d, c in db.query(sql, p)[1]
    })


def _rate(cost: int, amt: int) -> float | None:
    """원가율(%) = 원가 금액 / 실판금액 × 100"""
    return round(cost * 100 / amt, 1) if amt else None


def summary(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None, dim: str,
            teams: list[str] | None = None) -> dict:
    """전년 동기 = 판매년월을 12개월 앞당기고, 기획년도 조건이 있으면 기획년도도 1년 앞당긴 같은 조건.
    (예: 2026-01~08 · 2026 기획 ↔ 2025-01~08 · 2025 기획)"""
    if dim not in SUMMARY_DIMS:
        _bad(f"요약 기준은 {list(SUMMARY_DIMS)} 중 하나입니다.")
    col, label = SUMMARY_DIMS[dim]
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons, teams)
    prev_from, prev_to = _shift_ym(p["ym_from"], -12), _shift_ym(p["ym_to"], -12)
    prev_yys = ",".join(str(int(y) - 1) for y in _split(plan_yys)) or None
    pwhere, pp = _where(prev_from, prev_to, shops, prev_yys, seasons, teams)
    with ThreadPoolExecutor(max_workers=2) as ex:
        cur_f, prev_f = ex.submit(_group, where, p, col), ex.submit(_group, pwhere, pp, col)
        cur, prev = cur_f.result(), prev_f.result()

    # 전년 행과 맞출 키: 월은 +12개월, 기획년도는 +1년, 나머지는 같은 값
    def to_cur(k):
        if k is None:
            return None
        if dim == "month":
            return _shift_ym(k, 12)
        if dim == "plan_yy" and str(k).isdigit():
            return str(int(k) + 1)
        return k

    prev_by = {to_cur(k): v for k, v in prev.items()}
    keys = list(dict.fromkeys(list(cur) + ([k for k in prev_by if k not in cur] if dim != "month" else [])))
    if dim == "month":
        keys = sorted(cur)
    names = shop_names([k for k in keys if k]) if dim == "shop" else {}
    total_amt = sum(v[2] for v in cur.values()) or 1
    rows = []
    for k in keys:
        s, q, a, d, c = cur.get(k, (0, 0, 0, 0, 0))
        ps, pq, pa, pd, pc = prev_by.get(k, (0, 0, 0, 0, 0))
        rate, prate = _rate(c, a), _rate(pc, pa)
        rows.append({
            "key": k, "label": (f"{k[:4]}-{k[4:]}" if dim == "month" and k else names.get(k, k) if dim == "shop" else k) or "(없음)",
            "shopNm": names.get(k) if dim == "shop" else None,
            "shops": s, "qty": q, "amt": a, "dsct": d, "share": round(a * 100 / total_amt, 1),
            "prevKey": (_shift_ym(k, -12) if dim == "month" and k else str(int(k) - 1) if dim == "plan_yy" and k and str(k).isdigit() else k),
            "prevQty": pq, "prevAmt": pa,
            "growth": round((a / pa - 1) * 100, 1) if pa else None,
            "cost": c, "costRate": rate, "prevCostRate": prate,
            "costRateDiff": round(rate - prate, 1) if rate is not None and prate is not None else None,
        })
    if dim == "month":
        rows.sort(key=lambda r: r["key"] or "")
    elif dim == "season":
        rows.sort(key=lambda r: SEASONS.index(r["key"]) if r["key"] in SEASONS else 99)
    elif dim == "plan_yy":
        rows.sort(key=lambda r: r["key"] or "", reverse=True)
    else:
        rows.sort(key=lambda r: r["amt"], reverse=True)
    tot = lambda src, i: sum(v[i] for v in src.values())  # noqa: E731
    t_amt, t_cost, p_amt, p_cost = tot(cur, 2), tot(cur, 4), tot(prev, 2), tot(prev, 4)
    t_rate, p_rate = _rate(t_cost, t_amt), _rate(p_cost, p_amt)
    return {
        "dim": dim, "dimLabel": label, "rows": rows,
        "period": {"from": p["ym_from"], "to": p["ym_to"], "prevFrom": prev_from, "prevTo": prev_to,
                   "planYys": _split(plan_yys), "prevPlanYys": _split(prev_yys)},
        "total": {"qty": tot(cur, 1), "amt": tot(cur, 2), "dsct": tot(cur, 3),
                  "prevQty": tot(prev, 1), "prevAmt": tot(prev, 2),
                  "growth": round((tot(cur, 2) / tot(prev, 2) - 1) * 100, 1) if tot(prev, 2) else None,
                  "cost": t_cost, "costRate": t_rate, "prevCostRate": p_rate,
                  "costRateDiff": round(t_rate - p_rate, 1) if t_rate is not None and p_rate is not None else None},
    }


def shop_trend(shop_id: str, months: int = 12, teams: list[str] | None = None) -> dict:
    """매장 최근 N개월(지난달까지) 월별 판매와 전년 같은 달 비교. (판매년월, 매장코드) 인덱스로 빠르게 조회."""
    shop_id = (shop_id or "").strip().upper()
    if not shop_id or len(shop_id) > 6:
        _bad("매장코드가 올바르지 않습니다.")
    last = _shift_ym(date.today().strftime("%Y%m"), -1)
    first = _shift_ym(last, -(months - 1))
    # 기간을 BETWEEN 으로 주면 24개월치 모든 매장 인덱스를 훑어 약 2초, 월 목록(IN)으로 주면 월별로 바로 찾아 수십 ms
    binds = {f"m{i}": ym for i, ym in enumerate(_month_list(_shift_ym(first, -12), last))}
    team_sql = ""
    if teams is not None:  # 브랜드 권한: 허용 팀의 판매만
        tb = {f"t{i}": t for i, t in enumerate(teams or ["-"])}
        team_sql = f" AND TEAM_CD IN ({', '.join(':' + k for k in tb)})"
        binds.update(tb)
    rows = db.query(
        "SELECT MAKE_YYMM, NVL(SUM(QTY), 0), NVL(SUM(REAL_SALE_AMT), 0) FROM T_CLOSE_SALE_BASE "
        f"WHERE MAKE_YYMM IN ({', '.join(':' + k for k in binds if k.startswith('m'))}) AND SHOP_ID = :shop{team_sql} GROUP BY MAKE_YYMM",
        {**binds, "shop": shop_id})[1]
    by = {ym: (int(q), int(a)) for ym, q, a in rows}
    out, ym = [], first
    for _ in range(months):
        q, a = by.get(ym, (0, 0))
        pq, pa = by.get(_shift_ym(ym, -12), (0, 0))
        out.append({"ym": ym, "qty": q, "amt": a, "prevQty": pq, "prevAmt": pa,
                    "growth": round((a / pa - 1) * 100, 1) if pa else None})
        ym = _shift_ym(ym, 1)
    amt, pamt = sum(r["amt"] for r in out), sum(r["prevAmt"] for r in out)
    return {"shopId": shop_id, "shopNm": shop_names([shop_id]).get(shop_id), "from": first, "to": last, "months": out,
            "total": {"qty": sum(r["qty"] for r in out), "amt": amt, "prevQty": sum(r["prevQty"] for r in out),
                      "prevAmt": pamt, "growth": round((amt / pamt - 1) * 100, 1) if pamt else None}}


# ----------------------------------------------------------------------------
# 전체 엑셀: 백그라운드 작업 (행 수 제한 없음, 시트당 SHEET_ROWS 행)
# 36개월이면 1,400만 행 이상이라 요청 하나로 기다릴 수 없으므로 작업을 만들고 진행률을 조회한다.
# 월 단위로 나눠 조회해 DB 정렬 부담을 줄이고, 결과 순서는 판매년월 → 매장코드 순 그대로 유지된다.
# ----------------------------------------------------------------------------
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _month_list(f: str, t: str) -> list[str]:
    y, m, out = int(f[:4]), int(f[4:]), []
    while f"{y:04d}{m:02d}" <= t:
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _public(job: dict) -> dict:
    now = time.time()
    return {
        "id": job["id"], "status": job["status"], "total": job["total"], "written": job["written"],
        "sheets": max(1, -(-job["written"] // SHEET_ROWS)) if job["written"] else 0,
        "startedAt": job["started"], "elapsedSec": int((job["finished"] or now) - job["started"]),
        "fileName": job["file_name"], "fileSize": job["file_size"], "error": job["error"], "cond": job["cond"],
    }


def cleanup_exports() -> None:
    """보관 시간이 지난 작업·파일 삭제. 서버 재시작 전 남은 파일도 정리."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with _jobs_lock:
        for jid, j in list(_jobs.items()):
            if j["status"] != "running" and (j["finished"] or now) + EXPORT_KEEP_SEC < now:
                _jobs.pop(jid, None)
        live = {j["path"] for j in _jobs.values()}
    for f in EXPORT_DIR.glob("*.xlsx"):
        if str(f) not in live:
            try:
                f.unlink()
            except OSError:
                pass


def start_export(usr_id: str, ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None,
                 seasons: str | None, teams: list[str] | None = None) -> dict:
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons, teams)
    cleanup_exports()
    with _jobs_lock:
        mine = [j for j in _jobs.values() if j["usr_id"] == usr_id and j["status"] == "running"]
        if mine:
            raise HTTPException(status_code=409, detail={"message": "이미 엑셀을 만들고 있습니다. 끝나거나 취소한 뒤 다시 요청하세요.",
                                                         "code": "EXPORT_RUNNING", "job": _public(mine[0])})
        if sum(j["status"] == "running" for j in _jobs.values()) >= MAX_RUNNING_JOBS:
            raise HTTPException(status_code=429, detail={"message": "다른 사용자의 대용량 엑셀 작업이 진행 중입니다. 잠시 후 다시 시도하세요.",
                                                         "code": "EXPORT_BUSY"})
    total = sum(m[1] for m in _month_stats(where, p))
    if total == 0:
        _bad("조회된 데이터가 없습니다.")
    f, t = p["ym_from"], p["ym_to"]
    jid = uuid.uuid4().hex
    job = {
        "id": jid, "usr_id": usr_id, "status": "running", "total": total, "written": 0,
        "started": time.time(), "finished": None, "error": None, "cancel": False,
        "path": str(EXPORT_DIR / f"{jid}.xlsx"), "file_size": None,
        "file_name": f"월별매장별판매집계_{f}-{t}_{date.today():%Y%m%d}.xlsx",
        "cond": {"ymFrom": f, "ymTo": t, "shops": shops or "", "planYys": plan_yys or "", "seasons": seasons or ""},
    }
    with _jobs_lock:
        _jobs[jid] = job
    _log.info("엑셀 시작 job=%s user=%s rows=%d cond=%s", jid[:8], usr_id, total, job["cond"])
    threading.Thread(target=_run_export, args=(job, where, p), daemon=True, name=f"export-{jid[:8]}").start()
    return _public(job)


def _run_export(job: dict, where: str, p: dict) -> None:
    try:
        with XlsxStreamWriter(job["path"], [label for _, label, _ in COLUMNS], [k for _, _, k in COLUMNS], WIDTHS,
                              sheet_name="판매집계", sheet_rows=SHEET_ROWS) as w:
            with db.get_pool().acquire() as conn:
                cur = conn.cursor()
                cur.arraysize = 5000
                cur.prefetchrows = 5000
                for ym in _month_list(p["ym_from"], p["ym_to"]):
                    cur.execute(f"SELECT {COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} AND MAKE_YYMM = :cur_ym {ORDER_SQL}",
                                {**p, "cur_ym": ym})
                    while batch := cur.fetchmany():
                        if job["cancel"]:
                            raise InterruptedError
                        w.write_rows(batch)
                        job["written"] = w.total
        job["file_size"] = os.path.getsize(job["path"])
        job["status"] = "done"
    except InterruptedError:
        job["status"] = "cancelled"
    except Exception as ex:  # noqa: BLE001 - 작업 실패는 상태로 전달
        job["status"] = "error"
        job["error"] = f"엑셀 생성 중 오류가 발생했습니다: {ex}"
        _log.exception("엑셀 실패 job=%s user=%s", job["id"][:8], job["usr_id"])
    finally:
        job["finished"] = time.time()
        _log.info("엑셀 %s job=%s user=%s rows=%d/%d %.0fs size=%s", job["status"], job["id"][:8], job["usr_id"],
                  job["written"], job["total"], job["finished"] - job["started"], job["file_size"])
        if job["status"] != "done":
            try:
                os.remove(job["path"])
            except OSError:
                pass


def _own_job(usr_id: str, job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["usr_id"] != usr_id:
        raise HTTPException(status_code=404, detail={"message": "엑셀 작업을 찾을 수 없습니다. 다시 요청하세요.", "code": "NOT_FOUND"})
    return job


def export_status(usr_id: str, job_id: str) -> dict:
    return _public(_own_job(usr_id, job_id))


def current_export(usr_id: str) -> dict | None:
    """화면 재진입 시 이어서 보여줄 작업 (진행 중이거나 받을 수 있는 최근 작업)."""
    cleanup_exports()
    with _jobs_lock:
        mine = sorted((j for j in _jobs.values() if j["usr_id"] == usr_id and j["status"] in ("running", "done")),
                      key=lambda j: j["started"], reverse=True)
    return _public(mine[0]) if mine else None


def cancel_export(usr_id: str, job_id: str) -> dict:
    job = _own_job(usr_id, job_id)
    job["cancel"] = True
    if job["status"] == "done":  # 완료 후 취소 = 파일 삭제
        job["status"] = "cancelled"
        try:
            os.remove(job["path"])
        except OSError:
            pass
    return _public(job)


def export_file(usr_id: str, job_id: str) -> tuple[str, str]:
    job = _own_job(usr_id, job_id)
    if job["status"] != "done" or not os.path.exists(job["path"]):
        _bad("아직 엑셀 파일이 준비되지 않았습니다.")
    return job["path"], job["file_name"]


def options() -> dict:
    this_year = date.today().year
    return {
        "seasons": SEASONS,
        "planYears": [str(y) for y in range(this_year + 1, 2019, -1)],
        "columns": [{"key": c, "label": label, "type": kind} for c, label, kind in COLUMNS],
        "pageSize": PAGE_SIZE,
        "maxMonths": MAX_MONTHS,
        "sheetRows": SHEET_ROWS,
        "summaryDims": [{"key": k, "label": v[1]} for k, v in SUMMARY_DIMS.items()],
    }


def shop_mix(shop_id: str, months: int = 12, teams: list[str] | None = None, top_items: int = 8) -> dict:
    """매장 정보 팝업: 최근 N개월(지난달까지) 판매형태(행사/정상/세일…) 구성과 주력 아이템, 같은 브랜드 전체 판매형태 비중.
    매장 하나는 (판매년월, 매장코드) 인덱스로 12개월 0.1초 수준. 브랜드 평균은 상품 사전 집계 뷰가 최신일 때만."""
    from . import sale_dashboard as sd
    from . import sale_products as sp

    shop_id = (shop_id or "").strip().upper()
    last = _shift_ym(date.today().strftime("%Y%m"), -1)
    month_list = _month_list(_shift_ym(last, -(months - 1)), last)
    binds = {f"m{i}": ym for i, ym in enumerate(month_list)}
    team_sql = ""
    if teams is not None:
        tb = {f"t{i}": t for i, t in enumerate(teams or ["-"])}
        team_sql = f" AND TEAM_CD IN ({', '.join(':' + k for k in tb)})"
        binds.update(tb)
    rows = db.query(
        f"""SELECT GROUPING_ID(ITEM_NM, DSCT_CLSBY_NM, TEAM_CD), ITEM_NM, DSCT_CLSBY_NM, TEAM_CD,
                   NVL(SUM(REAL_SALE_AMT), 0), NVL(SUM(QTY), 0), NVL(SUM(DSCT_AMT), 0)
              FROM T_CLOSE_SALE_BASE
             WHERE MAKE_YYMM IN ({', '.join(':' + k for k in binds if k.startswith('m'))}) AND SHOP_ID = :shop{team_sql}
             GROUP BY GROUPING SETS ((ITEM_NM), (DSCT_CLSBY_NM), (TEAM_CD))""", {**binds, "shop": shop_id})[1]
    items, types, team_amt = [], [], {}
    for gid, item, typ, team, amt, qty, dsct in rows:
        row = {"amt": int(amt), "qty": int(qty), "dsctRate": sd._dsct_rate(int(dsct), int(amt))}
        if gid == 3:      # ITEM_NM
            items.append({"name": item or "(없음)", **row})
        elif gid == 5:    # DSCT_CLSBY_NM
            types.append({"name": typ or "(없음)", **row})
        else:             # TEAM_CD
            team_amt[team] = int(amt)
    tot = sum(t["amt"] for t in types)
    for x in items + types:
        x["share"] = round(x["amt"] * 100 / tot, 1) if tot else None
    items.sort(key=lambda x: x["amt"], reverse=True)
    types.sort(key=lambda x: x["amt"], reverse=True)
    brand = sd.brand_of(max(team_amt, key=team_amt.get)) if team_amt else None
    brand_types = None
    st = sp.mv_state()
    if brand and tot and st["usable"] and st["mv_max"] and last <= st["mv_max"]:
        bteams = sd.brand_teams().get(brand) or []
        if teams is not None:
            bteams = [t for t in bteams if t in set(teams)]
        if bteams:
            mb = {f"m{i}": ym for i, ym in enumerate(month_list)}
            tb2 = {f"b{i}": t for i, t in enumerate(bteams)}
            brows = db.query(f"""SELECT DSCT_CLSBY_NM, SUM(TOTAL_SALE_AMT) FROM {sp.MV_NAME}
                                  WHERE MAKE_YYMM IN ({', '.join(':' + k for k in mb)}) AND TEAM_CD IN ({', '.join(':' + k for k in tb2)})
                                  GROUP BY DSCT_CLSBY_NM""", {**mb, **tb2})[1]
            btot = sum(int(a or 0) for _, a in brows)
            brand_types = {(n or "(없음)"): round(int(a or 0) * 100 / btot, 1) for n, a in brows} if btot else None
    if brand_types:
        for t in types:
            t["brandShare"] = brand_types.get(t["name"], 0.0)
            t["shareDiff"] = round(t["share"] - t["brandShare"], 1) if t["share"] is not None else None
    return {"from": month_list[0], "to": last, "brand": brand, "amt": tot, "salesTypes": types, "items": items[:top_items],
            "itemCount": len(items), "brandAvg": brand_types is not None}
