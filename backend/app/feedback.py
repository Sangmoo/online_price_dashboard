"""화면 내 문의·오류 신고: 사용자가 화면 오른쪽 위 버튼으로 남기면 현재 화면·조회 조건·최근 오류가 함께 저장되고,
관리자 화면(관리자 › 문의·신고)에서 상태(접수/처리 중/완료)와 답변을 남긴다. 사용자는 같은 창에서 내 문의와 답변을 본다.
이미지(화면 캡처 등)는 문의 하나에 최대 3개까지 첨부한다.

저장소: Oracle T_ERP_WEB_FEEDBACK + T_ERP_WEB_FEEDBACK_FILE (db/create_erp_web_feedback.sql, 기존 테이블은
db/alter_erp_web_feedback_files.sql). 두 테이블이 모두 없으면 서버 로컬 SQLite 에 저장하고, 생기면 1분 안에 Oracle 을 쓰며
SQLite 기록을 한 번 옮긴다 (menu_usage 와 같은 방식). 번호는 시각+난수 문자열이라 옮겨도 그대로.
내용·답변은 CLOB (VARCHAR2(4000) 은 바이트 기준이라 한글 1,333자를 넘으면 저장되지 않음). 아직 VARCHAR2 면 그 길이로 제한한다.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import threading
import time
from datetime import datetime

import oracledb
from fastapi import HTTPException

from . import config, db, logs, store

_log = logs.get("app")
ORA_TABLE = "T_ERP_WEB_FEEDBACK"
ORA_FILE_TABLE = "T_ERP_WEB_FEEDBACK_FILE"
TYPES = {"BUG": "오류", "REQ": "요청", "ASK": "문의"}
STATUSES = {"NEW": "접수", "DOING": "처리 중", "DONE": "완료"}
MAX_TEXT = 10_000              # 내용·답변 최대 글자 수 (CLOB)
MAX_TEXT_VARCHAR = 1_300       # 아직 VARCHAR2(4000) 이면 (한글 3바이트 기준)
MAX_CTX = 3800
MAX_FILES = 3
MAX_FILE_BYTES = 5 * 1024 * 1024
# 파일 앞 바이트로 형식을 확인한다 (확장자·브라우저가 알려준 형식은 믿지 않음)
IMAGE_MAGIC = [(b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
               (b"GIF89a", "image/gif")]
COLS = ["FB_ID", "USR_ID", "USR_NM", "FB_TYPE", "CONTENT", "PAGE_CD", "CTX_JSON", "STATUS", "ANSWER", "ANSWER_USR",
        "ANSWER_DAY", "INS_DAY", "UPT_DAY"]
FILE_COLS = ["FB_ID", "FILE_NO", "FILE_NM", "MIME_TYPE", "FILE_SIZE", "FILE_DATA", "INS_DAY"]

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    fb_id TEXT PRIMARY KEY, usr_id TEXT NOT NULL, usr_nm TEXT, fb_type TEXT NOT NULL, content TEXT NOT NULL,
    page_cd TEXT, ctx_json TEXT, status TEXT NOT NULL, answer TEXT, answer_usr TEXT, answer_day TEXT,
    ins_day TEXT NOT NULL, upt_day TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_file (
    fb_id TEXT NOT NULL, file_no INTEGER NOT NULL, file_nm TEXT NOT NULL, mime_type TEXT NOT NULL, file_size INTEGER NOT NULL,
    file_data BLOB NOT NULL, ins_day TEXT NOT NULL, PRIMARY KEY (fb_id, file_no)
);
"""
_state: tuple[float, bool, bool] | None = None   # (만료, Oracle 사용, 내용이 CLOB)
_lock = threading.Lock()


def _bad(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"message": msg, "code": "BAD_REQUEST" if status == 400 else "NOT_FOUND"})


def _sqlite() -> None:
    store.conn().executescript(SQLITE_SCHEMA)


def _probe() -> tuple[bool, bool]:
    try:
        db.query(f"SELECT 1 FROM {ORA_TABLE} WHERE 1 = 0")
        db.query(f"SELECT 1 FROM {ORA_FILE_TABLE} WHERE 1 = 0")
    except Exception:  # noqa: BLE001
        return False, False
    try:
        r = db.query("SELECT DATA_TYPE FROM ALL_TAB_COLUMNS WHERE OWNER = :o AND TABLE_NAME = :t AND COLUMN_NAME = 'CONTENT'",
                     {"o": config.DB_OWNER_SCHEMA, "t": ORA_TABLE})[1]
        clob = bool(r) and r[0][0] == "CLOB"
    except Exception:  # noqa: BLE001
        clob = False
    return True, clob


def _status() -> tuple[bool, bool]:
    global _state
    now = time.time()
    with _lock:
        if _state and _state[0] > now:
            return _state[1], _state[2]
    ok, clob = _probe()
    first = ok and not (_state and _state[1])
    with _lock:
        _state = (now + 60, ok, clob)
    if first and os.getenv("ERP_NO_AUTO_MIGRATE") != "1":
        _migrate()
    return ok, clob


def use_oracle() -> bool:
    return _status()[0]


def max_text() -> int:
    ok, clob = _status()
    return MAX_TEXT if (not ok or clob) else MAX_TEXT_VARCHAR


def backend_name() -> str:
    return "oracle" if use_oracle() else "sqlite"


def limits() -> dict:
    return {"maxText": max_text(), "maxFiles": MAX_FILES, "maxFileBytes": MAX_FILE_BYTES,
            "types": sorted({t for _, t in IMAGE_MAGIC} | {"image/webp"})}


def _now() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _fmt(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}" if v and len(v) >= 12 else v


def _lob(v):
    return v.read() if hasattr(v, "read") else v


def _ora_rows(sql: str, params: dict) -> list[dict]:
    """LOB 을 연결이 열려 있는 동안 읽는다."""
    with db.timed(sql, params), db.get_pool().acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [{c: _lob(v) for c, v in zip(cols, r)} for r in cur.fetchall()]


def _out(r: dict, files: list[dict]) -> dict:
    r = {k.upper(): v for k, v in r.items()}
    try:
        ctx = json.loads(r.get("CTX_JSON") or "{}")
    except ValueError:
        ctx = {"raw": r.get("CTX_JSON")}
    return {"id": r["FB_ID"], "userId": r["USR_ID"], "userName": r.get("USR_NM"), "type": r["FB_TYPE"],
            "typeLabel": TYPES.get(r["FB_TYPE"], r["FB_TYPE"]), "content": r["CONTENT"], "page": r.get("PAGE_CD"),
            "context": ctx, "status": r["STATUS"], "statusLabel": STATUSES.get(r["STATUS"], r["STATUS"]),
            "answer": r.get("ANSWER"), "answerBy": r.get("ANSWER_USR"), "answeredAt": _fmt(r.get("ANSWER_DAY")),
            "createdAt": _fmt(r["INS_DAY"]), "updatedAt": _fmt(r.get("UPT_DAY")), "files": files}


def _file_meta(ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not ids:
        return out
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        b = {f"i{j}": v for j, v in enumerate(chunk)}
        if use_oracle():
            rows = db.query_dicts(f"""SELECT FB_ID, FILE_NO, FILE_NM, MIME_TYPE, FILE_SIZE FROM {ORA_FILE_TABLE}
                                       WHERE FB_ID IN ({', '.join(':' + k for k in b)}) ORDER BY FB_ID, FILE_NO""", b)
        else:
            _sqlite()
            rows = store.rows(f"""SELECT fb_id, file_no, file_nm, mime_type, file_size FROM feedback_file
                                   WHERE fb_id IN ({', '.join(':' + k for k in b)}) ORDER BY fb_id, file_no""", b)
        for r in rows:
            r = {k.upper(): v for k, v in r.items()}
            out.setdefault(r["FB_ID"], []).append({"no": int(r["FILE_NO"]), "name": r["FILE_NM"], "type": r["MIME_TYPE"],
                                                   "size": int(r["FILE_SIZE"])})
    return out


def _select(where: str = "", params: dict | None = None, limit: int = 300) -> list[dict]:
    params = params or {}
    if use_oracle():
        sql = f"SELECT {', '.join(COLS)} FROM {ORA_TABLE}{(' WHERE ' + where) if where else ''} ORDER BY INS_DAY DESC"
        rows = _ora_rows(f"SELECT * FROM ({sql}) WHERE ROWNUM <= {int(limit)}", params)
    else:
        _sqlite()
        sql = f"SELECT * FROM feedback{(' WHERE ' + where.lower()) if where else ''} ORDER BY ins_day DESC LIMIT {int(limit)}"
        rows = store.rows(sql, {k.lower(): v for k, v in params.items()})
    files = _file_meta([r.get("FB_ID") or r.get("fb_id") for r in rows])
    return [_out(r, files.get(r.get("FB_ID") or r.get("fb_id"), [])) for r in rows]


def _sniff(data: bytes) -> str | None:
    for magic, mime in IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _images(body: dict) -> list[dict]:
    """[{name, data(base64 또는 data URL)}] → 검증한 파일 목록"""
    raw = body.get("images") or []
    if not isinstance(raw, list):
        _bad("images 는 목록입니다.")
    if len(raw) > MAX_FILES:
        _bad(f"이미지는 최대 {MAX_FILES}개까지 첨부할 수 있습니다.")
    out = []
    for i, f in enumerate(raw, 1):
        if not isinstance(f, dict) or not isinstance(f.get("data"), str):
            _bad("이미지 형식이 올바르지 않습니다.")
        b64 = f["data"].split(",", 1)[1] if f["data"].startswith("data:") else f["data"]
        if len(b64) > MAX_FILE_BYTES * 4 // 3 + 16:
            _bad(f"이미지 하나는 {MAX_FILE_BYTES // 1024 // 1024}MB 까지입니다.")
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            _bad("이미지 데이터를 읽을 수 없습니다.")
        if len(data) > MAX_FILE_BYTES:
            _bad(f"이미지 하나는 {MAX_FILE_BYTES // 1024 // 1024}MB 까지입니다.")
        mime = _sniff(data)
        if not mime:
            _bad("PNG · JPG · GIF · WEBP 이미지만 첨부할 수 있습니다.")
        name = os.path.basename(str(f.get("name") or f"image{i}")).strip()[:100] or f"image{i}"
        out.append({"file_no": i, "file_nm": name, "mime_type": mime, "file_size": len(data), "file_data": data})
    return out


def create(me: dict, body: dict) -> dict:
    typ = str(body.get("type") or "").upper()
    if typ not in TYPES:
        _bad(f"구분은 {', '.join(TYPES.values())} 중 하나입니다.")
    content = str(body.get("content") or "").strip()
    if len(content) < 2:
        _bad("내용을 적어 주세요.")
    limit = max_text()
    if len(content) > limit:
        _bad(f"내용은 {limit:,}자까지입니다.")
    files = _images(body)
    ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
    ctx_json = json.dumps(ctx, ensure_ascii=False)
    while len(ctx_json.encode("utf-8")) > MAX_CTX and ctx:  # 큰 항목부터 줄인다 (오류 목록 → 그 밖)
        big = max(ctx, key=lambda k: len(json.dumps(ctx[k], ensure_ascii=False)))
        ctx.pop(big)
        ctx["_trimmed"] = True
        ctx_json = json.dumps(ctx, ensure_ascii=False)
    now = _now()
    row = {"fb_id": now + secrets.token_hex(2).upper(), "usr_id": me["id"], "usr_nm": me.get("name"), "fb_type": typ,
           "content": content, "page_cd": str(body.get("page") or "")[:30] or None, "ctx_json": ctx_json,
           "status": "NEW", "ins_day": now, "upt_day": now}
    _insert(row, [{**f, "fb_id": row["fb_id"], "ins_day": now} for f in files])
    _log.info("문의·신고 접수 %s user=%s type=%s page=%s 이미지 %d개", row["fb_id"], me["id"], typ, row["page_cd"], len(files))
    return get(row["fb_id"])


def _ora_insert(cur, row: dict, files: list[dict]) -> None:
    cols = [c for c in COLS if c.lower() in row]
    if use_clob():
        cur.setinputsizes(content=oracledb.DB_TYPE_CLOB)
    cur.execute(f"INSERT INTO {ORA_TABLE} ({', '.join(cols)}) VALUES ({', '.join(':' + c.lower() for c in cols)})",
                {c.lower(): row[c.lower()] for c in cols})
    for f in files:
        cur.setinputsizes(file_data=oracledb.DB_TYPE_BLOB)
        cur.execute(f"INSERT INTO {ORA_FILE_TABLE} ({', '.join(FILE_COLS)}) VALUES ({', '.join(':' + c.lower() for c in FILE_COLS)})",
                    {c.lower(): f[c.lower()] for c in FILE_COLS})


def use_clob() -> bool:
    return _status()[1]


def _insert(row: dict, files: list[dict]) -> None:
    if use_oracle():
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            _ora_insert(cur, row, files)
            conn.commit()
    else:
        _sqlite()
        with store.tx() as c:
            c.execute(f"INSERT INTO feedback ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})", row)
            for f in files:
                c.execute(f"INSERT INTO feedback_file ({', '.join(x.lower() for x in FILE_COLS)}) "
                          f"VALUES ({', '.join(':' + x.lower() for x in FILE_COLS)})", {x.lower(): f[x.lower()] for x in FILE_COLS})


def get(fb_id: str) -> dict:
    rows = _select("FB_ID = :id", {"id": fb_id}, 1)
    if not rows:
        _bad("문의를 찾을 수 없습니다.", 404)
    return rows[0]


def get_file(fb_id: str, no: int, me: dict) -> tuple[bytes, str, str]:
    """첨부 이미지 (작성자 본인 또는 관리자만). (데이터, 형식, 파일명)"""
    fb = get(fb_id)
    if fb["userId"] != me["id"] and me.get("role") != "ADMIN":
        _bad("문의를 찾을 수 없습니다.", 404)
    if use_oracle():
        rows = _ora_rows(f"SELECT FILE_DATA, MIME_TYPE, FILE_NM FROM {ORA_FILE_TABLE} WHERE FB_ID = :id AND FILE_NO = :no",
                         {"id": fb_id, "no": int(no)})
        r = rows[0] if rows else None
        if r:
            return r["FILE_DATA"], r["MIME_TYPE"], r["FILE_NM"]
    else:
        _sqlite()
        rows = store.rows("SELECT file_data, mime_type, file_nm FROM feedback_file WHERE fb_id = :id AND file_no = :no",
                          {"id": fb_id, "no": int(no)})
        if rows:
            return bytes(rows[0]["file_data"]), rows[0]["mime_type"], rows[0]["file_nm"]
    _bad("첨부 이미지를 찾을 수 없습니다.", 404)


def mine(usr_id: str) -> list[dict]:
    return _select("USR_ID = :u", {"u": usr_id}, 50)


def list_all(status: str | None = None) -> dict:
    every = _select()
    counts = {k: 0 for k in STATUSES}
    for r in every:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    rows = [r for r in every if r["status"] == status] if status in STATUSES else every
    return {"rows": rows, "counts": counts, "storage": backend_name()}


def open_count() -> int:
    if use_oracle():
        return int(db.query(f"SELECT COUNT(*) FROM {ORA_TABLE} WHERE STATUS <> 'DONE'")[1][0][0])
    _sqlite()
    return int(store.rows("SELECT COUNT(*) AS n FROM feedback WHERE status <> 'DONE'")[0]["n"])


def answer(admin: dict, fb_id: str, body: dict) -> dict:
    cur = get(fb_id)
    status = str(body.get("status") or cur["status"]).upper()
    if status not in STATUSES:
        _bad(f"상태는 {', '.join(STATUSES.values())} 중 하나입니다.")
    ans = body.get("answer")
    limit = max_text()
    if ans is not None and len(str(ans).strip()) > limit:
        _bad(f"답변은 {limit:,}자까지입니다.")
    ans = cur["answer"] if ans is None else (str(ans).strip() or None)
    now = _now()
    answered = ans != cur["answer"]
    p = {"id": fb_id, "st": status, "ans": ans, "now": now, **({"usr": admin["id"]} if answered else {})}
    set_ans = ", ANSWER_USR = :usr, ANSWER_DAY = :now" if answered else ""
    if use_oracle():
        sql = f"UPDATE {ORA_TABLE} SET STATUS = :st, ANSWER = :ans, UPT_DAY = :now{set_ans} WHERE FB_ID = :id"
        with db.timed(sql, p, "execute"), db.get_pool().acquire() as conn, conn.cursor() as c:
            if use_clob():
                c.setinputsizes(ans=oracledb.DB_TYPE_CLOB)
            c.execute(sql, p)
            conn.commit()
    else:
        _sqlite()
        store.execute(f"UPDATE feedback SET status = :st, answer = :ans, upt_day = :now{set_ans.lower()} WHERE fb_id = :id", p)
    _log.info("문의·신고 처리 %s by=%s status=%s answered=%s", fb_id, admin["id"], status, answered)
    return get(fb_id)


def _migrate() -> None:
    """SQLite 에 저장된 문의·첨부 이미지를 Oracle 로 옮기고(이미 있으면 건너뜀) 지운다."""
    try:
        _sqlite()
        rows = store.rows("SELECT * FROM feedback")
        if not rows:
            return
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(f"SELECT COUNT(*) FROM {ORA_TABLE} WHERE FB_ID = :id", {"id": r["fb_id"]})
                if cur.fetchone()[0]:
                    continue
                files = [{**f, "file_data": bytes(f["file_data"])}
                         for f in store.rows("SELECT * FROM feedback_file WHERE fb_id = :id ORDER BY file_no", {"id": r["fb_id"]})]
                _ora_insert(cur, {c.lower(): r.get(c.lower()) for c in COLS}, files)
            conn.commit()
        store.execute("DELETE FROM feedback_file")
        store.execute("DELETE FROM feedback")
        _log.info("문의·신고 %d건을 Oracle 로 옮겼습니다.", len(rows))
    except Exception:  # noqa: BLE001
        _log.exception("문의·신고 Oracle 이전 실패 (SQLite 기록은 그대로)")
