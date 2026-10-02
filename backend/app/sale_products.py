"""판매 현황 > 상품 순위 · 아이템/품군 전년 비교 · 판매형태 구성, 상품 팝업의 월별 매장 판매.

- 상품 순위: 기간 안의 순위만 (품번은 시즌마다 새로 나와 품번 단위 전년 비교는 의미가 없다).
- 전년(비교 기간) 비교: 아이템 · 품군 단위.
- 판매형태(DSCT_CLSBY_NM: 행사/정상/세일 …) 구성: 비중 · 비교 기간 대비 · 월별 비중 추이.
조건(기간 · 비교 기준 · 브랜드 · 브랜드 권한)은 판매 현황(sale_dashboard.resolve)과 같다.

원천: 상품 사전 집계 뷰 MV_CLOSE_SALE_PRDT_YM (db/create_mv_close_sale_prdt_ym.sql) 가 최신이고 기간을 담고 있으면 뷰,
아니면 원본 T_CLOSE_SALE_BASE — 원본은 상품 단위 집계가 무거워(1개월 약 6초, 12개월 80초 이상) 기간·비교 기간이 각 1개월일 때만 계산한다.
"""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException

from . import config, db
from . import sale_dashboard as sd
from . import sale_monthly as sm

MV_NAME = f"{config.DB_OWNER_SCHEMA}.MV_CLOSE_SALE_PRDT_YM"
TOP_N = 20
MIN_AMT_FOR_DSCT_RANK = 5_000_000   # 할인율 순위: 기간 실판금액 500만원 이상 상품만 (소량 상품의 극단값 제외)
CACHE_TTL = 10 * 60
STATE_TTL = 60
_cache: dict[tuple, tuple[float, dict]] = {}
_state: tuple[float, dict] | None = None
_lock = threading.Lock()

# 원천별 컬럼 (뷰는 이미 합계, 원본은 행 단위)
_SRC = {
    "mv": {"table": MV_NAME, "grp": "PRDT_GRP_NM", "amt": "TOTAL_SALE_AMT", "qty": "TOTAL_QTY", "dsct": "TOTAL_DSCT_AMT"},
    "base": {"table": "T_CLOSE_SALE_BASE", "grp": sm.PRDT_GRP_EXPR, "amt": "REAL_SALE_AMT", "qty": "QTY", "dsct": "DSCT_AMT"},
}


def mv_state() -> dict:
    """상품 사전 집계 뷰: 있는지 · 최신(FRESH)인지 · 최신 월 (1분 캐시)"""
    global _state
    now = time.time()
    with _lock:
        if _state and _state[0] > now:
            return _state[1]
    st = {"exists": False, "usable": False, "mv_max": None, "staleness": None}
    try:
        info = db.query("SELECT STALENESS FROM ALL_MVIEWS WHERE OWNER = :o AND MVIEW_NAME = 'MV_CLOSE_SALE_PRDT_YM'",
                        {"o": config.DB_OWNER_SCHEMA})[1]
        if info:
            st["exists"], st["staleness"] = True, info[0][0]
            st["mv_max"] = db.query(f"SELECT MAX(MAKE_YYMM) FROM {MV_NAME}")[1][0][0]
            st["usable"] = st["mv_max"] is not None and st["staleness"] in (None, "FRESH")
    except Exception:  # noqa: BLE001 - 뷰가 없거나 권한이 없으면 원본
        pass
    with _lock:
        _state = (now + STATE_TTL, st)
    return st


def clear_cache() -> None:
    global _state
    with _lock:
        _cache.clear()
        _state = None


def _source(months: list[str]) -> str | None:
    st = mv_state()
    if st["usable"] and st["mv_max"] and max(months) <= st["mv_max"]:
        return "mv"
    return None


def _in(values: list[str], prefix: str) -> tuple[str, dict]:
    b = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return ", ".join(":" + k for k in b), b


def _dr(dsct: float, amt: float) -> float | None:
    gross = amt + dsct
    return round(dsct * 100 / gross, 1) if gross else None


def _rate(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 1) if b else None


def analyze(ym: str | None = None, frm: str | None = None, cmp: str | None = None, cmp_from: str | None = None,
            cmp_to: str | None = None, brand: str | None = None, allowed: list[str] | None = None) -> dict:
    r = sd.resolve(ym, frm, cmp, cmp_from, cmp_to, brand, allowed)
    period, base, teams = r["period"], r["base"], r["teams"]
    meta = {"period": sd.period_label(period), "base": sd.period_label(base), "baseKind": sd.CMP_KINDS[r["kind"]],
            "brand": r["brand"]}
    src = _source(period + base)
    if src is None:
        if len(period) > 1 or len(base) > 1:
            return {**meta, "unavailable": "기간 또는 비교 기간이 1개월을 넘으면 상품 사전 집계 뷰가 필요합니다 "
                                          "(관리자: db/create_mv_close_sale_prdt_ym.sql 실행 후 [지금 갱신]). 1개월로 조회하면 원본에서 계산합니다."}
        src = "base"
    key = (src, tuple(period), tuple(base), tuple(teams) if teams is not None else None)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return {**meta, **hit[1]}
    out = _compute(src, period, base, teams)
    with _lock:
        if len(_cache) > 50:
            _cache.clear()
        _cache[key] = (time.time() + CACHE_TTL, out)
    return {**meta, **out}


def _compute(src: str, period: list[str], base: list[str], teams: list[str] | None) -> dict:
    c = _SRC[src]
    agg = f"SUM({c['amt']}), SUM({c['qty']}), SUM({c['dsct']})"
    team_sql, tb = "", {}
    if teams is not None:
        tinl, tb = _in(teams or ["-"], "t")
        team_sql = f" AND TEAM_CD IN ({tinl})"

    # 1) 상품 (기간만)
    pinl, pb = _in(period, "p")
    prods = []
    for cd, item, grp, amt, qty, dsct in db.query(
            f"""SELECT PRDT_CD, MAX(ITEM_NM), MAX({c['grp']}), {agg} FROM {c['table']}
                 WHERE MAKE_YYMM IN ({pinl}){team_sql} GROUP BY PRDT_CD""", {**pb, **tb})[1]:
        amt, qty, dsct = int(amt or 0), int(qty or 0), int(dsct or 0)
        prods.append({"prdtCd": cd, "itemNm": item, "prdtGrpNm": grp, "amt": amt, "qty": qty, "dsct": dsct, "dsctRate": _dr(dsct, amt)})
    total_amt = sum(p["amt"] for p in prods) or 1
    for p in prods:
        p["share"] = round(p["amt"] * 100 / total_amt, 2)
    selling = [p for p in prods if p["amt"] > 0]
    rankings = {
        "amt": sorted(selling, key=lambda p: p["amt"], reverse=True)[:TOP_N],
        "qty": sorted(selling, key=lambda p: p["qty"], reverse=True)[:TOP_N],
        "dsctRate": sorted((p for p in selling if p["amt"] >= MIN_AMT_FOR_DSCT_RANK and p["dsctRate"] is not None),
                           key=lambda p: p["dsctRate"], reverse=True)[:TOP_N],
    }

    # 2) 아이템 · 품군 · 판매형태 (기간 + 비교 기간, 월별) — 한 번에
    months = sorted(set(period) | set(base))
    minl, mb = _in(months, "m")
    sp, sb = set(period), set(base)
    groups: dict[str, dict[str, dict]] = {"item": {}, "grp": {}, "type": {}}
    type_month: dict[str, dict[str, int]] = {}
    for gid, ym, item, grp, typ, amt, qty, dsct in db.query(
            f"""SELECT GROUPING_ID(ITEM_NM, {c['grp']}, DSCT_CLSBY_NM), MAKE_YYMM, ITEM_NM, {c['grp']}, DSCT_CLSBY_NM, {agg}
                  FROM {c['table']} WHERE MAKE_YYMM IN ({minl}){team_sql}
                 GROUP BY GROUPING SETS ((MAKE_YYMM, ITEM_NM), (MAKE_YYMM, {c['grp']}), (MAKE_YYMM, DSCT_CLSBY_NM))""",
            {**mb, **tb})[1]:
        kind, name = ("item", item) if gid == 3 else ("grp", grp) if gid == 5 else ("type", typ)
        name = name or "(없음)"
        g = groups[kind].setdefault(name, {"name": name, "amt": 0, "qty": 0, "dsct": 0, "baseAmt": 0, "baseQty": 0, "baseDsct": 0})
        amt, qty, dsct = int(amt or 0), int(qty or 0), int(dsct or 0)
        if ym in sp:
            g["amt"] += amt
            g["qty"] += qty
            g["dsct"] += dsct
            if kind == "type":
                type_month.setdefault(ym, {})[name] = type_month.get(ym, {}).get(name, 0) + amt
        if ym in sb:
            g["baseAmt"] += amt
            g["baseQty"] += qty
            g["baseDsct"] += dsct

    def finish(kind: str) -> list[dict]:
        rows = list(groups[kind].values())
        tot, btot = sum(x["amt"] for x in rows) or 0, sum(x["baseAmt"] for x in rows) or 0
        for x in rows:
            x["change"] = _rate(x["amt"], x["baseAmt"])
            x["share"] = round(x["amt"] * 100 / tot, 1) if tot else None
            x["baseShare"] = round(x["baseAmt"] * 100 / btot, 1) if btot else None
            x["shareDiff"] = round(x["share"] - x["baseShare"], 1) if x["share"] is not None and x["baseShare"] is not None else None
            x["dsctRate"], x["baseDsctRate"] = _dr(x["dsct"], x["amt"]), _dr(x["baseDsct"], x["baseAmt"])
        return sorted((x for x in rows if x["amt"] or x["baseAmt"]), key=lambda x: x["amt"], reverse=True)

    types = finish("type")
    type_names = [t["name"] for t in types]
    trend = [{"ym": m, **{n: type_month.get(m, {}).get(n, 0) for n in type_names}} for m in sorted(sp)]
    return {
        "source": "사전 집계 뷰" if src == "mv" else "원본(1개월)",
        "productCount": len(selling), "rankings": rankings,
        "items": finish("item"), "groups": finish("grp"), "salesTypes": types, "salesTypeTrend": trend,
        "minAmtForDsctRank": MIN_AMT_FOR_DSCT_RANK,
    }


def product_sales(prdt_cd: str, months: list[str], teams: list[str] | None = None) -> dict:
    """상품 팝업: 품번의 월별 매장 판매 (수량 · 실판금액 · 할인율). 뷰가 없으면 원본에서 최근 6개월만."""
    src = _source(months)
    if src is None:
        months = months[-6:]
    c = _SRC[src or "base"]
    minl, mb = _in(months, "m")
    team_sql, tb = "", {}
    if teams is not None:
        tinl, tb = _in(teams or ["-"], "t")
        team_sql = f" AND TEAM_CD IN ({tinl})"
    rows = db.query(f"""SELECT MAKE_YYMM, SUM({c['amt']}), SUM({c['qty']}), SUM({c['dsct']}), MAX(ITEM_NM), MAX({c['grp']})
                          FROM {c['table']} WHERE PRDT_CD = :p AND MAKE_YYMM IN ({minl}){team_sql} GROUP BY MAKE_YYMM""",
                    {**mb, **tb, "p": prdt_cd})[1]
    by = {r[0]: r for r in rows}
    item = next((r[4] for r in rows if r[4]), None)
    grp = next((r[5] for r in rows if r[5]), None)
    out = []
    for m in months:
        r = by.get(m)
        amt, qty, dsct = (int(r[1] or 0), int(r[2] or 0), int(r[3] or 0)) if r else (0, 0, 0)
        out.append({"ym": m, "amt": amt, "qty": qty, "dsctRate": _dr(dsct, amt)})
    return {"itemNm": item, "prdtGrpNm": grp, "months": out, "source": "사전 집계 뷰" if src == "mv" else "원본(최근 6개월)"}


def bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})
