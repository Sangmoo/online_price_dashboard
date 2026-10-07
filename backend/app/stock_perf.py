"""재고 재배치 추천 > RT 성과: 본사지시 RT 지시가 매장에서 어떻게 처리됐고, 받은 매장에서 팔렸는지.

- 대상: 지시일(INDC_DT) 기간(최대 31일)의 본사지시 RT (T_INDC_RT) — scope=web 이면 이 화면에서 넣은 것만(ATTR1 표시), all 이면 본사지시 전체
- 처리: 연결된 매장 이동요청(T_SHOP_REQ)의 처리구분 — 미확정 · 매장 미처리(C2954) · 수락(C2951) · 거부(C2952, 3일 무응답 자동거부 따로) · 지시 취소(DEL_DAY)
- 판매 전환: 수락된 건 중 받은 매장이 수락일부터 7일 안에 그 상품(품번 · 칼라 · 사이즈)을 판매한 비율 (T_SHOP_RNDS_BASE 판매)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import db
from . import stock_ctl as sc

CACHE_TTL = 5 * 60
SOLD_DAYS = 7
STATUS_NM = {"N": "미확정", "C2954": "매장 미처리", "C2951": "수락", "C2952": "거부", "AUTO": "자동거부(3일 무응답)", "DEL": "지시 취소",
             "ETC": "기타"}


def _d8(v: str | None) -> datetime | None:
    try:
        return datetime.strptime(v[:8], "%Y%m%d") if v else None
    except ValueError:
        return None


def _hours(a: str | None, b: str | None) -> float | None:
    try:
        return (datetime.strptime(b[:14], "%Y%m%d%H%M%S") - datetime.strptime(a[:14], "%Y%m%d%H%M%S")).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _reason(v: str | None) -> str:
    s = re.sub(r"\s+", " ", (v or "").strip())
    s = re.sub(r"^\(?자동거부\)?\s*", "", s)
    return s or "(사유 없음)"


def performance(brand: str | None = None, frm: str | None = None, to: str | None = None, scope: str = "web",
                allowed: list[str] | None = None, refresh: bool = False, include_virtual: bool = False) -> dict:
    b = sc.brand_code(brand, allowed)
    f, t = sc.period(frm, to, 14)
    if scope not in ("web", "all"):
        sc.bad("범위는 web(이 화면에서 지시) 또는 all(본사지시 전체) 입니다.")
    iv = bool(include_virtual)
    return sc.cached(("rtperf", b, f, t, scope, iv), CACHE_TTL, lambda: _compute(b, f, t, scope, iv), force=refresh)


def _compute(brand: str, f: str, t: str, scope: str, include_virtual: bool = False) -> dict:
    rows = db.query(f"""SELECT /*+ INDEX(I T_INDC_RT_IDX01) */ I.INDC_ID, I.DELV_MOVE_SHOP_ID, I.STOR_MOVE_SHOP_ID, I.PRDT_CD, I.COLOR_CD, I.SIZE_CD,
                               NVL(I.INDC_QTY, 0), I.INDC_DT, NVL(I.CNFM_YN, 'N'), R.INS_DAY, R.PRCS_CLSBY, R.PRCS_DAY, R.RESN, R.DEL_DAY,
                               R.REQ_PRCS_DT, R.PRCS_USERID
                          FROM T_INDC_RT I, T_SHOP_REQ R
                         WHERE I.INDC_DT BETWEEN :f AND :t AND I.BRD_CD = :b AND I.DEL_DAY IS NULL {"AND I.ATTR1 = :m" if scope == "web" else ""}
                           AND R.MAKE_DT(+) = I.SHOP_REQ_MAKE_DT AND R.SEQ(+) = I.SHOP_REQ_SEQ""",
                    {"f": f, "t": t, "b": brand, **({"m": sc.WEB_MARK} if scope == "web" else {})}, arraysize=20000)[1]
    shops = sc.shops()
    items = []
    virtual_qty = 0
    for (iid, dl, st, p, c, s, q, dt, cnfm, req_ins, prcs, prcs_day, resn, rdel, req_prcs_dt, prcs_user) in rows:
        if not include_virtual and ((shops.get(dl) or {}).get("virtual") or (shops.get(st) or {}).get("virtual")):
            virtual_qty += int(q)              # 행사 · 가상 매장(오픈매장 · 사내 · 온라인 등)이 낀 지시는 통계에서 뺀다
            continue
        if cnfm != "Y":
            status = "N"
        elif rdel:
            status = "DEL"
        elif prcs == "C2952" and (prcs_user == "ADMIN" or "자동거부" in (resn or "")):
            status = "AUTO"
        elif prcs in ("C2954", "C2951", "C2952"):
            status = prcs
        else:
            status = "ETC"
        items.append({"id": iid, "from": dl, "to": st, "sku": (p, c, s), "qty": int(q), "dt": dt, "status": status,
                      "hours": _hours(req_ins, prcs_day) if status in ("C2951", "C2952") else None,
                      "acceptDt": (req_prcs_dt or (prcs_day or "")[:8]) if status == "C2951" else None, "resn": resn})

    # 판매 전환: 수락 건의 받은 매장 × 상품을 수락일부터 7일 판매로 확인 (품번 · 칼라 인덱스)
    acc = [x for x in items if x["status"] == "C2951" and x["acceptDt"]]
    sold: dict[tuple, list[str]] = {}
    if acc:
        start = min(x["acceptDt"] for x in acc)
        pcs = sorted({x["sku"][:2] for x in acc})
        shops_needed = {x["to"] for x in acc}
        for part in sc.chunks(pcs, 300):
            bnd: dict = {"f": start, "t": sc.today()}
            keys = []
            for i, (p, c) in enumerate(part):
                bnd[f"p{i}"], bnd[f"c{i}"] = p, c
                keys.append(f"(:p{i}, :c{i})")
            for sid, p, c, s, d in db.query(f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_04) */ R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD, R.MAKE_DT
                                                 FROM T_SHOP_RNDS_BASE R
                                                WHERE (R.PRDT_CD, R.COLOR_CD) IN ({', '.join(keys)}) AND R.MAKE_DT BETWEEN :f AND :t
                                                  AND R.STOCK_STAT = 'C20922' AND NVL(R.RET_YN, 'N') = 'N' AND R.DEL_DAY IS NULL
                                                  AND R.COMPY_CD = '{sc.COMPY_CD}'""", bnd, arraysize=20000)[1]:
                if sid in shops_needed:
                    sold.setdefault((sid, p, c, s), []).append(d)
    today = _d8(sc.today())
    for x in acc:
        a = _d8(x["acceptDt"])
        until = a + timedelta(days=SOLD_DAYS) if a else None
        x["matured"] = bool(a and until <= today)
        x["sold"] = bool(a and any(a <= _d8(d) <= until for d in sold.get((x["to"],) + x["sku"], [])))

    nm = {sid: sh["shopNm"] for sid, sh in shops.items()}
    tm = sc.team_names()

    def agg(key: str) -> list[dict]:
        out: dict[str, dict] = {}
        for x in items:
            g = out.setdefault(x[key], {"shopId": x[key], "total": 0, **{k: 0 for k in STATUS_NM}, "sold": 0, "hours": []})
            g["total"] += x["qty"]
            g[x["status"]] += x["qty"]
            g["sold"] += x["qty"] if x.get("sold") else 0
            if x["hours"] is not None:
                g["hours"].append(x["hours"])
        res = []
        for g in out.values():
            done = g["C2951"] + g["C2952"] + g["AUTO"]
            sh = shops.get(g["shopId"]) or {}
            res.append({"shopId": g["shopId"], "shopNm": nm.get(g["shopId"]), "team": tm.get(sh.get("team")), "total": g["total"],
                        "accepted": g["C2951"], "denied": g["C2952"], "autoDenied": g["AUTO"], "pending": g["C2954"] + g["N"],
                        "canceled": g["DEL"], "acceptRate": round(g["C2951"] / done * 100, 1) if done else None,
                        "avgHours": round(sum(g["hours"]) / len(g["hours"]), 1) if g["hours"] else None,
                        "sold": g["sold"], "soldRate": round(g["sold"] / g["C2951"] * 100, 1) if g["C2951"] else None})
        res.sort(key=lambda r: (-r["total"], r["shopId"]))
        return res

    tot = {k: sum(x["qty"] for x in items if x["status"] == k) for k in STATUS_NM}
    done = tot["C2951"] + tot["C2952"] + tot["AUTO"]
    hours = [x["hours"] for x in items if x["hours"] is not None]
    matured = [x for x in acc if x["matured"]]
    reasons: dict[str, int] = {}
    for x in items:
        if x["status"] in ("C2952", "AUTO"):
            k = "자동거부 (3일 무응답)" if x["status"] == "AUTO" else _reason(x["resn"])
            reasons[k] = reasons.get(k, 0) + x["qty"]
    days: dict[str, dict] = {}
    for x in items:
        g = days.setdefault(x["dt"], {"day": sc.ymd_label(x["dt"]), "total": 0, "accepted": 0, "denied": 0, "pending": 0})
        g["total"] += x["qty"]
        g["accepted"] += x["qty"] if x["status"] == "C2951" else 0
        g["denied"] += x["qty"] if x["status"] in ("C2952", "AUTO") else 0
        g["pending"] += x["qty"] if x["status"] in ("C2954", "N") else 0
    return {
        "brand": brand, "brandNm": sc.BRAND_CODES[brand], "from": sc.ymd_label(f), "to": sc.ymd_label(t), "scope": scope,
        "includeVirtual": include_virtual, "virtualQty": virtual_qty,
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "soldDays": SOLD_DAYS,
        "summary": {"total": sum(x["qty"] for x in items), "byStatus": [{"code": k, "name": v, "qty": tot[k]} for k, v in STATUS_NM.items() if tot[k]],
                    "accepted": tot["C2951"], "denied": tot["C2952"], "autoDenied": tot["AUTO"], "pending": tot["C2954"] + tot["N"],
                    "canceled": tot["DEL"], "acceptRate": round(tot["C2951"] / done * 100, 1) if done else None,
                    "avgHours": round(sum(hours) / len(hours), 1) if hours else None,
                    "sold": sum(x["qty"] for x in acc if x["sold"]),
                    "soldRate": round(sum(x["qty"] for x in acc if x["sold"]) / tot["C2951"] * 100, 1) if tot["C2951"] else None,
                    "maturedAccepted": sum(x["qty"] for x in matured), "maturedSold": sum(x["qty"] for x in matured if x["sold"])},
        "senders": agg("from")[:200], "receivers": agg("to")[:200],
        "reasons": [{"reason": k, "qty": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:20]],
        "days": [days[k] for k in sorted(days)],
    }


PERF_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("total", "지시", 8), ("accepted", "수락", 8),
             ("denied", "거부", 8), ("autoDenied", "자동거부", 8), ("pending", "미처리", 8), ("canceled", "취소", 8),
             ("acceptRate", "수락률(%)", 9), ("avgHours", "평균 처리 시간(h)", 11), ("sold", f"{SOLD_DAYS}일 내 판매", 9), ("soldRate", "판매 전환(%)", 9)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"RT 성과 ({d['asOf']} 기준 · {d['brandNm']} · 지시일 {d['from']} ~ {d['to']} · {'이 화면에서 지시' if d['scope'] == 'web' else '본사지시 전체'})",
             f"지시 {s['total']:,}장 · 수락 {s['accepted']:,} · 거부 {s['denied']:,} · 자동거부 {s['autoDenied']:,} · 미처리 {s['pending']:,} · 취소 {s['canceled']:,}"
             f" · 수락률 {s['acceptRate'] if s['acceptRate'] is not None else '-'}% · {SOLD_DAYS}일 내 판매 전환 {s['soldRate'] if s['soldRate'] is not None else '-'}%"]
    return sc.xlsx([("보내는 매장", notes, PERF_COLS, d["senders"]), ("받는 매장", notes, PERF_COLS, d["receivers"]),
                    ("거부 사유", notes, [("reason", "사유", 30), ("qty", "수량", 8)], d["reasons"]),
                    ("일별", notes, [("day", "지시일", 11), ("total", "지시", 8), ("accepted", "수락", 8), ("denied", "거부", 8), ("pending", "미처리", 8)],
                     d["days"])])
