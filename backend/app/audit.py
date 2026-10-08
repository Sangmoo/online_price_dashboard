"""관리자 변경 이력: 누가 · 언제 · 어디서 · 무엇을 · 어떻게(이전 → 이후) 바꿨는지 기록하고 조회한다.

저장소: Oracle T_ERP_WEB_ADMIN_LOG (db/create_erp_web_admin_log.sql). 테이블이 없으면 서버 로컬 SQLite 에 기록하고,
테이블이 생기면 1분 안에 Oracle 을 쓰며 SQLite 기록을 한 번 옮긴다(Oracle 이 비어 있을 때만).
기록 실패가 관리자 작업 자체를 막지 않도록, 실패는 서버 로그에만 남긴다.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

import oracledb

from . import auth, db, logs, store

_log = logs.get("audit")
ORA_TABLE = "T_ERP_WEB_ADMIN_LOG"

ACTIONS = {
    "USER_CREATE": "사용자 추가",
    "USER_UPDATE": "사용자 설정 변경",
    "PERM_UPDATE": "메뉴 권한 변경",
    "SETTING_UPDATE": "AI 전역 설정 변경",
    "TOOL_BUILTIN": "기본 AI 도구 설정",
    "TOOL_CREATE": "AI 도구 추가",
    "TOOL_UPDATE": "AI 도구 수정",
    "TOOL_DELETE": "AI 도구 삭제",
    "LOCK_RELEASE": "로그인 잠금 해제",
    "SESSION_KILL": "세션 강제 로그아웃",
    "MV_REFRESH": "사전 집계 뷰 갱신",
    "STOCK_BASE_REFRESH": "매장 재고 기준 재집계",
    "SETTINGS_RESTORE": "설정 복원",
    "FEEDBACK_UPDATE": "문의·신고 처리",
    "MALL_SHOP_MAP": "판매처 매장 연결",
    "ONLINE_SHOP_FILL": "온라인 수집 매장코드 채우기",
    "NOTICE_SAVE": "공지 등록·수정",
    "NOTICE_DELETE": "공지 삭제",
    "MAINTENANCE": "점검 모드",
    "STOCK_RT_INDC": "본사지시 RT 지시 등록",
    "STOCK_RT_DEL": "본사지시 RT 지시 삭제",
    "STOCK_ALLOC_ASK": "배분의뢰 등록",
    "STOCK_ALLOC_DEL": "배분의뢰 삭제",
    "ROLE_SAVE": "권한 묶음 등록·수정",
    "ROLE_DELETE": "권한 묶음 삭제",
    "VIEW_AS": "사용자 화면 미리보기",
}
FIELD_LABELS = {
    "on": "점검 모드", "message": "안내 문구", "until": "종료 예정", "title": "제목", "level": "구분", "start": "게시 시작",
    "end": "게시 종료", "use": "사용", "body": "내용",
    "role": "권한", "pages": "메뉴 권한", "ai_enabled": "AI 사용", "daily_questions": "일일 질문 한도",
    "daily_cost_usd": "일일 비용 한도($)", "active": "계정 사용", "usr_nm": "이름", "brands": "브랜드 권한",
    "ai_enabled_global": "AI 기능", "default_daily_questions": "기본 질문 한도", "default_daily_cost_usd": "기본 비용 한도($)",
    "model": "모델", "effort": "effort", "auto_model": "모델 자동 선택", "simple_model": "단순 조회 모델", "enabled": "사용", "extraDesc": "추가 안내", "description": "설명",
    "label": "표시 이름", "page": "연결 메뉴", "sql": "SQL", "params": "입력값", "maxRows": "최대 행",
    "lastRefresh": "마지막 갱신", "staleness": "상태", "rows": "행 수", "maxMonth": "최신 월",
    "status": "상태", "answer": "답변", "log_keep_days": "로그 보관(일)", "feedback_img_keep_months": "문의 이미지 보관(개월)",
}

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    log_day     TEXT NOT NULL,
    admin_id    TEXT NOT NULL,
    action_cd   TEXT NOT NULL,
    target      TEXT,
    summary     TEXT,
    before_json TEXT,
    after_json  TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS ix_admin_log_day ON admin_log(log_day);
"""

_state: tuple[float, bool] | None = None
_state_lock = threading.Lock()


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _fmt14(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}" if v and len(v) >= 14 else v


def _lob(v):
    return v.read() if hasattr(v, "read") else v


def _sqlite() -> None:
    store.conn().executescript(SQLITE_SCHEMA)


def use_oracle() -> bool:
    global _state
    now = time.time()
    with _state_lock:
        if _state and _state[0] > now:
            return _state[1]
    try:
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {ORA_TABLE} WHERE 1 = 0")
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    first = ok and not (_state and _state[1])
    with _state_lock:
        _state = (now + 60, ok)
    if first and os.getenv("ERP_NO_AUTO_MIGRATE") != "1":
        _migrate()
    return ok


def backend_name() -> str:
    return "oracle" if use_oracle() else "sqlite"


# ----------------------------------------------------------------------------
# 요약 문장
# ----------------------------------------------------------------------------
def _show(k: str, v) -> str:
    if v is None or v == "":
        return "기본값" if k in ("daily_questions", "daily_cost_usd") else "(없음)"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if k == "brands" and isinstance(v, list):
        return ", ".join(v) or "모든 브랜드"
    if k == "pages" and isinstance(v, list):
        return ", ".join(auth.PAGE_LABELS.get(p, p) for p in v) or "(없음)"
    if k == "page":
        return auth.PAGE_LABELS.get(v, v)
    if k in ("sql", "description", "extraDesc") and isinstance(v, str) and len(v) > 40:
        return v[:40] + "…"
    if isinstance(v, list):
        return f"{len(v)}개"
    return str(v)


def diff_summary(before: dict | None, after: dict | None) -> str:
    before, after = before or {}, after or {}
    parts = []
    for k in list(dict.fromkeys(list(after) + list(before))):
        b, a = before.get(k), after.get(k)
        if isinstance(b, list) and isinstance(a, list) and sorted(map(str, b)) == sorted(map(str, a)):
            continue
        if b == a:
            continue
        parts.append(f"{FIELD_LABELS.get(k, k)}: {_show(k, b)} → {_show(k, a)}")
    return " / ".join(parts)


# ----------------------------------------------------------------------------
# 기록 · 조회
# ----------------------------------------------------------------------------
def record(admin: dict, action: str, target: str | None, before: dict | None = None, after: dict | None = None,
           summary: str | None = None) -> None:
    """관리자 작업 기록. 바뀐 게 없으면(변경 전후 동일) 남기지 않는다."""
    try:
        text = summary if summary is not None else diff_summary(before, after)
        if before is not None and after is not None and not text:
            return
        row = {"log_day": _now14(), "admin_id": admin.get("id", "-"), "action_cd": action, "target": (target or "")[:100],
               "summary": (text or "")[:1000], "before_json": json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
               "after_json": json.dumps(after, ensure_ascii=False, default=str) if after is not None else None, "ip": admin.get("ip")}
        if use_oracle():
            with db.get_pool().acquire() as conn, conn.cursor() as cur:
                cur.setinputsizes(b=oracledb.DB_TYPE_CLOB, a=oracledb.DB_TYPE_CLOB)
                cur.execute(f"""INSERT INTO {ORA_TABLE} (LOG_ID, LOG_DAY, ADMIN_ID, ACTION_CD, TARGET, SUMMARY, BEFORE_JSON, AFTER_JSON, IP)
                                VALUES (SQ_ERP_WEB_ADMIN_LOG.NEXTVAL, :d, :u, :ac, :t, :s, :b, :a, :ip)""",
                            {"d": row["log_day"], "u": row["admin_id"], "ac": action, "t": row["target"], "s": row["summary"],
                             "b": row["before_json"], "a": row["after_json"], "ip": row["ip"]})
                conn.commit()
        else:
            _sqlite()
            store.execute("INSERT INTO admin_log(log_day, admin_id, action_cd, target, summary, before_json, after_json, ip) "
                          "VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
        _log.info("%s %s target=%s by=%s ip=%s | %s", action, ACTIONS.get(action, ""), target, row["admin_id"], row["ip"], row["summary"])
    except Exception:  # noqa: BLE001 - 이력 기록 실패가 관리자 작업을 막지 않게
        _log.exception("관리자 변경 이력 기록 실패: %s %s", action, target)


def search(action: str | None = None, q: str | None = None, days: int = 90, limit: int = 300) -> list[dict]:
    limit = max(1, min(limit, 1000))
    since = datetime.fromtimestamp(time.time() - max(1, min(days, 3650)) * 86400).strftime("%Y%m%d%H%M%S")
    if use_oracle():
        conds, p = ["LOG_DAY >= :since"], {"since": since}
        if action:
            conds.append("ACTION_CD = :ac")
            p["ac"] = action
        if q:
            conds.append("(ADMIN_ID LIKE :q OR TARGET LIKE :q OR SUMMARY LIKE :q)")
            p["q"] = f"%{q}%"
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            cur.execute(f"""SELECT * FROM (SELECT LOG_ID, LOG_DAY, ADMIN_ID, ACTION_CD, TARGET, SUMMARY, BEFORE_JSON, AFTER_JSON, IP
                              FROM {ORA_TABLE} WHERE {' AND '.join(conds)} ORDER BY LOG_ID DESC) WHERE ROWNUM <= {limit}""", p)
            rows = [(i, d, u, a, t, s, _lob(b), _lob(af), ip) for i, d, u, a, t, s, b, af, ip in cur.fetchall()]
    else:
        _sqlite()
        sql, params = "SELECT id, log_day, admin_id, action_cd, target, summary, before_json, after_json, ip FROM admin_log WHERE log_day >= ?", [since]
        if action:
            sql += " AND action_cd = ?"
            params.append(action)
        if q:
            sql += " AND (admin_id LIKE ? OR target LIKE ? OR summary LIKE ?)"
            params += [f"%{q}%"] * 3
        rows = [tuple(r.values()) for r in store.rows(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))]
    return [{"id": int(i), "ts": _fmt14(d), "adminId": u, "action": a, "actionLabel": ACTIONS.get(a, a), "target": t,
             "summary": s, "before": json.loads(b) if b else None, "after": json.loads(af) if af else None, "ip": ip}
            for i, d, u, a, t, s, b, af, ip in rows]


def _migrate() -> None:
    try:
        _sqlite()
        rows = store.rows("SELECT log_day, admin_id, action_cd, target, summary, before_json, after_json, ip FROM admin_log ORDER BY id")
        if not rows or db.query(f"SELECT COUNT(*) FROM {ORA_TABLE}")[1][0][0] > 0:
            return
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            cur.setinputsizes(b=oracledb.DB_TYPE_CLOB, a=oracledb.DB_TYPE_CLOB)
            for r in rows:
                cur.execute(f"""INSERT INTO {ORA_TABLE} (LOG_ID, LOG_DAY, ADMIN_ID, ACTION_CD, TARGET, SUMMARY, BEFORE_JSON, AFTER_JSON, IP)
                                VALUES (SQ_ERP_WEB_ADMIN_LOG.NEXTVAL, :d, :u, :ac, :t, :s, :b, :a, :ip)""",
                            {"d": r["log_day"], "u": r["admin_id"], "ac": r["action_cd"], "t": r["target"], "s": r["summary"],
                             "b": r["before_json"], "a": r["after_json"], "ip": r["ip"]})
            conn.commit()
        _log.info("관리자 변경 이력 %d건을 Oracle 로 옮겼습니다.", len(rows))
    except Exception:  # noqa: BLE001
        _log.exception("관리자 변경 이력 Oracle 이전 실패 (SQLite 기록은 그대로)")
