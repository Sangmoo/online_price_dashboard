"""판매 현황 대시보드: 기간(1~12개월) 핵심 지표 · 13개월 추이 · 브랜드/팀별 · 목표 대비 · 매장 순위.

- 기간: 기준 월 하나(기본) 또는 시작~끝 월. 비교 기준: 전년 동기(기본) · 직전 기간 · 직접 선택한 기간.
- 브랜드 조건: 팀(TEAM_CD '쉬즈3팀' → 브랜드 '쉬즈') 기준으로 거른다.
- 목표: T_SHOP_SELL_MGOAL(매장 × 브랜드 × 월 목표금액)을 매장 단위로 합쳐 판매와 같은 매장 기준으로 비교한다.
  한 매장에 여러 브랜드 목표가 있어도 판매는 매장의 팀(브랜드) 하나로 잡히므로, 목표도 매장의 판매 브랜드로 모은다.
  달성률 = 목표가 있는 매장의 실판금액 ÷ 목표금액 (목표 없는 매장의 매출은 따로 표시).

원본(T_CLOSE_SALE_BASE)에 월·매장·팀 단위 합계만 묻고, Oracle 이 사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM)로
자동 재작성해 즉시 계산한다(뷰가 최신일 때). 기간 조건은 월 목록(IN)으로 줘서 인덱스를 월 단위로 바로 찾는다.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import date

from fastapi import HTTPException

from . import db
from .sale_monthly import _shift_ym, shop_names

CACHE_TTL = 10 * 60
MAX_PERIOD = 12                      # 기간·비교 기간 최대 개월 수
MIN_PREV_FOR_GROWTH = 10_000_000     # 증감 순위: 비교 기간 월평균 실판금액 1천만원 이상 매장만 (작은 매장의 큰 % 변동 제외)
CLOSED_RE = re.compile(r"\(폐\)|종료")  # 매장명에 폐점/종료 표시가 있는 매장
CMP_KINDS = {"yoy": "전년 동기", "prev": "직전 기간", "custom": "직접 선택"}
GOAL_TABLE = "T_SHOP_SELL_MGOAL"
_cache: dict[tuple, tuple[float, dict]] = {}
_teams_cache: tuple[float, dict[str, list[str]]] | None = None
_months_cache: tuple[float, list[str]] | None = None
MONTHS_TTL = 60
_lock = threading.Lock()


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


def _in(values: list[str], prefix: str = "m") -> tuple[str, dict]:
    binds = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return ", ".join(":" + k for k in binds), binds


def _rate(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 1) if b else None


def _cost_rate(cost: float, amt: float) -> float | None:
    return round(cost * 100 / amt, 1) if amt else None


def _dsct_rate(dsct: float, amt: float) -> float | None:
    """할인율(%) = 할인금액 ÷ (실판금액 + 할인금액) — 할인 전 금액 대비 깎아 준 비율"""
    gross = amt + dsct
    return round(dsct * 100 / gross, 1) if gross else None


def _diff(a: float | None, b: float | None) -> float | None:
    return round(a - b, 1) if a is not None and b is not None else None


def _achieve(amt: float, goal: float) -> float | None:
    return round(amt * 100 / goal, 1) if goal else None


# 팀명에서 뗀 이름과 화면에 보일 브랜드명이 다른 경우 (팀명 '쉬즈3팀' → 브랜드 '쉬즈미스')
BRAND_NAMES = {"쉬즈": "쉬즈미스"}
BRAND_ALIASES = {v: v for v in BRAND_NAMES.values()} | {k: v for k, v in BRAND_NAMES.items()}  # 예전 이름으로 찾아도 됨


def brand_of(team: str | None) -> str:
    """'쉬즈3팀' → '쉬즈미스', '시스티나1팀' → '시스티나', '리스트2팀' → '리스트'"""
    name = re.sub(r"\s*\d*\s*팀$", "", team or "").strip() or "(미지정)"
    return BRAND_NAMES.get(name, name)


def ym_label(v: str) -> str:
    return f"{v[:4]}-{v[4:]}"


def month_range(f: str, t: str) -> list[str]:
    out, m = [], f
    while m <= t:
        out.append(m)
        m = _shift_ym(m, 1)
    return out


def period_label(months: list[str]) -> str:
    return ym_label(months[0]) if len(months) == 1 else f"{ym_label(months[0])}~{ym_label(months[-1])}"


def available_months() -> list[str]:
    """판매 데이터가 있는 월 (최근 60개, 1분 캐시)"""
    global _months_cache
    with _lock:
        if _months_cache and _months_cache[0] > time.time():
            return _months_cache[1]
    out = [r[0] for r in db.query("SELECT DISTINCT MAKE_YYMM FROM T_CLOSE_SALE_BASE ORDER BY 1 DESC")[1] if r[0]][:60]
    with _lock:
        _months_cache = (time.time() + MONTHS_TTL, out)
    return out


def clear_cache() -> None:
    """사전 집계 뷰 갱신 후: 새 월·새 숫자를 바로 쓰도록"""
    global _teams_cache, _months_cache
    with _lock:
        _cache.clear()
        _teams_cache = _months_cache = None


def brand_teams() -> dict[str, list[str]]:
    """브랜드 → 팀 목록 (10분 캐시). 최근 3년 판매 + 사전 집계 뷰 전체 기간의 팀 (브랜드 권한이 옛 기간에도 맞게)."""
    global _teams_cache
    with _lock:
        if _teams_cache and _teams_cache[0] > time.time():
            return _teams_cache[1]
    months = available_months()[:36]
    found: set[str] = set()
    if months:
        inl, b = _in(months)
        found |= {t for (t,) in db.query(f"SELECT DISTINCT TEAM_CD FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({inl})", b)[1] if t}
    try:
        from .chat_tools_sale import MV_NAME

        found |= {t for (t,) in db.query(f"SELECT DISTINCT TEAM_CD FROM {MV_NAME}")[1] if t}
    except Exception:  # noqa: BLE001 - 뷰가 없으면 최근 3년 팀만
        pass
    out: dict[str, list[str]] = {}
    for team in found:
        out.setdefault(brand_of(team), []).append(team)
    out = {k: sorted(v) for k, v in sorted(out.items())}
    with _lock:
        _teams_cache = (time.time() + CACHE_TTL, out)
    return out


def _ym(v: str | None, name: str) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip().replace("-", "")
    if not re.match(r"^\d{4}(0[1-9]|1[0-2])$", s):
        _bad(f"{name} 는 YYYYMM 형식입니다.")
    return s


def resolve(ym: str | None = None, frm: str | None = None, cmp: str | None = None, cmp_from: str | None = None,
            cmp_to: str | None = None, brand: str | None = None, allowed: list[str] | None = None) -> dict:
    """allowed: 사용자가 볼 수 있는 브랜드 (None = 모든 브랜드). 브랜드 조건이 없으면 허용 브랜드 전체로 거른다."""
    """조회 조건 검증 → 기간·비교 기간·보조 비교 기간(KPI 에 함께 표시)·연 누계 월 목록"""
    months = available_months()
    if not months:
        _bad("판매 데이터가 없습니다.")
    to = _ym(ym, "기준 월") or months[0]
    if to not in months:
        _bad(f"{ym_label(to)} 판매 데이터가 없습니다.")
    frm = _ym(frm, "시작 월") or to
    if frm > to:
        _bad("시작 월이 끝 월보다 늦습니다.")
    period = month_range(frm, to)
    if len(period) > MAX_PERIOD:
        _bad(f"기간은 최대 {MAX_PERIOD}개월입니다.")
    kind = cmp or "yoy"
    if kind not in CMP_KINDS:
        _bad(f"비교 기준은 {', '.join(CMP_KINDS)} 중 하나입니다.")
    yoy = [_shift_ym(m, -12) for m in period]
    prev = [_shift_ym(m, -len(period)) for m in period]
    if kind == "custom":
        cf, ct = _ym(cmp_from, "비교 시작 월"), _ym(cmp_to, "비교 끝 월")
        if not cf or not ct:
            _bad("직접 선택 비교는 비교 기간(시작·끝 월)이 필요합니다.")
        if cf > ct:
            _bad("비교 시작 월이 비교 끝 월보다 늦습니다.")
        base = month_range(cf, ct)
        if len(base) > MAX_PERIOD:
            _bad(f"비교 기간은 최대 {MAX_PERIOD}개월입니다.")
    else:
        base = yoy if kind == "yoy" else prev
    # 보조 비교: 기준이 전년 동기면 직전 기간(한 달이면 전월), 아니면 전년 동기
    extra, extra_label = (prev, "전월" if len(period) == 1 else "직전 기간") if kind == "yoy" else (yoy, "전년 동기")
    brand = (brand or "").strip() or None
    brand = BRAND_ALIASES.get(brand, brand) if brand else None
    bt = brand_teams()
    allowed_set = set(allowed) if allowed is not None else None
    teams, scope = None, None
    if brand:
        if brand not in bt:
            _bad(f"브랜드 '{brand}' 가 없습니다. 선택지: {', '.join(b for b in bt if allowed_set is None or b in allowed_set)}")
        if allowed_set is not None and brand not in allowed_set:
            raise HTTPException(status_code=403, detail={"message": f"'{brand}' 브랜드 조회 권한이 없습니다.", "code": "FORBIDDEN"})
        scope = {brand}
    elif allowed_set is not None:
        scope = allowed_set
    if scope is not None:
        teams = sorted({t for b in scope for t in bt.get(b, [])})
    ytd = [f"{to[:4]}{m:02d}" for m in range(1, int(to[4:]) + 1)]
    return {
        "months": months, "to": to, "from": frm, "period": period, "kind": kind, "base": base, "extra": extra,
        "extraLabel": extra_label, "ytd": ytd, "ytdPrev": [_shift_ym(m, -12) for m in ytd], "brand": brand, "teams": teams, "scope": scope, "allowedSet": allowed_set,
        "brandOptions": [b for b in bt if allowed_set is None or b in allowed_set],
    }


def _goals(period: list[str]) -> dict[str, tuple[int, str | None]]:
    """매장별 목표 합계와 목표의 대표 브랜드 코드(가장 큰 목표). 테이블이 없거나 권한이 없으면 빈 값."""
    inl, b = _in(period)
    try:
        rows = db.query(f"""SELECT SHOP_ID, PARENT_BRD_CD, SUM(GOAL_AMT) FROM {GOAL_TABLE}
                             WHERE MAKE_YYMM IN ({inl}) AND DEL_DAY IS NULL GROUP BY SHOP_ID, PARENT_BRD_CD""", b)[1]
    except Exception:  # noqa: BLE001 - 목표 없이도 나머지 화면은 보여준다
        return {}
    out: dict[str, list] = {}
    for sid, brd, amt in rows:
        o = out.setdefault(sid, [0, None, -1])
        o[0] += int(amt or 0)
        if int(amt or 0) > o[2]:
            o[1], o[2] = brd, int(amt or 0)
    return {k: (v[0], v[1]) for k, v in out.items()}


def dashboard(ym: str | None = None, frm: str | None = None, cmp: str | None = None, cmp_from: str | None = None,
              cmp_to: str | None = None, brand: str | None = None, full: bool = False, allowed: list[str] | None = None,
              ttl: int | None = None) -> dict:
    """화면·AI·엑셀 공통 계산. full=True 면 전체 매장 목록(allShops)까지 (엑셀용).
    ttl: 캐시 유지 시간(초). 미리 계산(prewarm)은 길게 둔다 — 데이터가 바뀌면 prewarm 이 캐시를 비운다."""
    r = resolve(ym, frm, cmp, cmp_from, cmp_to, brand, allowed)
    key = (r["to"], r["from"], r["kind"], tuple(r["base"]), r["brand"], tuple(sorted(r["scope"])) if r["scope"] is not None else None)
    hit = _cache.get(key)
    if hit and hit[0] > time.time() and ttl is None:
        out = hit[1]
    else:
        out = _compute(r)
        with _lock:
            if len(_cache) > 50:
                _cache.clear()
            _cache[key] = (time.time() + (ttl or CACHE_TTL), out)
    if full:
        return out
    return {k: v for k, v in out.items() if k != "allShops"}


def _compute(r: dict) -> dict:
    to, period, base, extra = r["to"], r["period"], r["base"], r["extra"]
    team_set = set(r["teams"]) if r["teams"] is not None else None
    bset = r["scope"]  # 보이는 브랜드 (None = 전체)
    zero = {"amt": 0, "qty": 0, "dsct": 0, "cost": 0, "shops": 0}

    # 1) 월별 합계 (13개월 추이 + 전년 같은 달 + 연 누계): 브랜드 조건은 SQL 로
    series = [_shift_ym(to, -i) for i in range(24, -1, -1)]
    inl, b = _in(series)
    team_sql = ""
    if team_set is not None:
        tinl, tb = _in(sorted(team_set) or ["-"], "t")
        team_sql, b = f" AND TEAM_CD IN ({tinl})", {**b, **tb}
    monthly = {row[0]: {"amt": int(row[1] or 0), "qty": int(row[2] or 0), "dsct": int(row[3] or 0), "cost": int(row[4] or 0),
                        "shops": int(row[5] or 0)}
               for row in db.query(f"""SELECT MAKE_YYMM, SUM(REAL_SALE_AMT), SUM(QTY), SUM(DSCT_AMT), SUM(PRODUCT_COST2 * QTY),
                                              COUNT(DISTINCT SHOP_ID)
                                         FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({inl}){team_sql} GROUP BY MAKE_YYMM""", b)[1]}
    ysum = lambda ms: sum(monthly.get(m, zero)["amt"] for m in ms)  # noqa: E731
    trend = []
    for m in series[-13:]:
        c, p = monthly.get(m, zero), monthly.get(_shift_ym(m, -12), zero)
        trend.append({"ym": m, "amt": c["amt"], "prevAmt": p["amt"], "yoy": _rate(c["amt"], p["amt"]),
                      "costRate": _cost_rate(c["cost"], c["amt"]), "dsctRate": _dsct_rate(c["dsct"], c["amt"]), "shops": c["shops"]})

    # 2) 매장 × 팀 × 월 (기간 · 비교 기간 · 보조 비교 기간): 브랜드별 표는 전체 기준이 필요해 SQL 은 거르지 않고 여기서 거른다
    need = sorted(set(period) | set(base) | set(extra))
    inl, b = _in(need)
    sp, sb, se = set(period), set(base), set(extra)
    shops: dict[str, dict] = {}
    for m, sid, team, amt, qty, dsct, cost in db.query(
            f"""SELECT MAKE_YYMM, SHOP_ID, TEAM_CD, SUM(REAL_SALE_AMT), SUM(QTY), SUM(DSCT_AMT), SUM(PRODUCT_COST2 * QTY)
                  FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ({inl}) GROUP BY MAKE_YYMM, SHOP_ID, TEAM_CD""", b)[1]:
        team = team or "(미지정)"
        s = shops.setdefault(sid, {"shopId": sid, "teams": {}})
        t = s["teams"].setdefault(team, {"p": dict(zero), "b": dict(zero), "e": dict(zero), "inP": False, "inB": False, "inE": False})
        vals = {"amt": int(amt or 0), "qty": int(qty or 0), "dsct": int(dsct or 0), "cost": int(cost or 0)}
        for tag, ms in (("p", sp), ("b", sb), ("e", se)):
            if m in ms:
                for k, v in vals.items():
                    t[tag][k] += v
                t["in" + tag.upper()] = True

    # 매장의 대표 팀(기간 매출이 가장 큰 팀, 없으면 비교 기간) → 브랜드. 목표도 이 브랜드로 모은다.
    for s in shops.values():
        s["team"] = max(s["teams"], key=lambda k: (s["teams"][k]["p"]["amt"], s["teams"][k]["b"]["amt"]))
        s["brand"] = brand_of(s["team"])

    # 3) 목표 (기간 합계, 매장 단위)
    goals = _goals(period)
    # 판매가 없는 목표 매장의 브랜드: 목표 브랜드코드 → 브랜드 (판매가 있는 매장에서 가장 많이 짝지어진 브랜드)
    code_votes: dict[str, dict[str, int]] = {}
    for sid, (_, code) in goals.items():
        if sid in shops and code:
            code_votes.setdefault(code, {}).setdefault(shops[sid]["brand"], 0)
            code_votes[code][shops[sid]["brand"]] += 1
    code_brand = {c: max(v, key=v.get) for c, v in code_votes.items()}

    def agg(s: dict, tag: str, teams_ok) -> dict:
        o = dict(zero)
        present = False
        for team, t in s["teams"].items():
            if teams_ok is None or team in teams_ok:
                for k in ("amt", "qty", "dsct", "cost"):
                    o[k] += t[tag][k]
                present = present or t["in" + tag.upper()]
        o["present"] = present
        return o

    rows: list[dict] = []
    all_brand_rows: dict[str, dict] = {}
    team_rows: dict[str, dict] = {}
    for sid in set(shops) | set(goals):
        s = shops.get(sid)
        g_amt, g_code = goals.get(sid, (0, None))
        brand = s["brand"] if s else code_brand.get(g_code or "", "(미지정)")
        # 브랜드별 표 (전체 기준)
        if s:
            pa, ba = agg(s, "p", None), agg(s, "b", None)
            br = all_brand_rows.setdefault(brand, {"brand": brand, "amt": 0, "baseAmt": 0, "cost": 0, "dsct": 0, "baseDsct": 0, "shops": 0, "teams": set(),
                                                  "goalAmt": 0, "goalSalesAmt": 0})
            br["amt"] += pa["amt"]
            br["baseAmt"] += ba["amt"]
            br["cost"] += pa["cost"]
            br["dsct"] += pa["dsct"]
            br["baseDsct"] += ba["dsct"]
            br["shops"] += 1 if pa["present"] else 0
            for team, t in s["teams"].items():
                if t["inP"]:
                    br["teams"].add(team)
                tr = team_rows.setdefault(team, {"team": team, "brand": brand_of(team), "amt": 0, "baseAmt": 0, "cost": 0, "dsct": 0, "baseDsct": 0, "shops": 0,
                                                 "goalAmt": 0, "goalSalesAmt": 0})
                tr["amt"] += t["p"]["amt"]
                tr["baseAmt"] += t["b"]["amt"]
                tr["cost"] += t["p"]["cost"]
                tr["dsct"] += t["p"]["dsct"]
                tr["baseDsct"] += t["b"]["dsct"]
                tr["shops"] += 1 if t["inP"] else 0
            if g_amt:
                tr = team_rows[s["team"]]
                tr["goalAmt"] += g_amt
                tr["goalSalesAmt"] += pa["amt"]
                br["goalAmt"] += g_amt
                br["goalSalesAmt"] += pa["amt"]
        elif g_amt:
            br = all_brand_rows.setdefault(brand, {"brand": brand, "amt": 0, "baseAmt": 0, "cost": 0, "dsct": 0, "baseDsct": 0, "shops": 0, "teams": set(),
                                                  "goalAmt": 0, "goalSalesAmt": 0})
            br["goalAmt"] += g_amt
        # 조건(브랜드)에 맞는 매장 행
        if bset is not None and brand not in bset and not (s and any(t in team_set for t in s["teams"])):
            continue
        teams_ok = team_set
        pa = agg(s, "p", teams_ok) if s else {**zero, "present": False}
        ba = agg(s, "b", teams_ok) if s else {**zero, "present": False}
        ea = agg(s, "e", teams_ok) if s else {**zero, "present": False}
        goal_here = g_amt if (bset is None or brand in bset) else 0
        if not (pa["present"] or ba["present"] or ea["present"] or goal_here):
            continue
        rows.append({
            "shopId": sid, "team": s["team"] if s else None, "brand": brand,
            "amt": pa["amt"], "qty": pa["qty"], "dsct": pa["dsct"], "cost": pa["cost"], "inPeriod": pa["present"],
            "baseAmt": ba["amt"], "baseQty": ba["qty"], "baseDsct": ba["dsct"], "baseCost": ba["cost"], "inBase": ba["present"],
            "extraAmt": ea["amt"], "inExtra": ea["present"],
            "change": _rate(pa["amt"], ba["amt"]), "extraChange": _rate(pa["amt"], ea["amt"]),
            "costRate": _cost_rate(pa["cost"], pa["amt"]),
            "goalAmt": goal_here, "achieve": _achieve(pa["amt"], goal_here),
        })

    names = shop_names([x["shopId"] for x in rows])
    for x in rows:
        x["shopNm"] = names.get(x["shopId"])
        x["closed"] = bool(CLOSED_RE.search(x["shopNm"] or ""))

    # 핵심 지표
    tot = lambda k, cond=None: sum(x[k] for x in rows if cond is None or cond(x))  # noqa: E731
    amt, base_amt, extra_amt = tot("amt"), tot("baseAmt"), tot("extraAmt")
    cost, base_cost = tot("cost"), tot("baseCost")
    shops_n, base_shops = sum(1 for x in rows if x["inPeriod"]), sum(1 for x in rows if x["inBase"])
    goal_amt = tot("goalAmt")
    goal_sales = tot("amt", lambda x: x["goalAmt"] > 0)
    no_goal = [x for x in rows if x["goalAmt"] <= 0 and x["amt"] > 0]
    kpi = {
        "amt": amt, "baseAmt": base_amt, "change": _rate(amt, base_amt),
        "extraAmt": extra_amt, "extraChange": _rate(amt, extra_amt),
        "qty": tot("qty"), "baseQty": tot("baseQty"), "qtyChange": _rate(tot("qty"), tot("baseQty")),
        "dsct": tot("dsct"), "baseDsct": tot("baseDsct"), "dsctChange": _rate(tot("dsct"), tot("baseDsct")),
        "cost": cost, "costRate": _cost_rate(cost, amt), "baseCostRate": _cost_rate(base_cost, base_amt),
        "shops": shops_n, "baseShops": base_shops,
        "avgPerShop": round(amt / shops_n) if shops_n else None,
        "ytdAmt": ysum(r["ytd"]), "prevYtdAmt": ysum(r["ytdPrev"]), "ytdYoy": _rate(ysum(r["ytd"]), ysum(r["ytdPrev"])),
        "goalAmt": goal_amt, "goalSalesAmt": goal_sales, "achieve": _achieve(goal_sales, goal_amt),
        "goalGap": goal_sales - goal_amt if goal_amt else None,
        "goalShops": sum(1 for x in rows if x["goalAmt"] > 0),
        "noGoalShops": len(no_goal), "noGoalAmt": sum(x["amt"] for x in no_goal),
    }
    kpi["costRateDiff"] = _diff(kpi["costRate"], kpi["baseCostRate"])
    kpi["dsctRate"], kpi["baseDsctRate"] = _dsct_rate(kpi["dsct"], amt), _dsct_rate(kpi["baseDsct"], base_amt)
    kpi["dsctRateDiff"] = _diff(kpi["dsctRate"], kpi["baseDsctRate"])

    def finish(g: dict) -> dict:
        g = {k: (sorted(v) if isinstance(v, set) else v) for k, v in g.items()}
        g["change"], g["costRate"] = _rate(g["amt"], g["baseAmt"]), _cost_rate(g["cost"], g["amt"])
        g["achieve"] = _achieve(g["goalSalesAmt"], g["goalAmt"])
        g["dsctRate"], g["baseDsctRate"] = _dsct_rate(g.get("dsct", 0), g["amt"]), _dsct_rate(g.get("baseDsct", 0), g["baseAmt"])
        g["dsctRateDiff"] = _diff(g["dsctRate"], g["baseDsctRate"])
        return g

    # 비중: 보이는 브랜드 합계 기준 (브랜드 하나만 고르면 전체 대비, 권한이 제한된 사용자는 허용 브랜드 합계 대비)
    total_all = sum(x["amt"] for x in all_brand_rows.values()
                    if r["allowedSet"] is None or x["brand"] in r["allowedSet"])
    brands = []
    for g in all_brand_rows.values():
        g = finish(g)
        g["teams"] = len(g["teams"])
        g["share"] = round(g["amt"] * 100 / total_all, 1) if total_all else None
        if bset is None or g["brand"] in bset:
            if g["amt"] or g["baseAmt"] or g["goalAmt"]:
                brands.append(g)
    teams = [finish(t) for t in team_rows.values() if (not team_set or t["team"] in team_set) and (t["amt"] or t["baseAmt"])]

    # 매장 순위
    selling = [x for x in rows if x["amt"] > 0]
    min_base = MIN_PREV_FOR_GROWTH * len(base)
    comparable = [x for x in selling if x["baseAmt"] >= min_base and x["change"] is not None]
    closed = [x for x in comparable if x["closed"]]
    comparable = [x for x in comparable if not x["closed"]]
    goal_rows = [x for x in rows if x["goalAmt"] > 0 and x["amt"] > 0 and not x["closed"]]  # 달성률 하위: 영업 중인 매장만
    public = lambda xs: [{k: v for k, v in x.items() if not k.startswith("in") and k not in ("qty", "dsct", "baseQty", "baseDsct", "baseCost")}  # noqa: E731
                         for x in xs]

    return {
        "ym": to, "from": r["from"], "months": r["months"][:36],
        "period": {"from": r["from"], "to": to, "months": r["period"], "label": period_label(r["period"])},
        "base": {"from": r["base"][0], "to": r["base"][-1], "months": r["base"], "label": period_label(r["base"]),
                 "kind": r["kind"], "kindLabel": CMP_KINDS[r["kind"]]},
        "extra": {"label": r["extraLabel"], "period": period_label(r["extra"])},
        "brand": r["brand"], "brandOptions": r["brandOptions"], "brandLimited": r["allowedSet"] is not None,
        "kpi": kpi, "trend": trend,
        "brands": sorted(brands, key=lambda x: x["amt"], reverse=True),
        "teams": sorted(teams, key=lambda x: (x["brand"], x["team"])),
        "topShops": public(sorted(selling, key=lambda x: x["amt"], reverse=True)[:10]),
        "risers": public(sorted(comparable, key=lambda x: x["change"], reverse=True)[:10]),
        "fallers": public(sorted(comparable, key=lambda x: x["change"])[:10]),
        "laggards": public(sorted(goal_rows, key=lambda x: (x["achieve"] if x["achieve"] is not None else 0, -x["goalAmt"]))[:10]),
        "allShops": public(sorted(rows, key=lambda x: x["amt"], reverse=True)),
        "shopCounts": {"selling": len(selling), "new": sum(1 for x in selling if not x["inBase"]), "comparable": len(comparable),
                       "closedExcluded": len(closed)},
        "minBaseForGrowth": min_base, "hasGoals": bool(goals),
        "generatedAt": date.today().isoformat(),
    }
