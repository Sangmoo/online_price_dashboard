"""월별 매장별 판매 집계: T_CLOSE_SALE_BASE(마감 매출 기초 데이터) 조회 · 페이징 · 전체 엑셀."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from . import db
from .xlsx_stream import XlsxStreamWriter

PAGE_SIZE = 100
MAX_MONTHS = 36                  # 조회 기간 최대 개월 수
SHEET_ROWS = 1_000_000           # 엑셀 시트당 행 수. 넘으면 다음 시트에 이어서 쓴다 (엑셀 한도 1,048,576)
EXPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "exports"   # git 제외 폴더
EXPORT_KEEP_SEC = 2 * 60 * 60    # 완료된 엑셀 파일 보관 시간 (다시 받기 가능)
MAX_RUNNING_JOBS = 2             # 서버 전체 동시 생성 작업 수
WIDTHS = [10, 12, 10, 22, 8, 9, 10, 12, 10, 10, 14, 7, 7, 8, 11, 11, 11, 13, 11, 10, 8, 10, 10, 12]

# 시즌: 계절 순서 (봄 → 여름 → 가을 → 겨울, 각 계절은 기본 → 기획)
SEASONS = ["봄", "봄기획", "여름", "여름기획", "가을", "가을기획", "겨울", "겨울기획"]

# (컬럼, 한글명, 형식) — 테이블 컬럼 순서
COLUMNS: list[tuple[str, str, str]] = [
    ("MAKE_YYMM", "판매년월", "text"),
    ("TEAM_CD", "팀", "text"),
    ("SHOP_ID", "매장코드", "text"),
    ("SHOP_NM", "매장명", "text"),
    ("PLAN_YY", "기획년도", "text"),
    ("SESS_NM", "시즌", "text"),
    ("PRDT_GRP_NM", "품군", "text"),
    ("ITEM_NM", "아이템", "text"),
    ("CHARGE_CLSBY_NM", "수수료구분", "text"),
    ("DSCT_CLSBY_NM", "판매형태", "text"),
    ("PRDT_CD", "상품", "text"),
    ("COLOR_CD", "색상", "text"),
    ("SIZE_CD", "사이즈", "text"),
    ("QTY", "수량", "int"),
    ("FIRST_PRICE", "최초가", "int"),
    ("REAL_SALE_PRICE", "판매단가", "int"),
    ("REAL_SALE_AMT_PRICE", "실판단가", "int"),
    ("REAL_SALE_AMT", "실판금액", "int"),
    ("DSCT_AMT", "할인금액", "int"),
    ("PRDT_CLSBY_NM", "생산형태", "text"),
    ("ACC_YN", "악세사리 구분", "text"),
    ("ONLINE_SALE", "온라인 판매 구분", "text"),
    ("GOODS_CLSBY_NM", "상품구분", "text"),
    ("PRODUCT_COST2", "제조원가(V+)", "int"),
]
COL_SQL = ", ".join(c for c, _, _ in COLUMNS)
# 요청 정렬은 판매년월, 매장코드. 페이지 간 순서가 흔들리지 않도록 뒤에 고유 순서를 덧붙인다.
ORDER_SQL = "ORDER BY MAKE_YYMM, SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD, ROWID"

_YYMM = re.compile(r"^\d{6}$")


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


def _months(f: str, t: str) -> int:
    return (int(t[:4]) - int(f[:4])) * 12 + int(t[4:]) - int(f[4:]) + 1


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _where(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None) -> tuple[str, dict]:
    ym_from, ym_to = (ym_from or "").replace("-", ""), (ym_to or "").replace("-", "")
    if not (_YYMM.match(ym_from) and _YYMM.match(ym_to)) or not (1 <= int(ym_from[4:]) <= 12 and 1 <= int(ym_to[4:]) <= 12):
        _bad("판매년월은 YYYY-MM 형식으로 입력하세요.")
    if ym_from > ym_to:
        _bad("판매년월 시작이 종료보다 늦습니다.")
    if _months(ym_from, ym_to) > MAX_MONTHS:
        _bad(f"판매년월은 최대 {MAX_MONTHS}개월까지 조회할 수 있습니다.")

    conds, p = ["MAKE_YYMM BETWEEN :ym_from AND :ym_to"], {"ym_from": ym_from, "ym_to": ym_to}

    def _in(col: str, prefix: str, values: list[str], limit: int):
        if len(values) > limit:
            _bad(f"선택 가능한 개수({limit}개)를 넘었습니다.")
        binds = {f"{prefix}{i}": v for i, v in enumerate(values)}
        conds.append(f"{col} IN ({', '.join(':' + k for k in binds)})")
        p.update(binds)

    shop_list = _split(shops)
    if shop_list:
        if any(len(s) > 6 for s in shop_list):
            _bad("매장코드가 올바르지 않습니다.")
        _in("SHOP_ID", "shop", shop_list, 500)
    yy_list = _split(plan_yys)
    if yy_list:
        if any(not re.match(r"^\d{4}$", y) for y in yy_list):
            _bad("기획년도가 올바르지 않습니다.")
        _in("PLAN_YY", "yy", yy_list, 30)
    sess_list = _split(seasons)
    if sess_list:
        if any(s not in SEASONS for s in sess_list):
            _bad("시즌이 올바르지 않습니다.")
        _in("SESS_NM", "sess", sess_list, len(SEASONS))
    return " AND ".join(conds), p


def _row(r: tuple) -> dict:
    return {c: (int(v) if kind == "int" and v is not None and float(v).is_integer() else v)
            for (c, _, kind), v in zip(COLUMNS, r)}


# 조회 결과 월별 건수/합계 캐시. 마감 데이터라 자주 바뀌지 않으므로 같은 조건의 페이지 이동은 캐시로 위치를 계산한다.
STATS_TTL = 10 * 60
_stats_cache: dict[tuple, tuple[float, object]] = {}
_stats_lock = threading.Lock()


def _cached(kind: str, where: str, p: dict, fn):
    key = (kind, where, tuple(sorted(p.items())))
    now = time.time()
    with _stats_lock:
        hit = _stats_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    val = fn()
    with _stats_lock:
        if len(_stats_cache) > 500:
            _stats_cache.clear()
        _stats_cache[key] = (now + STATS_TTL, val)
    return val


def _month_stats(where: str, p: dict) -> list[tuple[str, int, int, int]]:
    """(판매년월, 건수, 수량, 실판금액). 매장 조건까지는 인덱스(IX_03)만으로 계산되어 36개월도 수 초 안에 끝난다."""
    return _cached("months", where, p, lambda: [
        (ym, int(c), int(q or 0), int(a or 0))
        for ym, c, q, a in db.query(
            f"SELECT MAKE_YYMM, COUNT(*), SUM(QTY), SUM(REAL_SALE_AMT) FROM T_CLOSE_SALE_BASE WHERE {where} "
            "GROUP BY MAKE_YYMM ORDER BY MAKE_YYMM", p)[1]
    ])


def search(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None,
           page: int = 1, with_total: bool = True) -> dict:
    """정렬(판매년월 → 매장코드 …)의 첫 키가 판매년월이므로, 월별 건수로 페이지가 걸친 월을 찾아 그 월만 정렬해 가져온다.
    전체 기간을 한 번에 정렬하면 36개월(1,400만 행)에서 페이지마다 수십 초가 걸린다."""
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons)
    page = max(1, int(page))
    months = _month_stats(where, p)
    total = sum(m[1] for m in months)
    out: dict = {"page": page, "pageSize": PAGE_SIZE, "total": total}
    if with_total:
        out["summary"] = {"rows": total, "qty": sum(m[2] for m in months), "realSaleAmt": sum(m[3] for m in months)}

    lo, need, acc, rows = (page - 1) * PAGE_SIZE, PAGE_SIZE, 0, []
    for ym, cnt, _, _ in months:
        if need <= 0:
            break
        if lo >= acc + cnt:
            acc += cnt
            continue
        local_lo = lo - acc
        got = db.query(
            f"""SELECT {COL_SQL} FROM (
                   SELECT A.*, ROWNUM RN FROM (
                       SELECT {COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} AND MAKE_YYMM = :cur_ym {ORDER_SQL}
                   ) A WHERE ROWNUM <= :hi
                ) WHERE RN > :lo""",
            {**p, "cur_ym": ym, "hi": local_lo + need, "lo": local_lo},
        )[1]
        rows += got
        need -= len(got)
        acc += cnt
        lo = acc  # 다음 월은 처음부터
    out["rows"] = [_row(r) for r in rows]
    return out


def dsct_total(ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None, seasons: str | None) -> dict:
    """할인금액 합계는 인덱스에 없어 테이블을 읽어야 하므로(36개월 약 40초) 화면에서 따로 요청한다."""
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons)
    val = _cached("dsct", where, p, lambda: int(db.query(
        f"SELECT NVL(SUM(DSCT_AMT), 0) FROM T_CLOSE_SALE_BASE WHERE {where}", p)[1][0][0] or 0))
    return {"dsctAmt": val}


# ----------------------------------------------------------------------------
# 전체 엑셀: 백그라운드 작업 (행 수 제한 없음, 시트당 SHEET_ROWS 행)
# 36개월이면 1,400만 행 이상이라 요청 하나로 기다릴 수 없으므로 작업을 만들고 진행률을 조회한다.
# 월 단위로 나눠 조회해 DB 정렬 부담을 줄이고, 결과 순서는 판매년월 → 매장코드 순 그대로 유지된다.
# ----------------------------------------------------------------------------
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _month_list(f: str, t: str) -> list[str]:
    y, m, out = int(f[:4]), int(f[4:]), []
    while f"{y:04d}{m:02d}" <= t:
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _public(job: dict) -> dict:
    now = time.time()
    return {
        "id": job["id"], "status": job["status"], "total": job["total"], "written": job["written"],
        "sheets": max(1, -(-job["written"] // SHEET_ROWS)) if job["written"] else 0,
        "startedAt": job["started"], "elapsedSec": int((job["finished"] or now) - job["started"]),
        "fileName": job["file_name"], "fileSize": job["file_size"], "error": job["error"], "cond": job["cond"],
    }


def cleanup_exports() -> None:
    """보관 시간이 지난 작업·파일 삭제. 서버 재시작 전 남은 파일도 정리."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with _jobs_lock:
        for jid, j in list(_jobs.items()):
            if j["status"] != "running" and (j["finished"] or now) + EXPORT_KEEP_SEC < now:
                _jobs.pop(jid, None)
        live = {j["path"] for j in _jobs.values()}
    for f in EXPORT_DIR.glob("*.xlsx"):
        if str(f) not in live:
            try:
                f.unlink()
            except OSError:
                pass


def start_export(usr_id: str, ym_from: str, ym_to: str, shops: str | None, plan_yys: str | None,
                 seasons: str | None) -> dict:
    where, p = _where(ym_from, ym_to, shops, plan_yys, seasons)
    cleanup_exports()
    with _jobs_lock:
        mine = [j for j in _jobs.values() if j["usr_id"] == usr_id and j["status"] == "running"]
        if mine:
            raise HTTPException(status_code=409, detail={"message": "이미 엑셀을 만들고 있습니다. 끝나거나 취소한 뒤 다시 요청하세요.",
                                                         "code": "EXPORT_RUNNING", "job": _public(mine[0])})
        if sum(j["status"] == "running" for j in _jobs.values()) >= MAX_RUNNING_JOBS:
            raise HTTPException(status_code=429, detail={"message": "다른 사용자의 대용량 엑셀 작업이 진행 중입니다. 잠시 후 다시 시도하세요.",
                                                         "code": "EXPORT_BUSY"})
    total = sum(m[1] for m in _month_stats(where, p))
    if total == 0:
        _bad("조회된 데이터가 없습니다.")
    f, t = p["ym_from"], p["ym_to"]
    jid = uuid.uuid4().hex
    job = {
        "id": jid, "usr_id": usr_id, "status": "running", "total": total, "written": 0,
        "started": time.time(), "finished": None, "error": None, "cancel": False,
        "path": str(EXPORT_DIR / f"{jid}.xlsx"), "file_size": None,
        "file_name": f"월별매장별판매집계_{f}-{t}_{date.today():%Y%m%d}.xlsx",
        "cond": {"ymFrom": f, "ymTo": t, "shops": shops or "", "planYys": plan_yys or "", "seasons": seasons or ""},
    }
    with _jobs_lock:
        _jobs[jid] = job
    threading.Thread(target=_run_export, args=(job, where, p), daemon=True, name=f"export-{jid[:8]}").start()
    return _public(job)


def _run_export(job: dict, where: str, p: dict) -> None:
    try:
        with XlsxStreamWriter(job["path"], [label for _, label, _ in COLUMNS], [k for _, _, k in COLUMNS], WIDTHS,
                              sheet_name="판매집계", sheet_rows=SHEET_ROWS) as w:
            with db.get_pool().acquire() as conn:
                cur = conn.cursor()
                cur.arraysize = 5000
                cur.prefetchrows = 5000
                for ym in _month_list(p["ym_from"], p["ym_to"]):
                    cur.execute(f"SELECT {COL_SQL} FROM T_CLOSE_SALE_BASE WHERE {where} AND MAKE_YYMM = :cur_ym {ORDER_SQL}",
                                {**p, "cur_ym": ym})
                    while batch := cur.fetchmany():
                        if job["cancel"]:
                            raise InterruptedError
                        w.write_rows(batch)
                        job["written"] = w.total
        job["file_size"] = os.path.getsize(job["path"])
        job["status"] = "done"
    except InterruptedError:
        job["status"] = "cancelled"
    except Exception as ex:  # noqa: BLE001 - 작업 실패는 상태로 전달
        job["status"] = "error"
        job["error"] = f"엑셀 생성 중 오류가 발생했습니다: {ex}"
    finally:
        job["finished"] = time.time()
        if job["status"] != "done":
            try:
                os.remove(job["path"])
            except OSError:
                pass


def _own_job(usr_id: str, job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["usr_id"] != usr_id:
        raise HTTPException(status_code=404, detail={"message": "엑셀 작업을 찾을 수 없습니다. 다시 요청하세요.", "code": "NOT_FOUND"})
    return job


def export_status(usr_id: str, job_id: str) -> dict:
    return _public(_own_job(usr_id, job_id))


def current_export(usr_id: str) -> dict | None:
    """화면 재진입 시 이어서 보여줄 작업 (진행 중이거나 받을 수 있는 최근 작업)."""
    cleanup_exports()
    with _jobs_lock:
        mine = sorted((j for j in _jobs.values() if j["usr_id"] == usr_id and j["status"] in ("running", "done")),
                      key=lambda j: j["started"], reverse=True)
    return _public(mine[0]) if mine else None


def cancel_export(usr_id: str, job_id: str) -> dict:
    job = _own_job(usr_id, job_id)
    job["cancel"] = True
    if job["status"] == "done":  # 완료 후 취소 = 파일 삭제
        job["status"] = "cancelled"
        try:
            os.remove(job["path"])
        except OSError:
            pass
    return _public(job)


def export_file(usr_id: str, job_id: str) -> tuple[str, str]:
    job = _own_job(usr_id, job_id)
    if job["status"] != "done" or not os.path.exists(job["path"]):
        _bad("아직 엑셀 파일이 준비되지 않았습니다.")
    return job["path"], job["file_name"]


def options() -> dict:
    this_year = date.today().year
    return {
        "seasons": SEASONS,
        "planYears": [str(y) for y in range(this_year + 1, 2019, -1)],
        "columns": [{"key": c, "label": label, "type": kind} for c, label, kind in COLUMNS],
        "pageSize": PAGE_SIZE,
        "maxMonths": MAX_MONTHS,
        "sheetRows": SHEET_ROWS,
    }
