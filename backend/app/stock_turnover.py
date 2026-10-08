"""재고 재배치 추천 > 재고 회전: 매장 × 스타일 재고를 최근 N일 판매 속도와 비교한다.

- 재고 = 장기 미판매 재고와 같은 기준(이번 달 매장 재고, 매장 × 스타일, 12시간 캐시 · 아침 미리 계산)
- 판매 = 최근 N일(기본 28) 순판매 (T_SHOP_RNDS_BASE, 반품 차감, 0 미만은 0)
- 일평균 판매 = 판매 ÷ N, 재고일수 = 재고 ÷ 일평균 판매 (판매가 없으면 '판매 없음'), 판매율 = 판매 ÷ (판매 + 재고)
- 구간: 품절(재고 0 · 판매 있음) · 7일 미만(품절 위험) · 7~30일 · 30~90일 · 90~180일 · 180일 넘음 · 판매 없음(재고만)
"""
from __future__ import annotations

import time
from datetime import datetime

from . import db
from . import stock_ctl as sc

SALES_TTL = 30 * 60
MAX_DETAIL = 30000
CLASSES = [("out", "품절 (재고 0)"), ("c7", "7일 미만"), ("c30", "7~30일"), ("c90", "30~90일"), ("c180", "90~180일"), ("c999", "180일 넘음"),
           ("nosale", "판매 없음")]
SHORT = {"out", "c7"}
OVER = {"c180", "c999", "nosale"}


def _class(stock: int, sales: int, days: int) -> tuple[str, float | None]:
    if sales <= 0:
        return ("nosale", None)
    if stock <= 0:
        return ("out", 0.0)
    cover = stock / (sales / days)
    k = "c7" if cover < 7 else "c30" if cover < 30 else "c90" if cover < 90 else "c180" if cover < 180 else "c999"
    return (k, round(cover, 1))


def _sales(brand: str, days: int) -> dict[tuple, int]:
    rows = db.query(f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_05) */ R.SHOP_ID, R.PRDT_CD, SUM(DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY))
                          FROM T_SHOP_RNDS_BASE R
                         WHERE R.MAKE_DT BETWEEN TO_CHAR(SYSDATE - :d, 'YYYYMMDD') AND TO_CHAR(SYSDATE - 1, 'YYYYMMDD')
                           AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL AND R.COMPY_CD = '{sc.COMPY_CD}' AND R.PRDT_CD LIKE :b || '%'
                         GROUP BY R.SHOP_ID, R.PRDT_CD""", {"d": days, "b": brand}, arraysize=50000)[1]
    return {(sid, p): max(int(q or 0), 0) for sid, p, q in rows}


def report(brand: str | None = None, days: int = 28, plan_yy=None, seasons=None, teams=None, prdt: str | None = None,
           include_virtual: bool = False, allowed: list[str] | None = None, refresh: bool = False) -> dict:
    from . import stock_aging

    b = sc.brand_code(brand, allowed)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days not in (7, 14, 28, 56, 91):
        sc.bad("판매 기간은 7 · 14 · 28 · 56 · 91일 중 하나입니다.")
    yy = sc.code_list(plan_yy, "기획년도", r"^\d{4}$", 20)
    ss = sc.code_list(seasons, "시즌", r"^C007[0-9A-Z]$", 14)
    tm = sc.code_list(teams, "팀", r"^C620\d{1,3}$", 20)
    pp = sc.prdt_prefix(prdt)
    started = time.perf_counter()
    bs = stock_aging.base(b, refresh)
    sales = sc.cached(("turn-sales", b, days), SALES_TTL, lambda: _sales(b, days), force=refresh)
    shops = sc.shops()
    team_nm = sc.team_names()
    sesn_nm = sc.code_names("C007")
    stock = {(sid, p): (int(q), int(amt or 0)) for sid, p, q, amt, *_ in bs["rows"]}
    keys = set(stock) | {k for k, v in sales.items() if v > 0}
    cls_tot = {k: {"rows": 0, "stock": 0, "sales": 0} for k, _ in CLASSES}
    by_shop: dict[str, dict] = {}
    by_style: dict[str, dict] = {}
    detail = []
    tot = {"stock": 0, "amt": 0, "sales": 0}
    virtual_rows = 0
    for sid, p in keys:
        sh = shops.get(sid) or {}
        if not include_virtual and sh.get("virtual"):
            virtual_rows += 1
            continue
        if tm and sh.get("team") not in tm:
            continue
        nm, py, sn = bs["styles"].get(p, (None, None, None))
        if (yy and py not in yy) or (ss and sn not in ss) or (pp and not p.startswith(pp)):
            continue
        st, amt = stock.get((sid, p), (0, 0))
        sl = sales.get((sid, p), 0)
        k, cover = _class(st, sl, days)
        for g in (tot,):
            g["stock"] += st
            g["amt"] += amt
            g["sales"] += sl
        c = cls_tot[k]
        c["rows"] += 1
        c["stock"] += st
        c["sales"] += sl
        gs = by_shop.setdefault(sid, {"shopId": sid, "shopNm": sh.get("shopNm"), "team": team_nm.get(sh.get("team")), "teamCd": sh.get("team"),
                                      "stock": 0, "amt": 0, "sales": 0, "short": 0, "over": 0, "overStock": 0, "styles": 0})
        gy = by_style.setdefault(p, {"prdtCd": p, "styleNm": nm, "planYy": py, "sesnNm": sesn_nm.get(sn, sn), "stock": 0, "amt": 0, "sales": 0,
                                     "shops": 0, "short": 0, "over": 0, "overStock": 0})
        for g in (gs, gy):
            g["stock"] += st
            g["amt"] += amt
            g["sales"] += sl
            g["short"] += int(k in SHORT)
            g["over"] += int(k in OVER)
            g["overStock"] += st if k in OVER else 0
        gs["styles"] += 1
        gy["shops"] += 1
        if k in SHORT or k in OVER:
            detail.append({"shopId": sid, "shopNm": sh.get("shopNm"), "team": team_nm.get(sh.get("team")), "prdtCd": p, "styleNm": nm, "planYy": py,
                           "sesnNm": sesn_nm.get(sn, sn), "stock": st, "amt": amt, "sales": sl, "daily": round(sl / days, 2), "cover": cover,
                           "sellThru": round(sl / (sl + st) * 100, 1) if (sl + st) else None, "cls": k})

    def finish(g):
        daily = g["sales"] / days
        g["daily"] = round(daily, 2)
        g["cover"] = round(g["stock"] / daily, 1) if daily > 0 else None
        g["sellThru"] = round(g["sales"] / (g["sales"] + g["stock"]) * 100, 1) if (g["sales"] + g["stock"]) else None
        return g

    shop_rows = sorted((finish(g) for g in by_shop.values()), key=lambda g: (-(g["cover"] or 1e9), -g["stock"], g["shopId"]))
    style_rows = sorted((finish(g) for g in by_style.values()), key=lambda g: (-g["sales"], -g["stock"], g["prdtCd"]))
    teams: dict[str, dict] = {}
    for g in shop_rows:
        t = teams.setdefault(g["team"] or "(팀 없음)", {"team": g["team"] or "(팀 없음)", "shops": 0, "stock": 0, "amt": 0, "sales": 0, "short": 0, "over": 0,
                                                       "overStock": 0})
        t["shops"] += 1
        for f in ("stock", "amt", "sales", "short", "over", "overStock"):
            t[f] += g[f]
    team_rows = sorted((finish(t) for t in teams.values()), key=lambda t: t["team"])
    # 품절 위험은 많이 팔리는 순, 과다는 재고 많은 순
    detail.sort(key=lambda x: (x["cls"] not in SHORT, -(x["daily"] if x["cls"] in SHORT else x["stock"]), x["shopId"], x["prdtCd"]))
    t_daily = tot["sales"] / days
    return {
        "brand": b, "brandNm": sc.BRAND_CODES[b], "days": days, "stockAsOf": bs["asOf"], "stockSource": bs.get("source"), "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cond": {"planYy": yy, "seasons": ss, "teams": tm, "prdt": pp, "includeVirtual": bool(include_virtual)}, "virtualRows": virtual_rows,
        "summary": {**tot, "daily": round(t_daily, 1), "cover": round(tot["stock"] / t_daily, 1) if t_daily else None,
                    "sellThru": round(tot["sales"] / (tot["sales"] + tot["stock"]) * 100, 1) if (tot["sales"] + tot["stock"]) else None,
                    "shops": len(shop_rows), "styles": len(style_rows), "shortRows": sum(cls_tot[k]["rows"] for k in SHORT),
                    "overRows": sum(cls_tot[k]["rows"] for k in OVER), "overStock": sum(cls_tot[k]["stock"] for k in OVER)},
        "classes": [{"key": k, "name": n, **cls_tot[k]} for k, n in CLASSES],
        "shops": shop_rows, "teams": team_rows, "styles": style_rows[:5000], "stylesTotal": len(style_rows),
        "detail": detail[:MAX_DETAIL], "detailTotal": len(detail), "timing": {"total": round(time.perf_counter() - started, 2)},
    }


TURN_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("stock", "재고", 9), ("amt", "재고금액", 13), ("sales", "기간 판매", 9),
             ("daily", "일평균 판매", 9), ("cover", "재고일수", 9), ("sellThru", "판매율(%)", 9), ("short", "품절 위험 스타일", 11),
             ("over", "과다 스타일", 9), ("overStock", "과다 재고", 9)]
TURN_STYLE_COLS = [("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("planYy", "기획년도", 8), ("sesnNm", "시즌", 8), ("stock", "재고", 9),
                   ("sales", "기간 판매", 9), ("daily", "일평균 판매", 9), ("cover", "재고일수", 9), ("sellThru", "판매율(%)", 9), ("shops", "매장 수", 8),
                   ("short", "품절 위험 매장", 10), ("over", "과다 매장", 9)]
TURN_DETAIL_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("prdtCd", "품번", 14), ("planYy", "기획년도", 8),
                    ("sesnNm", "시즌", 8), ("stock", "재고", 7), ("sales", "기간 판매", 8), ("daily", "일평균", 7), ("cover", "재고일수", 8),
                    ("sellThru", "판매율(%)", 8), ("clsNm", "구분", 12)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    names = dict(CLASSES)
    notes = [f"재고 회전 ({d['asOf']} · 재고 {d['stockAsOf']} 기준 · {d['brandNm']} · 최근 {d['days']}일 판매)",
             f"재고 {s['stock']:,}장 · 판매 {s['sales']:,}장 · 재고일수 {s['cover'] or '-'}일 · 판매율 {s['sellThru'] or '-'}% · "
             f"품절 위험 {s['shortRows']:,} · 과다 {s['overRows']:,}(매장 × 스타일)"]
    return sc.xlsx([("매장별", notes, TURN_COLS, d["shops"]), ("스타일별", notes, TURN_STYLE_COLS, d["styles"]),
                    ("품절 위험 · 과다", notes, TURN_DETAIL_COLS, [{**x, "clsNm": names[x["cls"]]} for x in d["detail"]])])
