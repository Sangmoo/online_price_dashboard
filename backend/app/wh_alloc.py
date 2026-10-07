"""재고 재배치 추천 > 창고 → 매장 배분: 판매분 자동보충(SS10DEV.SP_AUTO_DVID)과 같은 규칙으로 배분 수량을 미리 계산.

추천 계산은 읽기만 한다. 배분의뢰(T_DELV_ASK) 등록 · 삭제는 stock_write (관리자).
- 스타일: 판매보충기준(T_SALE_SUPLM_BASE · _APLY, '*' 은 전체)에 맞는 품번 × 칼라 × 사이즈, 제외 목록(_XCLD) 빼고,
  최초 출고일(T_PRDT_DEAL)이 오늘 이전, 기간 중 등급 매장에서 (반품 아닌) 판매가 있는 상품.
  같은 상품이 기준 여러 줄에 걸리면 첫 줄(기준순번)만 쓴다 (프로시저는 줄마다 한 번 더 배분해 넘칠 수 있음).
- 창고 배분 가능 = 창고 재고(이번 달) − 오늘 이후 출고지시 미명세 − 오늘 이후 미확정 배분의뢰 − 창고재고하한.
  (오늘 이미 돌린 판매분 자동보충의 미확정 의뢰도 빠지므로, 실행 뒤에 보면 '추가로 더 보낼 수 있는 양'이 된다)
- 매장: 정상 매장 · 매장만(ATTR2 없음) · 백화점/아울렛/직영점/대리점 · 등급 그룹에 매장등급 있음 · 팀 조건,
  기간 판매(완불 · 일반, 배수 곱해 반올림)가 있고, 현재고 ≤ 매장재고상한, 판매율 ≥ 최소판매율(0 이면 확인 안 함).
  판매율 = 일반 판매 ÷ (현재고 + 기간 시작 시점 재고) × 100. 판매분 자동보충 수불제어('13')가 걸린 매장은 건너뛴다.
- 순서: 유통형태(백화점 → 아울렛 → 직영점 → 대리점) · 판매율 높은 순 · 매장등급 · 등급 내 순위(리스트는 반대) · 최초판매일.
- 배분: 1차 완불 수량, 2차 일반 판매 수량. 각각 min(판매, 매장재고상한 − 현재고 − 1차 배분, 창고 남은 수량).
프로시저 조건 중 상품구분 · 제품상태 · 리오더 · 지역 · 매장형태 · 판매유형 · 물류반품기간 · 스타일그룹은 쓰지 않는다
(판매유형 조건이 없을 때의 T_SALE 확인은 실측 100% 통과라 생략).
"""
from __future__ import annotations

import time
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from . import db
from . import stock_ctl as sc

DEFAULT_DAYS = 1                   # 기본 판매 기간 = 어제 하루 (자동보충 실행 기록의 대부분)
CACHE_TTL = 10 * 60
MAX_ROWS = 3000
SHOP_TYPES = {"C0041": 1, "C0043": 2, "C0044": 3, "C0042": 4}     # 백화점 · 아울렛 · 직영점 · 대리점
DEFAULT_WH = "IN"


def oround(v: float, nd: int = 0) -> float:
    """Oracle ROUND (0.5 는 0 에서 먼 쪽)"""
    q = Decimal(1).scaleb(-nd)
    return float(Decimal(str(v)).quantize(q, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- 선택지
def options(brand: str | None, allowed: list[str] | None) -> dict:
    b = sc.brand_code(brand, allowed)

    def load():
        whs = [{"code": c, "name": n} for c, n in db.query(
            """SELECT W.WH_CD, W.WH_NM FROM T_WH W
                WHERE W.COMPY_CD = :c AND W.WH_CLSBY = 'C2271'
                  AND EXISTS (SELECT 1 FROM T_WH_STOCK_PRDT S WHERE S.WH_CD = W.WH_CD AND S.MAKE_YYMM = :ym AND S.STOCK_QTY > 0)
                ORDER BY W.ATTR2""", {"c": sc.COMPY_CD, "ym": sc.today()[:6]})[1]]
        bases = [{"id": i, "aplyDt": sc.ymd_label(d), "rmk": r} for i, d, r in db.query(
            """SELECT * FROM (SELECT BASE_ID, APLY_DT, RMK FROM T_SALE_SUPLM_BASE
                WHERE COMPY_CD = :c AND PARENT_BRD_CD = :b AND DEL_DAY IS NULL ORDER BY APLY_DT DESC, BASE_ID DESC) WHERE ROWNUM <= 40""",
            {"c": sc.COMPY_CD, "b": b})[1]]
        grps = [{"id": i, "name": n, "base": y == "Y"} for i, n, y in db.query(
            """SELECT GRD_GRP_ID, GRD_GRP_NM, BASE_GRP_YN FROM T_SHOP_GRD_GRP_INFO
                WHERE COMPY_CD = :c AND PARENT_BRD_CD = :b AND DEL_DAY IS NULL ORDER BY BASE_GRP_YN DESC, GRD_GRP_ID DESC""",
            {"c": sc.COMPY_CD, "b": b})[1]]
        return {"warehouses": whs, "bases": bases, "gradeGroups": grps, "recentRuns": recent_runs(b)}
    out = sc.cached(("dvopt", b), sc.CACHE_TTL, load)
    prefix = {"S": "쉬즈", "T": "리스트", "A": "시스티나"}[b]
    return {**out, "brand": b, "brands": sc.brand_options(allowed),
            "teams": [{"code": k, "name": v} for k, v in sorted(sc.team_names().items()) if v.startswith(prefix)],
            "seasons": [{"code": k, "name": v} for k, v in sorted(sc.code_names("C007").items())],
            "prdtGrps": [{"code": k, "name": v} for k, v in sorted(sc.code_names("C673").items())],
            "planYears": [str(y) for y in range(datetime.now().year + 1, datetime.now().year - 3, -1)]}


def recent_runs(brand: str, limit: int = 15) -> list[dict]:
    """최근 판매분 자동보충 실행 조건 (SS10DEV.T_AUTO_DVID_MASTER_HIST) — 화면에서 골라 같은 조건으로 미리 계산"""
    def split(v):
        return [x for x in (v or "").split(",") if x]
    rows = db.query("""SELECT * FROM (SELECT DIVID_SEQ, WH_CD, ARR_PLAN_YY, ARR_SESN_CD, ARR_PRDT_GRP_CD, ARR_PRDT_KIND_CD, PRDT_CD,
                                             ARR_TEAM_CD, GRD_GRP_ID, SALE_DT, CALC_RATE, SALE_SUPLM_ID, INS_DAY, INS_USERID, ASK_SEQN,
                                             ARR_FST_SALE_TYPE, ARR_GOODS_CLSBY, RE_ORDER_YN, ARR_MGN_CLSBY, ARR_AREA, SHOP_ID, ARR_DSCT_CLSBY,
                                             RTN_SALE_DT, STYLE_GRP_ID
                                        FROM SS10DEV.T_AUTO_DVID_MASTER_HIST WHERE PARENT_BRD_CD = :b
                                       ORDER BY TO_NUMBER(DIVID_SEQ) DESC) WHERE ROWNUM <= :n""", {"b": brand, "n": limit})[1]
    out = []
    for r in rows:
        (seq, wh, yy, ss, grp, kind, prdt, team, grd, sale_dt, rate, base, ins, usr, ask_seqn,
         fst, goods, reorder, mgn, area, shop, dsct, rtn, sgrp) = r
        frm, _, to = (sale_dt or "").partition("/")
        ignored = [nm for nm, v in (("제품상태", fst), ("상품구분", goods), ("매장형태", mgn), ("지역", area), ("매장", shop),
                                    ("판매유형", dsct), ("스타일그룹", sgrp)) if v]
        if reorder == "Y":
            ignored.append("리오더")
        if rtn and rtn.replace("/", "").strip("9") and not rtn.startswith("99991231"):
            rf, _, rt = rtn.partition("/")
            if len(rf) == 8 and len(rt) == 8 and rf <= rt:
                ignored.append("물류반품기간")
        out.append({"seq": seq, "at": f"{sc.ymd_label(ins)} {ins[8:10]}:{ins[10:12]}" if ins and len(ins) >= 12 else None, "user": usr,
                    "askSeqn": ask_seqn, "wh": wh, "planYy": split(yy), "seasons": split(ss), "prdtGrps": split(grp), "items": split(kind),
                    "prdt": prdt, "teams": split(team), "grdGrp": grd, "from": sc.ymd_label(frm), "to": sc.ymd_label(to or frm),
                    "rate": float(rate) if rate is not None else 1, "base": base, "ignored": ignored})
    return out


# ---------------------------------------------------------------- 조회
def _styles(brand: str, base: str, ask_dt: str, yy, ss, grps, items, prdt) -> dict[tuple, dict]:
    cond, b = [], {"c": sc.COMPY_CD, "b": brand, "base": base, "ask": ask_dt}
    for col, vals, pfx in (("T1.PLAN_YY", yy, "yy"), ("T1.SESN_CD", ss, "ss"), ("T1.PRDT_GRP_CD", grps, "gp"), ("T1.ITEM_CD", items, "it")):
        if vals:
            ph, bb = sc.binds(vals, pfx)
            cond.append(f"AND {col} IN ({ph})")
            b.update(bb)
    if prdt:
        cond.append("AND T1.PRDT_CD LIKE :pp || '%'")
        b["pp"] = prdt
    rows = db.query(f"""
SELECT T1.PRDT_CD, T2.COLOR_CD, T2.SIZE_CD, T3.MIN_SALE_RATE, DECODE(T3.MAX_SHOP_STOCK_QTY, 0, 9999, T3.MAX_SHOP_STOCK_QTY),
       T3.MIN_WH_STOCK_QTY, T3.BASE_SEQ, T1.BRD_CD, T1.STYLE_NM, T1.PLAN_YY, T1.SESN_CD, T1.ITEM_CD
  FROM T_STYLE_PLAN T1, T_STYLE_SIZE T2,
       (SELECT A.BASE_ID, A.BASE_SEQ, A.YEAR_CD AS PLAN_YY, A.SEASON_CD AS SESN_CD, A.PRDCLS_CD AS PRDT_GRP_CD, A.ITEM_CD AS PRDT_KIND_CD,
               A.PRDT_CD, A.SIZE_CD, A.MIN_SALE_RATE, A.MAX_SHOP_STOCK_QTY, A.MIN_WH_STOCK_QTY
          FROM T_SALE_SUPLM_BASE_APLY A, T_SALE_SUPLM_BASE B
         WHERE A.COMPY_CD = B.COMPY_CD AND A.BASE_ID = B.BASE_ID AND B.COMPY_CD = :c AND B.PARENT_BRD_CD = :b AND B.BASE_ID = :base) T3,
       (SELECT COMPY_CD, SUBSTR(PRDT_ID, 1, 11) AS PRDT_CD, MIN(DELV_F_DT) AS DELV_F_DT FROM T_PRDT_DEAL
         GROUP BY COMPY_CD, SUBSTR(PRDT_ID, 1, 11)) T4
 WHERE T1.PRDT_CD = T2.PRDT_CD AND T1.COMPY_CD = T2.COMPY_CD AND T1.COMPY_CD = T4.COMPY_CD(+) AND T1.PRDT_CD = T4.PRDT_CD(+)
   AND T1.COMPY_CD = :c AND T1.PARENT_BRD_CD = :b AND T1.PLAN_YY = T3.PLAN_YY AND T1.SESN_CD = T3.SESN_CD
   AND NVL(T1.PRDT_GRP_CD, ' ') LIKE DECODE(T3.PRDT_GRP_CD, '*', '%', T3.PRDT_GRP_CD)
   AND NVL(T1.ITEM_CD, ' ') LIKE DECODE(T3.PRDT_KIND_CD, '*', '%', T3.PRDT_KIND_CD)
   AND T1.PRDT_CD LIKE DECODE(T3.PRDT_CD, '*', '%', T3.PRDT_CD)
   AND T2.SIZE_CD LIKE DECODE(T3.SIZE_CD, '*', '%', T3.SIZE_CD)
   {' '.join(cond)}
   AND NOT EXISTS (SELECT 1 FROM T_SALE_SUPLM_BASE_XCLD T
                    WHERE T.COMPY_CD = T1.COMPY_CD AND T1.PLAN_YY = T.YEAR_CD AND T1.SESN_CD = T.SEASON_CD AND T3.BASE_ID = T.BASE_ID
                      AND NVL(T1.ITEM_CD, ' ') LIKE DECODE(T.ITEM_CD, '*', '%', T.ITEM_CD)
                      AND T1.PRDT_CD LIKE DECODE(T.PRDT_CD, '*', '%', T.PRDT_CD))
   AND NVL(T4.DELV_F_DT, '99991231') <= :ask""", b, arraysize=20000)[1]
    out: dict[tuple, dict] = {}
    for p, c, s, min_rate, max_stk, min_wh, seq, brd, nm, py, sesn, item in sorted(rows, key=lambda r: (r[0], r[1], r[2], r[6] or 0)):
        out.setdefault((p, c, s), {"minRate": float(min_rate or 0), "maxStock": int(max_stk or 0), "minWh": int(min_wh or 0),
                                   "brd": brd, "styleNm": nm, "planYy": py, "sesn": sesn, "item": item})
    return out


def _sales(frm: str, to: str, prdts: list[str]) -> list[tuple]:
    """기간 판매 (매장 × 상품): 완불 · 일반(반품은 빼서), 반품 아닌 판매 여부"""
    out: list[tuple] = []
    for part in sc.chunks(sorted(prdts), 500):
        ph, b = sc.binds(part, "p")
        out += db.query(f"""SELECT R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD,
                                   SUM(DECODE(R.FULPAY_YN, 'Y', DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY), 0)),
                                   SUM(DECODE(R.FULPAY_YN, 'Y', 0, DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY))),
                                   MAX(DECODE(R.RET_YN, 'N', 1, 0))
                              FROM T_SHOP_RNDS_BASE R
                             WHERE R.MAKE_DT BETWEEN :f AND :t AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL
                               AND R.COMPY_CD = '{sc.COMPY_CD}' AND R.PRDT_CD IN ({ph})
                             GROUP BY R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD""", {**b, "f": frm, "t": to}, arraysize=20000)[1]
    return out


def _pc_query(pcs: list[tuple], sql: str, extra: dict) -> list[tuple]:
    """(품번, 칼라) 목록으로 나눠 읽기 — sql 의 {keys} 자리에 (:p0, :c0), …"""
    out: list[tuple] = []
    for part in sc.chunks(sorted(pcs), 300):
        b = dict(extra)
        keys = []
        for i, (p, c) in enumerate(part):
            b[f"p{i}"], b[f"c{i}"] = p, c
            keys.append(f"(:p{i}, :c{i})")
        out += db.query(sql.replace("{keys}", ", ".join(keys)), b, arraysize=20000)[1]
    return out


def _stock(pcs: list[tuple], ym: str) -> dict[tuple, tuple]:
    """(매장, 상품) → (현재고, 기초수량) — 그 달 행"""
    return {tuple(r[:4]): (int(r[4] or 0), int(r[5] or 0)) for r in _pc_query(pcs, """
        SELECT /*+ INDEX(S T_SHOP_STOCK2_IDX01) */ S.SHOP_ID, S.PRDT_CD, S.COLOR_CD, S.SIZE_CD, S.STOCK_QTY, S.BGN_QTY FROM T_SHOP_STOCK S
         WHERE (S.PRDT_CD, S.COLOR_CD) IN ({keys}) AND S.MAKE_YYMM = :ym AND (S.STOCK_QTY <> 0 OR S.BGN_QTY <> 0)""", {"ym": ym})}


def _moves(pcs: list[tuple], frm_month_start: str, frm: str) -> dict[tuple, int]:
    """그 달 1일 ~ 판매 시작일까지 수불 (판매는 빼고 그 외는 더함, 반품은 반대) — 기간 시작 시점 재고 계산용"""
    out: dict[tuple, int] = {}
    for r in _pc_query(pcs, f"""
        SELECT M.SHOP_ID, M.PRDT_CD, M.COLOR_CD, M.SIZE_CD,
               SUM(DECODE(M.STOCK_STAT, 'C20922', DECODE(M.RET_YN, 'Y', M.QTY, -M.QTY), DECODE(M.RET_YN, 'Y', -M.QTY, M.QTY)))
          FROM T_SHOP_RNDS_BASE M
         WHERE (M.PRDT_CD, M.COLOR_CD) IN ({{keys}}) AND M.MAKE_DT BETWEEN :ms AND :f AND M.DEL_DAY IS NULL AND M.COMPY_CD = '{sc.COMPY_CD}'
         GROUP BY M.SHOP_ID, M.PRDT_CD, M.COLOR_CD, M.SIZE_CD""", {"ms": frm_month_start, "f": frm}):
        out[tuple(r[:4])] = int(r[4] or 0)
    return out


def _first_sale(brand: str, keys: list[tuple]) -> dict[tuple, str]:
    """(매장, 상품) → 최초판매일 (T_SHOP_PRDT_BASE)"""
    out: dict[tuple, str] = {}
    for part in sc.chunks(sorted(keys), 200):
        b: dict = {"brd": brand}
        ks = []
        for i, (sid, p, c, s) in enumerate(part):
            b[f"h{i}"], b[f"p{i}"], b[f"c{i}"], b[f"s{i}"] = sid, p, c, s
            ks.append(f"(:h{i}, :p{i}, :c{i}, :s{i})")
        for sid, p, c, s, d in db.query(f"""SELECT SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, F_SALE_DT FROM T_SHOP_PRDT_BASE
                                             WHERE COMPY_CD = '{sc.COMPY_CD}' AND PARENT_BRD_CD = :brd
                                               AND (SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD) IN ({', '.join(ks)})""", b)[1]:
            out[(sid, p, c, s)] = d
    return out


def _wh_avail(brand: str, wh: str, prdts: list[str], td: str) -> dict[tuple, dict]:
    """상품 → 창고 재고 · 출고지시 미명세 · 미확정 배분의뢰 (오늘 이후)"""
    out: dict[tuple, dict] = {}

    def add(k, field, q):
        out.setdefault(k, {"wh": 0, "indc": 0, "ask": 0})[field] += int(q or 0)
    for part in sc.chunks(sorted(prdts), 500):
        ph, b = sc.binds(part, "p")
        for p, c, s, q in db.query(f"""SELECT PRDT_CD, COLOR_CD, SIZE_CD, SUM(NVL(STOCK_QTY, 0)) FROM T_WH_STOCK_PRDT
                                        WHERE MAKE_YYMM = :ym AND WH_CD = :wh AND PRDT_CD IN ({ph})
                                        GROUP BY PRDT_CD, COLOR_CD, SIZE_CD""", {**b, "ym": td[:6], "wh": wh})[1]:
            add((p, c, s), "wh", q)
    for p, c, s, q in db.query("""SELECT PRDT_CD, COLOR_CD, SIZE_CD, SUM(NVL(DELV_REQ_QTY, 0)) FROM T_DELV_INDC
                                   WHERE COMPY_CD = :c AND PARENT_BRD_CD = :b AND MAKE_DT >= :td AND TRAN_SPEC_DT IS NULL
                                   GROUP BY PRDT_CD, COLOR_CD, SIZE_CD""", {"c": sc.COMPY_CD, "b": brand, "td": td})[1]:
        add((p, c, s), "indc", q)
    for p, c, s, q in db.query("""SELECT PRDT_CD, COLOR_CD, SIZE_CD, SUM(NVL(ASK_QTY, 0)) FROM T_DELV_ASK
                                   WHERE COMPY_CD = :c AND PARENT_BRD_CD = :b AND ASK_DT >= :td AND NVL(CNFM_YN, 'N') = 'N' AND DEL_DAY IS NULL
                                   GROUP BY PRDT_CD, COLOR_CD, SIZE_CD""", {"c": sc.COMPY_CD, "b": brand, "td": td})[1]:
        add((p, c, s), "ask", q)
    return out


def web_asked(brand: str, td: str) -> dict[tuple, int]:
    """이 화면에서 넣은 미확정 배분의뢰 (오늘 이후 의뢰일) — (매장, 상품) → 수량"""
    out: dict[tuple, int] = {}
    for sid, p, c, s, q in db.query("""SELECT SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, SUM(NVL(ASK_QTY, 0)) FROM T_DELV_ASK
                                        WHERE ASK_DT >= :td AND PARENT_BRD_CD = :b AND ATTR1 = :m AND NVL(CNFM_YN, 'N') = 'N'
                                        GROUP BY SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD""", {"td": td, "b": brand, "m": sc.WEB_MARK})[1]:
        out[(sid, p, c, s)] = int(q or 0)
    return out


# ---------------------------------------------------------------- 배분 (DB 없이 테스트 가능)
def shop_key(c: dict, brand: str) -> tuple:
    """SP_AUTO_DVID 매장 순서: 유통형태 · 판매율 높은 순 · 매장등급 · 등급 내 순위 (리스트는 등급 · 순위 반대) · 최초판매일"""
    sign = 1 if brand == "T" else -1
    big = (1, 0)
    grd = big if c["prty"] is None else (0, sign * c["prty"])
    rank = big if c["rank"] is None else (0, sign * c["rank"])
    return (c["typeRank"], -c["srate"], grd, rank, c.get("sdt") or "99999999", c["shopId"])


def allocate(avail: int, shops: list[dict], max_stock: int) -> list[dict]:
    """shops: 순서대로 정렬된 후보 (fq, sq, stk, ctl). 1차 완불 → 2차 일반 판매. 돌려줌: [{shopId, fp, sale}]"""
    got: dict[str, dict] = {}
    left = avail
    for phase in ("fp", "sale"):
        if left <= 0:
            break
        for c in shops:
            if c["ctl"]:
                continue
            q = c["fq"] if phase == "fp" else c["sq"]
            already = got.get(c["shopId"], {}).get("fp", 0) if phase == "sale" else 0
            room = max_stock - (c["stk"] + already)
            if q > 0 and room > 0:
                ask = min(q, room, left)
                if ask > 0:
                    got.setdefault(c["shopId"], {"shopId": c["shopId"], "fp": 0, "sale": 0})[phase] += ask
                    left -= ask
            if left <= 0:
                break
    return list(got.values())


# ---------------------------------------------------------------- 추천
def recommend(brand: str | None = None, wh: str | None = None, frm: str | None = None, to: str | None = None, base: str | None = None,
              grd_grp: str | None = None, plan_yy=None, seasons=None, prdt_grps=None, items=None, prdt: str | None = None, teams=None,
              rate: float = 1, allowed: list[str] | None = None, use_cache: bool = True, refresh: bool = False) -> dict:
    b = sc.brand_code(brand, allowed)
    f, t = sc.period(frm, to, DEFAULT_DAYS, end_yesterday=True)
    wh = (wh or DEFAULT_WH).strip().upper()
    if not wh.isalnum() or len(wh) > 4:
        sc.bad("창고코드가 올바르지 않습니다.")
    yy = sc.code_list(plan_yy, "기획년도", r"^\d{4}$", 5)
    ss = sc.code_list(seasons, "시즌", r"^C007[0-9A-Z]$", 14)
    gp = sc.code_list(prdt_grps, "품군", r"^C673[0-9A-Z]{1,2}$", 30)
    it = sc.code_list(items, "아이템", r"^[A-Z0-9]{1,4}$", 40)
    tm = sc.code_list(teams, "팀", r"^C620\d{1,3}$", 20)
    pp = sc.prdt_prefix(prdt)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        sc.bad("배수는 숫자입니다.")
    if not 0 < rate <= 10:
        sc.bad("배수는 0 보다 크고 10 이하입니다.")
    opts = options(b, allowed)
    if not base:
        runs = opts["recentRuns"]
        base = runs[0]["base"] if runs else (opts["bases"][0]["id"] if opts["bases"] else None)
    if not base or not any(x["id"] == base for x in opts["bases"]):
        sc.bad("판매보충기준을 고르세요 (이 브랜드의 기준만 쓸 수 있습니다).")
    grd_grp = grd_grp or next((g["id"] for g in opts["gradeGroups"] if g["base"]), None)
    if not grd_grp or not any(g["id"] == grd_grp for g in opts["gradeGroups"]):
        sc.bad("매장 등급 그룹이 이 브랜드의 것이 아닙니다.")
    key = ("dvid", b, wh, f, t, base, grd_grp, tuple(yy), tuple(ss), tuple(gp), tuple(it), pp, tuple(tm), rate)
    args = (b, wh, f, t, base, grd_grp, yy, ss, gp, it, pp, tm, rate)
    if use_cache:
        return sc.cached(key, CACHE_TTL, lambda: _compute(*args), force=refresh)
    return _compute(*args)


def _compute(brand, wh, f, t, base, grd_grp, yy, ss, gp, it, pp, tm, rate) -> dict:
    started = time.perf_counter()
    td = sc.today()
    timing: dict[str, float] = {}

    def lap(name, t0):
        timing[name] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    styles = _styles(brand, base, td, yy, ss, gp, it, pp)
    lap("styles", t0)
    shops = sc.shops()
    graded = sc.grade_shops(grd_grp)
    ctl = sc.controls(brand, td)
    vt = {sid: g for sid, g in graded.items()
          if (sh := shops.get(sid)) and sh["normal"] and not sh["attr2"] and sh["type"] in SHOP_TYPES and (not tm or sh["team"] in tm)}

    t0 = time.perf_counter()
    sales = _sales(f, t, sorted({k[0] for k in styles})) if styles else []
    lap("sales", t0)
    # 스타일 조건: 기간 중 등급 매장(팀 · 유통형태 조건과 무관)에서 반품 아닌 판매가 있는 상품
    sold_skus = {(p, c, s) for sid, p, c, s, fq, sq, nonret in sales if nonret and (p, c, s) in styles and sid in graded}
    cand = [(sid, (p, c, s), int(fq or 0), int(sq or 0)) for sid, p, c, s, fq, sq, _ in sales if (p, c, s) in sold_skus and sid in vt]
    pcs = sorted({(k[0], k[1]) for _, k, _, _ in cand})
    t0 = time.perf_counter()
    stock_now = _stock(pcs, td[:6]) if pcs else {}
    fm = f[:6]
    stock_from = stock_now if fm == td[:6] else (_stock(pcs, fm) if pcs else {})
    moves = _moves(pcs, fm + "01", f) if pcs else {}
    lap("stock", t0)
    t0 = time.perf_counter()
    whq = _wh_avail(brand, wh, sorted({k[0] for k in sold_skus}), td) if sold_skus else {}
    asked = web_asked(brand, td)
    lap("warehouse", t0)

    by_sku: dict[tuple, list[dict]] = {}
    n_asked = 0
    for sid, sku, fq_raw, sq_raw in cand:
        st = styles[sku]
        k = (sid,) + sku
        stk = stock_now.get(k, (0, 0))[0]
        bstk = stock_from.get(k, (0, 0))[1] + moves.get(k, 0)
        fq, sq = int(oround(fq_raw * rate)), int(oround(sq_raw * rate))
        if fq <= 0 and sq <= 0:
            continue
        denom = stk + bstk
        srate = oround(sq_raw / denom * 100, 2) if denom else 0.0
        if stk > st["maxStock"]:
            continue
        if st["minRate"] and st["minRate"] > srate:
            continue
        if k in asked:          # 이 화면에서 이미 배분의뢰(미확정)를 넣은 매장 × 상품은 다시 배분하지 않는다
            n_asked += 1
            continue
        g = vt[sid]
        by_sku.setdefault(sku, []).append({"shopId": sid, "typeRank": SHOP_TYPES[shops[sid]["type"]], "srate": srate, "prty": g["prty"],
                                           "rank": g["rank"], "grdNm": g["grdNm"], "fq": fq, "sq": sq, "stk": stk,
                                           "ctl": ctl.controlled_id(sid, sku[0], sku[1], "13")})
    # 최초판매일은 앞 순서가 모두 같은 매장끼리만 필요 → 그런 매장만 읽는다
    t0 = time.perf_counter()
    need_sdt = []
    for sku, lst in by_sku.items():
        seen: dict[tuple, list] = {}
        for c in lst:
            seen.setdefault(shop_key(c, brand)[:4], []).append(c["shopId"])
        need_sdt += [(sid,) + sku for v in seen.values() if len(v) > 1 for sid in v]
    sdt = _first_sale(brand, need_sdt) if need_sdt else {}
    lap("firstSale", t0)

    rows, sku_rows = [], []
    teams = sc.team_names()
    for sku in sorted(by_sku):
        lst = by_sku[sku]
        for c in lst:
            c["sdt"] = sdt.get((c["shopId"],) + sku)
        lst.sort(key=lambda c: shop_key(c, brand))
        st = styles[sku]
        w = whq.get(sku, {"wh": 0, "indc": 0, "ask": 0})
        avail = w["wh"] - w["indc"] - w["ask"] - st["minWh"]
        alloc = allocate(avail, lst, st["maxStock"]) if avail > 0 else []
        got = {a["shopId"]: a for a in alloc}
        demand = sum(max(0, min(c["fq"] + c["sq"], st["maxStock"] - c["stk"])) for c in lst if not c["ctl"])
        total = sum(a["fp"] + a["sale"] for a in alloc)
        sku_rows.append({"prdtCd": sku[0], "styleNm": st["styleNm"], "colorCd": sku[1], "sizeCd": sku[2], "whStock": w["wh"],
                         "reserved": w["indc"] + w["ask"], "minWh": st["minWh"], "avail": max(avail, 0), "shops": len(lst),
                         "demand": demand, "alloc": total, "short": max(demand - total, 0), "maxStock": st["maxStock"],
                         "minRate": st["minRate"]})
        for rank, c in enumerate(lst, 1):
            a = got.get(c["shopId"])
            sh = shops[c["shopId"]]
            need = 0 if c["ctl"] else max(0, min(c["fq"] + c["sq"], st["maxStock"] - c["stk"]))
            ask = (a["fp"] + a["sale"]) if a else 0
            rows.append({"prdtCd": sku[0], "styleNm": st["styleNm"], "colorCd": sku[1], "sizeCd": sku[2], "rank": rank,
                         "shopId": c["shopId"], "shopNm": sh["shopNm"], "team": teams.get(sh["team"]),
                         "shopType": sc.SHOP_TYPE_NM.get(sh["type"]), "grade": c["grdNm"], "gradeRank": c["rank"], "srate": c["srate"],
                         "fq": c["fq"], "sq": c["sq"], "stock": c["stk"], "askFp": a["fp"] if a else 0, "askSale": a["sale"] if a else 0,
                         "ask": ask, "ctl": c["ctl"], "need": need, "short": max(need - ask, 0)})
    alloc_rows = [r for r in rows if r["ask"]]
    short_rows = [r for r in rows if r["short"] > 0]          # 창고 수량이 모자라 필요만큼 못 받은 매장 (일부 · 전혀)
    by_shop: dict[str, int] = {}
    for r in alloc_rows:
        by_shop[r["shopId"]] = by_shop.get(r["shopId"], 0) + r["ask"]
    names = {sid: sh["shopNm"] for sid, sh in shops.items()}
    timing["total"] = round(time.perf_counter() - started, 2)
    return {
        "brand": brand, "brandNm": sc.BRAND_CODES[brand], "wh": wh, "from": sc.ymd_label(f), "to": sc.ymd_label(t), "base": base,
        "grdGrp": grd_grp, "rate": rate, "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cond": {"planYy": yy, "seasons": ss, "prdtGrps": gp, "items": it, "prdt": pp, "teams": tm},
        "summary": {"styleSkus": len(styles), "soldSkus": len(sold_skus), "skus": len(by_sku),
                    "allocSkus": sum(1 for s in sku_rows if s["alloc"]), "allocQty": sum(r["ask"] for r in alloc_rows),
                    "allocFp": sum(r["askFp"] for r in alloc_rows), "shops": len(by_shop),
                    "demand": sum(s["demand"] for s in sku_rows), "short": sum(s["short"] for s in sku_rows),
                    "noStockSkus": sum(1 for s in sku_rows if s["avail"] <= 0 and s["demand"] > 0),
                    "ctlRows": sum(1 for r in rows if r["ctl"]), "candidates": sum(len(v) for v in by_sku.values()),
                    "shortRows": len(short_rows), "shortZero": sum(1 for r in short_rows if not r["ask"]), "asked": n_asked},
        "rows": alloc_rows, "shortRows": short_rows, "ctlRows": [r for r in rows if r["ctl"]], "skus": sku_rows, "allRows": rows,
        "topShops": [{"shopId": k, "shopNm": names.get(k), "qty": v} for k, v in sorted(by_shop.items(), key=lambda x: (-x[1], x[0]))[:15]],
        "timing": timing,
    }


# ---------------------------------------------------------------- 엑셀
def cond_text(d: dict) -> str:
    c = d["cond"]
    seasons, grps, teams = sc.code_names("C007"), sc.code_names("C673"), sc.team_names()
    parts = [f"브랜드 {d['brandNm']}", f"창고 {d['wh']}", f"판매 기간 {d['from']} ~ {d['to']}", f"판매보충기준 {d['base']}",
             f"등급 그룹 {d['grdGrp']}", f"배수 {d['rate']:g}"]
    if c["planYy"]:
        parts.append("기획년도 " + ", ".join(c["planYy"]))
    if c["seasons"]:
        parts.append("시즌 " + ", ".join(seasons.get(x, x) for x in c["seasons"]))
    if c["prdtGrps"]:
        parts.append("품군 " + ", ".join(grps.get(x, x) for x in c["prdtGrps"]))
    if c["items"]:
        parts.append("아이템 " + ", ".join(c["items"]))
    if c["teams"]:
        parts.append("팀 " + ", ".join(teams.get(x, x) for x in c["teams"]))
    if c["prdt"]:
        parts.append(f"품번 {c['prdt']}…")
    return " · ".join(parts)


ALLOC_COLS = [("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7), ("rank", "매장 순위", 8),
              ("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("shopType", "유통형태", 9), ("grade", "등급", 8),
              ("gradeRank", "등급 내 순위", 9), ("srate", "판매율(%)", 9), ("fq", "완불 판매", 8), ("sq", "일반 판매", 8), ("stock", "현재고", 8),
              ("askFp", "배분(완불)", 9), ("askSale", "배분(판매)", 9), ("ask", "배분 합계", 9), ("need", "필요", 7),
              ("short", "창고 부족", 9), ("ctl", "수불제어", 8)]
SKU_COLS = [("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7), ("whStock", "창고 재고", 9),
            ("reserved", "출고지시 · 미확정 의뢰", 12), ("minWh", "창고재고하한", 10), ("avail", "배분 가능", 9), ("shops", "후보 매장", 9),
            ("demand", "필요 수량", 9), ("alloc", "배분", 8), ("short", "부족", 8), ("maxStock", "매장재고상한", 10), ("minRate", "최소판매율", 9)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"창고 → 매장 배분 추천 ({d['asOf']} 기준, 판매분 자동보충 규칙 · 추천 — ERP 등록은 화면의 [배분의뢰 등록])", cond_text(d),
             f"상품 {s['skus']:,}개 · 배분 {s['allocQty']:,}장(완불 {s['allocFp']:,}) · 매장 {s['shops']:,}곳 · 필요 {s['demand']:,}장 중 부족 {s['short']:,}장"]
    return sc.xlsx([("배분 추천", notes, ALLOC_COLS, d["rows"]), ("창고 부족", notes, ALLOC_COLS, d["shortRows"]), ("상품별", notes, SKU_COLS, d["skus"]),
                    ("후보 매장 전체", notes, ALLOC_COLS, d["allRows"])])
