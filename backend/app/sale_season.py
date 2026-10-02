"""판매 현황 > 시즌 판매 진척: 시즌(기획년도 + 시즌)별 월 누적 판매를 전년 같은 시즌의 같은 시점과 비교.

- 같은 시점 = 판매년월을 12개월 앞당긴 달 (2026 가을의 2026-09 ↔ 2025 가을의 2025-09).
- 진척률 = 올해 누적 ÷ 전년 시즌 최종 누적 (전년 시즌이 그 뒤로 얼마나 더 팔렸는지까지 보고 지금 어디쯤인지).
- 기준 월·브랜드·브랜드 권한은 판매 현황(sale_dashboard.resolve)과 같다. 기간·비교 기준은 쓰지 않는다 (시즌이 기간을 정함).

원천: 상품 사전 집계 뷰(MV_CLOSE_SALE_PRDT_YM, 기획년도·시즌 열 포함)가 최신이고 기준 월을 담고 있으면 뷰(즉시),
아니면 원본 T_CLOSE_SALE_BASE (최근 30개월 약 10~15초, 10분 캐시 · 기본 조건은 prewarm 이 미리 계산).
"""
from __future__ import annotations

import threading
import time

from . import db, logs
from . import sale_dashboard as sd
from . import sale_monthly as sm
from . import sale_products as sp

_log = logs.get("app")
LOOKBACK = 30                # 기준 월에서 몇 개월 전까지 읽나 (시즌 창 18개월 + 전년 12개월)
WINDOW = 18                  # 시즌 창 최대 개월 수 (시작 월부터)
LEAD_MIN_SHARE = 0.003       # 시작 월: 시즌 합계의 0.3% 미만인 앞쪽 달은 건너뜀 (선판매 몇 건)
OPTION_MONTHS = 12           # 선택지: 최근 12개월 안에 판매가 있는 시즌
CACHE_TTL = 10 * 60
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _season_key(yy: str | None, ss: str | None) -> tuple:
    return (-(int(yy) if yy and str(yy).isdigit() else 0), sm.SEASONS.index(ss) if ss in sm.SEASONS else 99, ss or "")


def _load(to: str, teams: list[str] | None, ttl: int | None) -> dict:
    """{(기획년도, 시즌): {월: (실판금액, 수량, 할인금액)}} + 원천"""
    frm = sm._shift_ym(to, -(LOOKBACK - 1))
    key = (to, tuple(teams) if teams is not None else None)
    hit = _cache.get(key)
    if hit and hit[0] > time.time() and ttl is None:
        return hit[1]
    months = sd.month_range(frm, to)
    team_sql, tb = "", {}
    if teams is not None:
        tinl, tb = sp._in(teams or ["-"], "t")
        team_sql = f" AND TEAM_CD IN ({tinl})"
    rows, src = None, "base"
    st = sp.mv_state()
    if st["usable"] and st["mv_max"] and to <= st["mv_max"]:
        try:
            rows = db.query(f"""SELECT PLAN_YY, SESS_NM, MAKE_YYMM, SUM(TOTAL_SALE_AMT), SUM(TOTAL_QTY), SUM(TOTAL_DSCT_AMT)
                                  FROM {sp.MV_NAME} WHERE MAKE_YYMM BETWEEN :f AND :t{team_sql}
                                 GROUP BY PLAN_YY, SESS_NM, MAKE_YYMM""", {"f": frm, "t": to, **tb})[1]
            src = "mv"
        except Exception:  # noqa: BLE001 - 기획년도·시즌 열이 없는 예전 뷰면 원본
            _log.warning("상품 뷰에 기획년도·시즌 열이 없어 원본으로 시즌 진척을 계산합니다 (db/create_mv_close_sale_prdt_ym.sql 다시 실행)")
    if rows is None:
        minl, mb = sp._in(months, "m")
        rows = db.query(f"""SELECT PLAN_YY, {sm.SESS_EXPR}, MAKE_YYMM, SUM(REAL_SALE_AMT), SUM(QTY), SUM(DSCT_AMT)
                              FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({minl}){team_sql}
                             GROUP BY PLAN_YY, {sm.SESS_EXPR}, MAKE_YYMM""", {**mb, **tb})[1]
    data: dict[tuple, dict[str, tuple[int, int, int]]] = {}
    for yy, ss, ym, amt, qty, dsct in rows:
        if not yy or not ss:
            continue
        data.setdefault((str(yy), ss), {})[ym] = (int(amt or 0), int(qty or 0), int(dsct or 0))
    out = {"data": data, "source": src, "from": frm}
    with _lock:
        if len(_cache) > 30:
            _cache.clear()
        _cache[key] = (time.time() + (ttl or CACHE_TTL), out)
    return out


def _start(series: dict[str, tuple]) -> str | None:
    total = sum(v[0] for v in series.values())
    for ym in sorted(series):
        if total and series[ym][0] >= total * LEAD_MIN_SHARE:
            return ym
    return min(series) if series else None


def progress(ym: str | None = None, brand: str | None = None, allowed: list[str] | None = None,
             plan_yy: str | None = None, season: str | None = None, ttl: int | None = None) -> dict:
    r = sd.resolve(ym, None, None, None, None, brand, allowed)
    to, teams = r["to"], r["teams"]
    loaded = _load(to, teams, ttl)
    data = loaded["data"]
    recent = set(sd.month_range(sm._shift_ym(to, -(OPTION_MONTHS - 1)), to))
    options = []
    for (yy, ss), series in data.items():
        amt = sum(v[0] for m, v in series.items() if m in recent)
        if amt > 0:
            options.append({"planYy": yy, "season": ss, "amt": amt, "lastAmt": series.get(to, (0, 0, 0))[0]})
    options.sort(key=lambda o: _season_key(o["planYy"], o["season"]))
    meta = {"to": to, "toLabel": sd.ym_label(to), "brand": r["brand"], "brandOptions": r["brandOptions"],
            "options": options, "source": "사전 집계 뷰" if loaded["source"] == "mv" else "원본"}
    if not options:
        return {**meta, "planYy": None, "season": None, "months": []}
    if plan_yy and season:
        if not any(o["planYy"] == str(plan_yy) and o["season"] == season for o in options):
            avail = ", ".join(f"{o['planYy']} {o['season']}" for o in options[:16])
            sd._bad(f"{plan_yy} {season} 시즌은 최근 {OPTION_MONTHS}개월 판매가 없습니다"
                    f"{' (' + r['brand'] + ')' if r['brand'] else ''}. 선택할 수 있는 시즌: {avail}")
        yy, ss = str(plan_yy), season
    else:  # 기본: 기준 월에 가장 많이 팔린 시즌
        best = max(options, key=lambda o: (o["lastAmt"], o["amt"]))
        yy, ss = best["planYy"], best["season"]
    cur = data.get((yy, ss), {})
    prev_raw = data.get((str(int(yy) - 1), ss), {}) if yy.isdigit() else {}
    prev = {sm._shift_ym(m, 12): v for m, v in prev_raw.items()}  # 전년 달을 올해 달 위치로
    starts = [s for s in (_start(cur), _start(prev)) if s]
    start = min(starts)
    window = sd.month_range(start, sm._shift_ym(start, WINDOW - 1))
    last_prev = max(prev) if prev else None
    window = [m for m in window if m <= to or (last_prev and m <= last_prev)]
    months, cum, pcum = [], 0, 0
    prev_final = sum(v[0] for m, v in prev.items() if m >= start)
    for i, m in enumerate(window):
        c = cur.get(m) if m <= to else None
        p = prev.get(m)
        if c is not None or m <= to:
            cum += (c or (0, 0, 0))[0]
        pcum += (p or (0, 0, 0))[0]
        months.append({
            "ym": m, "label": sd.ym_label(m), "step": i + 1, "prevYm": sm._shift_ym(m, -12),
            "amt": (c or (0, 0, 0))[0] if m <= to else None, "qty": (c or (0, 0, 0))[1] if m <= to else None,
            "cum": cum if m <= to else None,
            "prevAmt": p[0] if p else 0, "prevCum": pcum,
        })
    upto = [x for x in months if x["ym"] <= to]
    cur_amt = sum(v[0] for m, v in cur.items() if start <= m <= to)
    cur_qty = sum(v[1] for m, v in cur.items() if start <= m <= to)
    cur_dsct = sum(v[2] for m, v in cur.items() if start <= m <= to)
    p_same = [v for m, v in prev.items() if start <= m <= to]
    p_amt, p_qty, p_dsct = sum(v[0] for v in p_same), sum(v[1] for v in p_same), sum(v[2] for v in p_same)
    return {
        **meta, "planYy": yy, "season": ss, "prevPlanYy": str(int(yy) - 1) if yy.isdigit() else None,
        "start": start, "startLabel": sd.ym_label(start), "step": len(upto),
        "months": months,
        "kpi": {
            "amt": cur_amt, "qty": cur_qty, "prevSameAmt": p_amt, "prevSameQty": p_qty,
            "change": sd._rate(cur_amt, p_amt), "qtyChange": sd._rate(cur_qty, p_qty),
            "prevFinalAmt": prev_final,
            "progress": round(cur_amt * 100 / prev_final, 1) if prev_final else None,
            "prevProgressSame": round(p_amt * 100 / prev_final, 1) if prev_final else None,
            "dsctRate": sd._dsct_rate(cur_dsct, cur_amt), "prevDsctRate": sd._dsct_rate(p_dsct, p_amt),
            "lastAmt": cur.get(to, (0, 0, 0))[0], "prevLastAmt": prev.get(to, (0, 0, 0))[0],
        },
    }


def items(ym: str | None = None, brand: str | None = None, allowed: list[str] | None = None,
          plan_yy: str | None = None, season: str | None = None) -> dict:
    """시즌 진척을 아이템별로: 아이템마다 누적 · 전년 같은 시점 · 증감 · 전년 시즌 최종 대비 진척률 · 비중.
    시즌·시작 월·기준 월은 progress() 와 같다. 상품 뷰에 아이템 열이 있어 뷰면 즉시, 없으면 원본(시즌 2개 × 최대 30개월)."""
    p = progress(ym, brand, allowed, plan_yy, season)
    if not p.get("planYy"):
        return {**p, "items": []}
    yy, ss, start, to = p["planYy"], p["season"], p["start"], p["to"]
    prev_yy = str(int(yy) - 1) if yy.isdigit() else None
    teams = sd.resolve(ym, None, None, None, None, brand, allowed)["teams"]
    key = ("items", to, yy, ss, tuple(teams) if teams is not None else None)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return {**{k: v for k, v in p.items() if k != "months"}, **hit[1]}
    frm = sm._shift_ym(start, -12)
    team_sql, tb = "", {}
    if teams is not None:
        tinl, tb = sp._in(teams or ["-"], "t")
        team_sql = f" AND TEAM_CD IN ({tinl})"
    st = sp.mv_state()
    binds = {"f": frm, "t": to, "y": yy, "py": prev_yy or "-", "s": ss, **tb}
    rows = None
    if st["usable"] and st["mv_max"] and to <= st["mv_max"]:
        try:
            rows = db.query(f"""SELECT PLAN_YY, ITEM_NM, MAKE_YYMM, SUM(TOTAL_SALE_AMT), SUM(TOTAL_QTY) FROM {sp.MV_NAME}
                                 WHERE PLAN_YY IN (:y, :py) AND SESS_NM = :s AND MAKE_YYMM BETWEEN :f AND :t{team_sql}
                                 GROUP BY PLAN_YY, ITEM_NM, MAKE_YYMM""", binds)[1]
        except Exception:  # noqa: BLE001 - 예전 뷰(기획년도·시즌 열 없음)면 원본
            rows = None
    if rows is None:
        minl, mb = sp._in(sd.month_range(frm, to), "m")
        rows = db.query(f"""SELECT PLAN_YY, ITEM_NM, MAKE_YYMM, SUM(REAL_SALE_AMT), SUM(QTY) FROM T_CLOSE_SALE_BASE
                             WHERE MAKE_YYMM IN ({minl}) AND PLAN_YY IN (:y, :py) AND {sm.SESS_EXPR} = :s{team_sql}
                             GROUP BY PLAN_YY, ITEM_NM, MAKE_YYMM""", {**mb, **{k: v for k, v in binds.items() if k not in ("f", "t")}})[1]
    agg: dict[str, dict] = {}
    for py, item, m, amt, qty in rows:
        name = item or "(없음)"
        a = agg.setdefault(name, {"name": name, "amt": 0, "qty": 0, "prevSameAmt": 0, "prevSameQty": 0, "prevFinalAmt": 0})
        amt, qty = int(amt or 0), int(qty or 0)
        if str(py) == yy and start <= m <= to:
            a["amt"] += amt
            a["qty"] += qty
        elif str(py) == prev_yy:
            m12 = sm._shift_ym(m, 12)   # 전년 달을 올해 달 위치로
            if m12 >= start:
                a["prevFinalAmt"] += amt
                if m12 <= to:
                    a["prevSameAmt"] += amt
                    a["prevSameQty"] += qty
    tot = sum(a["amt"] for a in agg.values())
    out = []
    for a in agg.values():
        if not (a["amt"] or a["prevSameAmt"]):
            continue
        a["change"] = sd._rate(a["amt"], a["prevSameAmt"])
        a["progress"] = round(a["amt"] * 100 / a["prevFinalAmt"], 1) if a["prevFinalAmt"] else None
        a["prevProgressSame"] = round(a["prevSameAmt"] * 100 / a["prevFinalAmt"], 1) if a["prevFinalAmt"] else None
        a["share"] = round(a["amt"] * 100 / tot, 1) if tot else None
        out.append(a)
    out.sort(key=lambda a: a["amt"], reverse=True)
    res = {"items": out}
    with _lock:
        _cache[key] = (time.time() + CACHE_TTL, res)
    return {**{k: v for k, v in p.items() if k != "months"}, **res}
