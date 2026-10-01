"""매장 정보: 브랜드 · 팀 · 담당 영업직원 · 운영상태 (매장 정보 팝업, AI 도구 search_shops 공용).

원천 (ERP 매장 담당 영업직원 조회와 같은 기준)
- T_SHOP_BRD(매장 × 브랜드, COMPY_CD = 'A01C01') + T_SHOP(매장명 · 팀 · 담당 영업직원 사번 · 운영상태 · 오픈/폐점일)
- 팀명 = T_COMN_CD(CD_KEY = T_SHOP.TEAM_CD), 영업직원명 = T_EMP.EMP_NM_KOR, 운영상태 = F_GET_NM_CLSBY(DSHOP_CLSBY)
매장 마스터는 2,800여 행이라 10분 캐시로 한 번에 읽어 파이썬에서 거른다.
브랜드 데이터 권한이 있는 사용자는 허용 브랜드 매장만 본다 (브랜드코드 S=쉬즈미스, T=리스트, A=시스티나).
"""
from __future__ import annotations

import threading
import time
from fastapi import HTTPException

from . import db

COMPY_CD = "A01C01"
BRAND_CODES = {"S": "쉬즈미스", "T": "리스트", "A": "시스티나"}  # T_SHOP_BRD.BRD_CD → 판매 현황 브랜드명
OPEN_STATUSES = {"정상", "가폐점"}
CACHE_TTL = 10 * 60

_SQL = """
SELECT T1.BRD_CD,
       (SELECT CD_NM FROM T_COMN_CD WHERE CD_KEY = T2.TEAM_CD AND LANG_CLSBY = 'ko') AS TEAM_NM,
       T2.SHOP_ID, T2.SHOP_NM, T2.BS_DEPT_USERID,
       (SELECT E.EMP_NM_KOR FROM T_EMP E WHERE E.EMP_ID = T2.BS_DEPT_USERID) AS BS_DEPT_USER_NM,
       F_GET_NM_CLSBY(T2.DSHOP_CLSBY, 'ko') AS SHOP_STATUS_NM,
       T2.OPEN_DT, T2.DSHOP_DT
  FROM T_SHOP_BRD T1, T_SHOP T2
 WHERE T1.SHOP_ID = T2.SHOP_ID AND T1.COMPY_CD = :compy
"""
_cache: tuple[float, list[dict]] | None = None
_lock = threading.Lock()


def _bad(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"message": msg, "code": "BAD_REQUEST" if status == 400 else "FORBIDDEN"})


def _d8(v) -> str | None:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and not s.startswith("9999") else None


def brand_name(code: str | None) -> str:
    return BRAND_CODES.get(code or "", code or "(미지정)")


def all_rows() -> list[dict]:
    """매장 × 브랜드 행 (10분 캐시)"""
    global _cache
    with _lock:
        if _cache and _cache[0] > time.time():
            return _cache[1]
    rows = [{
        "shopId": r[2], "shopNm": r[3], "brdCd": r[0], "brand": brand_name(r[0]), "teamNm": r[1],
        "repId": r[4], "repNm": r[5], "status": r[6], "openDt": _d8(r[7]), "closeDt": _d8(r[8]),
    } for r in db.query(_SQL + " ORDER BY T2.SHOP_ID, T1.BRD_CD", {"compy": COMPY_CD})[1]]
    with _lock:
        _cache = (time.time() + CACHE_TTL, rows)
    return rows


def _visible(rows: list[dict], allowed: list[str] | None) -> list[dict]:
    return rows if allowed is None else [r for r in rows if r["brand"] in allowed]


def shop_brands(shop_id: str) -> list[str]:
    return sorted({r["brand"] for r in all_rows() if r["shopId"] == shop_id})


def profile(shop_id: str, allowed: list[str] | None = None) -> dict:
    """매장 한 곳: 기본 정보 + 브랜드별 행. 브랜드 권한 밖의 매장이면 403."""
    shop_id = (shop_id or "").strip().upper()
    if not shop_id or len(shop_id) > 6:
        _bad("매장코드가 올바르지 않습니다.")
    rows = [r for r in all_rows() if r["shopId"] == shop_id]
    if allowed is not None and rows and not _visible(rows, allowed):
        _bad("이 매장의 브랜드 조회 권한이 없습니다.", 403)
    rows = _visible(rows, allowed)
    extra = db.query_dicts(
        "SELECT SHOP_ADDR1, SHOP_ADDR2, SHOP_TEL_NO1, SHOP_TEL_NO2, SHOP_TEL_NO3 FROM T_SHOP WHERE SHOP_ID = :id", {"id": shop_id})
    e = extra[0] if extra else {}
    tel = "-".join(x for x in (e.get("SHOP_TEL_NO1"), e.get("SHOP_TEL_NO2"), e.get("SHOP_TEL_NO3")) if x)
    first = rows[0] if rows else {}
    return {
        "shopId": shop_id, "shopNm": first.get("shopNm"), "status": first.get("status"), "teamNm": first.get("teamNm"),
        "repId": first.get("repId"), "repNm": first.get("repNm"), "openDt": first.get("openDt"), "closeDt": first.get("closeDt"),
        "brands": [{"brdCd": r["brdCd"], "brand": r["brand"]} for r in rows],
        "addr": " ".join(x for x in (e.get("SHOP_ADDR1"), e.get("SHOP_ADDR2")) if x) or None, "tel": tel or None,
        "found": bool(rows),
    }


def goals_by_month(shop_id: str, months: list[str], allowed: list[str] | None = None) -> dict[str, int]:
    """월별 목표금액 (T_SHOP_SELL_MGOAL, 삭제 안 된 행). 브랜드 권한이 있으면 허용 브랜드코드의 목표만."""
    if not months:
        return {}
    binds = {f"m{i}": m for i, m in enumerate(months)}
    sql = (f"SELECT MAKE_YYMM, PARENT_BRD_CD, SUM(GOAL_AMT) FROM T_SHOP_SELL_MGOAL WHERE SHOP_ID = :id AND DEL_DAY IS NULL "
           f"AND MAKE_YYMM IN ({', '.join(':' + k for k in binds)}) GROUP BY MAKE_YYMM, PARENT_BRD_CD")
    out: dict[str, int] = {}
    try:
        for ym, code, amt in db.query(sql, {**binds, "id": shop_id})[1]:
            if allowed is None or brand_name(code) in allowed:
                out[ym] = out.get(ym, 0) + int(amt or 0)
    except Exception:  # noqa: BLE001 - 목표 테이블 접근 실패 시 목표 없이 표시
        return {}
    return out


def search(*, shop_ids: list[str] | None = None, shop_nm: str | None = None, rep: str | None = None, team: str | None = None,
           brand: str | None = None, include_closed: bool = False, allowed: list[str] | None = None) -> list[dict]:
    rows = _visible(all_rows(), allowed)
    if shop_ids:
        ids = {s.strip().upper() for s in shop_ids}
        rows = [r for r in rows if r["shopId"] in ids]
    if shop_nm:
        rows = [r for r in rows if shop_nm in (r["shopNm"] or "")]
    if rep:
        rows = [r for r in rows if rep == (r["repId"] or "") or rep in (r["repNm"] or "")]
    if team:
        rows = [r for r in rows if team in (r["teamNm"] or "")]
    if brand:
        rows = [r for r in rows if r["brand"] == brand or r["brdCd"] == brand]
    if not include_closed:
        rows = [r for r in rows if r["status"] in OPEN_STATUSES]
    return rows
