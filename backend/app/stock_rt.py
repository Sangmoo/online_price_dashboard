"""재고 재배치 추천 > 매장 간 RT: 판매 후 품절된 매장(받는 매장)에 같은 RT 그룹의 재고 매장(보내는 매장)을 짝지어 추천.

추천 계산은 읽기만 한다. 본사지시 RT(T_INDC_RT) 등록 · 삭제는 stock_write (관리자). 규칙은 ERP 자동 RT(SP_AUTO_RT_SEARCH · SAVE)와 같다.
- 받는 매장: 기간(최대 31일) 판매가 있는데 지금 재고가 0 이하인 매장 × 상품(품번 · 칼라 · 사이즈),
  그리고 기간 중 자동 RT 가 '지시가능매장없음'으로 취소된 요청. 필요 수량 = 1(선택 1~3) + 마이너스 재고(완불 대기).
  RT 그룹이 없거나 정상 매장이 아니면 빼고, 자동 RT 반입 수불제어(F_GET_RNDS_CNTR …'36')가 걸린 매장도 뺀다.
- 보내는 매장 (SP_AUTO_RT_SEARCH 와 같은 조건)
  1. 받는 매장과 같은 RT 그룹(T_SHOP_RT_GRP_DETL) · 모매장 브랜드 행낭 규칙(시스티나) · 정상 매장
  2. 매장 상품 기준(T_SHOP_PRDT_BASE)에 최초출고일(2023-01-01 이후)이 있음 · 최초/최종 출고 경과일 기준
  3. 요청 가능 재고 = 현재고 − 이동중(30일 미확정) − 자동 RT 요청중(10일) − 최소보유재고 ≥ 1
  4. 매장등급(기본 등급 그룹) 있음 · 자동 RT 반출 수불제어 · 자동RT 제외 스타일 · 매장 요청가능여부
  5. 오늘 같은 상품을 이미 지정받은 매장 제외
  6. (선택 '보내는 매장당 최대 수량') 한 매장에서 너무 많이 빠지지 않게.
  7. (선택 '자동 RT 하루 한도') 지정가능수(ASIGN_ABLE_QTY) 0 매장 제외, 보내는 매장 오늘 남은 지정가능수 · 받는 매장 요청가능수.
     지정가능수 0 매장이 재고 후보의 절반 가까이라(쉬즈미스 실측) 켜면 추천이 거의 없다 → 기본은 끔(본사 지시 RT 계획용).
- 순서: '안 팔리는 매장 우선'(기본) = 기간 판매 적은 순 → 이후 자동 RT 순서,
        '자동 RT 순서' = 요청가능 재고 많은 순 · 판매율(입고÷판매) 낮은 순 · 최종판매일 · 최초출고일 오래된 순.
  받는 매장은 자동 RT 취소 요청 → 마이너스 재고 → 기간 판매 많은 순으로 먼저 채운다.
속도: 매장 상품 기준(T_SHOP_PRDT_BASE, 약 1,860만 행)은 후보 전부가 아니라 (상품, RT 그룹)마다 순서 앞쪽 8곳씩 읽고
      모자라면 더 읽는다 (같은 순위는 경계에서 8곳까지 더 포함). 재고는 판매가 있던 품번 · 칼라 단위로 한 번에 읽는다.
결과는 30분 캐시 (같은 조건 엑셀 · AI 도구 재사용).
"""
from __future__ import annotations

import time
from datetime import date, datetime

from . import db
from . import stock_ctl as sc

DEFAULT_DAYS = 7
MAX_ROWS = 2000                    # 화면에 보내는 추천 행 (엑셀은 전부)
CACHE_TTL = 30 * 60                # 같은 조건 결과 재사용 (화면 · 엑셀 · AI)
MANY_STYLES = 300                  # 품번이 이보다 많으면 판매를 날짜 인덱스로 읽음
TOP_K = 8                          # (상품, RT 그룹)마다 매장 상품 기준을 먼저 읽는 후보 수
MAX_ROUNDS = 6
ORDERS = {"slow": "안 팔리는 매장 우선", "auto": "자동 RT 순서"}
FIRST_DELV_AFTER = "20230101"      # SP_AUTO_RT_SEARCH: E.F_RNDS_DT > '20230101'
FAIL_RMK = "지시가능매장없음"
REASONS = {"no_stock": "같은 RT 그룹에 재고 없음", "rules": "재고는 있으나 자동 RT 조건에 막힘", "limit": "보낼 매장의 지정가능수 · 최대 수량 소진",
           "recv_limit": "받는 매장 하루 요청가능수 초과"}
RULES = {"moving": "이동중 · 요청중 · 지시 · 최소보유로 남는 재고 없음", "days": "최초/최종 출고 경과일 미달", "control": "자동 RT 반출 제어 · 제외 스타일",
         "grade": "매장등급 없음", "abnormal": "정상 매장 아님", "today": "오늘 같은 상품 지정받음", "asign0": "자동 RT 지정가능수 0",
         "nobase": "매장 상품 기준 없음(2023년 이후 출고 없음)"}

def _days_since(d8: str | None, now: date) -> int:
    if not d8:
        return 0
    try:
        return (now - datetime.strptime(d8[:8], "%Y%m%d").date()).days
    except ValueError:
        return 0


def _mo_brands(shop_id: str, mo: str | None) -> set[str]:
    """SP_AUTO_RT_SEARCH 의 W_MO_BRD: 받는 매장의 모매장 브랜드로 행낭 이동이 되는 브랜드"""
    if shop_id.startswith("A"):
        return {"A": {"A", "S", "T"}, "S": {"S", "A"}, "T": {"T", "A"}}.get(mo or "", {mo} if mo else set())
    if shop_id.startswith("S"):
        return {"S"}
    if shop_id.startswith("T"):
        return {"T"}
    return {mo} if mo else set()


def _style_cond(brand: str, plan_yy: list[str], seasons: list[str], prdt: str | None) -> tuple[str, dict]:
    cond = [f"COMPY_CD = '{sc.COMPY_CD}'", "PARENT_BRD_CD = :brd"]
    b: dict = {"brd": brand}
    if plan_yy:
        ph, bb = sc.binds(plan_yy, "yy")
        cond.append(f"PLAN_YY IN ({ph})")
        b.update(bb)
    if seasons:
        ph, bb = sc.binds(seasons, "ss")
        cond.append(f"SESN_CD IN ({ph})")
        b.update(bb)
    if prdt:
        cond.append("PRDT_CD LIKE :pp || '%'")
        b["pp"] = prdt
    return " AND ".join(cond), b


# ---------------------------------------------------------------- 조회
def _styles(where: str, b: dict) -> list[str]:
    return [r[0] for r in db.query(f"SELECT PRDT_CD FROM T_STYLE_PLAN WHERE {where}", b)[1]]


def _sales(frm: str, to: str, where: str, b: dict, many: bool) -> list[tuple]:
    """기간 판매 (매장 × 상품, 순판매 수량 · 마지막 판매일). 품번이 많으면 날짜 인덱스로 읽는다 (품번별로 읽으면 수십 초)"""
    hint = "/*+ INDEX(R IDX_T_SHOP_RNDS_BASE_05) */" if many else ""
    sj = "/*+ HASH_SJ */" if many else ""
    return db.query(f"""SELECT {hint} R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD, SUM(DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY)), MAX(R.MAKE_DT)
                          FROM T_SHOP_RNDS_BASE R
                         WHERE R.MAKE_DT BETWEEN :f AND :t AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL AND R.COMPY_CD = '{sc.COMPY_CD}'
                           AND R.PRDT_CD IN (SELECT {sj} PRDT_CD FROM T_STYLE_PLAN WHERE {where})
                         GROUP BY R.SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD""", {**b, "f": frm, "t": to}, arraysize=20000)[1]


def _failed(frm: str, to: str, where: str, b: dict) -> list[tuple]:
    """기간 중 '지시가능매장없음'으로 취소된 자동 RT 요청 (매장 × 상품)"""
    return db.query(f"""SELECT STOR_REQ_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, COUNT(*), MAX(REQ_DAY) FROM T_AUTO_RT
                         WHERE REQ_DAY BETWEEN :f || '000000' AND :t || '999999' AND COMPY_CD = '{sc.COMPY_CD}' AND RSLT_CD = 'C6869'
                           AND RMK = '{FAIL_RMK}' AND DEL_DAY IS NULL AND PRDT_CD IN (SELECT PRDT_CD FROM T_STYLE_PLAN WHERE {where})
                         GROUP BY STOR_REQ_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD""", {**b, "f": frm, "t": to})[1]


def _stock(pcs: list[tuple], ym: str) -> list[tuple]:
    """품번 · 칼라의 이번 달 매장 재고 (0 이 아닌 행). (PRDT_CD, COLOR_CD, MAKE_YYMM) 인덱스로 칼라 단위만 읽는다"""
    out: list[tuple] = []
    for part in sc.chunks(sorted(pcs), 300):
        b: dict = {"ym": ym}
        keys = []
        for i, (p, c) in enumerate(part):
            b[f"p{i}"], b[f"c{i}"] = p, c
            keys.append(f"(:p{i}, :c{i})")
        out += db.query(f"""SELECT /*+ INDEX(S T_SHOP_STOCK2_IDX01) */ S.SHOP_ID, S.PRDT_CD, S.COLOR_CD, S.SIZE_CD, S.STOCK_QTY
                              FROM T_SHOP_STOCK S
                             WHERE (S.PRDT_CD, S.COLOR_CD) IN ({', '.join(keys)}) AND S.MAKE_YYMM = :ym AND S.STOCK_QTY <> 0""",
                        b, arraysize=20000)[1]
    return out


def _prdt_base(brand: str, keys: list[tuple]) -> dict[tuple, tuple]:
    """매장 상품 기준 (최초 · 최종 출고일, 최종판매일, 판매율용 수량) — 매장 × 상품 PK 로 필요한 것만"""
    out: dict[tuple, tuple] = {}
    for part in sc.chunks(sorted(keys), 200):
        b: dict = {"brd": brand}
        ks = []
        for i, (sid, p, c, s) in enumerate(part):
            b[f"h{i}"], b[f"p{i}"], b[f"c{i}"], b[f"s{i}"] = sid, p, c, s
            ks.append(f"(:h{i}, :p{i}, :c{i}, :s{i})")
        for r in db.query(f"""SELECT SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, F_RNDS_DT, L_RNDS_DT, L_SALE_DT, NVL(DELV_QTY, 0), NVL(MOVE_STOR_QTY, 0),
                                     NVL(MOVE_DELV_QTY, 0), NVL(SALE_QTY, 0), NVL(RET_QTY, 0)
                                FROM T_SHOP_PRDT_BASE
                               WHERE COMPY_CD = '{sc.COMPY_CD}' AND PARENT_BRD_CD = :brd
                                 AND (SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD) IN ({', '.join(ks)})""", b, arraysize=20000)[1]:
            out[tuple(r[:4])] = r[4:]
    return out



def _moving(td: str) -> dict[tuple, int]:
    """최근 30일 미확정 매장 이동 수량 (입고 이동 매장 기준, SP_AUTO_RT_SEARCH 의 G) — 30일치 이동을 읽어 약 4초라 5분 캐시"""
    return {(sid, p, c, s): int(q or 0) for sid, p, c, s, q in db.query(
        f"""SELECT STOR_MOVE_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, SUM(NVL(MOVE_QTY, 0)) FROM T_SHOP_MOVE
             WHERE MAKE_DT BETWEEN TO_CHAR(SYSDATE - 30, 'YYYYMMDD') AND :td AND COMPY_CD = '{sc.COMPY_CD}' AND NVL(CNFM_YN, 'N') = 'N'
             GROUP BY STOR_MOVE_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD""", {"td": td})[1]}


def _reserved(brand: str, td: str) -> dict:
    """이동중 · 자동 RT 요청중 수량, 오늘 지정 · 요청 수 (SP_AUTO_RT_SEARCH · SAVE 와 같은 기준)"""
    moving = sc.cached(("moving", td), sc.CTL_TTL, lambda: _moving(td))
    pending: dict[tuple, int] = {}
    asigned: dict[str, int] = {}
    asigned_sku: set[tuple] = set()
    # 최근 10일 자동 RT 요청의 지정 매장: 요청중(C6870) 수량, 오늘 지정 수 · 오늘 지정받은 상품 (지정은 요청 때 함께 생김)
    for sid, p, c, s, q, rslt, aday in db.query(f"""SELECT T.DELV_REQ_SHOP_ID, A.PRDT_CD, A.COLOR_CD, A.SIZE_CD, NVL(A.REQ_QTY, 0), T.RSLT_CD, T.ASIGN_DAY
                                                    FROM T_AUTO_RT A, T_AUTO_RT_TARGET T
                                                   WHERE A.REQ_DAY BETWEEN TO_CHAR(SYSDATE - 10, 'YYYYMMDD') || '000000' AND :td || '999999'
                                                     AND A.COMPY_CD = '{sc.COMPY_CD}' AND T.AUTO_RT_ID = A.AUTO_RT_ID""", {"td": td})[1]:
        k = (sid, p, c, s)
        if rslt == "C6870":
            pending[k] = pending.get(k, 0) + int(q)
        if (aday or "").startswith(td) and rslt != "C6877":          # 요청취소 제외
            asigned[sid] = asigned.get(sid, 0) + 1
            asigned_sku.add(k)
    shop_req = dict(db.query("""SELECT DELV_REQ_SHOP_ID, SUM(DECODE(MOVE_TYPE, 'C6812', REQ_QTY, 0)) FROM T_SHOP_REQ
                                 WHERE MAKE_DT = :td AND PRCS_CLSBY IN ('C2951', 'C2954') AND BRD_CD = :b
                                 GROUP BY DELV_REQ_SHOP_ID""", {"td": td, "b": brand})[1])
    requested = dict(db.query("""SELECT STOR_REQ_SHOP_ID, COUNT(*) FROM T_AUTO_RT
                                  WHERE REQ_DAY LIKE :td || '%' AND RSLT_CD != 'C6869' AND DEL_DAY IS NULL
                                  GROUP BY STOR_REQ_SHOP_ID""", {"td": td})[1])
    out_q, in_q = open_instructions(brand, td)
    return {"moving": moving, "pending": pending, "asigned": asigned, "asignedSku": asigned_sku,
            "shopReq": {k: int(v or 0) for k, v in shop_req.items()}, "requested": {k: int(v or 0) for k, v in requested.items()},
            "instrOut": out_q, "instrIn": in_q}


def open_instructions(brand: str, td: str) -> tuple[dict[tuple, int], dict[tuple, int]]:
    """아직 매장이 처리하지 않은 본사지시 · 매장간 RT (최근 10일) — (보내는 매장, 상품) · (받는 매장, 상품) → 수량.
    본사지시 미확정(T_INDC_RT CNFM_YN = N) + 요청 미처리(T_SHOP_REQ C2954, 본사지시 C6811 · 매장간 C6813). 자동 RT 요청중은 pending 에서 뺀다"""
    out_q: dict[tuple, int] = {}
    in_q: dict[tuple, int] = {}

    def add(d, k, q):
        d[k] = d.get(k, 0) + int(q or 0)
    # 힌트 없으면 730만 행 전체를 읽어 약 3초 → 지시일 인덱스로 0.1초
    for dl, st, p, c, s, q in db.query("""SELECT /*+ INDEX(I T_INDC_RT_IDX01) */ DELV_MOVE_SHOP_ID, STOR_MOVE_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD,
                                                  NVL(INDC_QTY, 0) FROM T_INDC_RT I
                                           WHERE INDC_DT BETWEEN TO_CHAR(SYSDATE - 10, 'YYYYMMDD') AND :td AND BRD_CD = :b
                                             AND NVL(CNFM_YN, 'N') = 'N' AND DEL_DAY IS NULL""", {"td": td, "b": brand})[1]:
        add(out_q, (dl, p, c, s), q)
        add(in_q, (st, p, c, s), q)
    for dl, st, p, c, s, q in db.query("""SELECT DELV_REQ_SHOP_ID, STOR_REQ_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, NVL(REQ_QTY, 0) FROM T_SHOP_REQ
                                           WHERE MAKE_DT BETWEEN TO_CHAR(SYSDATE - 10, 'YYYYMMDD') AND :td AND BRD_CD = :b
                                             AND PRCS_CLSBY = 'C2954' AND MOVE_TYPE IN ('C6811', 'C6813') AND DEL_DAY IS NULL""",
                                        {"td": td, "b": brand})[1]:
        add(out_q, (dl, p, c, s), q)
        add(in_q, (st, p, c, s), q)
    return out_q, in_q


# ---------------------------------------------------------------- 짝 맞추기 (DB 없이 테스트 가능)
def prov_key(c: dict, order: str) -> tuple:
    """매장 상품 기준을 읽기 전에 정할 수 있는 순서 (기간 판매 · 요청가능 재고)"""
    return (-c["sendable"],) if order == "auto" else (c["sales"], -c["sendable"])


def sender_key(c: dict, order: str) -> tuple:
    return prov_key(c, order) + (c["srate"], c["lSaleDt"] or "99999999", c["fRndsDt"] or "99999999", c["shopId"])


def receiver_key(r: dict) -> tuple:
    return (-r["failCnt"], r["stock"], -r["sales"], r["shopId"], r["prdtCd"], r["colorCd"], r["sizeCd"])


def match(receivers: list[dict], candidates: dict[tuple, list[dict]], caps: dict[str, int | None],
          recv_caps: dict[str, int | None], order: str) -> tuple[list[dict], list[dict]]:
    """receivers: 받는 매장 × 상품 (need, grp, moOk, supplyAny), candidates: (상품, RT 그룹) → 규칙을 통과한 보내는 후보,
    caps: 보내는 매장 남은 지정가능수(없으면 제한 없음), recv_caps: 받는 매장 남은 요청가능수.
    돌려줌: (추천 행, 못 채운 받는 매장)"""
    left = {(c["shopId"],) + c["sku"]: c["sendable"] for lst in candidates.values() for c in lst}
    caps = dict(caps)
    recv_caps = dict(recv_caps)
    ordered = {k: sorted(v, key=lambda c: sender_key(c, order)) for k, v in candidates.items()}
    out, unfilled = [], []
    for r in sorted(receivers, key=receiver_key):
        sku = (r["prdtCd"], r["colorCd"], r["sizeCd"])
        rc = recv_caps.get(r["shopId"])
        need = r["need"] if rc is None else min(r["need"], max(rc, 0))
        got = 0
        capped = False
        for c in ordered.get((sku, r["grp"]), ()):
            if got >= need:
                break
            if c["shopId"] == r["shopId"] or c["moBrd"] not in r["moOk"]:
                continue
            k = (c["shopId"],) + sku
            if left[k] <= 0:
                continue
            cap = caps.get(c["shopId"])
            if cap is not None and cap <= 0:
                capped = True
                continue
            q = min(need - got, left[k], cap if cap is not None else need)
            left[k] -= q
            if cap is not None:
                caps[c["shopId"]] = cap - q
            got += q
            out.append({"receiver": r, "sender": c, "qty": q})
        if rc is not None:
            recv_caps[r["shopId"]] = rc - got
        if got < r["need"]:
            if got == need:
                reason = "recv_limit"
            elif capped:
                reason = "limit"
            else:
                reason = "rules" if r.get("supplyAny") else "no_stock"
            unfilled.append({**r, "reason": reason, "left": r["need"] - got})
    return out, unfilled


def next_batch(cands: list[dict], start: int, k: int, order: str) -> int:
    """정렬된 후보에서 start 부터 k 개 (경계에서 같은 순위는 k 개까지 더) — 돌려줌: 새 끝 위치"""
    end = min(start + k, len(cands))
    if 0 < end < len(cands):
        last = prov_key(cands[end - 1], order)
        stop = min(end + k, len(cands))
        while end < stop and prov_key(cands[end], order) == last:
            end += 1
    return end


# ---------------------------------------------------------------- 추천
def recommend(brand: str | None = None, frm: str | None = None, to: str | None = None, plan_yy=None, seasons=None,
              prdt: str | None = None, teams=None, per: int = 1, limits: bool = False, order: str = "slow",
              sender_max: int = 0, allowed: list[str] | None = None, use_cache: bool = True, refresh: bool = False) -> dict:
    b = sc.brand_code(brand, allowed)
    f, t = sc.period(frm, to, DEFAULT_DAYS)
    yy = sc.code_list(plan_yy, "기획년도", r"^\d{4}$", 5)
    ss = sc.code_list(seasons, "시즌", r"^C007[0-9A-Z]$", 14)
    tm = sc.code_list(teams, "팀", r"^C620\d{1,3}$", 20)
    pp = sc.prdt_prefix(prdt)
    if isinstance(per, bool) or not isinstance(per, int) or not 1 <= per <= 3:
        sc.bad("매장당 수량은 1~3 입니다.")
    if order not in ORDERS:
        sc.bad(f"순서는 {list(ORDERS)} 중 하나입니다.")
    if isinstance(sender_max, bool) or not isinstance(sender_max, int) or not 0 <= sender_max <= 1000:
        sc.bad("보내는 매장당 최대 수량은 0(제한 없음)~1000 입니다.")
    key = ("rt", b, f, t, tuple(yy), tuple(ss), tuple(tm), pp, per, bool(limits), order, sender_max)
    if use_cache:
        return sc.cached(key, CACHE_TTL, lambda: _compute(b, f, t, yy, ss, tm, pp, per, bool(limits), order, sender_max), force=refresh)
    return _compute(b, f, t, yy, ss, tm, pp, per, bool(limits), order, sender_max)


def _compute(brand, f, t, yy, ss, tm, pp, per, limits, order, sender_max=0) -> dict:
    started = time.perf_counter()
    td = sc.today()
    ym = td[:6]
    now = date.today()
    shops = sc.shops()
    grp_id = sc.base_grade_group(brand)
    graded = sc.grade_shops(grp_id) if grp_id else {}
    ctl = sc.controls(brand, td)
    where, b = _style_cond(brand, yy, ss, pp)
    timing: dict[str, float] = {}

    def lap(name, t0):
        timing[name] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    n_styles = len(_styles(where, b))
    sales_rows = _sales(f, t, where, b, n_styles > MANY_STYLES) if n_styles else []
    failed_rows = _failed(f, t, where, b) if n_styles else []
    lap("sales", t0)
    sales = {tuple(r[:4]): int(r[4] or 0) for r in sales_rows}
    last_sale = {tuple(r[:4]): r[5] for r in sales_rows}
    failed = {tuple(r[:4]): (int(r[4]), r[5]) for r in failed_rows}
    sold = {k for k, q in sales.items() if q > 0}
    pcs = {(k[1], k[2]) for k in sold} | {(k[1], k[2]) for k in failed}
    t0 = time.perf_counter()
    stock = {tuple(r[:4]): int(r[4]) for r in _stock(list(pcs), ym)} if pcs else {}
    lap("stock", t0)

    t0 = time.perf_counter()
    res = _reserved(brand, td)
    lap("reserved", t0)
    skipped = {"noGroup": 0, "recvCtl": 0, "team": 0, "incoming": 0}
    recv: list[dict] = []
    for k in sorted(sold | set(failed)):
        st = stock.get(k, 0)
        if st > 0:
            continue
        sid, p, c, s = k
        sh = shops.get(sid)
        if not sh or not sh["rt"] or not sh["normal"]:
            skipped["noGroup"] += 1
            continue
        if tm and sh["team"] not in tm:
            skipped["team"] += 1
            continue
        if ctl.controlled_id(sid, p, c, "36"):
            skipped["recvCtl"] += 1
            continue
        incoming = res["instrIn"].get(k, 0)
        need = per + max(0, -st) - incoming                        # 이미 지시 · 요청받아 들어올 수량은 뺀다
        if need <= 0:
            skipped["incoming"] += 1
            continue
        fc, fd = failed.get(k, (0, None))
        recv.append({"shopId": sid, "prdtCd": p, "colorCd": c, "sizeCd": s, "sales": max(sales.get(k, 0), 0), "lastSale": last_sale.get(k),
                     "failCnt": fc, "failLast": fd, "stock": st, "need": need, "incoming": incoming, "grp": sh["rt"]["grp"],
                     "moOk": _mo_brands(sid, sh["moBrd"])})
    want = {((r["prdtCd"], r["colorCd"], r["sizeCd"]), r["grp"]) for r in recv}
    styles = sc.style_info(sorted({r["prdtCd"] for r in recv}))

    # 1단계: 매장 상품 기준 없이 거를 수 있는 조건 (정상 · 등급 · 지정가능수 · 남는 재고 · 오늘 지정 · 수불제어)
    excluded = {k: 0 for k in RULES}
    pool: dict[tuple, list[dict]] = {}
    supply_any: set[tuple] = set()
    for (sid, p, c, s), q in stock.items():
        if q <= 0:
            continue
        sh = shops.get(sid)
        grp = sh["rt"]["grp"] if sh and sh["rt"] else None
        sku = (p, c, s)
        if not grp or (sku, grp) not in want:
            continue
        supply_any.add((sku, grp))
        rt = sh["rt"]
        k = (sid, p, c, s)
        real = q - res["moving"].get(k, 0) - res["pending"].get(k, 0) - res["instrOut"].get(k, 0)
        if not sh["normal"]:
            excluded["abnormal"] += 1
        elif sid not in graded:
            excluded["grade"] += 1
        elif limits and rt["asign"] <= 0:
            excluded["asign0"] += 1
        elif real - max(rt["minRetain"], 0) < 1:
            excluded["moving"] += 1
        elif k in res["asignedSku"]:
            excluded["today"] += 1
        elif ctl.controlled_rt_out(sid, p, c, sh, styles.get(p)):
            excluded["control"] += 1
        else:
            pool.setdefault((sku, grp), []).append({"shopId": sid, "sku": sku, "stock": q, "real": real,
                                                    "sendable": real - max(rt["minRetain"], 0), "sales": max(sales.get(k, 0), 0),
                                                    "moBrd": sh["moBrd"], "srate": 0, "lSaleDt": None, "fRndsDt": None})
    for lst in pool.values():
        lst.sort(key=lambda c: prov_key(c, order) + (c["shopId"],))
    for r in recv:
        r["supplyAny"] = ((r["prdtCd"], r["colorCd"], r["sizeCd"]), r["grp"]) in supply_any

    caps: dict[str, int | None] = {}
    recv_caps: dict[str, int | None] = {}
    for sid in {c["shopId"] for lst in pool.values() for c in lst}:
        cap = shops[sid]["rt"]["asign"] - max(res["asigned"].get(sid, 0), res["shopReq"].get(sid, 0)) if limits else None
        if sender_max:
            cap = sender_max if cap is None else min(cap, sender_max)
        if cap is not None:
            caps[sid] = cap
    if limits:
        for sid in {r["shopId"] for r in recv}:
            ra = shops[sid]["rt"]["reqAble"]
            # SP_AUTO_RT_SAVE: 오늘 요청 수가 요청가능수 이하이면 한 건 더 요청 가능 (NULL 이면 제한 없음)
            recv_caps[sid] = None if ra is None else ra - res["requested"].get(sid, 0) + 1

    # 2단계: 순서 앞쪽 후보부터 매장 상품 기준을 읽어 확인 (최초출고 · 출고 경과일 · 판매율 · 최종판매일), 모자라면 더 읽는다
    base: dict[tuple, tuple] = {}
    upto = {k: 0 for k in pool}
    valid: dict[tuple, list[dict]] = {k: [] for k in pool}
    todo = set(pool)
    t_base = t_match = 0.0
    rounds = 0
    pairs: list[dict] = []
    unfilled: list[dict] = []
    while True:
        rounds += 1
        t0 = time.perf_counter()
        grow, fetch = {}, set()
        for k in todo:
            grow[k] = next_batch(pool[k], upto[k], TOP_K * (1 if rounds == 1 else 2), order)
            fetch |= {(c["shopId"],) + c["sku"] for c in pool[k][upto[k]:grow[k]]}
        base.update(_prdt_base(brand, sorted(fetch - set(base))))
        for k, end in grow.items():
            for c in pool[k][upto[k]:end]:
                e = base.get((c["shopId"],) + c["sku"])
                rt = shops[c["shopId"]]["rt"]
                if not e or not e[0] or e[0] <= FIRST_DELV_AFTER:
                    excluded["nobase"] += 1
                    continue
                f_rnds, l_rnds, l_sale, delv, mstor, mdelv, sqty, rqty = e
                if not ((rt["fDays"] == 0 or _days_since(f_rnds, now) > rt["fDays"])
                        and (rt["lDays"] == 0 or _days_since(l_rnds, now) > rt["lDays"])):
                    excluded["days"] += 1
                    continue
                net = int(sqty) - int(rqty)
                valid[k].append({**c, "srate": round((int(delv) + int(mstor) - int(mdelv)) / net) if net else 0,
                                 "lSaleDt": l_sale, "fRndsDt": f_rnds})
            upto[k] = end
        t_base += time.perf_counter() - t0
        t0 = time.perf_counter()
        pairs, unfilled = match(recv, valid, caps, recv_caps, order)
        t_match += time.perf_counter() - t0
        # 못 채운 받는 매장이 있는 (상품, 그룹)에 아직 안 읽은 후보가 남았으면 더 읽어 다시 맞춘다
        todo = {((u["prdtCd"], u["colorCd"], u["sizeCd"]), u["grp"]) for u in unfilled if u["reason"] == "rules"}
        todo = {k for k in todo if k in pool and upto[k] < len(pool[k])}
        if not todo or rounds >= MAX_ROUNDS:
            break
    timing["prdtBase"] = round(t_base, 2)
    timing["match"] = round(t_match, 2)
    unfilled_by = {k: 0 for k in REASONS}
    for u in unfilled:
        unfilled_by[u["reason"]] += 1

    names = {sid: sh["shopNm"] for sid, sh in shops.items()}
    teams = sc.team_names()
    rows = []
    for i, m in enumerate(pairs, 1):
        r, c = m["receiver"], m["sender"]
        st = styles.get(r["prdtCd"], {})
        why = "자동RT 취소" if r["failCnt"] else ("완불 대기" if r["stock"] < 0 else "판매 후 품절")
        rows.append({
            "no": i, "prdtCd": r["prdtCd"], "styleNm": st.get("styleNm"), "colorCd": r["colorCd"], "sizeCd": r["sizeCd"], "qty": m["qty"],
            "fromShopId": c["shopId"], "fromShopNm": names.get(c["shopId"]), "fromTeam": teams.get(shops[c["shopId"]]["team"]),
            "fromStock": c["stock"], "fromSendable": c["sendable"], "fromSales": c["sales"], "fromLastSale": sc.ymd_label(c["lSaleDt"]),
            "toShopId": r["shopId"], "toShopNm": names.get(r["shopId"]), "toTeam": teams.get(shops[r["shopId"]]["team"]),
            "toStock": r["stock"], "toSales": r["sales"], "toFailCnt": r["failCnt"], "toIncoming": r["incoming"], "why": why})
    unfilled_rows = [{"shopId": u["shopId"], "shopNm": names.get(u["shopId"]), "team": teams.get(shops[u["shopId"]]["team"]),
                      "prdtCd": u["prdtCd"], "styleNm": styles.get(u["prdtCd"], {}).get("styleNm"), "colorCd": u["colorCd"],
                      "sizeCd": u["sizeCd"], "stock": u["stock"], "sales": u["sales"], "failCnt": u["failCnt"], "left": u["left"],
                      "reason": u["reason"], "reasonNm": REASONS[u["reason"]]} for u in unfilled]
    unfilled_rows.sort(key=lambda u: (-u["failCnt"], -u["sales"], u["shopId"], u["prdtCd"]))

    by_from: dict[str, int] = {}
    by_to: dict[str, int] = {}
    for r in rows:
        by_from[r["fromShopId"]] = by_from.get(r["fromShopId"], 0) + r["qty"]
        by_to[r["toShopId"]] = by_to.get(r["toShopId"], 0) + r["qty"]

    def top(d):
        return [{"shopId": k, "shopNm": names.get(k), "qty": v} for k, v in sorted(d.items(), key=lambda x: (-x[1], x[0]))[:15]]

    filled_keys = {(m["receiver"]["shopId"], m["receiver"]["prdtCd"], m["receiver"]["colorCd"], m["receiver"]["sizeCd"]) for m in pairs}
    fail_pairs = [r for r in recv if r["failCnt"]]
    timing["total"] = round(time.perf_counter() - started, 2)
    return {
        "brand": brand, "brandNm": sc.BRAND_CODES[brand], "from": sc.ymd_label(f), "to": sc.ymd_label(t),
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "per": per, "limits": limits, "order": order, "orderNm": ORDERS[order],
        "senderMax": sender_max,
        "cond": {"planYy": yy, "seasons": ss, "teams": tm, "prdt": pp},
        "summary": {
            "receivers": len(recv), "needQty": sum(r["need"] for r in recv), "filledReceivers": len(filled_keys),
            "recQty": sum(r["qty"] for r in rows), "recRows": len(rows), "senders": len(by_from), "receivingShops": len(by_to),
            "failRequests": len(fail_pairs),
            "failFilled": sum(1 for r in fail_pairs if (r["shopId"], r["prdtCd"], r["colorCd"], r["sizeCd"]) in filled_keys),
            "unfilled": len(unfilled), "unfilledBy": unfilled_by, "skipped": skipped, "senderExcluded": excluded,
            "checked": len(base), "styles": n_styles, "rounds": rounds,
        },
        "reasonNames": REASONS, "ruleNames": RULES, "rows": rows, "unfilled": unfilled_rows,
        "topSenders": top(by_from), "topReceivers": top(by_to), "timing": timing,
    }


# ---------------------------------------------------------------- 자동 RT 현황
RSLT_NM = {"C6860": "요청중", "C6861": "이동중", "C6868": "최종거부", "C6869": "취소", "C686Z": "완료"}


def auto_rt_stats(brand: str | None = None, frm: str | None = None, to: str | None = None, allowed: list[str] | None = None) -> dict:
    """자동 RT 요청 결과 (기간 · 브랜드): 결과별 건수, 취소 사유, 일별, 취소가 많은 매장 · 상품"""
    b = sc.brand_code(brand, allowed)
    f, t = sc.period(frm, to, DEFAULT_DAYS)

    def load():
        rows = db.query("""SELECT SUBSTR(A.REQ_DAY, 1, 8), A.STOR_REQ_SHOP_ID, A.PRDT_CD, NVL(A.RSLT_CD, '-'), NVL(TRIM(A.RMK), '-'), COUNT(*)
                             FROM T_AUTO_RT A
                            WHERE A.REQ_DAY BETWEEN :f || '000000' AND :t || '999999' AND A.COMPY_CD = :c AND A.DEL_DAY IS NULL
                              AND A.PRDT_CD IN (SELECT PRDT_CD FROM T_STYLE_PLAN WHERE COMPY_CD = :c AND PARENT_BRD_CD = :b)
                            GROUP BY SUBSTR(A.REQ_DAY, 1, 8), A.STOR_REQ_SHOP_ID, A.PRDT_CD, NVL(A.RSLT_CD, '-'), NVL(TRIM(A.RMK), '-')""",
                        {"f": f, "t": t, "c": sc.COMPY_CD, "b": b})[1]
        by_rslt: dict[str, int] = {}
        by_day: dict[str, dict] = {}
        fail_shop: dict[str, int] = {}
        fail_prdt: dict[str, int] = {}
        total = fail = 0
        for day, sid, p, rslt, rmk, n in rows:
            total += n
            by_rslt[rslt] = by_rslt.get(rslt, 0) + n
            d = by_day.setdefault(day, {"day": sc.ymd_label(day), "total": 0, "done": 0, "fail": 0})
            d["total"] += n
            if rslt == "C686Z":
                d["done"] += n
            if rmk == FAIL_RMK and rslt == "C6869":
                fail += n
                d["fail"] += n
                fail_shop[sid] = fail_shop.get(sid, 0) + n
                fail_prdt[p] = fail_prdt.get(p, 0) + n
        names = {sid: sh["shopNm"] for sid, sh in sc.shops().items()}
        styles = sc.style_info(list(fail_prdt))
        return {
            "brand": b, "brandNm": sc.BRAND_CODES[b], "from": sc.ymd_label(f), "to": sc.ymd_label(t), "total": total, "noShopCancel": fail,
            "noShopRate": round(fail * 100 / total, 1) if total else None,
            "results": [{"code": k, "name": RSLT_NM.get(k, k), "count": v} for k, v in sorted(by_rslt.items(), key=lambda x: -x[1])],
            "days": [by_day[k] for k in sorted(by_day)],
            "failShops": [{"shopId": k, "shopNm": names.get(k), "count": v} for k, v in sorted(fail_shop.items(), key=lambda x: -x[1])[:10]],
            "failProducts": [{"prdtCd": k, "styleNm": styles.get(k, {}).get("styleNm"), "count": v}
                             for k, v in sorted(fail_prdt.items(), key=lambda x: -x[1])[:10]],
        }
    return sc.cached(("rtstats", b, f, t), sc.CACHE_TTL, load)


# ---------------------------------------------------------------- 엑셀
def cond_text(d: dict) -> str:
    c = d["cond"]
    seasons = sc.code_names("C007")
    teams = sc.team_names()
    parts = [f"브랜드 {d['brandNm']}", f"판매 기간 {d['from']} ~ {d['to']}"]
    if c["planYy"]:
        parts.append("기획년도 " + ", ".join(c["planYy"]))
    if c["seasons"]:
        parts.append("시즌 " + ", ".join(seasons.get(x, x) for x in c["seasons"]))
    if c["teams"]:
        parts.append("받는 매장 팀 " + ", ".join(teams.get(x, x) for x in c["teams"]))
    if c["prdt"]:
        parts.append(f"품번 {c['prdt']}…")
    parts.append(f"매장당 {d['per']}장 · {d['orderNm']}")
    if d.get("senderMax"):
        parts.append(f"보내는 매장당 최대 {d['senderMax']}장")
    parts.append("자동 RT 하루 한도 적용" if d["limits"] else "자동 RT 하루 한도 미적용")
    return " · ".join(parts)


RT_COLS = [("no", "번호", 6), ("prdtCd", "품번", 14), ("styleNm", "스타일명", 18), ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7),
           ("qty", "추천 수량", 8), ("fromShopId", "보내는 매장", 10), ("fromShopNm", "보내는 매장명", 18), ("fromTeam", "보내는 팀", 10),
           ("fromStock", "보내는 재고", 9), ("fromSendable", "보낼 수 있는 수량", 10), ("fromSales", "보내는 매장 기간 판매", 10),
           ("fromLastSale", "보내는 매장 최종판매일", 12), ("toShopId", "받는 매장", 10), ("toShopNm", "받는 매장명", 18), ("toTeam", "받는 팀", 10),
           ("toStock", "받는 재고", 8), ("toSales", "받는 매장 기간 판매", 10), ("toFailCnt", "자동RT 취소 건수", 10), ("why", "사유", 12)]
UNFILLED_COLS = [("shopId", "매장", 10), ("shopNm", "매장명", 18), ("team", "팀", 10), ("prdtCd", "품번", 14), ("styleNm", "스타일명", 18),
                 ("colorCd", "칼라", 6), ("sizeCd", "사이즈", 7), ("stock", "재고", 7), ("sales", "기간 판매", 8), ("failCnt", "자동RT 취소", 9),
                 ("left", "못 채운 수량", 9), ("reasonNm", "사유", 30)]


def export_xlsx(d: dict) -> bytes:
    s = d["summary"]
    notes = [f"매장 간 RT 추천 ({d['asOf']} 기준, 조회 · 추천만 — ERP 에 등록되지 않음)", cond_text(d),
             f"받을 상품 {s['receivers']:,}건 · 추천 {s['recRows']:,}건 {s['recQty']:,}장 · 보내는 매장 {s['senders']:,}곳 · 못 채움 {s['unfilled']:,}건"]
    return sc.xlsx([("추천", notes, RT_COLS, d["rows"]), ("못 채운 수요", notes, UNFILLED_COLS, d["unfilled"])])
