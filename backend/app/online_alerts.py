"""판매 현황 > 온라인 할인 주의 상품: 매장 실판금액 상위 상품 중 최근 온라인 할인율이 크게 오른 상품.

- 대상: 판매 현황 조건(기간·브랜드·브랜드 권한)의 매장 실판금액 상위 50개 상품 (sale_products.analyze 결과 재사용)
- 온라인: 최근 7일 평균 할인율 vs 그 전 4주(8~35일 전) 평균 할인율. 품번 목록 + (PRDT_CD, DT) 인덱스로 1초 안팎.
- 주의: 최근 7일 평균이 이전 4주보다 ALERT_DIFF %p 이상 높거나, 이전 4주 수집이 없는데 최근 할인율이 ALERT_NEW 이상.
화면·API 는 온라인 가격 메뉴 권한도 있는 사용자에게만 보인다 (main.py).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from . import data_service as ds
from . import db
from . import sale_products as sp

RECENT_DAYS = 7
BASE_DAYS = 28
ALERT_DIFF = 3.0       # %p
ALERT_NEW = 15.0       # %
CACHE_TTL = 10 * 60
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _online(codes: list[str], today: datetime) -> dict[str, dict]:
    recent = (today - timedelta(days=RECENT_DAYS - 1)).strftime("%Y%m%d")
    since = (today - timedelta(days=RECENT_DAYS + BASE_DAYS - 1)).strftime("%Y%m%d")
    inl, b = sp._in(codes, "p")
    out = {}
    for cd, r7, r28, low7, malls, n7, n28, last in db.query(
            f"""SELECT PRDT_CD,
                       ROUND(AVG(CASE WHEN DT >= :r THEN {ds.DC_RATE_SQL} END), 1),
                       ROUND(AVG(CASE WHEN DT < :r THEN {ds.DC_RATE_SQL} END), 1),
                       MIN(CASE WHEN DT >= :r THEN DC_PRICE END),
                       COUNT(DISTINCT CASE WHEN DT >= :r THEN MALL_NM END),
                       COUNT(CASE WHEN DT >= :r THEN 1 END), COUNT(CASE WHEN DT < :r THEN 1 END), MAX(DT)
                  FROM {ds.TABLE} WHERE PRDT_CD IN ({inl}) AND DT >= :s AND PRICE > 0 GROUP BY PRDT_CD""",
            {**b, "r": recent, "s": since})[1]:
        out[cd] = {"recentRate": float(r7) if r7 is not None else None, "baseRate": float(r28) if r28 is not None else None,
                   "lowPrice": int(low7) if low7 is not None else None, "malls": int(malls or 0),
                   "recentRows": int(n7 or 0), "baseRows": int(n28 or 0), "lastDt": last}
    return out


def alerts(ym: str | None = None, frm: str | None = None, cmp: str | None = None, cmp_from: str | None = None,
           cmp_to: str | None = None, brand: str | None = None, allowed: list[str] | None = None,
           today: datetime | None = None) -> dict:
    pr = sp.analyze(ym, frm, cmp, cmp_from, cmp_to, brand, allowed, internal=True)
    today = today or datetime.now()
    meta = {"period": pr["period"], "brand": pr["brand"], "recentDays": RECENT_DAYS, "baseDays": BASE_DAYS,
            "alertDiff": ALERT_DIFF, "alertNew": ALERT_NEW,
            "recentFrom": (today - timedelta(days=RECENT_DAYS - 1)).strftime("%Y-%m-%d"),
            "baseFrom": (today - timedelta(days=RECENT_DAYS + BASE_DAYS - 1)).strftime("%Y-%m-%d")}
    if pr.get("unavailable"):
        return {**meta, "unavailable": pr["unavailable"], "rows": [], "alertCount": 0}
    top = pr.get("_top") or []
    codes = [p["prdtCd"] for p in top]
    key = (tuple(codes), today.strftime("%Y%m%d%H"))
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        online = hit[1]
    else:
        online = _online(codes, today) if codes else {}
        with _lock:
            if len(_cache) > 50:
                _cache.clear()
            _cache[key] = (time.time() + CACHE_TTL, online)
    rows = []
    for rank, p in enumerate(top, 1):
        o = online.get(p["prdtCd"])
        diff = round(o["recentRate"] - o["baseRate"], 1) if o and o["recentRate"] is not None and o["baseRate"] is not None else None
        flag = None
        if o and o["recentRate"] is not None:
            if diff is not None and diff >= ALERT_DIFF:
                flag = "rise"
            elif o["baseRate"] is None and o["recentRate"] >= ALERT_NEW:
                flag = "new"
        rows.append({"rank": rank, "prdtCd": p["prdtCd"], "itemNm": p["itemNm"], "prdtGrpNm": p["prdtGrpNm"],
                     "storeAmt": p["amt"], "storeQty": p["qty"], "storeDsctRate": p["dsctRate"],
                     "online": o, "diff": diff, "flag": flag})
    rows.sort(key=lambda x: (x["flag"] is None, -(x["diff"] if x["diff"] is not None else -999), x["rank"]))
    return {**meta, "rows": rows, "alertCount": sum(1 for x in rows if x["flag"]),
            "withOnline": sum(1 for x in rows if x["online"]), "total": len(rows)}
