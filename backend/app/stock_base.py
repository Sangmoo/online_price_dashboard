"""매장 재고 기준 집계 (T_ERP_WEB_STOCK_BASE) — 장기 미판매 · 재고 회전 · 주간 브리핑 · 매장 평가 카드의 재고 기준.

T_SHOP_STOCK 은 매달 재고 0 인 행까지 모두 쌓여(쉬즈미스 이번 달 1,748만 행 중 재고 있는 행 2.8%) 바로 읽으면 브랜드당 70초 안팎.
DB 스케줄(JOB_ERP_WEB_STOCK_BASE, 매일 06:30)이 매장 × 스타일 재고 있는 것만 모아 두고, 앱은 여기서 1초 안에 읽는다.

- 브랜드별 갱신 결과(T_ERP_WEB_STOCK_BASE_LOG)의 기준 월이 이번 달이고 36시간 안에 집계된 것만 쓴다.
  아니면(테이블 없음 · 집계 실패 · 새 달 첫날 06:30 전) 지금처럼 원장에서 바로 계산한다 (stock_aging._base).
- 관리자 > 스케줄 · 배치 [지금 재집계]: 같은 프로시저를 백그라운드로 실행 (동시에 한 번, DB 스케줄이 돌고 있으면 막음).
  끝나면 재고 기준 캐시를 비우고 다시 읽어 둔다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from . import db, logs
from . import stock_ctl as sc
from .tables import Tables

_log = logs.get("app")
TABLE = "T_ERP_WEB_STOCK_BASE"
LOG_TABLE = "T_ERP_WEB_STOCK_BASE_LOG"
PROC = "P_LOAD_ERP_WEB_STOCK_BASE"
JOB = "JOB_ERP_WEB_STOCK_BASE"
DDL = "db/create_erp_web_stock_base.sql"
MAX_AGE_H = 36           # 이보다 오래된 집계는 쓰지 않는다 (스케줄이 하루 이상 안 돈 경우)
RUNNING_GUARD_MIN = 20   # DB 스케줄이 집계 중(RUNNING)이면 이 시간 동안 [지금 재집계]를 막는다
tables = Tables(TABLE, LOG_TABLE, ddl=DDL)

_lock = threading.Lock()
_state: dict = {"status": "idle", "brand": None, "started": None, "finished": None, "by": None, "error": None, "elapsedSec": None}


def _fmt(d: datetime | None) -> str | None:
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else None


def _logs() -> dict[str, dict]:
    rows = db.query_dicts(f"SELECT BRAND, MAKE_YYMM, BASE_DT, ROW_CNT, SEC, STATUS, MSG, UPD_DT FROM {LOG_TABLE}")
    return {r["BRAND"]: r for r in rows}


def _usable(lg: dict | None, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return bool(lg and lg.get("BASE_DT") and lg.get("MAKE_YYMM") == now.strftime("%Y%m")
                and lg["BASE_DT"] >= now - timedelta(hours=MAX_AGE_H))


def read(brand: str) -> dict | None:
    """집계 테이블의 브랜드 재고 기준 (stock_aging._base 와 같은 모양) — 쓸 수 없으면 None"""
    if not tables.ready():
        return None
    try:
        lg = _logs().get(brand)
        if not _usable(lg):
            _log.info("매장 재고 기준 집계 사용 안 함 %s (%s)", brand,
                      f"기준 월 {lg.get('MAKE_YYMM')} · 집계 {_fmt(lg.get('BASE_DT'))} · {lg.get('STATUS')}" if lg else "집계 기록 없음")
            return None
        rows = db.query(f"""SELECT SHOP_ID, PRDT_CD, STOCK_QTY, STOCK_AMT, L_SALE_DT, L_RNDS_DT, F_RNDS_DT, SKU_CNT
                              FROM {TABLE} WHERE BRAND = :b""", {"b": brand}, arraysize=50000)[1]
    except Exception:  # noqa: BLE001 - 집계를 못 읽으면 원장에서 계산
        _log.warning("매장 재고 기준 집계 읽기 실패 %s", brand, exc_info=True)
        return None
    return {"rows": rows, "asOf": lg["BASE_DT"].strftime("%Y-%m-%d %H:%M"), "ym": lg["MAKE_YYMM"], "source": "table"}


def usable(brand: str) -> bool:
    try:
        return tables.ready() and _usable(_logs().get(brand))
    except Exception:  # noqa: BLE001
        return False


def state() -> dict:
    s = dict(_state)
    if s["status"] == "running" and s["started"]:
        s["elapsedSec"] = int(time.time() - s["started"])
    for k in ("started", "finished"):
        s[k] = datetime.fromtimestamp(s[k]).strftime("%Y-%m-%d %H:%M:%S") if s[k] else None
    return s


def status() -> dict:
    """관리자 화면: 브랜드별 마지막 집계 · 지금 쓰는지 · 진행 상태"""
    if not tables.ready():
        return {"ready": False, "message": tables.message(), "brands": [], "run": state(), "job": JOB, "ddl": DDL}
    now = datetime.now()
    lgs = _logs()
    brands = []
    for b, nm in sc.BRAND_CODES.items():
        lg = lgs.get(b) or {}
        brands.append({"brand": b, "brandNm": nm, "makeYymm": lg.get("MAKE_YYMM"), "baseDt": _fmt(lg.get("BASE_DT")),
                       "rows": int(lg["ROW_CNT"]) if lg.get("ROW_CNT") is not None else None,
                       "sec": float(lg["SEC"]) if lg.get("SEC") is not None else None,
                       "status": lg.get("STATUS"), "msg": lg.get("MSG"), "updDt": _fmt(lg.get("UPD_DT")), "inUse": _usable(lg or None, now)})
    return {"ready": True, "message": None, "brands": brands, "run": state(), "job": JOB, "ddl": DDL,
            "maxAgeHours": MAX_AGE_H, "schedule": "매일 06:30"}


def start(admin: dict, brand: str | None = None) -> dict:
    if brand is not None and brand not in sc.BRAND_CODES:
        sc.bad("브랜드는 S · T · A 중 하나입니다.")
    if not tables.ready():
        sc.bad(tables.message(), 409)
    with _lock:
        if _state["status"] == "running":
            return state()
    guard = datetime.now() - timedelta(minutes=RUNNING_GUARD_MIN)
    busy = [sc.BRAND_CODES.get(b, b) for b, lg in _logs().items() if lg.get("STATUS") == "RUNNING" and lg.get("UPD_DT") and lg["UPD_DT"] >= guard]
    if busy:
        sc.bad(f"DB 스케줄이 지금 집계 중입니다 ({', '.join(busy)}). 몇 분 뒤 다시 시도하세요.", 409)
    with _lock:
        if _state["status"] == "running":
            return state()
        _state.update({"status": "running", "brand": brand, "started": time.time(), "finished": None, "by": admin.get("id"),
                       "error": None, "elapsedSec": None})
    threading.Thread(target=_run, args=(dict(admin), brand), daemon=True, name="stock-base").start()
    return state()


def _call(brand: str | None) -> None:
    with db.get_pool().acquire() as conn, conn.cursor() as cur:
        cur.execute(f"BEGIN {PROC}(:b); END;", {"b": brand})


def _after(brands: list[str]) -> None:
    """새 집계로 재고 기준 · 브리핑을 다시 계산하게 하고, 재고 기준은 바로 다시 읽어 둔다"""
    from . import briefing, stock_aging

    for b in brands:
        stock_aging.drop(b)
    with briefing._lock:
        briefing._cache.clear()
    for b in brands:
        try:
            stock_aging.base(b)
        except Exception:  # noqa: BLE001
            _log.exception("재집계 후 재고 기준 다시 읽기 실패 %s", b)


def _run(admin: dict, brand: str | None) -> None:
    from . import audit, jobs

    brands = [brand] if brand else list(sc.BRAND_CODES)
    label = sc.BRAND_CODES[brand] if brand else "전체 브랜드"
    err = None
    try:
        _call(brand)
    except Exception as ex:  # noqa: BLE001 - 일부 브랜드만 실패해도 나머지는 갱신됐으므로 결과를 함께 보여 준다
        err = str(ex).splitlines()[0]
        _log.warning("매장 재고 기준 재집계 실패 (by %s): %s", admin.get("id"), err)
    try:
        lgs = _logs()
        detail = " · ".join(f"{sc.BRAND_CODES[b]} {int(lgs[b]['ROW_CNT'] or 0):,}행 {lgs[b]['SEC']}초" if lgs.get(b, {}).get("STATUS") == "OK"
                            else f"{sc.BRAND_CODES[b]} 실패" for b in brands)
    except Exception:  # noqa: BLE001
        detail = ""
    _after(brands)
    sec = int(time.time() - (_state["started"] or time.time()))
    summary = f"매장 재고 기준 재집계 ({label}) {sec}초 · {detail}" + (f" · 오류: {err[:200]}" if err else "")
    try:
        audit.record(admin, "STOCK_BASE_REFRESH", label, None, None, summary=summary)
    except Exception:  # noqa: BLE001
        _log.exception("매장 재고 기준 재집계 이력 기록 실패")
    jobs.record("stock_base", _state["started"] or time.time(), time.time(), "error" if err else "ok",
                f"{label} · {detail}" + (f" · {err[:200]}" if err else ""), admin.get("id"))
    with _lock:
        _state.update({"status": "error" if err else "done", "finished": time.time(), "elapsedSec": sec, "error": err})
    _log.info(summary)
