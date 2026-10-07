"""재고 재배치 추천 > 미처리 RT 현황판: 매장이 아직 수락 · 거부하지 않은 RT 요청 (T_SHOP_REQ 처리구분 미처리 C2954).

- 대상: 요청일(MAKE_DT) 최근 N일(기본 14, 최대 31) · 브랜드 · 본사지시(C6811) · 자동 RT(C6812) · 매장간(C6813), 삭제(DEL_DAY) 안 된 것
- 처리할 매장 = 보내는 매장(DELV_REQ_SHOP_ID). 경과 = 요청 등록(INS_DAY)부터 지금까지
- 본사지시 RT 는 3일 동안 응답이 없으면 새벽 배치가 자동거부한다 → 48시간 넘은 본사지시는 '자동거부 임박'
- 행사 · 가상 매장(오픈매장 · 사내 · 온라인 등)이 낀 요청은 기본으로 뺀다
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from . import stock_ctl as sc

CACHE_TTL = 2 * 60
MAX_DAYS = 31
TYPES = {"C6811": "본사지시", "C6812": "자동 RT", "C6813": "매장간"}
AGES = [("d0", "1일 미만", 24), ("d1", "1~2일", 48), ("d2", "2~3일", 72), ("d3", "3일 이상", None)]
URGENT_HOURS = 48


def _age(hours: float) -> str:
    for key, _, upto in AGES:
        if upto is None or hours < upto:
            return key
    return "d3"


def board(brand: str | None = None, days: int = 14, types: list[str] | None = None, include_virtual: bool = False,
          allowed: list[str] | None = None, refresh: bool = False) -> dict:
    b = sc.brand_code(brand, allowed)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 14
    if not 1 <= days <= MAX_DAYS:
        sc.bad(f"기간은 1~{MAX_DAYS}일입니다.")
    tp = [t for t in (types or list(TYPES)) if t]
    if not tp or any(t not in TYPES for t in tp):
        sc.bad("RT 종류는 본사지시(C6811) · 자동 RT(C6812) · 매장간(C6813) 중에서 고르세요.")
    key = ("pending", b, days, tuple(sorted(tp)), bool(include_virtual))
    return sc.cached(key, CACHE_TTL, lambda: _compute(b, days, sorted(tp), bool(include_virtual)), force=refresh)


def _compute(brand: str, days: int, types: list[str], include_virtual: bool) -> dict:
    now = datetime.now()
    f = (now - timedelta(days=days - 1)).strftime("%Y%m%d")
    t = now.strftime("%Y%m%d")
    ph, bnd = sc.binds(types, "m")
    rows = db.query(f"""SELECT R.MAKE_DT, R.SEQ, R.DELV_REQ_SHOP_ID, R.STOR_REQ_SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD, NVL(R.REQ_QTY, 0),
                               R.MOVE_TYPE, R.INS_DAY, R.INS_USERID, R.INDC_ID, R.AUTO_RT_ID
                          FROM T_SHOP_REQ R
                         WHERE R.MAKE_DT BETWEEN :f AND :t AND R.MOVE_TYPE IN ({ph}) AND R.BRD_CD = :b
                           AND R.PRCS_CLSBY = 'C2954' AND R.DEL_DAY IS NULL""", {**bnd, "f": f, "t": t, "b": brand})[1]
    shops = sc.shops()
    teams = sc.team_names()
    styles = sc.style_info(sorted({r[4] for r in rows})) if rows else {}
    items, virtual_rows = [], 0
    for mk, seq, dl, st, p, c, s, q, mt, ins, user, indc, auto in rows:
        sd, ss = shops.get(dl) or {}, shops.get(st) or {}
        if not include_virtual and (sd.get("virtual") or ss.get("virtual")):
            virtual_rows += 1
            continue
        try:
            hours = (now - datetime.strptime(ins[:14], "%Y%m%d%H%M%S")).total_seconds() / 3600
        except (TypeError, ValueError):
            hours = (now - datetime.strptime(mk, "%Y%m%d")).total_seconds() / 3600
        items.append({"makeDt": sc.ymd_label(mk), "seq": int(seq), "type": mt, "typeNm": TYPES.get(mt, mt), "fromShopId": dl, "fromShopNm": sd.get("shopNm"),
                      "fromTeam": teams.get(sd.get("team")), "toShopId": st, "toShopNm": ss.get("shopNm"), "prdtCd": p,
                      "styleNm": (styles.get(p) or {}).get("styleNm"), "colorCd": c, "sizeCd": s, "qty": int(q),
                      "requestedAt": f"{ins[4:6]}-{ins[6:8]} {ins[8:10]}:{ins[10:12]}" if ins and len(ins) >= 12 else None,
                      "hours": round(hours, 1), "age": _age(hours), "urgent": mt == "C6811" and hours >= URGENT_HOURS,
                      "requestedBy": user, "ref": indc or auto})
    items.sort(key=lambda x: (-x["hours"], x["fromShopId"]))

    def agg(key_fn, name_fn):
        out: dict[str, dict] = {}
        for x in items:
            k = key_fn(x)
            g = out.setdefault(k, {"key": k, "name": name_fn(x), "rows": 0, "qty": 0, "urgent": 0, "oldestHours": 0.0,
                                   **{a: 0 for a, _, _ in AGES}, **{m: 0 for m in TYPES}})
            g["rows"] += 1
            g["qty"] += x["qty"]
            g["urgent"] += int(x["urgent"])
            g["oldestHours"] = max(g["oldestHours"], x["hours"])
            g[x["age"]] += 1
            if x["type"] in TYPES:
                g[x["type"]] += 1
        return sorted(out.values(), key=lambda g: (-g["urgent"], -g["oldestHours"], -g["rows"]))

    by_shop = agg(lambda x: x["fromShopId"], lambda x: x["fromShopNm"])
    for g in by_shop:
        g["team"] = teams.get((shops.get(g["key"]) or {}).get("team"))
    by_team = agg(lambda x: x["fromTeam"] or "-", lambda x: x["fromTeam"] or "(팀 없음)")
    return {
        "brand": brand, "brandNm": sc.BRAND_CODES[brand], "from": sc.ymd_label(f), "to": sc.ymd_label(t), "days": days, "types": types,
        "typeNames": TYPES, "ages": [{"key": k, "name": n} for k, n, _ in AGES], "urgentHours": URGENT_HOURS,
        "asOf": now.strftime("%Y-%m-%d %H:%M"), "includeVirtual": include_virtual, "virtualRows": virtual_rows,
        "summary": {"rows": len(items), "qty": sum(x["qty"] for x in items), "shops": len(by_shop), "urgent": sum(1 for x in items if x["urgent"]),
                    "byAge": {k: sum(1 for x in items if x["age"] == k) for k, _, _ in AGES},
                    "byType": {m: sum(1 for x in items if x["type"] == m) for m in TYPES}},
        "shops": by_shop, "teams": by_team, "rows": items,
    }


PENDING_COLS = [("fromShopId", "처리할 매장(보내는)", 10), ("fromShopNm", "매장명", 18), ("fromTeam", "팀", 10), ("typeNm", "종류", 8),
                ("makeDt", "요청일", 11), ("requestedAt", "요청 시각", 11), ("hours", "경과(시간)", 9), ("prdtCd", "품번", 14), ("styleNm", "스타일명", 18),
                ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7), ("qty", "수량", 6), ("toShopId", "받는 매장", 10), ("toShopNm", "받는 매장명", 18),
                ("requestedBy", "요청자", 9), ("ref", "지시 · 자동RT 번호", 15)]
SHOP_COLS = [("key", "매장", 10), ("name", "매장명", 18), ("team", "팀", 10), ("rows", "미처리 건", 9), ("qty", "수량", 7),
             ("urgent", "자동거부 임박", 10), ("oldestHours", "가장 오래된(시간)", 12), ("d0", "1일 미만", 8), ("d1", "1~2일", 7), ("d2", "2~3일", 7),
             ("d3", "3일 이상", 8), ("C6811", "본사지시", 8), ("C6812", "자동 RT", 8), ("C6813", "매장간", 8)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"미처리 RT 현황 ({d['asOf']} 기준 · {d['brandNm']} · 요청일 {d['from']} ~ {d['to']} · {', '.join(d['typeNames'][x] for x in d['types'])})",
             f"미처리 {s['rows']:,}건 · {s['qty']:,}장 · 처리할 매장 {s['shops']:,}곳 · 본사지시 {URGENT_HOURS}시간 경과(자동거부 임박) {s['urgent']:,}건"]
    return sc.xlsx([("매장별", notes, SHOP_COLS, d["shops"]), ("미처리 요청", notes, PENDING_COLS, d["rows"])])
