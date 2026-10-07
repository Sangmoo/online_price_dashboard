"""재고 재배치 추천 > 창고 회수 추천: 창고 재고가 모자라 판매분 보충을 못 하는 상품(창고 부족)을,
그 상품이 안 팔리는 매장의 재고를 창고로 회수해 채우도록 추천한다 (조회 · 추천만, ERP 에 반품 지시를 넣지 않음).

- 회수할 상품 = 창고 → 매장 배분(판매분 자동보충 규칙) 결과의 창고 부족 상품, 필요 수량 = 창고 부족 수량
- 회수 후보 매장 = 그 상품(품번 · 칼라 · 사이즈) 재고가 있고, 최근 N일(기본 14일) 그 상품 판매가 없는 매장.
  창고 부족으로 그 상품을 받아야 하는 매장 · 행사 · 가상 매장은 뺀다. 폐점 · 비정상 매장 재고는 먼저 회수한다.
- 회수 가능 수량 = 현재고 − 이동중 · 자동 RT 요청중 · 미처리 지시 · 요청 (매장 간 RT 와 같은 기준)
- 순서 = 폐점 · 비정상 매장 → 최종판매일 오래된 순(판매 이력 없으면 먼저) → 회수 가능 수량 많은 순
- 방식 need = 창고 부족 수량만큼만, all = 판매 없는 매장의 회수 가능 재고 전부
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

from . import db
from . import stock_ctl as sc

CACHE_TTL = 10 * 60
MODES = {"need": "창고 부족 수량만큼", "all": "판매 없는 매장 재고 전부"}


def recommend(alloc_args: dict, lookback: int = 14, mode: str = "need", allowed: list[str] | None = None, refresh: bool = False) -> dict:
    from . import wh_alloc

    try:
        lookback = int(lookback)
    except (TypeError, ValueError):
        lookback = 14
    if not 3 <= lookback <= 90:
        sc.bad("판매 없음 기준 기간은 3~90일입니다.")
    if mode not in MODES:
        sc.bad("방식은 need(창고 부족 수량만큼) 또는 all(판매 없는 재고 전부)입니다.")
    d = wh_alloc.recommend(**alloc_args, allowed=allowed)
    key = ("return", d["brand"], json.dumps(alloc_args, sort_keys=True, default=str), d["asOf"], lookback, mode)
    return sc.cached(key, CACHE_TTL, lambda: _compute(d, lookback, mode), force=refresh)


def _sales(pcs: list[tuple], frm: str, to: str) -> dict[tuple, int]:
    """(매장, 상품) → 기간 순판매 (품번 · 칼라 인덱스)"""
    out: dict[tuple, int] = {}
    for part in sc.chunks(pcs, 300):
        b: dict = {"f": frm, "t": to}
        keys = []
        for i, (p, c) in enumerate(part):
            b[f"p{i}"], b[f"c{i}"] = p, c
            keys.append(f"(:p{i}, :c{i})")
        for sid, p, c, s, q in db.query(f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_04) */ R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD,
                                                   SUM(DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY))
                                              FROM T_SHOP_RNDS_BASE R
                                             WHERE (R.PRDT_CD, R.COLOR_CD) IN ({', '.join(keys)}) AND R.MAKE_DT BETWEEN :f AND :t
                                               AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL AND R.COMPY_CD = '{sc.COMPY_CD}'
                                             GROUP BY R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD""", b, arraysize=20000)[1]:
            out[(sid, p, c, s)] = int(q or 0)
    return out


def _days(d8: str | None, today: date) -> int | None:
    try:
        return (today - datetime.strptime(d8[:8], "%Y%m%d").date()).days if d8 else None
    except ValueError:
        return None


def _compute(d: dict, lookback: int, mode: str) -> dict:
    from . import stock_rt

    started = time.perf_counter()
    brand, td = d["brand"], sc.today()
    today = date.today()
    short = {(s["prdtCd"], s["colorCd"], s["sizeCd"]): s for s in d["skus"] if s["short"] > 0}
    need_shops = {(r["shopId"], r["prdtCd"], r["colorCd"], r["sizeCd"]) for r in d["shortRows"]}
    pcs = sorted({k[:2] for k in short})
    stock = [r for r in stock_rt._stock(pcs, td[:6]) if tuple(r[1:4]) in short and int(r[4]) > 0] if pcs else []
    frm = (today - timedelta(days=lookback - 1)).strftime("%Y%m%d")
    sales = _sales(pcs, frm, td) if pcs else {}
    res = stock_rt._reserved(brand, td)
    shops = sc.shops()
    teams = sc.team_names()
    excluded = {"sold": 0, "needs": 0, "virtual": 0, "reserved": 0}
    cands: dict[tuple, list[dict]] = {}
    for sid, p, c, s, q in stock:
        k = (sid, p, c, s)
        sh = shops.get(sid) or {}
        if sh.get("virtual"):
            excluded["virtual"] += 1
            continue
        if k in need_shops:
            excluded["needs"] += 1
            continue
        if sales.get(k, 0) > 0:
            excluded["sold"] += 1
            continue
        avail = int(q) - res["moving"].get(k, 0) - res["pending"].get(k, 0) - res["instrOut"].get(k, 0)
        if avail <= 0:
            excluded["reserved"] += 1
            continue
        cands.setdefault((p, c, s), []).append({"shopId": sid, "stock": int(q), "avail": avail, "closed": not sh.get("normal", False)})
    base = stock_rt._prdt_base(brand, [(c["shopId"],) + sku for sku, lst in cands.items() for c in lst]) if cands else {}
    rows, sku_rows = [], []
    styles = {}
    for sku in sorted(short):
        st = short[sku]
        styles.setdefault(sku[0], st.get("styleNm"))
        lst = cands.get(sku, [])
        for c in lst:
            e = base.get((c["shopId"],) + sku)
            c["lastSale"], c["lastDelv"] = (e[2], e[1]) if e else (None, None)
        # 폐점 · 비정상 먼저 → 판매 이력 없는 매장 → 최종판매일 오래된 순 → 회수 가능 많은 순
        lst.sort(key=lambda c: (not c["closed"], c["lastSale"] is not None, c["lastSale"] or "", -c["avail"], c["shopId"]))
        left = st["short"]
        got = 0
        for c in lst:
            if mode == "need" and left <= 0:
                break
            qty = c["avail"] if mode == "all" else min(c["avail"], left)
            left -= qty
            got += qty
            sh = shops.get(c["shopId"]) or {}
            rows.append({"prdtCd": sku[0], "styleNm": st.get("styleNm"), "colorCd": sku[1], "sizeCd": sku[2], "shopId": c["shopId"],
                         "shopNm": sh.get("shopNm"), "team": teams.get(sh.get("team")), "closed": c["closed"], "stock": c["stock"],
                         "avail": c["avail"], "qty": qty, "lastSale": sc.ymd_label(c["lastSale"]), "daysNoSale": _days(c["lastSale"], today),
                         "lastDelv": sc.ymd_label(c["lastDelv"]), "daysSinceDelv": _days(c["lastDelv"], today), "skuShort": st["short"]})
        sku_rows.append({"prdtCd": sku[0], "styleNm": st.get("styleNm"), "colorCd": sku[1], "sizeCd": sku[2], "whStock": st["whStock"],
                         "avail": st["avail"], "demand": st["demand"], "short": st["short"], "candidates": len(lst),
                         "candQty": sum(c["avail"] for c in lst), "returnQty": got, "left": max(st["short"] - got, 0)})
    by_shop: dict[str, int] = {}
    for r in rows:
        by_shop[r["shopId"]] = by_shop.get(r["shopId"], 0) + r["qty"]
    names = {sid: sh["shopNm"] for sid, sh in shops.items()}
    return {
        "brand": brand, "brandNm": d["brandNm"], "wh": d["wh"], "from": d["from"], "to": d["to"], "allocAsOf": d["asOf"],
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "lookback": lookback, "salesFrom": sc.ymd_label(frm), "mode": mode, "modeNm": MODES[mode],
        "summary": {"shortSkus": len(short), "shortQty": sum(s["short"] for s in short.values()), "returnQty": sum(r["qty"] for r in rows),
                    "rows": len(rows), "shops": len(by_shop), "coveredSkus": sum(1 for s in sku_rows if s["returnQty"] and not s["left"]),
                    "partialSkus": sum(1 for s in sku_rows if s["returnQty"] and s["left"]), "noSourceSkus": sum(1 for s in sku_rows if not s["returnQty"]),
                    "coveredQty": sum(min(s["returnQty"], s["short"]) for s in sku_rows), "excluded": excluded},
        "rows": rows, "skus": sku_rows,
        "topShops": [{"shopId": k, "shopNm": names.get(k), "qty": v} for k, v in sorted(by_shop.items(), key=lambda x: (-x[1], x[0]))[:15]],
        "timing": {"total": round(time.perf_counter() - started, 2)},
    }


RETURN_COLS = [("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7), ("shopId", "회수 매장", 10),
               ("shopNm", "매장명", 18), ("team", "팀", 10), ("closed", "폐점 · 비정상", 9), ("stock", "현재고", 7), ("avail", "회수 가능", 8),
               ("qty", "회수 추천", 8), ("lastSale", "최종판매일", 11), ("daysNoSale", "미판매 일수", 9), ("lastDelv", "최종출고일", 11),
               ("skuShort", "상품 창고 부족", 10)]
RETURN_SKU_COLS = [("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7), ("whStock", "창고 재고", 9),
                   ("avail", "배분 가능", 9), ("demand", "필요", 7), ("short", "창고 부족", 9), ("candidates", "회수 후보 매장", 10),
                   ("candQty", "후보 재고", 9), ("returnQty", "회수 추천", 9), ("left", "남는 부족", 9)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"창고 회수 추천 ({d['asOf']} 기준 · {d['brandNm']} · 창고 {d['wh']} · 배분 판매 기간 {d['from']} ~ {d['to']} · "
             f"최근 {d['lookback']}일 판매 없는 매장 · {d['modeNm']}) — 추천만, ERP 에 반품 지시를 넣지 않음",
             f"창고 부족 {s['shortSkus']:,}개 상품 · {s['shortQty']:,}장 중 회수로 채움 {s['coveredQty']:,}장 · 회수 추천 {s['returnQty']:,}장 · 매장 {s['shops']:,}곳"]
    return sc.xlsx([("회수 추천", notes, RETURN_COLS, d["rows"]), ("상품별", notes, RETURN_SKU_COLS, d["skus"])])
