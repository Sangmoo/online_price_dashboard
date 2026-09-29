"""서비스 운영 데이터 저장소: 로그인 세션 · 로그인 잠금/기록 · AI 대화 · 즐겨찾기 · 개인 화면 설정.

Oracle 테이블(db/create_erp_web_session.sql)이 있으면 Oracle 을 쓰고, 없으면(다른 PC·테스트) 서버 로컬 SQLite 를 쓴다.
Oracle 을 처음 쓰게 될 때 SQLite 에 있던 내용을 한 번 옮긴다(Oracle 이 비어 있을 때만).

- 세션 토큰은 원문 대신 SHA-256 해시로 저장한다 (DB 가 노출돼도 세션 탈취 불가).
- 세션 만료 연장은 요청마다 쓰지 않고 TOUCH_INTERVAL 초에 한 번만 DB 에 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime

import oracledb

from . import db, logs, store

_log = logs.get("app")
TOUCH_INTERVAL = 60
_ORA_TABLES = ["T_ERP_WEB_SESSION", "T_ERP_WEB_LOGIN_LOCK", "T_ERP_WEB_LOGIN_LOG", "T_ERP_WEB_AI_CONV", "T_ERP_WEB_AI_FAV",
               "T_ERP_WEB_USER_PREF"]

_state: tuple[float, bool] | None = None
_state_lock = threading.Lock()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _fmt14(v: str | None) -> str | None:
    if not v or len(v) < 14:
        return v
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}"


def _lob(v):
    return v.read() if hasattr(v, "read") else v


def use_oracle() -> bool:
    """Oracle 테이블 사용 가능 여부 (1분 캐시). 처음 가능해지면 SQLite 내용을 옮긴다."""
    global _state
    now = time.time()
    with _state_lock:
        if _state and _state[0] > now:
            return _state[1]
    try:
        with db.get_pool().acquire() as conn, conn.cursor() as cur:  # 조용히 확인 (없는 동안 오류 로그를 쌓지 않음)
            for t in _ORA_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {t} WHERE 1 = 0")
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    first = ok and not (_state and _state[1])
    with _state_lock:
        _state = (now + 60, ok)
    if first:
        _migrate_from_sqlite()
    return ok


def backend_name() -> str:
    return "oracle" if use_oracle() else "sqlite"


def _ora_exec(sql: str, params: dict, clobs: tuple[str, ...] = ()) -> int:
    with db.timed(sql, params, "execute"), db.get_pool().acquire() as conn:
        with conn.cursor() as cur:
            if clobs:
                cur.setinputsizes(**{k: oracledb.DB_TYPE_CLOB for k in clobs})
            cur.execute(sql, params)
            n = cur.rowcount
        conn.commit()
        return n


# ----------------------------------------------------------------------------
# 세션
# ----------------------------------------------------------------------------
def session_create(token: str, sid: str, usr_id: str, now: float, expires: float, ip: str | None, ua: str | None) -> None:
    h = token_hash(token)
    if use_oracle():
        _ora_exec("""INSERT INTO T_ERP_WEB_SESSION (TOKEN_HASH, SID, USR_ID, CREATED_TS, LAST_SEEN_TS, EXPIRES_TS, IP, USER_AGENT)
                     VALUES (:h, :sid, :u, :c, :l, :e, :ip, :ua)""",
                  {"h": h, "sid": sid, "u": usr_id, "c": now, "l": now, "e": expires, "ip": ip, "ua": (ua or "")[:200]})
    else:
        store.execute("INSERT INTO sessions(token, sid, usr_id, created_at, last_seen, expires_at, ip, user_agent) VALUES(?,?,?,?,?,?,?,?)",
                      (h, sid, usr_id, now, now, expires, ip, (ua or "")[:200]))


def session_get(token: str) -> dict | None:
    h = token_hash(token)
    if use_oracle():
        r = db.query_dicts("""SELECT SID, USR_ID, CREATED_TS, LAST_SEEN_TS, EXPIRES_TS, IP, USER_AGENT
                                FROM T_ERP_WEB_SESSION WHERE TOKEN_HASH = :h""", {"h": h})
        if not r:
            return None
        r = r[0]
        return {"sid": r["SID"], "usr_id": r["USR_ID"], "created_at": float(r["CREATED_TS"]), "last_seen": float(r["LAST_SEEN_TS"]),
                "expires_at": float(r["EXPIRES_TS"]), "ip": r["IP"], "user_agent": r["USER_AGENT"]}
    return store.row("SELECT sid, usr_id, created_at, last_seen, expires_at, ip, user_agent FROM sessions WHERE token=?", (h,))


def session_touch(token: str, now: float, expires: float) -> None:
    h = token_hash(token)
    if use_oracle():
        _ora_exec("UPDATE T_ERP_WEB_SESSION SET LAST_SEEN_TS = :l, EXPIRES_TS = :e WHERE TOKEN_HASH = :h", {"l": now, "e": expires, "h": h})
    else:
        store.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE token=?", (now, expires, h))


def session_delete(token: str) -> None:
    h = token_hash(token)
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_SESSION WHERE TOKEN_HASH = :h", {"h": h})
    else:
        store.execute("DELETE FROM sessions WHERE token=?", (h,))


def session_delete_sid(sid: str) -> None:
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_SESSION WHERE SID = :s", {"s": sid})
    else:
        store.execute("DELETE FROM sessions WHERE sid=?", (sid,))


def session_delete_user(usr_id: str) -> None:
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_SESSION WHERE USR_ID = :u", {"u": usr_id})
    else:
        store.execute("DELETE FROM sessions WHERE usr_id=?", (usr_id,))


def session_purge(now: float) -> None:
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_SESSION WHERE EXPIRES_TS < :n", {"n": now})
    else:
        store.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))


def sessions_active(now: float) -> list[dict]:
    if use_oracle():
        return [{"sid": r["SID"], "usr_id": r["USR_ID"], "created_at": float(r["CREATED_TS"]), "last_seen": float(r["LAST_SEEN_TS"]),
                 "expires_at": float(r["EXPIRES_TS"]), "ip": r["IP"], "user_agent": r["USER_AGENT"]}
                for r in db.query_dicts("""SELECT SID, USR_ID, CREATED_TS, LAST_SEEN_TS, EXPIRES_TS, IP, USER_AGENT
                                             FROM T_ERP_WEB_SESSION WHERE EXPIRES_TS > :n ORDER BY LAST_SEEN_TS DESC""", {"n": now})]
    return store.rows("""SELECT sid, usr_id, created_at, last_seen, expires_at, ip, user_agent
                           FROM sessions WHERE expires_at > ? ORDER BY last_seen DESC""", (now,))


def online_user_ids(now: float) -> set[str]:
    return {s["usr_id"] for s in sessions_active(now)}


# ----------------------------------------------------------------------------
# 로그인 잠금 · 기록
# ----------------------------------------------------------------------------
def lock_get(usr_id: str) -> dict:
    if use_oracle():
        r = db.query("SELECT FAIL_CNT, LOCK_TS FROM T_ERP_WEB_LOGIN_LOCK WHERE USR_ID = :u", {"u": usr_id})[1]
        return {"fail_count": int(r[0][0]), "locked_until": float(r[0][1])} if r else {"fail_count": 0, "locked_until": 0}
    return store.row("SELECT fail_count, locked_until FROM login_attempts WHERE usr_id=?", (usr_id,)) or {"fail_count": 0, "locked_until": 0}


def lock_set(usr_id: str, fail_count: int, locked_until: float) -> None:
    if use_oracle():
        _ora_exec("""MERGE INTO T_ERP_WEB_LOGIN_LOCK T USING (SELECT :u AS USR_ID FROM DUAL) S ON (T.USR_ID = S.USR_ID)
                     WHEN MATCHED THEN UPDATE SET FAIL_CNT = :f, LOCK_TS = :l
                     WHEN NOT MATCHED THEN INSERT (USR_ID, FAIL_CNT, LOCK_TS) VALUES (:u, :f, :l)""",
                  {"u": usr_id, "f": fail_count, "l": locked_until})
    else:
        store.execute("""INSERT INTO login_attempts(usr_id, fail_count, locked_until) VALUES(?,?,?)
                         ON CONFLICT(usr_id) DO UPDATE SET fail_count=excluded.fail_count, locked_until=excluded.locked_until""",
                      (usr_id, fail_count, locked_until))


def lock_clear(usr_id: str) -> None:
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_LOGIN_LOCK WHERE USR_ID = :u", {"u": usr_id})
    else:
        store.execute("DELETE FROM login_attempts WHERE usr_id=?", (usr_id,))


def locks_list(now: float) -> list[dict]:
    if use_oracle():
        rows = db.query("""SELECT USR_ID, FAIL_CNT, LOCK_TS FROM T_ERP_WEB_LOGIN_LOCK
                            WHERE FAIL_CNT > 0 OR LOCK_TS > :n ORDER BY LOCK_TS DESC""", {"n": now})[1]
        return [{"usr_id": u, "fail_count": int(f), "locked_until": float(l)} for u, f, l in rows]
    return store.rows("""SELECT usr_id, fail_count, locked_until FROM login_attempts
                          WHERE fail_count > 0 OR locked_until > ? ORDER BY locked_until DESC""", (now,))


def login_log_add(usr_id: str, success: bool, reason: str, ip: str | None) -> None:
    if use_oracle():
        _ora_exec("""INSERT INTO T_ERP_WEB_LOGIN_LOG (LOG_ID, USR_ID, LOGIN_DAY, SUCCESS_YN, REASON_CD, IP)
                     VALUES (SQ_ERP_WEB_LOGIN_LOG.NEXTVAL, :u, :d, :s, :r, :ip)""",
                  {"u": usr_id[:20], "d": _now14(), "s": "Y" if success else "N", "r": reason, "ip": ip})
    else:
        store.execute("INSERT INTO login_log(usr_id, success, reason, ip) VALUES(?,?,?,?)", (usr_id, int(success), reason, ip))


def login_log_list(limit: int, q: str | None) -> list[dict]:
    limit = max(1, min(limit, 1000))
    if use_oracle():
        where, p = ("WHERE USR_ID LIKE :q", {"q": f"%{q}%"}) if q else ("", {})
        rows = db.query(f"""SELECT * FROM (SELECT LOG_ID, USR_ID, LOGIN_DAY, SUCCESS_YN, REASON_CD, IP FROM T_ERP_WEB_LOGIN_LOG
                             {where} ORDER BY LOG_ID DESC) WHERE ROWNUM <= {limit}""", p)[1]
        return [{"id": int(i), "usr_id": u, "ts": _fmt14(d), "success": 1 if s == "Y" else 0, "reason": r, "ip": ip}
                for i, u, d, s, r, ip in rows]
    sql, params = "SELECT id, usr_id, ts, success, reason, ip FROM login_log", ()
    if q:
        sql += " WHERE usr_id LIKE ?"
        params = (f"%{q}%",)
    return store.rows(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))


# ----------------------------------------------------------------------------
# AI 대화
# ----------------------------------------------------------------------------
def conv_list(usr_id: str) -> list[dict]:
    if use_oracle():
        rows = db.query("""SELECT * FROM (SELECT CONV_ID, TITLE, INS_DAY, UPT_DAY FROM T_ERP_WEB_AI_CONV
                            WHERE USR_ID = :u ORDER BY UPT_DAY DESC) WHERE ROWNUM <= 100""", {"u": usr_id})[1]
        return [{"id": i, "title": t, "createdAt": _fmt14(c), "updatedAt": _fmt14(u)} for i, t, c, u in rows]
    return store.rows("SELECT id, title, created_at AS createdAt, updated_at AS updatedAt FROM conversations "
                      "WHERE usr_id=? ORDER BY updated_at DESC LIMIT 100", (usr_id,))


def conv_get(usr_id: str, conv_id: str) -> dict | None:
    """{'id','title','api_messages'(list),'display'(list),'updated_at'}"""
    if use_oracle():
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            cur.execute("""SELECT CONV_ID, TITLE, API_MESSAGES, DISPLAY_JSON, UPT_DAY FROM T_ERP_WEB_AI_CONV
                            WHERE CONV_ID = :c AND USR_ID = :u""", {"c": conv_id, "u": usr_id})
            r = cur.fetchone()
            if not r:
                return None
            i, t, api, disp, upd = r[0], r[1], _lob(r[2]), _lob(r[3]), r[4]
        return {"id": i, "title": t, "api_messages": json.loads(api or "[]"), "display": json.loads(disp or "[]"), "updated_at": _fmt14(upd)}
    r = store.row("SELECT id, title, api_messages, display, updated_at FROM conversations WHERE id=? AND usr_id=?", (conv_id, usr_id))
    if not r:
        return None
    return {"id": r["id"], "title": r["title"], "api_messages": json.loads(r["api_messages"]), "display": json.loads(r["display"]),
            "updated_at": r["updated_at"]}


def conv_create(conv_id: str, usr_id: str, title: str) -> None:
    if use_oracle():
        now = _now14()
        _ora_exec("""INSERT INTO T_ERP_WEB_AI_CONV (CONV_ID, USR_ID, TITLE, API_MESSAGES, DISPLAY_JSON, INS_DAY, UPT_DAY)
                     VALUES (:c, :u, :t, '[]', '[]', :d, :d)""", {"c": conv_id, "u": usr_id, "t": title[:300], "d": now})
    else:
        store.execute("INSERT INTO conversations(id, usr_id, title) VALUES(?,?,?)", (conv_id, usr_id, title))


def conv_save(conv_id: str, api_messages: list, display: list) -> None:
    api = json.dumps(api_messages, ensure_ascii=False, default=str)
    disp = json.dumps(display, ensure_ascii=False, default=str)
    if use_oracle():
        _ora_exec("UPDATE T_ERP_WEB_AI_CONV SET API_MESSAGES = :a, DISPLAY_JSON = :d, UPT_DAY = :t WHERE CONV_ID = :c",
                  {"a": api, "d": disp, "t": _now14(), "c": conv_id}, clobs=("a", "d"))
    else:
        store.execute("UPDATE conversations SET api_messages=?, display=?, updated_at=datetime('now','localtime') WHERE id=?",
                      (api, disp, conv_id))


def conv_delete(usr_id: str, conv_id: str) -> None:
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_AI_CONV WHERE CONV_ID = :c AND USR_ID = :u", {"c": conv_id, "u": usr_id})
    else:
        store.execute("DELETE FROM conversations WHERE id=? AND usr_id=?", (conv_id, usr_id))


def conv_rename(usr_id: str, conv_id: str, title: str) -> None:
    title = title.strip()[:80]
    if use_oracle():
        _ora_exec("UPDATE T_ERP_WEB_AI_CONV SET TITLE = :t WHERE CONV_ID = :c AND USR_ID = :u", {"t": title, "c": conv_id, "u": usr_id})
    else:
        store.execute("UPDATE conversations SET title=? WHERE id=? AND usr_id=?", (title, conv_id, usr_id))


# ----------------------------------------------------------------------------
# 즐겨찾기 · 개인 설정
# ----------------------------------------------------------------------------
def fav_list(usr_id: str) -> list[dict]:
    if use_oracle():
        rows = db.query("SELECT FAV_ID, FAV_TEXT, INS_DAY FROM T_ERP_WEB_AI_FAV WHERE USR_ID = :u ORDER BY FAV_ID DESC", {"u": usr_id})[1]
        return [{"id": int(i), "text": t, "createdAt": _fmt14(d)} for i, t, d in rows]
    return store.rows("SELECT id, text, created_at AS createdAt FROM favorites WHERE usr_id=? ORDER BY id DESC", (usr_id,))


def fav_add(usr_id: str, text: str) -> None:
    if use_oracle():
        try:
            _ora_exec("""INSERT INTO T_ERP_WEB_AI_FAV (FAV_ID, USR_ID, FAV_TEXT, FAV_HASH, INS_DAY)
                         SELECT SQ_ERP_WEB_AI_FAV.NEXTVAL, :u, :t, :h, :d FROM DUAL
                          WHERE NOT EXISTS (SELECT 1 FROM T_ERP_WEB_AI_FAV WHERE USR_ID = :u AND FAV_HASH = :h)""",
                      {"u": usr_id, "t": text, "h": hashlib.sha256(text.encode("utf-8")).hexdigest(), "d": _now14()})
        except oracledb.IntegrityError:
            pass  # 동시에 같은 질문을 저장한 경우
    else:
        store.execute("INSERT OR IGNORE INTO favorites(usr_id, text) VALUES(?,?)", (usr_id, text))


def fav_delete(usr_id: str, fav_id: int) -> None:
    if use_oracle():
        _ora_exec("DELETE FROM T_ERP_WEB_AI_FAV WHERE FAV_ID = :i AND USR_ID = :u", {"i": fav_id, "u": usr_id})
    else:
        store.execute("DELETE FROM favorites WHERE id=? AND usr_id=?", (fav_id, usr_id))


def pref_get(usr_id: str, key: str):
    if use_oracle():
        r = db.query("SELECT PREF_VAL FROM T_ERP_WEB_USER_PREF WHERE USR_ID = :u AND PREF_KEY = :k", {"u": usr_id, "k": key})[1]
        return json.loads(r[0][0]) if r and r[0][0] else None
    return store.get_pref(usr_id, key)


def pref_set(usr_id: str, key: str, value) -> None:
    val = json.dumps(value, ensure_ascii=False)
    if len(val.encode("utf-8")) > 4000:
        raise ValueError("설정 값이 너무 큽니다.")
    if use_oracle():
        _ora_exec("""MERGE INTO T_ERP_WEB_USER_PREF T USING (SELECT :u AS USR_ID, :k AS PREF_KEY FROM DUAL) S
                       ON (T.USR_ID = S.USR_ID AND T.PREF_KEY = S.PREF_KEY)
                     WHEN MATCHED THEN UPDATE SET PREF_VAL = :v, UPT_DAY = :d
                     WHEN NOT MATCHED THEN INSERT (USR_ID, PREF_KEY, PREF_VAL, UPT_DAY) VALUES (:u, :k, :v, :d)""",
                  {"u": usr_id, "k": key, "v": val, "d": _now14()})
    else:
        store.set_pref(usr_id, key, value)


# ----------------------------------------------------------------------------
# 1회: SQLite → Oracle
# ----------------------------------------------------------------------------
def _sqlite_ts14(v: str | None) -> str:
    """SQLite 'YYYY-MM-DD HH:MM:SS' → 'YYYYMMDDHHMISS'"""
    return (v or "").replace("-", "").replace(":", "").replace(" ", "")[:14] or _now14()


def _migrate_from_sqlite() -> None:
    if os.getenv("ERP_NO_AUTO_MIGRATE") == "1":  # 테스트·점검 스크립트에서는 실제 이전을 하지 않는다
        return
    if store.row("SELECT 1 FROM settings WHERE key='_migr_appdb_oracle'"):
        return
    try:
        if any(db.query(f"SELECT COUNT(*) FROM {t}")[1][0][0] for t in _ORA_TABLES):
            _log.info("운영 데이터 Oracle 이전 건너뜀 (Oracle 에 이미 데이터가 있음)")
        else:
            counts = {}
            now = time.time()
            with db.get_pool().acquire() as conn:
                cur = conn.cursor()
                s = store.rows("SELECT token, sid, usr_id, created_at, last_seen, expires_at, ip, user_agent FROM sessions WHERE expires_at > ?", (now,))
                for r in s:  # SQLite 는 토큰 원문을 저장해 왔으므로 해시로 바꿔 넣는다 → 로그인 유지
                    key = r["token"] if len(r["token"]) == 64 and all(c in "0123456789abcdef" for c in r["token"]) else token_hash(r["token"])
                    cur.execute("""INSERT INTO T_ERP_WEB_SESSION (TOKEN_HASH, SID, USR_ID, CREATED_TS, LAST_SEEN_TS, EXPIRES_TS, IP, USER_AGENT)
                                   VALUES (:h, :sid, :u, :c, :l, :e, :ip, :ua)""",
                                {"h": key, "sid": r["sid"], "u": r["usr_id"], "c": r["created_at"], "l": r["last_seen"],
                                 "e": r["expires_at"], "ip": r["ip"], "ua": r["user_agent"]})
                counts["sessions"] = len(s)
                la = store.rows("SELECT usr_id, fail_count, locked_until FROM login_attempts")
                for r in la:
                    cur.execute("INSERT INTO T_ERP_WEB_LOGIN_LOCK (USR_ID, FAIL_CNT, LOCK_TS) VALUES (:u, :f, :l)",
                                {"u": r["usr_id"][:20], "f": r["fail_count"], "l": r["locked_until"]})
                counts["locks"] = len(la)
                ll = store.rows("SELECT usr_id, ts, success, reason, ip FROM login_log ORDER BY id")
                for r in ll:
                    cur.execute("""INSERT INTO T_ERP_WEB_LOGIN_LOG (LOG_ID, USR_ID, LOGIN_DAY, SUCCESS_YN, REASON_CD, IP)
                                   VALUES (SQ_ERP_WEB_LOGIN_LOG.NEXTVAL, :u, :d, :s, :r, :ip)""",
                                {"u": r["usr_id"][:20], "d": _sqlite_ts14(r["ts"]), "s": "Y" if r["success"] else "N",
                                 "r": r["reason"], "ip": r["ip"]})
                counts["login_log"] = len(ll)
                cv = store.rows("SELECT id, usr_id, title, api_messages, display, created_at, updated_at FROM conversations")
                cur.setinputsizes(a=oracledb.DB_TYPE_CLOB, d=oracledb.DB_TYPE_CLOB)
                for r in cv:
                    cur.execute("""INSERT INTO T_ERP_WEB_AI_CONV (CONV_ID, USR_ID, TITLE, API_MESSAGES, DISPLAY_JSON, INS_DAY, UPT_DAY)
                                   VALUES (:c, :u, :t, :a, :d, :i, :p)""",
                                {"c": r["id"], "u": r["usr_id"], "t": (r["title"] or "")[:300], "a": r["api_messages"],
                                 "d": r["display"], "i": _sqlite_ts14(r["created_at"]), "p": _sqlite_ts14(r["updated_at"])})
                counts["conversations"] = len(cv)
                cur = conn.cursor()
                fv = store.rows("SELECT usr_id, text, created_at FROM favorites ORDER BY id")
                for r in fv:
                    cur.execute("""INSERT INTO T_ERP_WEB_AI_FAV (FAV_ID, USR_ID, FAV_TEXT, FAV_HASH, INS_DAY)
                                   VALUES (SQ_ERP_WEB_AI_FAV.NEXTVAL, :u, :t, :h, :d)""",
                                {"u": r["usr_id"], "t": r["text"], "h": hashlib.sha256(r["text"].encode("utf-8")).hexdigest(),
                                 "d": _sqlite_ts14(r["created_at"])})
                counts["favorites"] = len(fv)
                pf = store.rows("SELECT usr_id, key, value FROM prefs")
                for r in pf:
                    cur.execute("INSERT INTO T_ERP_WEB_USER_PREF (USR_ID, PREF_KEY, PREF_VAL, UPT_DAY) VALUES (:u, :k, :v, :d)",
                                {"u": r["usr_id"], "k": r["key"], "v": r["value"], "d": _now14()})
                counts["prefs"] = len(pf)
                conn.commit()
            _log.info("운영 데이터를 Oracle 로 옮겼습니다: %s", counts)
        store.execute("INSERT INTO settings(key, value) VALUES('_migr_appdb_oracle', 'true')")
    except Exception:  # noqa: BLE001 - 실패 시 롤백되고 SQLite 내용은 그대로 (서버 재시작 시 다시 시도)
        _log.exception("운영 데이터 Oracle 이전 실패 - 기존 SQLite 데이터는 그대로 남아 있습니다")
