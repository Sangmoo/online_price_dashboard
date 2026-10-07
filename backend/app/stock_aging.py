"""재고 재배치 추천 > 장기 미판매 재고: 매장 재고 중 오래 팔리지 않은 재고 (매장 × 스타일).

- 재고 = 이번 달 매장 재고(T_SHOP_STOCK, 0 보다 큰 행), 금액 = ERP 재고금액(STOCK_AMT)
- 미판매 일수 = 오늘 − 그 매장에서 그 스타일의 최종판매일(T_SHOP_PRDT_BASE.L_SALE_DT, 칼라 · 사이즈 중 가장 최근).
  그 매장에서 판 적이 없으면 최초출고일부터 (판매 이력 없음 표시), 둘 다 없으면 '기준 없음'
- 브랜드 전체 매장 재고를 매장 상품 기준과 합쳐 읽어 오래 걸린다(쉬즈미스 약 1~2분) → 결과(매장 × 스타일 묶음)를 12시간 두고,
  매일 아침 미리 계산한다. [새로 계산]으로 지금 재고를 다시 읽는다. 조건(기간 · 시즌 · 팀 등)은 그 결과에서 바로 거른다.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime

from . import db, logs
from . import stock_ctl as sc

_log = logs.get("app")
BASE_TTL = 12 * 3600
BUCKETS = [("b30", "30일 이하", 30), ("b60", "31~60일", 60), ("b90", "61~90일", 90), ("b180", "91~180일", 180), ("b365", "181~365일", 365),
           ("bOld", "1년 넘음", None)]
MAX_DETAIL = 30000


def _bucket(days: int | None) -> str:
    if days is None:
        return "none"
    for k, _, upto in BUCKETS:
        if upto is None or days <= upto:
            return k
    return "bOld"


def _base(brand: str) -> dict:
    """매장 × 스타일 묶음 (재고 수량 · 금액 · 최종판매일 · 최종/최초 출고일) — 오래 걸려 12시간 캐시"""
    t0 = time.perf_counter()
    ym = sc.today()[:6]
    rows = db.query(f"""SELECT /*+ PARALLEL(S 4) PARALLEL(B 4) USE_HASH(S B) FULL(B) */
                               S.SHOP_ID, S.PRDT_CD, SUM(S.STOCK_QTY), SUM(NVL(S.STOCK_AMT, 0)), MAX(B.L_SALE_DT), MAX(B.L_RNDS_DT), MIN(B.F_RNDS_DT),
                               COUNT(*)
                          FROM T_SHOP_STOCK S, T_SHOP_PRDT_BASE B
                         WHERE S.MAKE_YYMM = :ym AND S.STOCK_QTY > 0 AND S.PRDT_CD LIKE :b || '%'
                           AND B.COMPY_CD(+) = '{sc.COMPY_CD}' AND B.PARENT_BRD_CD(+) = :b AND B.SHOP_ID(+) = S.SHOP_ID
                           AND B.PRDT_CD(+) = S.PRDT_CD AND B.COLOR_CD(+) = S.COLOR_CD AND B.SIZE_CD(+) = S.SIZE_CD
                         GROUP BY S.SHOP_ID, S.PRDT_CD""", {"ym": ym, "b": brand}, arraysize=50000)[1]
    styles = {p: (nm, yy, ss) for p, nm, yy, ss in db.query(
        f"""SELECT PRDT_CD, STYLE_NM, PLAN_YY, SESN_CD FROM T_STYLE_PLAN WHERE COMPY_CD = '{sc.COMPY_CD}' AND PARENT_BRD_CD = :b""",
        {"b": brand}, arraysize=50000)[1]}
    sec = round(time.perf_counter() - t0, 1)
    _log.info("장기 미판매 재고 기준 읽기 %s %d행 %.1f초", brand, len(rows), sec)
    return {"rows": rows, "styles": styles, "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "sec": sec, "ym": ym}


# 공용 캐시(stock_ctl.cached)는 항목이 많으면 통째로 비우므로, 오래 걸리는 이 기준은 따로 둔다
_cache: dict[str, tuple[float, dict]] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def base(brand: str, refresh: bool = False) -> dict:
    with _guard:
        lock = _locks.setdefault(brand, threading.Lock())
        hit = _cache.get(brand)
    if hit and hit[0] > time.time() and not refresh:
        return hit[1]
    with lock:                                   # 같은 브랜드를 동시에 두 번 읽지 않게
        hit = _cache.get(brand)
        if hit and hit[0] > time.time() and not refresh:
            return hit[1]
        val = _base(brand)
        _cache[brand] = (time.time() + BASE_TTL, val)
        return val


def report(brand: str | None = None, min_days: int = 90, plan_yy=None, seasons=None, teams=None, prdt: str | None = None,
           include_virtual: bool = False, allowed: list[str] | None = None, refresh: bool = False) -> dict:
    b = sc.brand_code(brand, allowed)
    try:
        min_days = int(min_days)
    except (TypeError, ValueError):
        min_days = 90
    if not 7 <= min_days <= 1000:
        sc.bad("장기 미판매 기준은 7~1000일입니다.")
    yy = sc.code_list(plan_yy, "기획년도", r"^\d{4}$", 20)
    ss = sc.code_list(seasons, "시즌", r"^C007[0-9A-Z]$", 14)
    tm = sc.code_list(teams, "팀", r"^C620\d{1,3}$", 20)
    pp = sc.prdt_prefix(prdt)
    started = time.perf_counter()
    bs = base(b, refresh)
    shops = sc.shops()
    team_nm = sc.team_names()
    today = date.today()
    tot = {"qty": 0, "amt": 0, "rows": 0}
    aged = {"qty": 0, "amt": 0, "rows": 0}
    buckets = {k: {"qty": 0, "amt": 0, "rows": 0} for k, _, _ in BUCKETS}
    buckets["none"] = {"qty": 0, "amt": 0, "rows": 0}
    by_shop: dict[str, dict] = {}
    by_style: dict[str, dict] = {}
    detail = []
    virtual_qty = 0
    for sid, p, q, amt, l_sale, l_rnds, f_rnds, skus in bs["rows"]:
        sh = shops.get(sid) or {}
        if not include_virtual and sh.get("virtual"):
            virtual_qty += int(q)
            continue
        if tm and sh.get("team") not in tm:
            continue
        nm, py, sn = bs["styles"].get(p, (None, None, None))
        if (yy and py not in yy) or (ss and sn not in ss) or (pp and not p.startswith(pp)):
            continue
        ref = l_sale or f_rnds
        try:
            days = (today - datetime.strptime(ref[:8], "%Y%m%d").date()).days if ref else None
        except ValueError:
            days = None
        q, amt = int(q), int(amt or 0)
        k = _bucket(days)
        for g in (tot, buckets[k]):
            g["qty"] += q
            g["amt"] += amt
            g["rows"] += 1
        is_aged = days is not None and days >= min_days
        gs = by_shop.setdefault(sid, {"shopId": sid, "shopNm": sh.get("shopNm"), "team": team_nm.get(sh.get("team")), "closed": not sh.get("normal", False),
                                      "qty": 0, "amt": 0, "agedQty": 0, "agedAmt": 0, "agedStyles": 0})
        gy = by_style.setdefault(p, {"prdtCd": p, "styleNm": nm, "planYy": py, "sesn": sn, "qty": 0, "amt": 0, "agedQty": 0, "agedAmt": 0,
                                     "agedShops": 0, "maxDays": None})
        for g in (gs, gy):
            g["qty"] += q
            g["amt"] += amt
        if is_aged:
            aged["qty"] += q
            aged["amt"] += amt
            aged["rows"] += 1
            gs["agedQty"] += q
            gs["agedAmt"] += amt
            gs["agedStyles"] += 1
            gy["agedQty"] += q
            gy["agedAmt"] += amt
            gy["agedShops"] += 1
            gy["maxDays"] = max(gy["maxDays"] or 0, days)
            detail.append({"shopId": sid, "shopNm": sh.get("shopNm"), "team": team_nm.get(sh.get("team")), "prdtCd": p, "styleNm": nm,
                           "planYy": py, "sesn": sn, "qty": q, "amt": amt, "skus": int(skus), "days": days, "neverSold": not l_sale,
                           "lastSale": sc.ymd_label(l_sale), "lastDelv": sc.ymd_label(l_rnds), "firstDelv": sc.ymd_label(f_rnds)})
    sesn_nm = sc.code_names("C007")
    for g in by_style.values():
        g["sesnNm"] = sesn_nm.get(g["sesn"], g["sesn"])
    for x in detail:
        x["sesnNm"] = sesn_nm.get(x["sesn"], x["sesn"])
    detail.sort(key=lambda x: (-x["amt"], -x["qty"], x["shopId"]))
    shop_rows = sorted(by_shop.values(), key=lambda g: (-g["agedAmt"], -g["agedQty"], g["shopId"]))
    for g in shop_rows:
        g["agedRate"] = round(g["agedQty"] / g["qty"] * 100, 1) if g["qty"] else None
    style_rows = sorted((g for g in by_style.values() if g["agedQty"]), key=lambda g: (-g["agedAmt"], -g["agedQty"], g["prdtCd"]))
    return {
        "brand": b, "brandNm": sc.BRAND_CODES[b], "minDays": min_days, "asOf": bs["asOf"], "baseSec": bs["sec"], "ym": bs["ym"],
        "cond": {"planYy": yy, "seasons": ss, "teams": tm, "prdt": pp, "includeVirtual": bool(include_virtual)}, "virtualQty": virtual_qty,
        "summary": {"qty": tot["qty"], "amt": tot["amt"], "rows": tot["rows"], "agedQty": aged["qty"], "agedAmt": aged["amt"], "agedRows": aged["rows"],
                    "agedRate": round(aged["qty"] / tot["qty"] * 100, 1) if tot["qty"] else None, "shops": len(by_shop),
                    "agedShops": sum(1 for g in by_shop.values() if g["agedQty"]), "agedStyles": len(style_rows)},
        "buckets": [{"key": k, "name": n, **buckets[k]} for k, n, _ in BUCKETS] + [{"key": "none", "name": "판매 · 출고 기준 없음", **buckets["none"]}],
        "shops": shop_rows, "styles": style_rows[:5000], "stylesTotal": len(style_rows),
        "detail": detail[:MAX_DETAIL], "detailTotal": len(detail), "timing": {"total": round(time.perf_counter() - started, 2)},
    }


def skus(brand: str | None, shop_id: str, prdt: str, allowed: list[str] | None = None) -> list[dict]:
    """한 매장 × 스타일의 칼라 · 사이즈별 재고 · 최종판매일"""
    b = sc.brand_code(brand, allowed)
    if not shop_id or not prdt or len(shop_id) > 10 or len(prdt) > 20:
        sc.bad("매장 · 품번을 확인하세요.")
    today = date.today()
    out = []
    for c, s, q, amt, l_sale, l_rnds, f_rnds in db.query(
            f"""SELECT S.COLOR_CD, S.SIZE_CD, S.STOCK_QTY, NVL(S.STOCK_AMT, 0), B.L_SALE_DT, B.L_RNDS_DT, B.F_RNDS_DT
                  FROM T_SHOP_STOCK S, T_SHOP_PRDT_BASE B
                 WHERE S.MAKE_YYMM = :ym AND S.SHOP_ID = :sid AND S.PRDT_CD = :p AND S.STOCK_QTY > 0
                   AND B.COMPY_CD(+) = '{sc.COMPY_CD}' AND B.PARENT_BRD_CD(+) = :b AND B.SHOP_ID(+) = S.SHOP_ID AND B.PRDT_CD(+) = S.PRDT_CD
                   AND B.COLOR_CD(+) = S.COLOR_CD AND B.SIZE_CD(+) = S.SIZE_CD
                 ORDER BY S.COLOR_CD, S.SIZE_CD""", {"ym": sc.today()[:6], "sid": shop_id.upper(), "p": prdt.upper(), "b": b})[1]:
        ref = l_sale or f_rnds
        out.append({"colorCd": c, "sizeCd": s, "qty": int(q), "amt": int(amt), "lastSale": sc.ymd_label(l_sale), "lastDelv": sc.ymd_label(l_rnds),
                    "firstDelv": sc.ymd_label(f_rnds), "days": (today - datetime.strptime(ref[:8], "%Y%m%d").date()).days if ref else None})
    return out


def warm_all() -> None:
    """매일 아침 브랜드별 기준을 미리 읽어 둔다 (첫 사용자가 1~2분 기다리지 않게)"""
    for b in sc.BRAND_CODES:
        try:
            base(b, refresh=True)
        except Exception:  # noqa: BLE001 - 한 브랜드 실패가 나머지를 막지 않게
            _log.exception("장기 미판매 재고 미리 계산 실패 %s", b)


def warm_async() -> None:
    threading.Thread(target=warm_all, daemon=True, name="aging-warm").start()


AGING_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("prdtCd", "품번", 14), ("styleNm", "스타일명", 18),
              ("planYy", "기획년도", 8), ("sesnNm", "시즌", 8), ("qty", "재고", 7), ("amt", "재고금액", 12), ("skus", "칼라 · 사이즈", 9),
              ("days", "미판매 일수", 9), ("lastSale", "최종판매일", 11), ("lastDelv", "최종출고일", 11), ("firstDelv", "최초출고일", 11)]
AGING_SHOP_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("qty", "재고", 9), ("amt", "재고금액", 13),
                   ("agedQty", "장기 미판매 재고", 11), ("agedAmt", "장기 미판매 금액", 13), ("agedRate", "비중(%)", 8), ("agedStyles", "스타일 수", 8)]
AGING_STYLE_COLS = [("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("planYy", "기획년도", 8), ("sesnNm", "시즌", 8), ("qty", "매장 재고", 9),
                    ("agedQty", "장기 미판매 재고", 11), ("agedAmt", "장기 미판매 금액", 13), ("agedShops", "매장 수", 8), ("maxDays", "최장 미판매 일수", 10)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"장기 미판매 재고 ({d['asOf']} 재고 기준 · {d['brandNm']} · 미판매 {d['minDays']}일 이상)",
             f"매장 재고 {s['qty']:,}장 · {s['amt']:,}원 중 장기 미판매 {s['agedQty']:,}장 · {s['agedAmt']:,}원 ({s['agedRate'] or 0}%)"]
    return sc.xlsx([("매장별", notes, AGING_SHOP_COLS, d["shops"]), ("스타일별", notes, AGING_STYLE_COLS, d["styles"]),
                    ("매장 × 스타일", notes, AGING_COLS, d["detail"])])
