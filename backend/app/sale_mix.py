"""판매 현황 > 세일 비중이 높은 매장: 매장 실판금액 중 세일 판매 비중이 같은 브랜드 평균보다 크게 높은 매장.

- 세일 판매 = 판매형태(DSCT_CLSBY_NM) 이름에 '세일'이 들어간 판매. 행사는 백화점 행사장 등 정상 영업 형태라
  넣으면 브랜드 평균이 70%를 넘고 행사 전용 매장이 모두 100% 가 되어 구분이 안 되므로 뺀다.
- 행사·특판 전용 매장(매장명이 '(행)', '(특)' 으로 시작하거나 '사내행사')은 기본 제외 (include_event=True 면 포함).
- 매장의 브랜드 = 기간 중 가장 많이 판 팀의 브랜드. 브랜드 평균 = 그 브랜드 팀들의 전체 판매 기준 비중.
- 대상: 기간 월평균 실판금액 1천만원 이상 · 폐점/종료 표시 매장 제외 (판매 현황 성장 순위와 같은 기준).
- 비교 기간(판매 현황의 비교 기준)의 같은 매장 비중과 변화(%p)도 함께.
조건(기간 · 비교 기준 · 브랜드 · 브랜드 권한)은 판매 현황(sale_dashboard.resolve)과 같다.
원천: 원본 T_CLOSE_SALE_BASE (매장 × 판매형태). 기간·비교 기간 합 최대 24개월, 10분 캐시.
"""
from __future__ import annotations

import re
import threading
import time

from . import db
from . import sale_dashboard as sd
from . import sale_monthly as sm

TOP_N = 15
MIN_MONTHLY_AMT = sd.MIN_PREV_FOR_GROWTH   # 월평균 1천만원
CACHE_TTL = 10 * 60
EVENT_SHOP_RE = re.compile(r"^\((행|특)\)|사내행사")
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def is_discount(name: str | None) -> bool:
    return bool(name) and "세일" in name


def heavy_shops(ym: str | None = None, frm: str | None = None, cmp: str | None = None, cmp_from: str | None = None,
                cmp_to: str | None = None, brand: str | None = None, allowed: list[str] | None = None,
                include_event: bool = False, ttl: int | None = None) -> dict:
    r = sd.resolve(ym, frm, cmp, cmp_from, cmp_to, brand, allowed)
    period, base, teams = r["period"], r["base"], r["teams"]
    meta = {"period": sd.period_label(period), "base": sd.period_label(base), "baseKind": sd.CMP_KINDS[r["kind"]],
            "brand": r["brand"], "minMonthlyAmt": MIN_MONTHLY_AMT, "rule": "세일 비중 = 판매형태에 '세일'이 들어간 판매 ÷ 매장 실판금액",
            "includeEvent": include_event}
    key = (tuple(period), tuple(base), tuple(teams) if teams is not None else None)
    hit = _cache.get(key)
    if hit and hit[0] > time.time() and ttl is None:
        full = hit[1]
    else:
        full = _compute(period, base, teams)
        with _lock:
            if len(_cache) > 50:
                _cache.clear()
            _cache[key] = (time.time() + (ttl or CACHE_TTL), full)
    rows = [s for s in full["all"] if include_event or not s["event"]]
    return {**meta, "shops": rows[:TOP_N], "candidateCount": len(rows), "eventShops": sum(1 for s in full["all"] if s["event"]),
            "brandAverages": full["brandAverages"]}


def _compute(period: list[str], base: list[str], teams: list[str] | None) -> dict:
    months = sorted(set(period) | set(base))
    mb = {f"m{i}": m for i, m in enumerate(months)}
    team_sql, tb = "", {}
    if teams is not None:
        tb = {f"t{i}": t for i, t in enumerate(teams or ["-"])}
        team_sql = f" AND TEAM_CD IN ({', '.join(':' + k for k in tb)})"
    rows = db.query(f"""SELECT MAKE_YYMM, SHOP_ID, TEAM_CD, DSCT_CLSBY_NM, SUM(REAL_SALE_AMT)
                          FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({', '.join(':' + k for k in mb)}){team_sql}
                         GROUP BY MAKE_YYMM, SHOP_ID, TEAM_CD, DSCT_CLSBY_NM""", {**mb, **tb})[1]
    sp, sb = set(period), set(base)
    shops: dict[str, dict] = {}
    brands: dict[str, dict] = {}
    for ym, sid, team, typ, amt in rows:
        amt = int(amt or 0)
        disc = amt if is_discount(typ) else 0
        b = sd.brand_of(team)
        s = shops.setdefault(sid, {"shopId": sid, "teams": {}, "amt": 0, "disc": 0, "baseAmt": 0, "baseDisc": 0})
        g = brands.setdefault(b, {"amt": 0, "disc": 0, "baseAmt": 0, "baseDisc": 0})
        if ym in sp:
            s["amt"] += amt
            s["disc"] += disc
            s["teams"][team] = s["teams"].get(team, 0) + amt
            g["amt"] += amt
            g["disc"] += disc
        if ym in sb:
            s["baseAmt"] += amt
            s["baseDisc"] += disc
            g["baseAmt"] += amt
            g["baseDisc"] += disc

    def share(d, a):
        return round(d * 100 / a, 1) if a > 0 else None

    brand_avg = {b: {"brand": b, "share": share(g["disc"], g["amt"]), "baseShare": share(g["baseDisc"], g["baseAmt"]), "amt": g["amt"]}
                 for b, g in brands.items()}
    min_amt = MIN_MONTHLY_AMT * len(period)
    cands = [s for s in shops.values() if s["amt"] >= min_amt and s["teams"]]
    names = sm.shop_names([s["shopId"] for s in cands])
    out = []
    for s in cands:
        nm = names.get(s["shopId"])
        if nm and sd.CLOSED_RE.search(nm):
            continue
        team = max(s["teams"], key=s["teams"].get)
        b = sd.brand_of(team)
        sh, bsh = share(s["disc"], s["amt"]), share(s["baseDisc"], s["baseAmt"])
        avg = brand_avg.get(b, {}).get("share")
        out.append({"shopId": s["shopId"], "shopNm": nm, "event": bool(nm and EVENT_SHOP_RE.search(nm)), "team": team, "brand": b, "amt": s["amt"], "discAmt": s["disc"],
                    "share": sh, "brandShare": avg, "diff": sd._diff(sh, avg), "baseShare": bsh, "shareChange": sd._diff(sh, bsh)})
    out.sort(key=lambda x: (x["diff"] if x["diff"] is not None else -999), reverse=True)
    return {"all": out, "brandAverages": sorted(brand_avg.values(), key=lambda x: -x["amt"])}
