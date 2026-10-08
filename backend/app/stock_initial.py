"""재고 재배치 추천 > 초도 배분 적중률: 신상품 초도 배분(T_DELV_ASK 초도배분 C0631 · 확정)이 매장 판매 반응과 얼마나 맞았는지.

- 단위 = 상품(품번 · 칼라) × 매장, 배분 = 확정된 초도 배분 수량(사이즈 합), 시작일 = 출고예정일(없으면 의뢰일)
- 판매 = 시작일부터 N일(기본 28 — 시즌 초 상품은 14일 판매가 적어 적중률이 낮게 나와 28일을 기본으로) 순판매 (T_SHOP_RNDS_BASE, 반품 차감, 0 미만은 0)
- 판매율 = 판매 ÷ 배분, 무판매 매장 = 판매 0, 소진 매장 = 판매 ≥ 배분(더 받았어야)
- 적중률 = Σ 매장 min(배분 비중, 판매 비중) × 100 — 배분을 매장별로 나눈 모양이 실제 판매 모양과 겹치는 정도 (100 = 판매 비중대로 배분)
- 기본은 N일이 다 지난 배분만 (진행 중인 건은 판매가 덜 쌓여 낮게 나옴). 기간 판매가 10장 미만인 상품은 적중률을 매기지 않는다
- 출고예정일과 실제 첫 입고일(T_SHOP_PRDT_BASE.F_RNDS_DT)은 대부분 같거나 1~2일 차이 (2026-09 쉬즈미스 표본)
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from . import db
from . import stock_ctl as sc

CACHE_TTL = 30 * 60
MAX_SPAN = 92
WINDOWS = (7, 14, 28)


def _d(v: str) -> date:
    return datetime.strptime(v[:8], "%Y%m%d").date()


def _range(frm: str | None, to: str | None, window: int) -> tuple[str, str]:
    """기본: 끝 = 오늘 − N일(판매 확인 기간이 다 지난 배분까지), 시작 = 끝 − 29일"""
    today = date.today()
    t = (to or "").replace("-", "") or (today - timedelta(days=window)).strftime("%Y%m%d")
    f = (frm or "").replace("-", "") or (_d(t) - timedelta(days=29)).strftime("%Y%m%d")
    try:
        bad = _d(f) > _d(t)
        span = (_d(t) - _d(f)).days
    except ValueError:
        sc.bad("날짜가 올바르지 않습니다.")
    if bad:
        sc.bad("시작일이 끝일보다 늦습니다.")
    if span >= MAX_SPAN:
        sc.bad(f"초도 배분 기간은 최대 {MAX_SPAN}일입니다.")
    return f, t


def analyze(brand: str | None = None, frm: str | None = None, to: str | None = None, window: int = 28, plan_yy=None, seasons=None,
            include_virtual: bool = False, matured_only: bool = True, allowed: list[str] | None = None, refresh: bool = False) -> dict:
    b = sc.brand_code(brand, allowed)
    try:
        window = int(window)
    except (TypeError, ValueError):
        window = 28
    if window not in WINDOWS:
        sc.bad("판매 확인 기간은 7 · 14 · 28일 중 하나입니다.")
    f, t = _range(frm, to, window)
    yy = sc.code_list(plan_yy, "기획년도", r"^\d{4}$", 20)
    ss = sc.code_list(seasons, "시즌", r"^C007[0-9A-Z]$", 14)
    key = ("initial", b, f, t, window)
    base = sc.cached(key, CACHE_TTL, lambda: _load(b, f, t, window), force=refresh)
    return _summarize(base, yy, ss, bool(include_virtual), bool(matured_only))


def _load(brand: str, f: str, t: str, window: int) -> dict:
    t0 = time.perf_counter()
    asks = db.query("""SELECT SHOP_ID, PRDT_CD, COLOR_CD, SUM(NVL(ASK_QTY, 0)), MIN(NVL(DELV_PRE_DT, ASK_DT))
                         FROM T_DELV_ASK
                        WHERE ASK_DT BETWEEN :f AND :t AND PARENT_BRD_CD = :b AND ASK_CLSBY = 'C0631' AND CNFM_YN = 'Y' AND DEL_DAY IS NULL
                        GROUP BY SHOP_ID, PRDT_CD, COLOR_CD
                       HAVING SUM(NVL(ASK_QTY, 0)) > 0""", {"f": f, "t": t, "b": brand}, arraysize=50000)[1]
    prdts = sorted({r[1] for r in asks})
    starts = [r[4] for r in asks if r[4]]
    sales: dict[tuple, list[tuple]] = {}
    if prdts and starts:
        s_from = min(starts)[:8]
        s_to = min(max(_d(max(starts)) + timedelta(days=window - 1), date.today() - timedelta(days=1)), date.today()).strftime("%Y%m%d")
        for part in sc.chunks(prdts, 500):
            ph, bnd = sc.binds(part, "p")
            for sid, p, c, d8, q in db.query(f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_04) */ R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.MAKE_DT,
                                                       SUM(DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY))
                                                  FROM T_SHOP_RNDS_BASE R
                                                 WHERE R.PRDT_CD IN ({ph}) AND R.MAKE_DT BETWEEN :sf AND :st AND R.STOCK_STAT = 'C20922'
                                                   AND R.DEL_DAY IS NULL AND R.COMPY_CD = '{sc.COMPY_CD}'
                                                 GROUP BY R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.MAKE_DT""",
                                             {**bnd, "sf": s_from, "st": s_to}, arraysize=50000)[1]:
                sales.setdefault((sid, p, c), []).append((d8, int(q or 0)))
    today = date.today()
    items = []
    for sid, p, c, q, start in asks:
        st = _d(start or f)
        end = st + timedelta(days=window - 1)
        sold = sum(x for d8, x in sales.get((sid, p, c), []) if st <= _d(d8) <= end)
        items.append({"shopId": sid, "prdtCd": p, "colorCd": c, "alloc": int(q), "sold": max(sold, 0), "start": st.strftime("%Y%m%d"),
                      "matured": end < today})
    return {"brand": brand, "from": f, "to": t, "window": window, "items": items, "styles": sc.style_info(prdts) if prdts else {},
            "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "sec": round(time.perf_counter() - t0, 1)}


MIN_SOLD = 10         # 기간 판매가 이보다 적으면 적중률을 매기지 않는다 (한두 장 판매로는 판매 모양을 알 수 없음)


def _overlap(rows: list[dict]) -> float | None:
    a = sum(r["alloc"] for r in rows)
    s = sum(r["sold"] for r in rows)
    if not a or s < MIN_SOLD:
        return None
    return round(sum(min(r["alloc"] / a, r["sold"] / s) for r in rows) * 100, 1)


def _summarize(base: dict, yy: list[str], ss: list[str], include_virtual: bool, matured_only: bool) -> dict:
    shops = sc.shops()
    team_nm = sc.team_names()
    sesn_nm = sc.code_names("C007")
    styles = base["styles"]
    items, virtual_rows, immature = [], 0, 0
    for x in base["items"]:
        sh = shops.get(x["shopId"]) or {}
        if not include_virtual and sh.get("virtual"):
            virtual_rows += 1
            continue
        st = styles.get(x["prdtCd"]) or {}
        if (yy and st.get("planYy") not in yy) or (ss and st.get("sesn") not in ss):
            continue
        if not x["matured"]:
            immature += 1
            if matured_only:
                continue
        items.append(x)
    by_prod: dict[tuple, list[dict]] = {}
    by_shop: dict[str, list[dict]] = {}
    by_type: dict[str, list[dict]] = {}
    for x in items:
        by_prod.setdefault((x["prdtCd"], x["colorCd"]), []).append(x)
        by_shop.setdefault(x["shopId"], []).append(x)
        by_type.setdefault(sc.SHOP_TYPE_NM.get((shops.get(x["shopId"]) or {}).get("type"), "기타"), []).append(x)

    def agg(rows: list[dict]) -> dict:
        a = sum(r["alloc"] for r in rows)
        s = sum(r["sold"] for r in rows)
        return {"alloc": a, "sold": s, "sellThru": round(s / a * 100, 1) if a else None, "rows": len(rows),
                "zero": sum(1 for r in rows if r["sold"] <= 0), "soldOut": sum(1 for r in rows if r["sold"] >= r["alloc"])}

    prods = []
    for (p, c), rows in by_prod.items():
        st = styles.get(p) or {}
        prods.append({"prdtCd": p, "colorCd": c, "styleNm": st.get("styleNm"), "planYy": st.get("planYy"), "sesnNm": sesn_nm.get(st.get("sesn"), st.get("sesn")),
                      "start": sc.ymd_label(min(r["start"] for r in rows)), "shops": len(rows), "overlap": _overlap(rows), **agg(rows)})
    prods.sort(key=lambda r: (r["overlap"] if r["overlap"] is not None else 999, -r["alloc"], r["prdtCd"], r["colorCd"]))
    shop_rows = []
    for sid, rows in by_shop.items():
        sh = shops.get(sid) or {}
        shop_rows.append({"shopId": sid, "shopNm": sh.get("shopNm"), "team": team_nm.get(sh.get("team")), "shopType": sc.SHOP_TYPE_NM.get(sh.get("type")),
                          "products": len(rows), **agg(rows)})
    shop_rows.sort(key=lambda r: (r["sellThru"] if r["sellThru"] is not None else -1, -r["alloc"]))
    total = agg(items)
    w = sum(p["alloc"] for p in prods if p["overlap"] is not None)
    weighted = round(sum(p["overlap"] * p["alloc"] for p in prods if p["overlap"] is not None) / w, 1) if w else None
    return {
        "brand": base["brand"], "brandNm": sc.BRAND_CODES[base["brand"]], "from": sc.ymd_label(base["from"]), "to": sc.ymd_label(base["to"]),
        "window": base["window"], "asOf": base["asOf"], "maturedOnly": matured_only, "immature": immature, "virtualRows": virtual_rows,
        "includeVirtual": include_virtual,
        "summary": {**total, "products": len(prods), "shops": len(shop_rows), "overlap": weighted,
                    "lowOverlap": sum(1 for p in prods if p["overlap"] is not None and p["overlap"] < 50),
                    "judged": sum(1 for p in prods if p["overlap"] is not None), "minSold": MIN_SOLD,
                    "zeroProducts": sum(1 for p in prods if p["sold"] <= 0)},
        "products": prods, "shops": shop_rows,
        "types": sorted(({"shopType": k, **agg(v)} for k, v in by_type.items()), key=lambda r: -r["alloc"]),
    }


def product_shops(brand: str | None, frm: str | None, to: str | None, window: int, prdt: str, color: str, include_virtual: bool = False,
                  allowed: list[str] | None = None) -> list[dict]:
    """한 상품(품번 · 칼라)의 매장별 배분 · 판매 (적중률 팝업)"""
    b = sc.brand_code(brand, allowed)
    window = int(window) if str(window).isdigit() and int(window) in WINDOWS else 28
    f, t = _range(frm, to, window)
    base = sc.cached(("initial", b, f, t, window), CACHE_TTL, lambda: _load(b, f, t, window))
    shops = sc.shops()
    team_nm = sc.team_names()
    rows = [x for x in base["items"] if x["prdtCd"] == prdt and x["colorCd"] == color
            and (include_virtual or not (shops.get(x["shopId"]) or {}).get("virtual"))]
    a = sum(r["alloc"] for r in rows) or 1
    s = sum(r["sold"] for r in rows) or 1
    out = []
    for x in sorted(rows, key=lambda r: (-r["sold"], -r["alloc"], r["shopId"])):
        sh = shops.get(x["shopId"]) or {}
        out.append({"shopId": x["shopId"], "shopNm": sh.get("shopNm"), "team": team_nm.get(sh.get("team")), "shopType": sc.SHOP_TYPE_NM.get(sh.get("type")),
                    "alloc": x["alloc"], "sold": x["sold"], "sellThru": round(x["sold"] / x["alloc"] * 100, 1) if x["alloc"] else None,
                    "allocShare": round(x["alloc"] / a * 100, 1), "soldShare": round(x["sold"] / s * 100, 1), "start": sc.ymd_label(x["start"]),
                    "matured": x["matured"]})
    return out


INIT_PROD_COLS = [("prdtCd", "품번", 14), ("colorCd", "칼라", 6), ("styleNm", "스타일명", 18), ("planYy", "기획년도", 8), ("sesnNm", "시즌", 8),
                  ("start", "첫 출고예정", 11), ("shops", "매장 수", 7), ("alloc", "초도 배분", 9), ("sold", "기간 판매", 9), ("sellThru", "판매율(%)", 9),
                  ("zero", "무판매 매장", 9), ("soldOut", "소진 매장", 9), ("overlap", "적중률(%)", 9)]
INIT_SHOP_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("shopType", "유통형태", 9), ("products", "상품 수", 8),
                  ("alloc", "초도 배분", 9), ("sold", "기간 판매", 9), ("sellThru", "판매율(%)", 9), ("zero", "무판매 상품", 9), ("soldOut", "소진 상품", 9)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"초도 배분 적중률 ({d['asOf']} 기준 · {d['brandNm']} · 초도 배분 {d['from']} ~ {d['to']} · 출고예정일부터 {d['window']}일 판매"
             f"{' · 기간이 다 지난 배분만' if d['maturedOnly'] else ''})",
             f"배분 {s['alloc']:,}장 · 판매 {s['sold']:,}장 · 판매율 {s['sellThru'] or '-'}% · 적중률 {s['overlap'] or '-'}% "
             "(적중률 = Σ 매장 min(배분 비중, 판매 비중))"]
    return sc.xlsx([("상품별", notes, INIT_PROD_COLS, d["products"]), ("매장별", notes, INIT_SHOP_COLS, d["shops"])])
