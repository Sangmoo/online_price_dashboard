"""매장 평가 카드 (매장 정보 팝업): 판매 추세 · 재고 회전 · RT 응답 · 초도 판매율을 브랜드 평균과 비교해 한 장으로.

- 판매 추세: 최근 4주(어제까지 28일) 실판금액 vs 그 전 4주 · 전년 같은 4주(364일 전), 브랜드 같은 기준과 비교
- 재고 회전: 매장 재고(이번 달) ÷ 최근 28일 일평균 판매 = 재고일수, 90일 넘게 안 팔린 재고 비중
  (브랜드 평균은 재고 회전 · 장기 미판매 기준이 계산돼 있을 때만 — 매일 아침 미리 계산)
- RT 응답: 최근 30일 이 매장이 보내는 쪽인 RT 요청(본사지시 · 자동 RT · 매장간)의 수락률 · 평균 처리 시간 · 자동거부 · 미처리, 브랜드 평균
- 초도 판매율: 초도 배분 적중률(기본 28일 판매)의 이 매장 행과 브랜드 전체
- 평가: 브랜드 평균 대비 좋음 · 보통 · 주의 (기준은 각 항목 note)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import db, logs
from . import stock_ctl as sc

_log = logs.get("app")
TYPES = ("C6811", "C6812", "C6813")


def _d8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _rate(a: float, b: float) -> float | None:
    return round((a - b) / b * 100, 1) if b else None


def _sales(shop: str, brand: str) -> dict:
    y = date.today() - timedelta(days=1)
    rng = {"cur": (y - timedelta(days=27), y), "prev": (y - timedelta(days=55), y - timedelta(days=28)),
           "ly": (y - timedelta(days=27 + 364), y - timedelta(days=364))}
    out: dict = {"from": sc.ymd_label(_d8(rng["cur"][0])), "to": sc.ymd_label(_d8(y))}
    for k, (f, t) in rng.items():
        amt, qty = db.query("""SELECT SUM(DECODE(RET_YN, 'Y', -1, 1) * NVL(REAL_SALE_AMT, 0)), SUM(DECODE(RET_YN, 'Y', -QTY, QTY)) FROM T_SHOP_RNDS_BASE
                                WHERE SHOP_ID = :s AND MAKE_DT BETWEEN :f AND :t AND STOCK_STAT = 'C20922' AND DEL_DAY IS NULL""",
                            {"s": shop, "f": _d8(f), "t": _d8(t)})[1][0]
        out[f"{k}Amt"], out[f"{k}Qty"] = int(amt or 0), int(qty or 0)

    def brand_total(f, t):
        return sc.cached(("sc-brand-sales", brand, _d8(f), _d8(t)), 3600, lambda: int(db.query(
            f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_05) */ SUM(DECODE(R.RET_YN, 'Y', -1, 1) * NVL(R.REAL_SALE_AMT, 0)) FROM T_SHOP_RNDS_BASE R
                 WHERE R.MAKE_DT BETWEEN :f AND :t AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL AND R.COMPY_CD = '{sc.COMPY_CD}'
                   AND R.PRDT_CD LIKE :b || '%'""", {"f": _d8(f), "t": _d8(t), "b": brand})[1][0][0] or 0))
    bc, bp, bl = (brand_total(*rng[k]) for k in ("cur", "prev", "ly"))
    out.update({"vsPrev": _rate(out["curAmt"], out["prevAmt"]), "vsLy": _rate(out["curAmt"], out["lyAmt"]),
                "brandVsPrev": _rate(bc, bp), "brandVsLy": _rate(bc, bl)})
    gap = None if out["vsPrev"] is None or out["brandVsPrev"] is None else out["vsPrev"] - out["brandVsPrev"]
    out["grade"] = "none" if gap is None else "good" if gap >= 5 else "bad" if gap <= -5 else "ok"
    out["note"] = "최근 4주 전 4주 대비 증감을 브랜드와 비교 (±5%p)"
    return out


def _stock(shop: str, brand: str, sales28: int) -> dict:
    qty, amt, aged = db.query(f"""SELECT SUM(S.STOCK_QTY), SUM(NVL(S.STOCK_AMT, 0)),
                                         SUM(CASE WHEN NVL(B.L_SALE_DT, B.F_RNDS_DT) < TO_CHAR(SYSDATE - 90, 'YYYYMMDD') THEN S.STOCK_QTY ELSE 0 END)
                                    FROM T_SHOP_STOCK S, T_SHOP_PRDT_BASE B
                                   WHERE S.MAKE_YYMM = TO_CHAR(SYSDATE, 'YYYYMM') AND S.SHOP_ID = :s AND S.STOCK_QTY > 0
                                     AND B.COMPY_CD(+) = '{sc.COMPY_CD}' AND B.PARENT_BRD_CD(+) = :b AND B.SHOP_ID(+) = S.SHOP_ID
                                     AND B.PRDT_CD(+) = S.PRDT_CD AND B.COLOR_CD(+) = S.COLOR_CD AND B.SIZE_CD(+) = S.SIZE_CD""",
                              {"s": shop, "b": brand})[1][0]
    qty, amt, aged = int(qty or 0), int(amt or 0), int(aged or 0)
    daily = max(sales28, 0) / 28
    out = {"stock": qty, "amt": amt, "sales28": sales28, "cover": round(qty / daily, 1) if daily else None,
           "sellThru": round(sales28 / (sales28 + qty) * 100, 1) if (sales28 + qty) > 0 else None,
           "agedQty": aged, "agedRate": round(aged / qty * 100, 1) if qty else None, "brandCover": None, "brandAgedRate": None}
    try:                                             # 브랜드 평균: 재고 기준이 이미 계산돼 있으면 (매일 아침 미리 계산) — 없으면 비교 생략
        from . import stock_aging, stock_turnover
        if brand in stock_aging._cache:
            out["brandCover"] = stock_turnover.report(brand, 28)["summary"]["cover"]
            out["brandAgedRate"] = stock_aging.report(brand, 90)["summary"]["agedRate"]
    except Exception:  # noqa: BLE001
        _log.warning("매장 평가 카드 브랜드 재고 평균 실패 %s", brand, exc_info=True)
    c, bc = out["cover"], out["brandCover"]
    if c is None:
        out["grade"] = "bad" if qty else "none"
    elif bc:
        out["grade"] = "good" if c <= bc * 0.8 else "bad" if c >= bc * 1.3 else "ok"
    else:
        out["grade"] = "good" if c <= 60 else "bad" if c >= 180 else "ok"
    out["note"] = "재고일수를 브랜드 평균과 비교 (0.8배 이하 좋음 · 1.3배 이상 주의, 평균이 없으면 60 · 180일)"
    return out


def _rt_rows(where: str, b: dict) -> list[tuple]:
    return db.query(f"""SELECT PRCS_CLSBY, PRCS_USERID, NVL(RESN, ' '), COUNT(*),
                               SUM(CASE WHEN PRCS_CLSBY IN ('C2951', 'C2952') AND PRCS_DAY IS NOT NULL AND INS_DAY IS NOT NULL
                                        THEN (TO_DATE(SUBSTR(PRCS_DAY, 1, 14), 'YYYYMMDDHH24MISS') - TO_DATE(SUBSTR(INS_DAY, 1, 14), 'YYYYMMDDHH24MISS')) * 24 END),
                               SUM(CASE WHEN PRCS_CLSBY IN ('C2951', 'C2952') AND PRCS_DAY IS NOT NULL AND INS_DAY IS NOT NULL THEN 1 ELSE 0 END)
                          FROM T_SHOP_REQ
                         WHERE {where} AND MOVE_TYPE IN ('C6811', 'C6812', 'C6813') AND MAKE_DT >= TO_CHAR(SYSDATE - 30, 'YYYYMMDD') AND DEL_DAY IS NULL
                         GROUP BY PRCS_CLSBY, PRCS_USERID, NVL(RESN, ' ')""", b)[1]


def _rt_sum(rows: list[tuple]) -> dict:
    acc = den = auto = pend = 0
    hours = n_h = 0.0
    for prcs, user, resn, n, h, nh in rows:
        n = int(n)
        is_auto = prcs == "C2952" and (user == "ADMIN" or "자동거부" in (resn or ""))
        if prcs == "C2951":
            acc += n
        elif is_auto:
            auto += n
        elif prcs == "C2952":
            den += n
        elif prcs == "C2954":
            pend += n
        if (prcs == "C2951" or (prcs == "C2952" and not is_auto)) and h is not None:   # 처리 시간은 매장이 직접 처리한 건만
            hours += float(h)
            n_h += float(nh or 0)
    done = acc + den + auto
    return {"requests": done + pend, "accepted": acc, "denied": den, "autoDenied": auto, "pending": pend,
            "acceptRate": round(acc / done * 100, 1) if done else None, "avgHours": round(hours / n_h, 1) if n_h else None}


def _rt(shop: str, brand: str) -> dict:
    out = _rt_sum(_rt_rows("DELV_REQ_SHOP_ID = :s", {"s": shop}))
    br = sc.cached(("sc-brand-rt", brand, sc.today()), 3600, lambda: _rt_sum(_rt_rows("BRD_CD = :b", {"b": brand})))
    out.update({"brandAcceptRate": br["acceptRate"], "brandAvgHours": br["avgHours"]})
    a, ba = out["acceptRate"], br["acceptRate"]
    if a is None:
        out["grade"] = "none"
    elif ba is not None and (a <= ba - 10 or (out["avgHours"] or 0) > 48 or out["autoDenied"] >= 5):
        out["grade"] = "bad"
    elif ba is not None and a >= ba + 5 and (out["avgHours"] or 0) <= (br["avgHours"] or 999):
        out["grade"] = "good"
    else:
        out["grade"] = "ok"
    out["note"] = "최근 30일 이 매장이 보내는 RT 요청 — 수락률 브랜드 −10%p 이하 · 평균 처리 48시간 넘음 · 자동거부 5건 이상이면 주의"
    return out


def _initial(shop: str, brand: str) -> dict:
    from . import stock_initial

    d = stock_initial.analyze(brand, window=28)
    row = next((r for r in d["shops"] if r["shopId"] == shop), None)
    s = d["summary"]
    out = {"period": f"{d['from']} ~ {d['to']}", "window": d["window"], "brandSellThru": s["sellThru"], "brandOverlap": s["overlap"]}
    if not row:
        return {**out, "alloc": 0, "sold": 0, "sellThru": None, "products": 0, "zero": 0, "soldOut": 0, "grade": "none",
                "note": "이 기간에 이 매장 초도 배분이 없습니다"}
    st, bst = row["sellThru"], s["sellThru"]
    grade = "none" if st is None or not bst else "good" if st >= bst * 1.2 else "bad" if st <= bst * 0.7 else "ok"
    return {**out, **{k: row[k] for k in ("alloc", "sold", "sellThru", "products", "zero", "soldOut")}, "grade": grade,
            "note": f"초도 배분 뒤 {d['window']}일 판매율을 브랜드와 비교 (1.2배 이상 좋음 · 0.7배 이하 주의)"}


def scorecard(shop_id: str, me: dict) -> dict:
    pages = set(me.get("pages") or [])
    sale_ok = bool(pages & {"sale_dashboard", "sale_monthly"})
    stock_ok = "stock_rt" in pages
    if not (sale_ok or stock_ok):
        sc.bad("매장 평가 카드는 판매 또는 재고 재배치 추천 메뉴 권한이 있어야 볼 수 있습니다.", 403)
    sid = (shop_id or "").upper()
    sh = sc.shops().get(sid)
    if not sh:
        sc.bad("매장을 찾을 수 없습니다.", 404)
    brand = sid[:1]
    if brand not in sc.BRAND_CODES:
        sc.bad("브랜드를 알 수 없는 매장입니다.")
    sc.brand_code(brand, me.get("brands") or None)       # 브랜드 권한
    out: dict = {"shopId": sid, "shopNm": sh.get("shopNm"), "brand": brand, "brandNm": sc.BRAND_CODES[brand], "virtual": sh.get("virtual"),
                 "virtualWhy": sh.get("virtualWhy"), "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "errors": []}

    def take(name, fn):
        try:
            out[name] = fn()
        except Exception as ex:  # noqa: BLE001 - 한 항목 실패가 카드 전체를 막지 않게
            out["errors"].append(f"{name}: {str(getattr(ex, 'detail', ex))[:120]}")
            _log.warning("매장 평가 카드 %s %s 실패", sid, name, exc_info=True)
    take("sales", lambda: _sales(sid, brand))
    if stock_ok:
        take("stock", lambda: _stock(sid, brand, (out.get("sales") or {}).get("curQty") or _qty28(sid)))
        take("rt", lambda: _rt(sid, brand))
        take("initial", lambda: _initial(sid, brand))
    if not sale_ok:                                       # 판매 권한이 없으면 금액은 숨기고 수량만
        s = out.get("sales") or {}
        for k in ("curAmt", "prevAmt", "lyAmt"):
            s.pop(k, None)
    grades = [out[k]["grade"] for k in ("sales", "stock", "rt", "initial") if k in out and out[k].get("grade") != "none"]
    out["summary"] = {"good": grades.count("good"), "ok": grades.count("ok"), "bad": grades.count("bad")}
    return out


def _qty28(shop: str) -> int:
    y = date.today() - timedelta(days=1)
    return int(db.query("""SELECT SUM(DECODE(RET_YN, 'Y', -QTY, QTY)) FROM T_SHOP_RNDS_BASE
                            WHERE SHOP_ID = :s AND MAKE_DT BETWEEN :f AND :t AND STOCK_STAT = 'C20922' AND DEL_DAY IS NULL""",
                        {"s": shop, "f": _d8(y - timedelta(days=27)), "t": _d8(y)})[1][0][0] or 0)
