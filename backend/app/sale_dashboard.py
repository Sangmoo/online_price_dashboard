"""판매 현황 대시보드: 한 달 기준 핵심 지표 · 13개월 추이 · 브랜드/팀별 · 매장 순위.

원본(T_CLOSE_SALE_BASE)에 월·매장·팀 단위 합계만 묻고, Oracle 이 사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM)로
자동 재작성해 즉시 계산한다(뷰가 최신일 때). 뷰가 오래됐으면 같은 SQL 이 원본에서 계산된다(느리지만 정확).
기간 조건은 월 목록(IN)으로 줘서 인덱스를 월 단위로 바로 찾는다.
"""
from __future__ import annotations

import re
import time
from datetime import date

from fastapi import HTTPException

from . import db
from .sale_monthly import _shift_ym, shop_names

CACHE_TTL = 10 * 60
MIN_PREV_FOR_GROWTH = 10_000_000   # 증감 순위는 전년 동월 실판금액 1천만원 이상 매장만 (작은 매장의 큰 % 변동 제외)
CLOSED_RE = re.compile(r"\(폐\)|종료")    # 매장명에 폐점/종료 표시가 있는 매장
_cache: dict[str, tuple[float, dict]] = {}


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


def _in(months: list[str], prefix: str = "m") -> tuple[str, dict]:
    binds = {f"{prefix}{i}": m for i, m in enumerate(months)}
    return ", ".join(":" + k for k in binds), binds


def _rate(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 1) if b else None


def _cost_rate(cost: float, amt: float) -> float | None:
    return round(cost * 100 / amt, 1) if amt else None


def brand_of(team: str | None) -> str:
    """'쉬즈3팀' → '쉬즈', '시스티나1팀' → '시스티나'"""
    return re.sub(r"\s*\d*\s*팀$", "", team or "").strip() or "(미지정)"


def available_months() -> list[str]:
    return [r[0] for r in db.query("SELECT DISTINCT MAKE_YYMM FROM T_CLOSE_SALE_BASE ORDER BY 1 DESC")[1] if r[0]][:60]


def dashboard(ym: str | None = None) -> dict:
    months = available_months()
    if not months:
        _bad("판매 데이터가 없습니다.")
    ym = (ym or "").replace("-", "") or months[0]
    if ym not in months:
        _bad(f"{ym[:4]}-{ym[4:]} 판매 데이터가 없습니다.")
    hit = _cache.get(ym)
    if hit and hit[0] > time.time():
        return hit[1]

    prev_m, prev_y = _shift_ym(ym, -1), _shift_ym(ym, -12)
    series = [_shift_ym(ym, -i) for i in range(24, -1, -1)]  # 25개월: 13개월 추이 + 전년 같은 달 + 누계 비교

    # 1) 월별 합계
    inl, b = _in(series)
    monthly = {r[0]: {"amt": int(r[1] or 0), "qty": int(r[2] or 0), "dsct": int(r[3] or 0), "cost": int(r[4] or 0),
                      "shops": int(r[5] or 0)}
               for r in db.query(f"""SELECT MAKE_YYMM, SUM(REAL_SALE_AMT), SUM(QTY), SUM(DSCT_AMT), SUM(PRODUCT_COST2 * QTY),
                                            COUNT(DISTINCT SHOP_ID)
                                       FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({inl}) GROUP BY MAKE_YYMM""", b)[1]}
    zero = {"amt": 0, "qty": 0, "dsct": 0, "cost": 0, "shops": 0}
    cur, pm, py = monthly.get(ym, zero), monthly.get(prev_m, zero), monthly.get(prev_y, zero)
    ytd_cur = [f"{ym[:4]}{m:02d}" for m in range(1, int(ym[4:]) + 1)]
    ytd_prev = [_shift_ym(m, -12) for m in ytd_cur]
    ysum = lambda ms, k: sum(monthly.get(m, zero)[k] for m in ms)  # noqa: E731
    kpi = {
        "amt": cur["amt"], "prevYearAmt": py["amt"], "prevMonthAmt": pm["amt"],
        "yoy": _rate(cur["amt"], py["amt"]), "mom": _rate(cur["amt"], pm["amt"]),
        "qty": cur["qty"], "prevYearQty": py["qty"], "qtyYoy": _rate(cur["qty"], py["qty"]),
        "dsct": cur["dsct"], "dsctYoy": _rate(cur["dsct"], py["dsct"]),
        "cost": cur["cost"], "costRate": _cost_rate(cur["cost"], cur["amt"]), "prevYearCostRate": _cost_rate(py["cost"], py["amt"]),
        "shops": cur["shops"], "prevYearShops": py["shops"],
        "ytdAmt": ysum(ytd_cur, "amt"), "prevYtdAmt": ysum(ytd_prev, "amt"),
        "ytdYoy": _rate(ysum(ytd_cur, "amt"), ysum(ytd_prev, "amt")),
        "avgPerShop": round(cur["amt"] / cur["shops"]) if cur["shops"] else None,
    }
    if kpi["costRate"] is not None and kpi["prevYearCostRate"] is not None:
        kpi["costRateDiff"] = round(kpi["costRate"] - kpi["prevYearCostRate"], 1)
    trend = []
    for m in series[-13:]:
        c, p = monthly.get(m, zero), monthly.get(_shift_ym(m, -12), zero)
        trend.append({"ym": m, "amt": c["amt"], "prevAmt": p["amt"], "yoy": _rate(c["amt"], p["amt"]),
                      "costRate": _cost_rate(c["cost"], c["amt"]), "shops": c["shops"]})

    # 2) 팀별 (이번 달 vs 전년 같은 달) → 브랜드별 합산
    inl, b = _in([ym, prev_y])
    team_rows = db.query(f"""SELECT MAKE_YYMM, TEAM_CD, SUM(REAL_SALE_AMT), SUM(PRODUCT_COST2 * QTY), COUNT(DISTINCT SHOP_ID)
                               FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({inl}) GROUP BY MAKE_YYMM, TEAM_CD""", b)[1]
    teams: dict[str, dict] = {}
    for m, team, amt, cost, shops in team_rows:
        t = teams.setdefault(team or "(미지정)", {"team": team or "(미지정)", "brand": brand_of(team), "amt": 0, "prevAmt": 0,
                                                  "cost": 0, "shops": 0})
        if m == ym:
            t["amt"], t["cost"], t["shops"] = int(amt or 0), int(cost or 0), int(shops or 0)
        else:
            t["prevAmt"] = int(amt or 0)
    brands: dict[str, dict] = {}
    for t in teams.values():
        t["yoy"], t["costRate"] = _rate(t["amt"], t["prevAmt"]), _cost_rate(t["cost"], t["amt"])
        br = brands.setdefault(t["brand"], {"brand": t["brand"], "amt": 0, "prevAmt": 0, "cost": 0, "shops": 0, "teams": 0})
        for k in ("amt", "prevAmt", "cost", "shops"):
            br[k] += t[k]
        br["teams"] += 1
    for br in brands.values():
        br["yoy"], br["costRate"] = _rate(br["amt"], br["prevAmt"]), _cost_rate(br["cost"], br["amt"])
        br["share"] = round(br["amt"] * 100 / cur["amt"], 1) if cur["amt"] else None

    # 3) 매장별 (이번 달 · 전월 · 전년 같은 달)
    inl, b = _in([ym, prev_m, prev_y])
    shop: dict[str, dict] = {}
    for m, sid, amt, cost in db.query(f"""SELECT MAKE_YYMM, SHOP_ID, SUM(REAL_SALE_AMT), SUM(PRODUCT_COST2 * QTY)
                                            FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({inl}) GROUP BY MAKE_YYMM, SHOP_ID""", b)[1]:
        s = shop.setdefault(sid, {"shopId": sid, "amt": 0, "prevMonthAmt": 0, "prevYearAmt": 0, "cost": 0})
        if m == ym:
            s["amt"], s["cost"] = int(amt or 0), int(cost or 0)
        elif m == prev_m:
            s["prevMonthAmt"] = int(amt or 0)
        else:
            s["prevYearAmt"] = int(amt or 0)
    for s in shop.values():
        s["yoy"], s["mom"], s["costRate"] = _rate(s["amt"], s["prevYearAmt"]), _rate(s["amt"], s["prevMonthAmt"]), _cost_rate(s["cost"], s["amt"])
    selling = [s for s in shop.values() if s["amt"] > 0]
    top = sorted(selling, key=lambda s: s["amt"], reverse=True)[:10]
    names = shop_names([s["shopId"] for s in selling])
    for s in selling:
        s["shopNm"] = names.get(s["shopId"])
    # 증감 순위: 전년 동월 매출이 충분하고(작은 매장의 큰 % 변동 제외), 폐점·종료 매장이 아닌 곳만
    comparable = [s for s in selling if s["prevYearAmt"] >= MIN_PREV_FOR_GROWTH and s["yoy"] is not None]
    closed = [s for s in comparable if CLOSED_RE.search(s["shopNm"] or "")]
    comparable = [s for s in comparable if s not in closed]
    risers = sorted(comparable, key=lambda s: s["yoy"], reverse=True)[:10]
    fallers = sorted(comparable, key=lambda s: s["yoy"])[:10]
    new_shops = sum(1 for s in selling if s["prevYearAmt"] == 0)

    out = {
        "ym": ym, "prevMonth": prev_m, "prevYear": prev_y, "months": months[:36], "kpi": kpi, "trend": trend,
        "brands": sorted(brands.values(), key=lambda x: x["amt"], reverse=True),
        "teams": sorted(teams.values(), key=lambda x: (x["brand"], x["team"])),
        "topShops": top, "risers": risers, "fallers": fallers,
        "shopCounts": {"selling": len(selling), "new": new_shops, "comparable": len(comparable), "closedExcluded": len(closed)},
        "minPrevForGrowth": MIN_PREV_FOR_GROWTH,
        "generatedAt": date.today().isoformat(),
    }
    if len(_cache) > 50:
        _cache.clear()
    _cache[ym] = (time.time() + CACHE_TTL, out)
    return out
