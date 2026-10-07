"""재고 재배치 추천 > ERP 등록 · 삭제 (관리자만).

- 매장 간 RT → 본사지시 RT 지시(T_INDC_RT)를 넣고 로그인한 사번으로 바로 확정한다 — ERP 본사지시 확정과 같은 데이터:
  지시 CNFM_YN 'Y' · CNFM__DT · CNFM_USERID · 요청 연결(SHOP_REQ_MAKE_DT · SEQ), 매장 이동요청 T_SHOP_REQ(본사지시 C6811 · 미처리 C2954,
  MAKE_DT = 지시일, INS · PRCS 사번 = 확정자). 매장은 그 요청을 수락 · 거부한다. ERP 등록(indcRtNew)처럼 1장에 1행, 지시번호 = 지시일 + 5자리 순번.
- 지시 취소는 ERP(SP_SHOP_INDC_UPDATE 취소)와 같이 매장이 아직 처리하지 않은 요청만 RESN '본사지시취소' · DEL_DAY 로 지운다.
- 창고 → 매장 배분 → 출고의뢰(T_DELV_ASK)를 판매분 자동보충(SP_AUTO_DVID)과 같은 값으로 넣는다 (ASK_CLSBY C0633, CNFM_YN 'N').
  의뢰 확정 · 출고지시는 ERP 에서 한다.
- 이 화면에서 넣은 행은 ATTR1 = WEB_MARK 로 표시하고, 그 표시가 있고 아직 확정되지 않은 행만 삭제한다 (ERP 화면에서 넣은 행은 건드리지 않음).
- 등록할 행 · 수량은 화면이 보낸 값이 아니라 서버의 추천 결과(같은 조건 캐시)에서 꺼내고, 넣기 직전에 지금 재고로 다시 확인한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import oracledb

from . import audit, db
from . import stock_ctl as sc

MARK = sc.WEB_MARK
MAX_KEYS = 3000            # 한 번에 등록할 수 있는 추천 행
MAX_PIECES = 5000          # 본사지시 RT 는 1장에 1행
LIST_DAYS = 31
RT_STATUS = {"N": "미확정", "C2954": "확정 · 매장 미처리", "C2951": "매장 수락", "C2952": "매장 거부", "C2953": "기처리", "C2959": "요청취소",
             "DEL": "지시 취소"}


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _ymd(v: str | None, label: str, default: str) -> str:
    s = (v or default).replace("-", "")
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        sc.bad(f"{label}가 올바르지 않습니다.")
    return s


def _period(frm: str | None, to: str | None) -> tuple[str, str]:
    t = _ymd(to, "끝 날짜", (date.today() + timedelta(days=7)).strftime("%Y%m%d"))
    f = _ymd(frm, "시작 날짜", (date.today() - timedelta(days=7)).strftime("%Y%m%d"))
    if f > t:
        sc.bad("시작 날짜가 끝 날짜보다 늦습니다.")
    if (datetime.strptime(t, "%Y%m%d") - datetime.strptime(f, "%Y%m%d")).days >= LIST_DAYS + 8:
        sc.bad(f"조회 기간이 너무 깁니다 (최대 {LIST_DAYS + 7}일).")
    return f, t


def _keys(raw, n: int, label: str) -> list[tuple]:
    if not isinstance(raw, list) or not raw:
        sc.bad(f"{label}을 하나 이상 고르세요.")
    if len(raw) > MAX_KEYS:
        sc.bad(f"한 번에 {MAX_KEYS:,}건까지 등록할 수 있습니다.")
    out = []
    for k in raw:
        if not isinstance(k, (list, tuple)) or len(k) != n or not all(isinstance(x, str) and 0 < len(x) <= 20 for x in k):
            sc.bad(f"{label} 값이 올바르지 않습니다.")
        out.append(tuple(k))
    return list(dict.fromkeys(out))


# ================================================================ 매장 간 RT → 본사지시 RT 지시
def _sender_live(keys: set[tuple], td: str, brand: str) -> tuple[dict[tuple, int], dict[tuple, int]]:
    """보내는 매장 × 상품의 지금 보낼 수 있는 수량 = 재고 − 이동중 − 자동 RT 요청중 − 미처리 지시 · 요청 − 최소보유"""
    from . import stock_rt

    if not keys:
        return {}, {}
    shops = sc.shops()
    pcs = sorted({(k[1], k[2]) for k in keys})
    stock = {tuple(r[:4]): int(r[4]) for r in stock_rt._stock(pcs, td[:6])}
    res = stock_rt._reserved(brand, td)
    out = {}
    for k in keys:
        rt = (shops.get(k[0]) or {}).get("rt") or {}
        out[k] = (stock.get(k, 0) - res["moving"].get(k, 0) - res["pending"].get(k, 0) - res["instrOut"].get(k, 0)
                  - max(rt.get("minRetain", 0), 0))
    return out, res["instrIn"]


def rt_preview(args: dict, keys_raw, allowed: list[str] | None, source: str = "rt") -> dict:
    return _rt_plan(args, keys_raw, allowed, source)


def _rt_plan(args: dict, keys_raw, allowed: list[str] | None, source: str = "rt") -> dict:
    """source: rt = 매장 간 RT 추천(args = RT 조건), short = 창고 부족 채우기(args = 창고 배분 조건)"""
    from . import stock_rt

    keys = _keys(keys_raw, 5, "RT 추천 행")          # (품번, 칼라, 사이즈, 보내는 매장, 받는 매장)
    d = stock_rt.recommend(**args, allowed=allowed) if source == "rt" else stock_rt.fill_shortage(args, allowed)
    brand = d["brand"]
    by_key = {(r["prdtCd"], r["colorCd"], r["sizeCd"], r["fromShopId"], r["toShopId"]): r for r in d["rows"]}
    td = sc.today()
    picked = [by_key[k] for k in keys if k in by_key]
    live, incoming = _sender_live({(r["fromShopId"], r["prdtCd"], r["colorCd"], r["sizeCd"]) for r in picked}, td, brand)
    ok, skipped = [], []
    for k in keys:
        if k not in by_key:
            skipped.append({"key": list(k), "reason": "추천 결과에 없음 (다시 계산하세요)"})
    left = dict(live)
    for r in sorted(picked, key=lambda r: r["no"]):
        sk = (r["fromShopId"], r["prdtCd"], r["colorCd"], r["sizeCd"])
        rk = (r["toShopId"], r["prdtCd"], r["colorCd"], r["sizeCd"])
        key = [r["prdtCd"], r["colorCd"], r["sizeCd"], r["fromShopId"], r["toShopId"]]
        if incoming.get(rk, 0) > r.get("toIncoming", 0):          # 추천 계산 뒤에 새로 지시 · 요청이 들어감
            skipped.append({"key": key, "reason": f"추천 뒤 받는 매장에 지시 · 요청이 새로 들어감 ({incoming[rk]}장)"})
        elif left.get(sk, 0) < r["qty"]:
            skipped.append({"key": key, "reason": f"보내는 매장 재고 부족 (지금 보낼 수 있는 수량 {max(left.get(sk, 0), 0)})"})
        else:
            left[sk] -= r["qty"]
            ok.append(r)
    pieces = sum(r["qty"] for r in ok)
    if pieces > MAX_PIECES:
        sc.bad(f"한 번에 {MAX_PIECES:,}장까지 지시할 수 있습니다 (선택 {pieces:,}장).")
    return {"brand": brand, "brandNm": d["brandNm"], "asOf": d["asOf"], "rows": ok, "skipped": skipped,
            "count": len(ok), "qty": pieces, "senders": len({r["fromShopId"] for r in ok}), "receivers": len({r["toShopId"] for r in ok})}


def rt_register(me: dict, args: dict, keys_raw, indc_dt: str | None, allowed: list[str] | None, commit: bool = True,
                source: str = "rt") -> dict:
    td = sc.today()
    dt = _ymd(indc_dt, "지시일자", td)
    if dt < td or dt > (date.today() + timedelta(days=7)).strftime("%Y%m%d"):
        sc.bad("지시일자는 오늘부터 7일 안에서 고르세요.")
    plan = _rt_plan(args, keys_raw, allowed, source)
    if not plan["rows"]:
        sc.bad("지시할 수 있는 행이 없습니다. " + "; ".join(sorted({s["reason"] for s in plan["skipped"]}))[:300])
    now = _now14()
    ids: list[str] = []
    for attempt in range(3):                       # 지시번호는 ERP 와 같이 MAX + 1 → 동시에 넣으면 PK 충돌 시 다시
        conn = db.get_pool().acquire()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT NVL(MAX(INDC_SEQ), 0), MAX(INDC_ID) FROM T_INDC_RT WHERE INDC_ID LIKE :d || '%'", {"d": dt})
                mseq, mid = cur.fetchone()
                seq = max(int(mseq or 0), int(mid[8:]) if mid and mid[8:].isdigit() else 0)
                pieces = sum(r["qty"] for r in plan["rows"])
                # 매장 이동요청 순번 (SP_AUTO_RT_SAVE · ERP 확정과 같은 시퀀스)
                cur.execute("SELECT S_SHOP_REQ_SEQ.NEXTVAL FROM DUAL CONNECT BY LEVEL <= :n", {"n": pieces})
                req_seqs = [int(x[0]) for x in cur.fetchall()]
                if len(req_seqs) != pieces:
                    raise RuntimeError("이동요청 순번을 받지 못했습니다.")
                rows, ids = [], []
                for r in plan["rows"]:
                    for _ in range(r["qty"]):
                        seq += 1
                        iid = f"{dt}{seq:05d}"
                        rows.append({"id": iid, "seq": seq, "dl": r["fromShopId"], "st": r["toShopId"], "p": r["prdtCd"], "c": r["colorCd"],
                                     "s": r["sizeCd"], "dt": dt, "b": plan["brand"], "now": now, "u": me["id"], "m": MARK,
                                     "cp": sc.COMPY_CD, "td": td, "rs": req_seqs[len(ids)]})
                        ids.append(iid)
                # 1) 지시 (확정 상태로 — ERP 는 등록 뒤 확정에서 UPDATE 하지만 최종 값은 같다)
                cur.executemany("""INSERT INTO T_INDC_RT (INDC_ID, INDC_SEQ, DELV_MOVE_SHOP_ID, STOR_MOVE_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD,
                                                          INDC_QTY, INDC_DT, CNFM_YN, CNFM__DT, CNFM_USERID, INDC_CLSBY, SHOP_REQ_MAKE_DT, SHOP_REQ_SEQ,
                                                          WH_CD, COMPY_CD, BRD_CD, INS_DAY, INS_USERID, UPT_DAY, UPT_USERID, ATTR1)
                                   VALUES (:id, :seq, :dl, :st, :p, :c, :s, 1, :dt, 'Y', :td, :u, 'C6811', :dt, :rs,
                                           'IN', :cp, :b, :now, :u, :now, :u, :m)""", rows)
                # 2) 매장 이동요청 (본사지시 · 미처리) — 매장이 수락 · 거부한다
                cur.executemany("""INSERT INTO T_SHOP_REQ (MAKE_DT, SEQ, DELV_REQ_SHOP_ID, STOR_REQ_SHOP_ID, INS_DAY, INS_USERID, BRD_CD,
                                                           PRDT_CD, COLOR_CD, SIZE_CD, REQ_QTY, PRCS_CLSBY, CUST_SEND_YN, COMPY_CD, MOVE_TYPE,
                                                           INDC_ID, INDC_DT, INDC_QTY, ASIGN_SEQN, PRCS_DAY, PRCS_USERID, INDC_CNFM_YN)
                                   VALUES (:dt, :rs, :dl, :st, :now, :u, :b, :p, :c, :s, 1, 'C2954', 'N', :cp, 'C6811',
                                           :id, :dt, 1, 0, :now, :u, 'N')""",
                                [{k: x[k] for k in ("dt", "rs", "dl", "st", "now", "u", "b", "p", "c", "s", "cp", "id")} for x in rows])
            if commit:
                conn.commit()
            else:
                conn.rollback()
            break
        except oracledb.IntegrityError:
            conn.rollback()
            if attempt == 2:
                sc.bad("지시번호가 겹쳤습니다. 잠시 후 다시 시도하세요.", 409)
        except Exception:
            conn.rollback()
            raise
        finally:
            db.get_pool().release(conn)
    if commit:
        sc.drop_cache("rt")
        audit.record(me, "STOCK_RT_INDC", f"{plan['brandNm']} {dt}{' (창고 부족 채우기)' if source == 'short' else ''}",
                     summary=f"본사지시 RT 지시 · 확정 {len(ids):,}장 ({plan['count']:,}건 · 보내는 매장 {plan['senders']} · 받는 매장 {plan['receivers']}) "
                             f"지시번호 {ids[0]} ~ {ids[-1]} · 제외 {len(plan['skipped'])}건",
                     after={"indcDt": dt, "ids": [ids[0], ids[-1]], "rows": [[r["prdtCd"], r["colorCd"], r["sizeCd"], r["fromShopId"],
                                                                               r["toShopId"], r["qty"]] for r in plan["rows"]][:2000]})
    return {"ok": True, "committed": commit, "indcDt": dt, "count": plan["count"], "qty": len(ids), "firstId": ids[0], "lastId": ids[-1],
            "skipped": plan["skipped"], "senders": plan["senders"], "receivers": plan["receivers"]}


def rt_list(brand: str | None, frm: str | None, to: str | None, allowed: list[str] | None, mine_only: bool = True) -> dict:
    b = sc.brand_code(brand, allowed)
    f, t = _period(frm, to)
    shops = sc.shops()
    rows = []
    for (iid, dl, st, p, c, s, q, dt, cnfm, ins_day, ins_user, prcs, req_dt, req_seq, mark, rdel, rmove, resn, cnfm_user) in db.query(
            f"""SELECT /*+ INDEX(I T_INDC_RT_IDX01) */ I.INDC_ID, I.DELV_MOVE_SHOP_ID, I.STOR_MOVE_SHOP_ID, I.PRDT_CD, I.COLOR_CD, I.SIZE_CD, I.INDC_QTY, I.INDC_DT,
                       NVL(I.CNFM_YN, 'N'), I.INS_DAY, I.INS_USERID, R.PRCS_CLSBY, I.SHOP_REQ_MAKE_DT, I.SHOP_REQ_SEQ, I.ATTR1,
                       R.DEL_DAY, R.SHOP_MOVE_SEQ, R.RESN, I.CNFM_USERID
                  FROM T_INDC_RT I, T_SHOP_REQ R
                 WHERE I.INDC_DT BETWEEN :f AND :t AND I.BRD_CD = :b AND I.DEL_DAY IS NULL {"AND I.ATTR1 = :m" if mine_only else ""}
                   AND R.MAKE_DT(+) = I.SHOP_REQ_MAKE_DT AND R.SEQ(+) = I.SHOP_REQ_SEQ
                 ORDER BY I.INDC_ID""", {"f": f, "t": t, "b": b, **({"m": MARK} if mine_only else {})})[1]:
        status = "N" if cnfm == "N" else ("DEL" if rdel else (prcs or "C2954"))
        rows.append({"id": iid, "indcDt": sc.ymd_label(dt), "prdtCd": p, "colorCd": c, "sizeCd": s, "qty": int(q or 0),
                     "fromShopId": dl, "fromShopNm": (shops.get(dl) or {}).get("shopNm"), "toShopId": st,
                     "toShopNm": (shops.get(st) or {}).get("shopNm"), "status": status, "statusNm": RT_STATUS.get(status, status),
                     "insDay": ins_day, "insUser": ins_user, "cnfmUser": cnfm_user, "resn": (resn or "").strip() or None, "web": mark == MARK,
                     # 미확정 지시, 또는 확정됐지만 매장이 아직 처리하지 않은 요청 (ERP 본사지시 취소와 같은 조건)
                     "deletable": mark == MARK and (cnfm == "N" and not req_seq or status == "C2954" and not rmove)})
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + r["qty"]
    return {"brand": b, "brandNm": sc.BRAND_CODES[b], "from": sc.ymd_label(f), "to": sc.ymd_label(t), "rows": rows[:5000],
            "total": len(rows), "byStatus": [{"code": k, "name": RT_STATUS.get(k, k), "qty": v} for k, v in sorted(by.items())],
            "deletable": sum(1 for r in rows if r["deletable"])}


def rt_delete(me: dict, brand: str | None, ids_raw, allowed: list[str] | None) -> dict:
    """이 화면에서 넣은 지시 취소: 미확정 지시는 삭제, 확정됐지만 매장이 아직 처리하지 않은(C2954) 요청은
    ERP 본사지시 취소(SP_SHOP_INDC_UPDATE)처럼 RESN '본사지시취소' · DEL_DAY · DEL_USERID 로 지운다. 매장이 처리한 건 건드리지 않는다."""
    b = sc.brand_code(brand, allowed)
    if not isinstance(ids_raw, list) or not ids_raw or len(ids_raw) > MAX_PIECES:
        sc.bad("취소할 지시를 고르세요.")
    ids = [x for x in dict.fromkeys(ids_raw) if isinstance(x, str) and x.isdigit() and len(x) == 13]
    if len(ids) != len(set(ids_raw)):
        sc.bad("지시번호가 올바르지 않습니다.")
    now = _now14()
    deleted, canceled, before = 0, 0, []
    with db.get_pool().acquire() as conn:
        try:
            with conn.cursor() as cur:
                for part in sc.chunks(ids, 500):
                    ph, bb = sc.binds(part, "i")
                    base = {**bb, "b": b, "m": MARK}
                    # 1) 미확정 지시 → 삭제
                    cond = f"""INDC_ID IN ({ph}) AND BRD_CD = :b AND ATTR1 = :m AND NVL(CNFM_YN, 'N') = 'N'
                               AND SHOP_REQ_SEQ IS NULL AND DEL_DAY IS NULL"""
                    cur.execute(f"""SELECT INDC_ID, DELV_MOVE_SHOP_ID, STOR_MOVE_SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, INDC_QTY, INDC_DT, INS_USERID
                                      FROM T_INDC_RT WHERE {cond} FOR UPDATE NOWAIT""", base)
                    before += [["delete"] + list(r) for r in cur.fetchall()]
                    cur.execute(f"DELETE FROM T_INDC_RT WHERE {cond}", base)
                    deleted += cur.rowcount
                    # 2) 확정 · 매장 미처리 요청 → ERP 본사지시 취소와 같은 소프트 삭제
                    req_cond = f"""(R.MAKE_DT, R.SEQ) IN (SELECT I.SHOP_REQ_MAKE_DT, I.SHOP_REQ_SEQ FROM T_INDC_RT I
                                                           WHERE I.INDC_ID IN ({ph}) AND I.BRD_CD = :b AND I.ATTR1 = :m AND I.CNFM_YN = 'Y')
                                   AND R.MOVE_TYPE = 'C6811' AND R.PRCS_CLSBY = 'C2954' AND R.DEL_DAY IS NULL AND R.SHOP_MOVE_SEQ IS NULL"""
                    cur.execute(f"""SELECT R.INDC_ID, R.MAKE_DT, R.SEQ, R.DELV_REQ_SHOP_ID, R.STOR_REQ_SHOP_ID, R.PRDT_CD, R.COLOR_CD, R.SIZE_CD
                                      FROM T_SHOP_REQ R WHERE {req_cond} FOR UPDATE NOWAIT""", base)
                    before += [["cancel"] + list(r) for r in cur.fetchall()]
                    cur.execute(f"""UPDATE T_SHOP_REQ R
                                       SET UPT_DAY = :now, UPT_USERID = :u, RESN = '본사지시취소 ' || RESN, DEL_DAY = :now, DEL_USERID = :u
                                     WHERE {req_cond}""", {**base, "now": now, "u": me["id"]})
                    canceled += cur.rowcount
            conn.commit()
        except oracledb.DatabaseError as ex:
            conn.rollback()
            if "ORA-00054" in str(ex):
                sc.bad("매장에서 처리 중인 지시가 있습니다. 잠시 후 다시 시도하세요.", 409)
            raise
    n = deleted + canceled
    if n:
        sc.drop_cache("rt")
        audit.record(me, "STOCK_RT_DEL", f"{sc.BRAND_CODES[b]}",
                     summary=f"본사지시 RT 취소 {n:,}건 (매장 미처리 요청 취소 {canceled:,} · 미확정 지시 삭제 {deleted:,}, 요청 {len(ids):,}건)",
                     before={"rows": before[:3000]})
    return {"ok": True, "deleted": n, "canceled": canceled, "removed": deleted, "requested": len(ids), "notDeleted": len(ids) - n}


# ================================================================ 창고 → 매장 배분 → 출고의뢰
def alloc_seqns(brand: str | None, ask_dt: str | None, allowed: list[str] | None) -> dict:
    """의뢰일자의 차수 사용 현황과 다음 차수 제안 (제안은 이 브랜드 마지막 차수 + 1, 다른 브랜드가 쓴 차수는 건너뜀).
    SP_AUTO_DVID 와 같이 확정된 차수에는 넣을 수 없다"""
    b = sc.brand_code(brand, allowed)
    dt = _ymd(ask_dt, "의뢰일자", sc.today())
    used = [{"seqn": int(n), "brand": pb, "brandNm": sc.BRAND_CODES.get(pb, pb), "clsby": cl, "rows": int(cnt), "confirmed": cf == "Y",
             "web": int(web) > 0}
            for n, pb, cl, cnt, cf, web in db.query("""SELECT ASK_SEQN, PARENT_BRD_CD, MIN(ASK_CLSBY), COUNT(*), MAX(NVL(CNFM_YN, 'N')),
                                                             SUM(DECODE(ATTR1, :m, 1, 0))
                                                        FROM T_DELV_ASK WHERE ASK_DT = :d GROUP BY ASK_SEQN, PARENT_BRD_CD ORDER BY ASK_SEQN""",
                                                     {"d": dt, "m": MARK})[1]]
    taken = {u["seqn"] for u in used}
    mine = [u["seqn"] for u in used if u["brand"] == b]
    nxt = (max(mine) if mine else 0) + 1
    while nxt in taken:
        nxt += 1
    return {"brand": b, "askDt": sc.ymd_label(dt), "used": used, "next": nxt,
            "codes": sc.code_names("C063")}


def _alloc_plan(args: dict, keys_raw, allowed: list[str] | None) -> dict:
    from . import wh_alloc

    keys = _keys(keys_raw, 4, "배분 행")          # (매장, 품번, 칼라, 사이즈)
    d = wh_alloc.recommend(**args, allowed=allowed)
    brand, td = d["brand"], sc.today()
    by_key = {(r["shopId"], r["prdtCd"], r["colorCd"], r["sizeCd"]): r for r in d["rows"]}
    sku_info = {(s["prdtCd"], s["colorCd"], s["sizeCd"]): s for s in d["skus"]}
    picked = [by_key[k] for k in keys if k in by_key]
    skipped = [{"key": list(k), "reason": "배분 추천에 없음 (다시 계산하세요)"} for k in keys if k not in by_key]
    whq = wh_alloc._wh_avail(brand, d["wh"], sorted({r["prdtCd"] for r in picked}), td) if picked else {}
    asked = wh_alloc.web_asked(brand, td) if picked else {}
    left = {}
    for sku in {(r["prdtCd"], r["colorCd"], r["sizeCd"]) for r in picked}:
        w = whq.get(sku, {"wh": 0, "indc": 0, "ask": 0})
        left[sku] = w["wh"] - w["indc"] - w["ask"] - sku_info.get(sku, {}).get("minWh", 0)
    ok = []
    for r in sorted(picked, key=lambda r: (r["prdtCd"], r["colorCd"], r["sizeCd"], r["rank"])):
        sku = (r["prdtCd"], r["colorCd"], r["sizeCd"])
        key = [r["shopId"], *sku]
        if (r["shopId"],) + sku in asked:
            skipped.append({"key": key, "reason": f"이미 이 화면에서 의뢰함 (미확정 {asked[(r['shopId'],) + sku]}장)"})
        elif left[sku] < r["ask"]:
            skipped.append({"key": key, "reason": f"창고 가용 부족 (지금 배분 가능 {max(left[sku], 0)}장)"})
        else:
            left[sku] -= r["ask"]
            ok.append(r)
    return {"brand": brand, "brandNm": d["brandNm"], "wh": d["wh"], "grdGrp": d["grdGrp"], "asOf": d["asOf"], "rows": ok, "skipped": skipped,
            "count": len(ok), "qty": sum(r["ask"] for r in ok), "shops": len({r["shopId"] for r in ok})}


def alloc_preview(args: dict, keys_raw, allowed: list[str] | None) -> dict:
    return _alloc_plan(args, keys_raw, allowed)


def alloc_register(me: dict, args: dict, keys_raw, ask_dt: str | None, ask_seqn, delv_pre_dt: str | None, allowed: list[str] | None,
                   commit: bool = True) -> dict:
    td = sc.today()
    dt = _ymd(ask_dt, "의뢰일자", td)
    if dt < td or dt > (date.today() + timedelta(days=7)).strftime("%Y%m%d"):
        sc.bad("의뢰일자는 오늘부터 7일 안에서 고르세요.")
    pre = _ymd(delv_pre_dt, "출고예정일", dt)
    if pre < dt:
        sc.bad("출고예정일은 의뢰일자 이후여야 합니다.")
    try:
        seqn = int(ask_seqn)
    except (TypeError, ValueError):
        seqn = 0
    if not 1 <= seqn <= 9999:
        sc.bad("의뢰차수는 1~9999 입니다.")
    plan = _alloc_plan(args, keys_raw, allowed)
    if not plan["rows"]:
        sc.bad("의뢰할 수 있는 행이 없습니다. " + "; ".join(sorted({s["reason"] for s in plan["skipped"]}))[:300])
    brand = plan["brand"]
    now = _now14()
    with db.get_pool().acquire() as conn:
        try:
            with conn.cursor() as cur:
                # 차수 확인 (SP_AUTO_DVID 처럼 확정된 행이 있는 차수는 못 씀) — 같은 차수 동시 등록은 행 잠금으로 막는다
                cur.execute("""SELECT PARENT_BRD_CD, NVL(CNFM_YN, 'N'), SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD FROM T_DELV_ASK
                                WHERE ASK_DT = :d AND ASK_SEQN = :n FOR UPDATE""", {"d": dt, "n": seqn})
                cur_rows = cur.fetchall()
                if any(r[1] == "Y" for r in cur_rows):
                    sc.bad(f"{sc.ymd_label(dt)} {seqn}차는 이미 확정된 차수입니다. 다른 차수를 고르세요.")
                exist = {tuple(r[2:]) for r in cur_rows if r[0] == brand}
                rows = [r for r in plan["rows"] if (r["shopId"], r["prdtCd"], r["colorCd"], r["sizeCd"]) not in exist]
                dup = len(plan["rows"]) - len(rows)
                if not rows:
                    sc.bad("고른 행이 모두 이 차수에 이미 있습니다.")
                cur.execute("SELECT NVL(MAX(SEQ), 0) FROM T_DELV_ASK WHERE ASK_DT = :d AND ASK_SEQN = :n", {"d": dt, "n": seqn})
                seq = int(cur.fetchone()[0] or 0)
                binds = []
                for r in rows:
                    seq += 1
                    rmk = f"재고재배치 배분({'완불 ' + str(r['askFp']) if r['askFp'] else ''}{' · ' if r['askFp'] and r['askSale'] else ''}" \
                          f"{'판매 ' + str(r['askSale']) if r['askSale'] else ''})"
                    binds.append({"d": dt, "n": seqn, "seq": seq, "cp": sc.COMPY_CD, "pb": brand, "b": brand, "wh": plan["wh"], "sh": r["shopId"],
                                  "g": plan["grdGrp"], "p": r["prdtCd"], "c": r["colorCd"], "s": r["sizeCd"], "q": r["ask"], "pre": pre,
                                  "rmk": rmk, "u": me["id"], "now": now, "m": MARK})
                cur.executemany("""INSERT INTO T_DELV_ASK (ASK_DT, ASK_SEQN, SEQ, COMPY_CD, PARENT_BRD_CD, BRD_CD, WH_CD, SHOP_ID, GRD_GRP_ID,
                                                           PRDT_CD, COLOR_CD, SIZE_CD, RE_ORDER_YN, ASK_CLSBY, ASK_QTY, DELV_PRE_DT, CNFM_YN, RMK,
                                                           INS_USERID, INS_DAY, ATTR1)
                                   VALUES (:d, :n, :seq, :cp, :pb, :b, :wh, :sh, :g, :p, :c, :s, 'N', 'C0633', :q, :pre, 'N', :rmk, :u, :now, :m)""",
                                binds)
            if commit:
                conn.commit()
            else:
                conn.rollback()
        except BaseException:
            conn.rollback()
            raise
    qty = sum(r["ask"] for r in rows)
    if commit:
        sc.drop_cache("dvid")
        audit.record(me, "STOCK_ALLOC_ASK", f"{plan['brandNm']} {dt} {seqn}차",
                     summary=f"배분의뢰 {len(rows):,}건 · {qty:,}장 (매장 {len({r['shopId'] for r in rows})}곳, 창고 {plan['wh']}) · "
                             f"출고예정 {pre} · 제외 {len(plan['skipped']) + dup}건",
                     after={"askDt": dt, "askSeqn": seqn, "rows": [[r["shopId"], r["prdtCd"], r["colorCd"], r["sizeCd"], r["ask"]] for r in rows][:3000]})
    return {"ok": True, "committed": commit, "askDt": sc.ymd_label(dt), "askSeqn": seqn, "count": len(rows), "qty": qty,
            "shops": len({r["shopId"] for r in rows}),
            "skipped": plan["skipped"] + ([{"key": [], "reason": f"이 차수에 이미 있는 행 {dup}건"}] if dup else [])}


def alloc_list(brand: str | None, frm: str | None, to: str | None, allowed: list[str] | None) -> dict:
    b = sc.brand_code(brand, allowed)
    f, t = _period(frm, to)
    shops = sc.shops()
    rows = []
    for (ask_dt, seqn, seq, sid, p, c, s, q, wh, pre, cnfm, indc, rmk, ins_day, ins_user) in db.query(
            """SELECT ASK_DT, ASK_SEQN, SEQ, SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, ASK_QTY, WH_CD, DELV_PRE_DT, NVL(CNFM_YN, 'N'),
                      DELV_INDC_SEQ, RMK, INS_DAY, INS_USERID
                 FROM T_DELV_ASK
                WHERE ASK_DT BETWEEN :f AND :t AND PARENT_BRD_CD = :b AND ATTR1 = :m
                ORDER BY ASK_DT, ASK_SEQN, SEQ""", {"f": f, "t": t, "b": b, "m": MARK})[1]:
        rows.append({"askDt": sc.ymd_label(ask_dt), "askSeqn": int(seqn), "seq": int(seq), "shopId": sid, "shopNm": (shops.get(sid) or {}).get("shopNm"),
                     "prdtCd": p, "colorCd": c, "sizeCd": s, "qty": int(q or 0), "wh": wh, "delvPreDt": sc.ymd_label(pre),
                     "confirmed": cnfm == "Y", "statusNm": "확정" if cnfm == "Y" else "미확정", "rmk": rmk, "insDay": ins_day, "insUser": ins_user,
                     "deletable": cnfm != "Y" and indc is None})
    runs: dict[tuple, dict] = {}
    for r in rows:
        g = runs.setdefault((r["askDt"], r["askSeqn"]), {"askDt": r["askDt"], "askSeqn": r["askSeqn"], "rows": 0, "qty": 0, "confirmed": 0,
                                                         "deletable": 0, "insUser": r["insUser"], "insDay": r["insDay"]})
        g["rows"] += 1
        g["qty"] += r["qty"]
        g["confirmed"] += int(r["confirmed"])
        g["deletable"] += int(r["deletable"])
    return {"brand": b, "brandNm": sc.BRAND_CODES[b], "from": sc.ymd_label(f), "to": sc.ymd_label(t), "rows": rows[:5000],
            "total": len(rows), "runs": list(runs.values()), "deletable": sum(1 for r in rows if r["deletable"])}


def alloc_delete(me: dict, brand: str | None, keys_raw, allowed: list[str] | None) -> dict:
    b = sc.brand_code(brand, allowed)
    if not isinstance(keys_raw, list) or not keys_raw or len(keys_raw) > MAX_PIECES:
        sc.bad("삭제할 의뢰를 고르세요.")
    keys = []
    for k in keys_raw:          # (의뢰일자, 차수, 순번)
        try:
            keys.append((_ymd(str(k[0]), "의뢰일자", ""), int(k[1]), int(k[2])))
        except (TypeError, ValueError, IndexError):
            sc.bad("삭제할 의뢰 값이 올바르지 않습니다.")
    keys = list(dict.fromkeys(keys))
    deleted, before = 0, []
    runs: dict[tuple, list[int]] = {}
    for d, n, sq in keys:
        runs.setdefault((d, n), []).append(sq)
    with db.get_pool().acquire() as conn:
        try:
            with conn.cursor() as cur:
                for (d, n), seqs in runs.items():
                    for part in sc.chunks(seqs, 500):
                        ph, bb = sc.binds(part, "s")
                        bb.update({"d": d, "n": n, "b": b, "m": MARK})
                        cond = f"""ASK_DT = :d AND ASK_SEQN = :n AND SEQ IN ({ph}) AND PARENT_BRD_CD = :b AND ATTR1 = :m
                                   AND NVL(CNFM_YN, 'N') = 'N' AND DELV_INDC_SEQ IS NULL"""
                        cur.execute(f"SELECT ASK_DT, ASK_SEQN, SEQ, SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, ASK_QTY, INS_USERID FROM T_DELV_ASK "
                                    f"WHERE {cond} FOR UPDATE NOWAIT", bb)
                        before += [list(r) for r in cur.fetchall()]
                        cur.execute(f"DELETE FROM T_DELV_ASK WHERE {cond}", bb)
                        deleted += cur.rowcount
            conn.commit()
        except oracledb.DatabaseError as ex:
            conn.rollback()
            if "ORA-00054" in str(ex):
                sc.bad("다른 사용자가 처리 중인 의뢰가 있습니다. 잠시 후 다시 시도하세요.", 409)
            raise
    if deleted:
        sc.drop_cache("dvid")
        audit.record(me, "STOCK_ALLOC_DEL", sc.BRAND_CODES[b],
                     summary=f"배분의뢰 미확정 {deleted:,}건 삭제 (요청 {len(keys):,}건)", before={"rows": before[:3000]})
    return {"ok": True, "deleted": deleted, "requested": len(keys), "notDeleted": len(keys) - deleted}
