"""관리자 > 스케줄 · 배치: 자동 작업의 마지막 실행 · 성공/실패 · 처리 결과 · 다음 실행.

- 앱 작업(이 서버가 돌리는 것): 실행할 때마다 Oracle T_ERP_WEB_JOB_RUN 에 기록한다 (90일 보관).
    테이블이 없으면 기록을 건너뛰고 화면에 DDL(db/create_erp_web_admin_ops.sql) 실행 안내를 보여준다.
    판매 현황 미리 계산(prewarm) · 사전 집계 뷰 갱신(mv_refresh) · 정리 작업(housekeeping) · 매장코드 채우기(화면 버튼)
- DB 스케줄(Oracle DBMS_SCHEDULER, SS10 소유): 앱 계정은 SS10 의 스케줄 이력을 직접 볼 수 없어서
    SS10 의 조회 함수 F_ERP_WEB_SCHED_JOBS / F_ERP_WEB_SCHED_RUNS (db/create_erp_web_admin_ops.sql) 를 부른다.
    함수가 없으면 '설정 필요' 로 보여준다.
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

from . import db, logs
from .tables import Tables

_log = logs.get("app")
KEEP_DAYS = 90

APP_JOBS: dict[str, dict[str, str]] = {
    "prewarm": {"label": "판매 현황 미리 계산", "schedule": "서버 시작 · 매일 07시 · 30분마다 데이터 변경 확인 · 뷰 갱신 직후"},
    "mv_refresh": {"label": "사전 집계 뷰 갱신", "schedule": "관리자 [지금 갱신] (월 마감 적재 후)"},
    "housekeeping": {"label": "정리 작업", "schedule": "6시간마다 (로그 · 엑셀 임시 파일 · 문의 이미지 · 다운로드 이력)"},
    "stock_base": {"label": "매장 재고 기준 재집계 (화면)", "schedule": "관리자 [지금 재집계] (스케줄 · 배치)"},
    "shop_fill": {"label": "매장코드 채우기 (화면)", "schedule": "일자별 상세 [매장코드 채우기] · 최근 7일"},
}
# DB 스케줄: 이름 → (표시 이름, 결과 확인 방법)
DB_JOBS: dict[str, dict[str, str]] = {
    "JOB_FILL_ONLINE_SHOP_ID": {"label": "온라인 수집 매장코드 채우기", "schedule": "매일 02:00 · 전일자",
                                "sql": "db/create_job_online_shop_id.sql"},
    "JOB_LOAD_CLOSE_SALE_BASE": {"label": "마감 매출 기초 데이터 적재", "schedule": "매월 1일 13:00 · 전월",
                                 "sql": "db/create_job_close_sale_base_monthly.sql"},
    "JOB_ERP_WEB_STOCK_BASE": {"label": "매장 재고 기준 집계 (재고 분석)", "schedule": "매일 06:30 · 이번 달 매장 재고",
                               "sql": "db/create_erp_web_stock_base.sql"},
}
SCHED_FUNC_JOBS = "F_ERP_WEB_SCHED_JOBS"
SCHED_FUNC_RUNS = "F_ERP_WEB_SCHED_RUNS"

RUN_TABLE = "T_ERP_WEB_JOB_RUN"
tables = Tables(RUN_TABLE)
_lock = threading.Lock()
_db_cache: tuple[float, dict] | None = None
DB_CACHE_TTL = 60


def _ts(t: float | None = None) -> str:
    return datetime.fromtimestamp(t or time.time()).strftime("%Y%m%d%H%M%S")


def _fmt(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}" if v and len(v) >= 14 else v


def record(job: str, started: float, finished: float | None, status: str, detail: str | None = None,
           by: str | None = None) -> None:
    """작업 1회 결과 기록. 실패해도 예외를 내지 않는다."""
    try:
        if not tables.ready():
            return
        db.execute(f"""INSERT INTO {RUN_TABLE} (RUN_ID, JOB_CD, START_DAY, END_DAY, STATUS_CD, DETAIL, USR_ID)
                       VALUES (:rid, :job, :s, :e, :st, :d, :u)""",
                   {"rid": f"{time.time_ns():020d}{uuid.uuid4().hex[:8]}",   # 시각 순으로 정렬되는 ID
                    "job": job[:30], "s": _ts(started), "e": _ts(finished) if finished else None, "st": status,
                    "d": _cut((detail or "").strip() or None, 1000), "u": (by or None) and by[:20]})
    except Exception:  # noqa: BLE001
        _log.exception("작업 실행 기록 실패 job=%s", job)


class _Run:
    def __init__(self) -> None:
        self.detail: str | None = None
        self.failed: str | None = None   # 예외 없이 일부 실패한 경우


@contextmanager
def track(job: str, by: str | None = None) -> Iterator[_Run]:
    """with jobs.track('housekeeping') as run: ... run.detail = '...'  — 예외가 나면 error 로 기록하고 다시 던진다."""
    t0 = time.time()
    run = _Run()
    try:
        yield run
    except Exception as ex:
        record(job, t0, time.time(), "error", f"{str(ex).splitlines()[0] if str(ex) else type(ex).__name__}"
               + (f" · {run.detail}" if run.detail else ""), by)
        raise
    record(job, t0, time.time(), "error" if run.failed else "ok", " · ".join(x for x in (run.detail, run.failed) if x), by)


def _cut(s: str | None, max_bytes: int) -> str | None:
    if s is None:
        return None
    b = s.encode("utf-8")
    return s if len(b) <= max_bytes else b[:max_bytes].decode("utf-8", errors="ignore")


def purge(keep_days: int = KEEP_DAYS) -> int:
    if not tables.ready():
        return 0
    cut = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d") + "000000"
    return db.execute(f"DELETE FROM {RUN_TABLE} WHERE START_DAY < :c", {"c": cut})


_RUN_SELECT = f"SELECT JOB_CD, START_DAY, END_DAY, STATUS_CD, DETAIL, USR_ID FROM {RUN_TABLE}"


def _run_dict(r: dict) -> dict:
    return {"job": r["JOB_CD"], "started": _fmt(r["START_DAY"]), "finished": _fmt(r["END_DAY"]), "status": r["STATUS_CD"],
            "detail": r["DETAIL"], "by_user": r["USR_ID"]}


def _app_jobs(days: int) -> list[dict]:
    if not tables.ready():
        return [{"key": k, "kind": "app", **m, "last": None, "lastOk": None, "runs": [], "count": 0, "failures": 0, "status": "unknown"}
                for k, m in APP_JOBS.items()]
    since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d") + "000000"
    # RUN_ID 는 기록 시각 순이라 같은 초에 여러 번 실행돼도 나중 기록이 앞에 온다
    rows = [_run_dict(r) for r in db.query_dicts(f"{_RUN_SELECT} WHERE START_DAY >= :s ORDER BY START_DAY DESC, RUN_ID DESC", {"s": since})]
    lasts = {r["JOB_CD"]: _run_dict(r) for r in db.query_dicts(
        f"""{_RUN_SELECT} R WHERE START_DAY = (SELECT MAX(START_DAY) FROM {RUN_TABLE} X WHERE X.JOB_CD = R.JOB_CD) ORDER BY RUN_ID""")}
    out = []
    for key, meta in APP_JOBS.items():
        runs = [r for r in rows if r["job"] == key]
        last = runs[0] if runs else lasts.get(key)
        out.append({
            "key": key, "kind": "app", **meta,
            "last": _run_out(last) if last else None,
            "lastOk": next((_run_out(r) for r in runs if r["status"] == "ok"), None),
            "runs": [_run_out(r) for r in runs[:30]],
            "count": len(runs), "failures": sum(1 for r in runs if r["status"] == "error"),
            "status": "never" if not last else "error" if last["status"] == "error" else "ok",
        })
    return out


def _run_out(r: dict) -> dict:
    sec = None
    if r.get("finished") and r.get("started"):
        sec = round((datetime.strptime(r["finished"], "%Y-%m-%d %H:%M:%S")
                     - datetime.strptime(r["started"], "%Y-%m-%d %H:%M:%S")).total_seconds())
    return {"start": r["started"], "end": r.get("finished"), "status": r["status"], "detail": r.get("detail"),
            "by": r.get("by_user"), "sec": sec}


def _cursor_rows(func: str, args: list) -> list[dict]:
    import oracledb

    with db.get_pool().acquire() as conn, conn.cursor() as cur:
        rc = cur.callfunc(func, oracledb.DB_TYPE_CURSOR, args)
        cols = [d[0] for d in rc.description]
        return [dict(zip(cols, r)) for r in rc.fetchall()]


def _check_result(name: str) -> dict | None:
    """작업이 실제로 해 놓은 일 확인 (스케줄 이력에는 처리 건수가 없어서 결과 데이터를 본다)"""
    try:
        if name == "JOB_FILL_ONLINE_SHOP_ID":
            y = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            n, s = db.query("SELECT COUNT(*), COUNT(SHOP_ID) FROM T_SELECT_ONLINE_MNG_R WHERE DT = :d", {"d": y})[1][0]
            n, s = int(n or 0), int(s or 0)
            return {"label": f"전일({y[:4]}-{y[4:6]}-{y[6:]}) 수집 {n:,}건 중 매장코드 {s:,}건"
                             + (f" ({s * 100 / n:.1f}%)" if n else ""), "warn": n > 0 and s == 0}
        if name == "JOB_LOAD_CLOSE_SALE_BASE":
            from . import mv_refresh

            f = mv_refresh.freshness()
            prev = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y%m")
            base = f.get("baseMaxMonth")
            late = datetime.now().day > 1 or datetime.now().hour >= 14
            return {"label": f"원본 최신 판매년월 {base or '-'} · 사전 집계 뷰 {f.get('mvMaxMonth') or '-'}",
                    "warn": bool(late and base and base < prev)}
        if name == "JOB_ERP_WEB_STOCK_BASE":
            from . import stock_base

            st = stock_base.status()
            if not st["ready"]:
                return {"label": "집계 테이블을 쓸 수 없습니다", "warn": True}
            parts = [f"{b['brandNm']} {b['rows']:,}행 ({(b['baseDt'] or '')[5:16]})" if b["status"] == "OK" and b["rows"] is not None
                     else f"{b['brandNm']} {b['status'] or '기록 없음'}" for b in st["brands"]]
            return {"label": " · ".join(parts), "warn": any(not b["inUse"] for b in st["brands"])}
    except Exception as ex:  # noqa: BLE001
        return {"label": f"결과 확인 실패: {str(ex).splitlines()[0][:120]}", "warn": True}
    return None


def _db_jobs(days: int) -> dict:
    global _db_cache
    now = time.time()
    with _lock:
        hit = _db_cache
    if hit and hit[0] > now and hit[1]["days"] == days:
        return hit[1]
    names = ",".join(DB_JOBS)
    try:
        jobs = {r["JOB_NAME"]: r for r in _cursor_rows(SCHED_FUNC_JOBS, [names])}
        runs = _cursor_rows(SCHED_FUNC_RUNS, [names, days])
        ready, error = True, None
    except Exception as ex:  # noqa: BLE001
        msg = str(ex)
        ready = False
        error = ("조회 함수가 없습니다. db/create_erp_web_admin_ops.sql 의 스케줄 조회 함수를 SS10 에서 실행하세요."
                 if "PLS-00201" in msg or "ORA-06550" in msg or "ORA-00904" in msg else msg.splitlines()[0][:200])
        jobs, runs = {}, []
    out = []
    for name, meta in DB_JOBS.items():
        j = jobs.get(name)
        rs = [r for r in runs if r["JOB_NAME"] == name]
        last = rs[0] if rs else None
        next_run = j and j.get("NEXT_RUN")
        overdue = bool(j and j.get("ENABLED") == "TRUE" and next_run
                       and next_run < (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
        if not ready:
            status = "unknown"
        elif not j:
            status = "missing"
        elif j.get("ENABLED") != "TRUE":
            status = "disabled"
        elif last and last["STATUS"] != "SUCCEEDED":
            status = "error"
        elif overdue:
            status = "overdue"
        else:
            status = "ok" if last else "never"
        out.append({
            "key": name, "kind": "db", **meta, "status": status,
            "enabled": j.get("ENABLED") == "TRUE" if j else None, "state": j.get("STATE") if j else None,
            "nextRun": next_run, "lastStart": j.get("LAST_START") if j else None,
            "failureCount": int(j["FAILURE_COUNT"] or 0) if j else None, "runCount": int(j["RUN_COUNT"] or 0) if j else None,
            "repeat": j.get("REPEAT_INTERVAL") if j else None,
            "last": _db_run(last) if last else None,
            "runs": [_db_run(r) for r in rs[:30]],
            "failures": sum(1 for r in rs if r["STATUS"] != "SUCCEEDED"),
            "result": _check_result(name) if ready and j else None,
        })
    res = {"days": days, "ready": ready, "error": error, "jobs": out}
    with _lock:
        _db_cache = (now + DB_CACHE_TTL, res)
    return res


def _db_run(r: dict) -> dict:
    return {"start": r.get("ACTUAL_START"), "end": r.get("LOG_DATE"), "status": "ok" if r["STATUS"] == "SUCCEEDED" else "error",
            "rawStatus": r["STATUS"], "sec": int(r["DURATION_SEC"]) if r.get("DURATION_SEC") is not None else None,
            "detail": (r.get("ADDITIONAL_INFO") or None) if r["STATUS"] != "SUCCEEDED" else None,
            "errorNo": int(r["ERROR_NO"]) if r.get("ERROR_NO") else None}


def overview(days: int = 14) -> dict:
    days = max(1, min(int(days), 90))
    d = _db_jobs(days)
    app = _app_jobs(days)
    all_jobs = d["jobs"] + app
    bad = [j for j in all_jobs if j["status"] in ("error", "overdue", "missing", "disabled")
           or (j.get("result") or {}).get("warn")]
    return {"days": days, "db": d, "app": app, "appTable": tables.status(),
            "summary": {"total": len(all_jobs), "problems": len(bad), "problemNames": [j["label"] for j in bad],
                        "dbReady": d["ready"], "appReady": tables.ready()}}


def clear_cache() -> None:
    global _db_cache
    with _lock:
        _db_cache = None


def summary_for_home() -> dict[str, Any]:
    o = overview(7)
    return o["summary"]
