"""관리자 > 쿼리 성능: 기능별 쿼리 실행 시간 · 느린 쿼리 순위 · 화면 요청 응답 시간 · 실행 계획.

- 기능별 · 느린 쿼리(값 포함): sql_trace 메모리 통계 (서버 시작 또는 [초기화] 이후)
- 화면 요청 응답 시간 · 로그 기준 느린 쿼리: logs/app.log* (보관 기간 동안, 재시작과 무관)
- 실행 계획: 실제 계획(V$SQL 커서 캐시, DBMS_XPLAN.DISPLAY_CURSOR) + 예상 계획(EXPLAIN PLAN). 쿼리를 실행하지는 않는다.
"""
from __future__ import annotations

import hashlib
import re
import struct
import threading
import time
import uuid
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from . import db, logs, sql_catalog, sql_trace

TOP_SQL = 40
_log_cache: dict[int, tuple[float, dict]] = {}
_log_lock = threading.Lock()

# 요청 경로 → 메뉴 (앞부분이 가장 길게 맞는 것)
PATH_MENU = [
    ("/api/dashboard", "대시보드"), ("/api/dates", "온라인 가격 공통"), ("/api/rows", "일자별 상세"),
    ("/api/mall-shops", "판매처 매장 연결"), ("/api/sale-dashboard", "판매 현황"), ("/api/sale-monthly", "월별 매장별 판매 집계"),
    ("/api/invt-plans", "매장 재고 실사계획"), ("/api/products", "상품 팝업"), ("/api/shops", "매장 정보 팝업"),
    ("/api/notices", "공지사항"), ("/api/me", "마이페이지"), ("/api/prefs", "개인 설정"), ("/api/chat", "AI 질문"),
    ("/api/feedback", "문의 · 신고"), ("/api/admin", "관리자"), ("/api/auth", "로그인"), ("/api/export", "엑셀"),
]
_REQ = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) \w+\s+erp\.request\s+user=(\S+) (GET|POST|PUT|DELETE|PATCH) (\S+?)(?:\?\S*)? (\d{3}) (\d+)ms\s*$")
_SLOW_SQL = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) \w+\s+erp\.sql\s+\S+ (?:query|execute|AI도구 \S+) ([\d.]+)s \| binds=(\[.*?\]) \| (.*)$")
_WS = re.compile(r"\s+")


def _norm(sql: str) -> str:
    return _WS.sub(" ", sql).strip()


def _menu(path: str) -> str:
    best = ""
    label = "-"
    for prefix, name in PATH_MENU:
        if path.startswith(prefix) and len(prefix) > len(best):
            best, label = prefix, name
    return label


def _path_key(path: str) -> str:
    """/api/invt-plans/shops/S1234 → /api/invt-plans/shops/{id}"""
    return "/".join("{id}" if re.search(r"\d", seg) and seg != "api" else seg for seg in path.split("/"))


def _fn_index() -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for page, features in sql_catalog.CATALOG.items():
        for title, _, srcs in features:
            for s in srcs:
                if isinstance(s, str):
                    idx.setdefault(s, []).append((sql_catalog.page_label(page), title))
    return idx


def _owner(keys: list[str], idx: dict) -> str:
    """SQL 을 실행한 기능 함수: 호출 스택에서 사용 쿼리 목록에 있는 가장 가까운 함수, 없으면 가장 가까운 앱 함수"""
    return next((k for k in keys if k in idx), keys[0] if keys else "-")


def _pct(vals: list[int], p: float) -> int:
    if not vals:
        return 0
    s = sorted(vals)
    return s[min(len(s) - 1, int(round((len(s) - 1) * p)))]


# ----------------------------------------------------------------------------
# 메모리 통계 (서버 시작 이후)
# ----------------------------------------------------------------------------
def _live() -> dict:
    idx = _fn_index()
    rows = sql_trace.stats()
    funcs: dict[str, dict] = {}
    for st in rows:
        fn = _owner(st["keys"], idx)
        f = funcs.setdefault(fn, {"fn": fn, "count": 0, "totalMs": 0, "maxMs": 0, "slow": 0, "sqls": 0, "lastAt": None})
        f["count"] += st["count"]
        f["totalMs"] += st["total_ms"]
        f["maxMs"] = max(f["maxMs"], st["max_ms"])
        f["slow"] += st["slow"]
        f["sqls"] += 1
        f["lastAt"] = max(f["lastAt"] or "", st["last_at"])
    for f in funcs.values():
        f["avgMs"] = round(f["totalMs"] / f["count"]) if f["count"] else 0
        f["where"] = [{"menu": m, "feature": t} for m, t in idx.get(f["fn"], [])]
    top = sorted(rows, key=lambda st: (st["max_ms"], st["total_ms"]), reverse=True)[:TOP_SQL]
    slow = []
    for st in top:
        sql = sql_catalog.tidy(st["sql"])
        fn = _owner(st["keys"], idx)
        slow.append({"sql": sql, "raw": st["sql"], "filled": sql_catalog.fill_binds(sql, st.get("max_binds") or {}), "fn": fn,
                     "where": [{"menu": m, "feature": t} for m, t in idx.get(fn, [])],
                     "count": st["count"], "avgMs": round(st["total_ms"] / st["count"]) if st["count"] else 0,
                     "maxMs": st["max_ms"], "maxAt": st.get("max_at"), "maxUsr": st.get("max_usr"), "slow": st["slow"],
                     "lastAt": st.get("last_at")})
    return {"funcs": sorted(funcs.values(), key=lambda f: f["totalMs"], reverse=True), "slowSql": slow}


# ----------------------------------------------------------------------------
# 로그 (보관 기간 동안)
# ----------------------------------------------------------------------------
def _log_files(days: int) -> list:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    out = []
    for p in sorted(logs.LOG_DIR.glob("app.log*")):
        suffix = p.name[len("app.log."):] if p.name.startswith("app.log.") else None
        if suffix is None or (re.match(r"^\d{4}-\d\d-\d\d$", suffix) and suffix >= since):
            out.append(p)
    return out


def _from_logs(days: int) -> dict:
    with _log_lock:
        hit = _log_cache.get(days)
        if hit and hit[0] > time.time():
            return hit[1]
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    req: dict[tuple[str, str], list[int]] = {}
    req_slow: dict[tuple[str, str], int] = {}
    req_last: dict[tuple[str, str], str] = {}
    daily: dict[str, dict] = {}
    sqls: dict[str, dict] = {}
    for p in _log_files(days):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if "erp.request" in line:
                m = _REQ.match(line)
                if not m or m.group(1) < since:
                    continue
                day, hm, _, method, path, status, ms = m.groups()
                if path in ("/api/health", "/api/auth/touch"):
                    continue
                k = (method, _path_key(path))
                ms_i = int(ms)
                req.setdefault(k, []).append(ms_i)
                req_last[k] = f"{day} {hm}"
                d = daily.setdefault(day, {"day": day, "requests": 0, "slow": 0, "ms": []})
                d["requests"] += 1
                d["ms"].append(ms_i)
                if ms_i >= logs.SLOW_REQUEST_SEC * 1000:
                    req_slow[k] = req_slow.get(k, 0) + 1
                    d["slow"] += 1
            elif "erp.sql" in line:
                m = _SLOW_SQL.match(line)
                if not m or m.group(1) < since:
                    continue
                day, hm, sec, binds, sql = m.groups()
                s = sqls.setdefault(sql, {"sql": sql, "count": 0, "maxMs": 0, "totalMs": 0, "binds": binds, "lastAt": None,
                                          "truncated": sql.endswith(" …")})
                ms_i = round(float(sec) * 1000)
                s["count"] += 1
                s["totalMs"] += ms_i
                s["maxMs"] = max(s["maxMs"], ms_i)
                s["lastAt"] = f"{day} {hm}"
    requests = []
    for (method, path), vals in req.items():
        requests.append({"method": method, "path": path, "menu": _menu(path), "count": len(vals), "avgMs": round(sum(vals) / len(vals)),
                         "p95Ms": _pct(vals, 0.95), "maxMs": max(vals), "slow": req_slow.get((method, path), 0),
                         "lastAt": req_last.get((method, path))})
    requests.sort(key=lambda r: (r["slow"], r["p95Ms"]), reverse=True)
    days_out = [{"day": d["day"], "requests": d["requests"], "slow": d["slow"], "p95Ms": _pct(d["ms"], 0.95),
                 "avgMs": round(sum(d["ms"]) / len(d["ms"])) if d["ms"] else 0} for d in sorted(daily.values(), key=lambda d: d["day"])]
    log_sql = sorted(sqls.values(), key=lambda s: (s["maxMs"], s["count"]), reverse=True)[:TOP_SQL]
    for s in log_sql:
        s["avgMs"] = round(s["totalMs"] / s["count"]) if s["count"] else 0
        s.pop("totalMs", None)
    out = {"requests": requests[:200], "daily": days_out, "logSlowSql": log_sql}
    with _log_lock:
        _log_cache[days] = (time.time() + 60, out)
    return out


def report(days: int = 7) -> dict:
    if days not in (1, 3, 7, 14, 30):
        raise HTTPException(400, {"message": "기간은 1, 3, 7, 14, 30일 중 하나입니다.", "code": "BAD_REQUEST"})
    return {"since": sql_trace.stats_since, "serverStarted": sql_trace.started, "slowSqlSec": logs.SLOW_SQL_SEC,
            "slowRequestSec": logs.SLOW_REQUEST_SEC, "days": days, **_live(), **_from_logs(days)}


def clear() -> dict:
    sql_trace.clear_stats()
    return {"since": sql_trace.stats_since}


# ----------------------------------------------------------------------------
# 실행 계획
# ----------------------------------------------------------------------------
_B32 = "0123456789abcdfghjkmnpqrstuvwxyz"
_TOKEN = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"|--[^\n]*|/\*.*?\*/|([;{}])", re.S)
_DML = re.compile(r"^\s*\(?\s*(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE)\b", re.I)


def sql_id(text: str, encoding: str = "utf-8") -> str:
    """Oracle SQL_ID (문장 + NUL 의 MD5 뒤 8바이트를 32진수 13자리로)"""
    h = hashlib.md5(text.encode(encoding, errors="replace") + b"\x00").digest()
    msb, lsb = struct.unpack("<II", h[8:16])
    n = msb * 2 ** 32 + lsb
    out = ""
    for _ in range(13):
        out = _B32[n % 32] + out
        n //= 32
    return out


def _bad(msg: str):
    raise HTTPException(400, {"message": msg, "code": "BAD_REQUEST"})


def _check(sql: str) -> str:
    sql = (sql or "").strip()
    sql = re.sub(r";\s*$", "", sql)
    if not sql:
        _bad("SQL 이 비어 있습니다.")
    if len(sql) > 100_000:
        _bad("SQL 이 너무 깁니다.")
    if sql.endswith("…"):
        _bad("로그에 앞부분만 남은 SQL 이라 실행 계획을 볼 수 없습니다. 화면에서 다시 조회한 뒤 '사용 쿼리' 나 느린 쿼리 순위에서 보세요.")
    if not _DML.match(sql):
        _bad("SELECT · WITH · INSERT · UPDATE · DELETE · MERGE 문만 실행 계획을 볼 수 있습니다.")
    for m in _TOKEN.finditer(sql):
        if m.group(1) == ";":
            _bad("문장 하나만 넣으세요 (; 로 이어진 여러 문장은 안 됩니다).")
        if m.group(1) in ("{", "}"):
            _bad("코드 기준 SQL ({ } 부분)은 실행 계획을 볼 수 없습니다. 화면에서 조회한 뒤 실제 실행 쿼리로 보세요.")
    return sql


def _actual(cur, texts: list[str]) -> dict | None:
    """커서 캐시(V$SQL)에 있으면 실제로 쓰인 계획과 실행 통계. 권한이 없거나 캐시에서 밀려났으면 None.
    SQL_ID 는 앱이 보낸 문장 그대로(공백 · 줄바꿈 포함)로 계산해야 맞으므로 원문을 받는다."""
    from .invt_plan import _db_encoding

    ids = list(dict.fromkeys(sql_id(t, enc) for t in texts for enc in ("utf-8", _db_encoding())))
    try:
        cur.execute(f"""SELECT SQL_ID, CHILD_NUMBER, PLAN_HASH_VALUE, EXECUTIONS, ROUND(ELAPSED_TIME / 1000) AS ELAPSED_MS,
                               BUFFER_GETS, DISK_READS, ROWS_PROCESSED, TO_CHAR(LAST_ACTIVE_TIME, 'YYYY-MM-DD HH24:MI:SS') AS LAST_ACTIVE
                          FROM V$SQL WHERE SQL_ID IN ({', '.join(f':i{n}' for n in range(len(ids)))})
                         ORDER BY LAST_ACTIVE_TIME DESC""", {f"i{n}": v for n, v in enumerate(ids)})
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        if not rows:
            return None
        r = rows[0]
        cur.execute("SELECT PLAN_TABLE_OUTPUT FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(:i, :c, 'TYPICAL +PEEKED_BINDS'))",
                    {"i": r["SQL_ID"], "c": r["CHILD_NUMBER"]})
        plan = "\n".join(x[0] or "" for x in cur.fetchall())
        ex = sum(int(x["EXECUTIONS"] or 0) for x in rows)
        el = sum(int(x["ELAPSED_MS"] or 0) for x in rows)
        return {"sqlId": r["SQL_ID"], "planHash": int(r["PLAN_HASH_VALUE"] or 0), "children": len(rows), "executions": ex,
                "avgMs": round(el / ex) if ex else None, "bufferGets": int(sum(int(x["BUFFER_GETS"] or 0) for x in rows) / ex) if ex else None,
                "diskReads": int(sum(int(x["DISK_READS"] or 0) for x in rows) / ex) if ex else None,
                "rows": int(sum(int(x["ROWS_PROCESSED"] or 0) for x in rows) / ex) if ex else None,
                "lastActive": r["LAST_ACTIVE"], "plan": plan}
    except Exception as ex:  # noqa: BLE001 - V$SQL 권한이 없을 수 있다
        return {"error": str(ex).splitlines()[0][:200]}


def explain(sql: str) -> dict:
    """실행 계획 (쿼리는 실행하지 않음). sql 은 앱이 보낸 문장 그대로(바인드 변수 포함) 또는 값이 채워진 문장."""
    text = _check(sql)
    sid = "ERPW" + uuid.uuid4().hex[:20].upper()
    out: dict = {"sqlId": sql_id(sql or "")}
    with db.timed(text, None, "실행 계획"), db.get_pool().acquire() as conn, conn.cursor() as cur:
        out["actual"] = _actual(cur, list(dict.fromkeys([sql or "", text])))
        try:
            cur.execute(f"EXPLAIN PLAN SET STATEMENT_ID = '{sid}' FOR {text}")
            cur.execute("SELECT PLAN_TABLE_OUTPUT FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', :s, 'TYPICAL'))", {"s": sid})
            out["estimate"] = {"plan": "\n".join(x[0] or "" for x in cur.fetchall())}
        except Exception as ex:  # noqa: BLE001 - 문법 오류 · 권한 등은 화면에 그대로 보여준다
            out["estimate"] = {"error": str(ex).splitlines()[0][:300]}
        finally:
            try:
                cur.execute("DELETE FROM PLAN_TABLE WHERE STATEMENT_ID = :s", {"s": sid})
                conn.commit()
            except Exception:  # noqa: BLE001
                conn.rollback()
    out["at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return out
