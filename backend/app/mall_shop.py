"""온라인 가격 > 판매처 매장 연결: 사이트(MALL_NM) · 판매자번호(NAVER_PAY_SELL_NO) · 브랜드별 매장코드(SHOP_ID) 매핑.

- 브랜드(BRD_CD) = 품번 첫 글자(S 쉬즈미스, T 리스트, A 시스티나). 온라인몰은 한 사이트에 세 브랜드 상품이 함께 있고 매장코드는
  브랜드마다 따로라(예: 하프클럽 S51005/T51005/A51005) 브랜드까지 키로 둔다. '*' = 모든 브랜드 공통 (브랜드 행이 없을 때 쓰임).
- 목록: 최근 N일 수집(T_SELECT_ONLINE_MNG_R)에 나온 사이트·판매자번호·브랜드 조합 + 이미 매핑된 조합.
  조합마다 수집 행 수·상품 수·마지막 수집일·매장정보(RMK) 예시·수집 테이블 SHOP_ID 반영률, 매핑, 매장 후보(사이트명에 매장명이 들어 있으면).
- 저장: T_SELECT_ONLINE_MALL_SHOP (db/create_online_mall_shop.sql) MERGE. 매장코드는 T_SHOP 에 있어야 한다. 변경 이력에 남긴다.
- 판매자번호가 없는 조합은 '-' 로 저장한다 (기본키). 수집 프로그램은 NVL(판매자번호, '-') 로 찾는다.
수집 테이블(T_SELECT_ONLINE_MNG_R)은 읽기만 한다 — SHOP_ID 는 수집 프로그램이 이 매핑으로 채운다.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta

from fastapi import HTTPException

from . import audit, db
from . import data_service as ds
from .shop_info import BRAND_CODES

MAP_TABLE = "T_SELECT_ONLINE_MALL_SHOP"
NO_SELLER = "-"
RMK_MIN_SHARE = 0.5   # 매장정보 예시: 같은 값이 그 조합 수집 행의 50% 이상일 때만
# 롯데 계열 RMK '모델번호 : TWWSTQ72070_BK / 업체명 : 업체명 없음 / 판매자 : 리스트' → '판매자 : 리스트' (상품마다 다른 모델번호, 빈 업체명 제거)
RMK_KEY_SQL = ("REGEXP_REPLACE(REGEXP_REPLACE(RMK, '^모델번호 :[^/]*/ *', ''), '업체명 : 업체명 없음( / )?', '')")
ALL_BRANDS = "*"
BRD_CODES = set(BRAND_CODES) | {ALL_BRANDS}
DAYS = (7, 31, 90)
CACHE_TTL = 5 * 60
_cache: dict[int, tuple[float, list[dict]]] = {}
_lock = threading.Lock()
_ready: tuple[float, bool] | None = None


def _bad(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"message": msg, "code": "BAD_REQUEST"})


def _now() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _fmt14(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}" if v and len(v) >= 12 else v


def table_ready() -> bool:
    """매핑 테이블이 있는지 (1분 캐시). 없으면 화면은 DDL 안내만 보여준다."""
    global _ready
    if _ready and _ready[0] > time.time():
        return _ready[1]
    try:
        db.query(f"SELECT 1 FROM {MAP_TABLE} WHERE 1 = 0")
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    _ready = (time.time() + 60, ok)
    return ok


def _combos(days: int) -> list[dict]:
    """최근 days 일 수집의 (사이트, 판매자번호, 브랜드) 조합 — 판매자번호가 있는 행만 (5분 캐시).

    판매자번호가 없는 행(오픈마켓 등)은 판매자가 상품마다 제각각이라 매장 하나로 이을 수 없어 뺀다. 인덱스(DT, MALL_NM, …,
    NAVER_PAY_SELL_NO)에서 판매자번호 조건까지 걸러 테이블을 덜 읽는다.
    매장정보(RMK) 예시는 (사이트, 판매자번호) 단위의 대표값: 롯데 계열 'RMK = 모델번호 : … / 업체명 : … / 판매자 : …' 는 모델번호를 떼고
    묶어, 같은 값이 그 판매자 수집 행의 RMK_MIN_SHARE 이상일 때만 쓴다. 네이버·SSG·지마켓은 사이트명이 '네이버(사이트)' 처럼 같고
    매장은 RMK('신세계 광주 리스트')로 구분되므로, 매장 후보도 이 예시를 먼저 본다.
    """
    hit = _cache.get(days)
    if hit and hit[0] > time.time():
        return hit[1]
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y%m%d")
    rows = db.query(f"""SELECT MALL_NM, NAVER_PAY_SELL_NO, SUBSTR(PRDT_CD, 1, 1), COUNT(*), COUNT(DISTINCT PRDT_CD), MAX(DT), COUNT(SHOP_ID)
                          FROM {ds.TABLE} WHERE DT >= :s AND MALL_NM IS NOT NULL AND NAVER_PAY_SELL_NO IS NOT NULL
                         GROUP BY MALL_NM, NAVER_PAY_SELL_NO, SUBSTR(PRDT_CD, 1, 1)""", {"s": since})[1]
    rmk_since = (datetime.now() - timedelta(days=min(days, 31) - 1)).strftime("%Y%m%d")
    best: dict[tuple, tuple[str, int]] = {}
    totals: dict[tuple, int] = {}
    for m, s_, r, n in db.query(
            f"""SELECT MALL_NM, NAVER_PAY_SELL_NO, {RMK_KEY_SQL}, COUNT(*) FROM {ds.TABLE}
                 WHERE DT >= :s AND MALL_NM IS NOT NULL AND NAVER_PAY_SELL_NO IS NOT NULL
                 GROUP BY MALL_NM, NAVER_PAY_SELL_NO, {RMK_KEY_SQL}""", {"s": rmk_since})[1]:
        totals[(m, s_)] = totals.get((m, s_), 0) + int(n)      # RMK 없는 행·'크롤링 실패' 도 분모에 넣는다
        if r and r.strip() and r.strip() != "크롤링 실패" and int(n) > best.get((m, s_), ("", 0))[1]:
            best[(m, s_)] = (r.strip(), int(n))
    rmk = {k: (t, round(n * 100 / totals[k])) for k, (t, n) in best.items() if totals.get(k) and n / totals[k] >= RMK_MIN_SHARE}
    out = [{"mallNm": m, "sellNo": s_, "brdCd": b or "?", "rows": int(n), "products": int(p), "lastDt": d, "shopFilled": int(f),
            "rmk": rmk.get((m, s_), (None, None))[0], "rmkShare": rmk.get((m, s_), (None, None))[1]}
           for m, s_, b, n, p, d, f in rows]
    with _lock:
        _cache[days] = (time.time() + CACHE_TTL, out)
    return out


def _maps() -> dict[tuple[str, str, str], dict]:
    if not table_ready():
        return {}
    return {(r["MALL_NM"], r["NAVER_PAY_SELL_NO"], r["BRD_CD"]): r for r in db.query_dicts(
        f"SELECT MALL_NM, NAVER_PAY_SELL_NO, BRD_CD, SHOP_ID, USE_YN, RMK, UPT_USERID, UPT_DAY FROM {MAP_TABLE}")}


def _norm(s: str | None) -> str:
    return re.sub(r"[\s()\[\]·.\-_/]", "", s or "").upper()


# 사이트명·매장정보에 붙는 공통 단어 — 매장명 비교에서 뺀다
_NOISE = re.compile(r"(네이버|사이트|SSG|신세계몰|쉬즈미스|리스트|시스티나|LIST|SHESMISS|SISTINA|판매자:?|업체명:?|업체명없음)", re.I)
# 유통 체인명: '광주신세계' ↔ '신세계광주' 처럼 순서가 달라도 맞추려고 체인과 지역을 따로 본다 (긴 것부터)
_CHAINS = sorted(["신세계", "롯데아울렛", "롯데", "현대아울렛", "현대시티아울렛", "현대", "갤러리아", "AK", "NC", "뉴코아", "동아", "모다아울렛",
                  "모다", "이마트", "홈플러스", "프리미엄", "아울렛", "스타필드", "세이브존", "2001"], key=len, reverse=True)
_EVENT = re.compile(r"^\((행|특|폐|T)\)")


def _tokens(text: str) -> tuple[str, list[str]]:
    """정규화한 전체 문자열과 (체인들 + 나머지 지역명) 토큰. '광주신세계' → ('광주신세계', ['신세계', '광주'])"""
    t = _NOISE.sub("", _norm(text))
    rest, chains = t, []
    for c in _CHAINS:
        if c in rest:
            chains.append(c)
            rest = rest.replace(c, "")
    rest = re.sub(r"(본점|점)$", "", rest) if len(rest) > 2 else rest
    return t, chains + ([rest] if len(rest) >= 2 else [])


def _suggest(text: str, shops: list[dict], limit: int = 3) -> list[dict]:
    """text(매장정보 예시 또는 사이트명)에 맞는 매장 후보. shops 는 같은 브랜드 매장.
    순위: 이름이 똑같음 > 이름이 text 안에 들어 있음 > 체인·지역 토큰이 모두 매장명에 있음(순서 무관).
    행사·특판·폐점 표시 매장((행)·(특)·(폐))은 다른 후보가 없을 때만."""
    target, toks = _tokens(text)
    if len(target) < 2:
        return []
    scored = []
    for s in shops:
        raw = s["shopNm"] or ""
        name = _NOISE.sub("", _norm(_EVENT.sub("", raw)))
        if len(name) < 2:
            continue
        if name == target:
            score = 3
        elif len(name) >= 3 and name in target:
            score = 2
        elif len(toks) >= 2 and all(t in name for t in toks):
            score = 1
        else:
            continue
        scored.append((score, 0 if _EVENT.match(raw) else 1, len(name), s))
    if any(x[1] for x in scored):   # 일반 매장 후보가 있으면 행사·특판 매장은 뺀다
        scored = [x for x in scored if x[1]]
    scored.sort(key=lambda x: (-x[0], -x[2]))
    top = scored[0][0] if scored else 0
    seen, out = set(), []
    for score, _, _, s in scored:
        if score < top or s["shopId"] in seen:   # 가장 높은 등급의 후보만
            continue
        seen.add(s["shopId"])
        out.append({"shopId": s["shopId"], "shopNm": s["shopNm"], "brand": s["brand"]})
        if len(out) >= limit:
            break
    return out


def shop_options() -> list[dict]:
    """매장 선택 목록: 영업 중 매장 (브랜드별 행을 매장 하나로)"""
    from . import shop_info

    seen: dict[str, dict] = {}
    for r in shop_info.search(include_closed=False):
        s = seen.setdefault(r["shopId"], {"shopId": r["shopId"], "shopNm": r["shopNm"], "brands": [], "teamNm": r["teamNm"]})
        if r["brand"] not in s["brands"]:
            s["brands"].append(r["brand"])
    return sorted(seen.values(), key=lambda s: s["shopId"])


def _shop_names(ids: list[str]) -> dict[str, str]:
    from .sale_monthly import shop_names

    return shop_names(ids)


def listing(days: int = 7) -> dict:
    """화면 목록: 판매자번호가 있는 조합 + 이미 매핑된 조합.
    사이트 → 판매자번호 → 브랜드 순. 수집 원본이 아무리 많아도 (사이트, 판매자번호, 브랜드) 단위로 묶은 1행씩."""
    if days not in DAYS:
        _bad(f"기간은 {DAYS} 일 중 하나입니다.")
    ready = table_ready()
    combos = _combos(days)
    maps = _maps()
    from . import shop_info

    shops = [{"shopId": r["shopId"], "shopNm": r["shopNm"], "brand": r["brand"], "brdCd": r["brdCd"]}
             for r in shop_info.search(include_closed=False)]
    keys = {(c["mallNm"], c["sellNo"], c["brdCd"]) for c in combos}

    def mapped(m):
        return {"shopId": m["SHOP_ID"] if m else None, "useYn": m["USE_YN"] if m else None, "mapRmk": m["RMK"] if m else None,
                "updatedBy": m["UPT_USERID"] if m else None, "updatedAt": _fmt14(m["UPT_DAY"]) if m else None}

    rows = []
    for c in combos:
        star = maps.get((c["mallNm"], c["sellNo"], ALL_BRANDS))   # 모든 브랜드 공통 매핑 (브랜드 행이 없을 때 적용)
        rows.append({**c, "seen": True, **mapped(maps.get((c["mallNm"], c["sellNo"], c["brdCd"]))),
                     "starShopId": star["SHOP_ID"] if star and star["USE_YN"] == "Y" else None})
    for (mall, sell, brd), m in maps.items():   # 매핑은 있는데 이 기간 수집에는 없는 조합, '*' 행
        if (mall, sell, brd) not in keys:
            n = sum(c["rows"] for c in combos if c["mallNm"] == mall and c["sellNo"] == sell) if brd == ALL_BRANDS else 0
            rows.append({"mallNm": mall, "sellNo": sell, "brdCd": brd, "rows": n, "products": 0, "lastDt": None, "shopFilled": 0,
                         "rmk": None, "rmkShare": None, "seen": n > 0, **mapped(m), "starShopId": None})
    names = _shop_names([x for r in rows for x in (r["shopId"], r["starShopId"]) if x])
    for r in rows:
        r["brand"] = "모든 브랜드" if r["brdCd"] == ALL_BRANDS else BRAND_CODES.get(r["brdCd"], r["brdCd"])
        r["shopNm"] = names.get(r["shopId"]) if r["shopId"] else None
        r["starShopNm"] = names.get(r["starShopId"]) if r["starShopId"] else None
        same = [s for s in shops if r["brdCd"] in (ALL_BRANDS, s["brdCd"])]
        # 매장 후보: 매장정보(RMK) 예시에서 먼저 찾고 (네이버·SSG·지마켓은 사이트명이 같고 매장이 RMK 에 있음), 없으면 사이트명에서
        r["suggestions"] = [] if r["shopId"] else (_suggest(r["rmk"] or "", same) or _suggest(r["mallNm"], same))
        # 수집 시 실제로 들어갈 매장: 브랜드 행 → 없으면 '*' 행
        r["effectiveShopId"] = (r["shopId"] if r["shopId"] and r["useYn"] == "Y" else None) or (
            r["starShopId"] if r["brdCd"] != ALL_BRANDS else None)
    # 판매자번호가 없는 조합은 수집 목록에 없다. 예전에 연결해 둔 판매자번호 없음('-') 행은 해제할 수 있게 남긴다.
    rows.sort(key=lambda r: (r["mallNm"], r["sellNo"], r["brdCd"] == ALL_BRANDS, r["brdCd"]))
    data_rows = [r for r in rows if r["brdCd"] != ALL_BRANDS]
    total_rows = sum(r["rows"] for r in data_rows)
    mapped_rows = sum(r["rows"] for r in data_rows if r["effectiveShopId"])
    return {
        "ready": ready, "days": days, "rows": rows,
        "summary": {"combos": len(data_rows), "sellers": len({(r["mallNm"], r["sellNo"]) for r in data_rows}),
                    "mapped": sum(1 for r in data_rows if r["effectiveShopId"]),
                    "unmapped": sum(1 for r in data_rows if not r["effectiveShopId"]), "malls": len({r["mallNm"] for r in rows}),
                    "rowsTotal": total_rows, "rowsMapped": mapped_rows,
                    "rowsMappedPct": round(mapped_rows * 100 / total_rows, 1) if total_rows else None,
                    "shopFilled": sum(r["shopFilled"] for r in data_rows)},
    }


def clean_item(it: dict) -> tuple:
    """항목 1개 정리 · 형식 검증 (매장 존재 확인은 validate 가 모아서). (사이트, 판매자, 브랜드, 매장, 사용, 비고)"""
    if not isinstance(it, dict):
        _bad("항목 형식이 올바르지 않습니다.")
    mall = str(it.get("mallNm") or "").strip()
    sell = str(it.get("sellNo") or "").strip() or NO_SELLER
    brd = str(it.get("brdCd") or ALL_BRANDS).strip().upper()
    if brd not in BRD_CODES:
        _bad(f"브랜드는 {', '.join(sorted(BRD_CODES))} 중 하나입니다.")
    shop = str(it.get("shopId") or "").strip().upper()
    use = "N" if it.get("useYn") == "N" else "Y"
    rmk = (str(it.get("rmk") or "").strip() or None)
    if not mall:
        _bad("사이트명이 없습니다.")
    if len(mall.encode("utf-8")) > 300 or len(sell) > 50:
        _bad("사이트명·판매자번호가 너무 깁니다.")
    if shop and not re.match(r"^[A-Z0-9]{1,6}$", shop):
        _bad(f"매장코드 '{shop}' 형식이 올바르지 않습니다 (6자리 이내).")
    if rmk and len(rmk.encode("utf-8")) > 500:
        _bad("비고가 너무 깁니다.")
    return mall, sell, brd, shop, use, rmk


def validate(items: list[dict]) -> tuple[list[tuple], dict[str, str]]:
    """저장 전 검증 (화면 저장 · AI 변경안 공용). (정리된 항목 [(사이트, 판매자, 브랜드, 매장, 사용, 비고)], 매장명) 을 돌려준다."""
    if not isinstance(items, list) or not items or len(items) > 500:
        _bad("저장할 항목(최대 500개)이 필요합니다.")
    clean = [clean_item(it) for it in items]
    ids = sorted({c[3] for c in clean if c[3]})
    names = _shop_names(ids)
    missing = [i for i in ids if i not in names]
    if missing:
        _bad(f"매장(T_SHOP)에 없는 매장코드: {', '.join(missing)}")
    return clean, names


def save(admin: dict, items: list[dict]) -> dict:
    """[{mallNm, sellNo, brdCd, shopId, useYn?, rmk?}] 등록·수정 (MERGE). shopId 가 비어 있으면 그 매핑을 지운다."""
    if not table_ready():
        _bad("매핑 테이블이 없습니다. 관리자에게 db/create_online_mall_shop.sql 실행을 요청하세요.")
    clean, _ = validate(items)
    before = _maps()
    now = _now()
    saved = deleted = 0
    with db.get_pool().acquire() as conn, conn.cursor() as cur:
        for mall, sell, brd, shop, use, rmk in clean:
            key = {"m": mall, "s": sell, "b": brd}
            if not shop:
                cur.execute(f"DELETE FROM {MAP_TABLE} WHERE MALL_NM = :m AND NAVER_PAY_SELL_NO = :s AND BRD_CD = :b", key)
                deleted += cur.rowcount
                continue
            cur.execute(f"""MERGE INTO {MAP_TABLE} T
                            USING (SELECT :m AS MALL_NM, :s AS NAVER_PAY_SELL_NO, :b AS BRD_CD FROM DUAL) S
                               ON (T.MALL_NM = S.MALL_NM AND T.NAVER_PAY_SELL_NO = S.NAVER_PAY_SELL_NO AND T.BRD_CD = S.BRD_CD)
                             WHEN MATCHED THEN UPDATE SET SHOP_ID = :shop, USE_YN = :u, RMK = :r, UPT_USERID = :p_user, UPT_DAY = :d
                             WHEN NOT MATCHED THEN INSERT (MALL_NM, NAVER_PAY_SELL_NO, BRD_CD, SHOP_ID, USE_YN, RMK,
                                                           INS_USERID, INS_DAY, UPT_USERID, UPT_DAY)
                                  VALUES (:m, :s, :b, :shop, :u, :r, :p_user, :d, :p_user, :d)""",
                        {**key, "shop": shop, "u": use, "r": rmk, "p_user": admin["id"], "d": now})
            saved += 1
        conn.commit()
    changes = []
    for mall, sell, brd, shop, use, rmk in clean:
        b = before.get((mall, sell, brd))
        old = f"{b['SHOP_ID']}{'' if b['USE_YN'] == 'Y' else '(미사용)'}" if b else "-"
        new = f"{shop}{'' if use == 'Y' else '(미사용)'}" if shop else "-"
        if old != new or (b and (b["RMK"] or None) != rmk):
            changes.append(f"{mall}/{sell}/{brd}: {old} → {new}")
    if changes:
        audit.record(admin, "MALL_SHOP_MAP", f"판매처 매장 연결 {len(changes)}건", summary=" / ".join(changes)[:1000])
    return {"saved": saved, "deleted": deleted, "changed": len(changes)}


# ----------------------------------------------------------------------------
# 수집 행 매장코드 채우기 (일자별 상세 [매장코드 채우기] 버튼)
# 매일 02:00 스케줄(JOB_FILL_ONLINE_SHOP_ID)은 전일자만 채운다. 매핑을 새로 등록했을 때 화면에서 최근 며칠을 바로 반영한다.
# ----------------------------------------------------------------------------
FILL_PROC = "P_FILL_ONLINE_SHOP_ID"   # db/create_job_online_shop_id.sql
FILL_DAYS = 7
_fill_lock = threading.Lock()


def fill_shop_ids(admin: dict, days: int = FILL_DAYS) -> dict:
    """최근 days 일(당일 포함) 수집 행의 SHOP_ID 를 판매처 매장 연결 매핑으로 채운다. 같은 값이면 건드리지 않는다."""
    import oracledb

    from . import jobs

    if not _fill_lock.acquire(blocking=False):
        _bad("다른 사용자가 매장코드를 채우는 중입니다. 잠시 후 다시 시도하세요.", 409)
    t0 = time.time()
    try:
        today = datetime.now()
        frm, to = (today - timedelta(days=days - 1)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
        start = time.time()
        try:
            with db.get_pool().acquire() as conn, conn.cursor() as cur:
                n = cur.var(int)
                cur.callproc(FILL_PROC, [frm, to, n])
                updated = int(n.getvalue() or 0)
        except oracledb.DatabaseError as ex:
            if "PLS-00201" in str(ex):   # 프로시저 없음 / 실행 권한 없음
                _bad("매장코드 채우기 프로시저가 없습니다. 관리자에게 db/create_job_online_shop_id.sql 실행을 요청하세요.")
            raise
        elapsed = round(time.time() - start, 1)
    except Exception as ex:
        jobs.record("shop_fill", t0, time.time(), "error", str(getattr(ex, "detail", ex))[:300], admin.get("id"))
        raise
    finally:
        _fill_lock.release()
    # 화면 캐시(일자별 상세·대시보드·판매처 매장 연결 반영률)를 비워 바로 보이게 한다
    ds._day_cache._data.clear()
    ds._dash_cache._data.clear()
    with _lock:
        _cache.clear()
    audit.record(admin, "ONLINE_SHOP_FILL", f"매장코드 채우기 {frm}~{to}", summary=f"{updated:,}행 변경 · {elapsed}초")
    jobs.record("shop_fill", t0, time.time(), "ok", f"{frm}~{to} · {updated:,}행 변경", admin.get("id"))
    return {"from": frm, "to": to, "updated": updated, "elapsedSec": elapsed}
