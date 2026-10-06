"""공지사항 · 점검 모드.

공지: 관리자가 게시 기간(시작일 ~ 종료일, 하루 단위 · 양 끝 포함)을 정해 등록하면 그 기간에 로그인한 모든 사용자 화면에 팝업으로 뜬다
      ('오늘 하루 보지 않기' 는 사용자 브라우저에 기억 — 화면 쪽). 공지사항 게시판에서는 게시가 시작된 공지(지난 공지 포함)를 모두 본다.
      - 첨부파일 최대 3개(각 10MB, 문서·압축·이미지 형식) · 본문 이미지 최대 5개(각 5MB, 클립보드 붙여넣기) — 형식은 파일 내용으로 확인
      - 댓글 · 대댓글(댓글에 다는 답글 1단계). 본인 글만 수정, 삭제는 본인 또는 관리자. 답글이 달린 댓글은 '삭제된 댓글' 로 남긴다.
      저장소: Oracle T_ERP_WEB_NOTICE / _FILE / _COMMENT (db/create_erp_web_admin_ops.sql) 만 쓴다. 테이블이 없으면
      팝업 · 게시판은 비어 있고, 관리자 화면에 DDL 실행 안내가 나오며 등록은 막힌다.
점검 모드: 켜면 관리자 외 사용자는 로그인 · API 사용이 막히고 점검 안내 화면을 본다 (설정 MAINTENANCE_ON / MAINTENANCE_MSG / MAINTENANCE_UNTIL).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta

import oracledb
from fastapi import HTTPException

from . import audit, db, logs, userdb
from .tables import Tables

_log = logs.get("app")
ORA_TABLE = "T_ERP_WEB_NOTICE"
FILE_TABLE = "T_ERP_WEB_NOTICE_FILE"
CMT_TABLE = "T_ERP_WEB_NOTICE_COMMENT"
LEVELS = {"info": "안내", "warn": "주의", "important": "중요"}
LEVEL_ORDER = {"important": 0, "warn": 1, "info": 2}
TITLE_MAX = 100
BODY_MAX = 1000          # 글자 수 (Oracle VARCHAR2(4000) 바이트 안)
COMMENT_MAX = 1000
MAX_SPAN_DAYS = 366
MAX_ATTACH, MAX_ATTACH_BYTES = 3, 10 * 1024 * 1024
MAX_IMAGES, MAX_IMAGE_BYTES = 5, 5 * 1024 * 1024
DEFAULT_MAINT_MSG = "시스템 점검 중입니다. 잠시 후 다시 접속해 주세요."
CACHE_TTL = 30
# 첨부 허용 형식 (확장자 → 형식). 실행 파일·스크립트는 받지 않는다. 내려받기는 항상 '다운로드' 로 (브라우저에서 열지 않음).
ATTACH_TYPES = {
    "pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel", "csv": "text/csv", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint", "hwp": "application/x-hwp", "hwpx": "application/hwp+zip", "txt": "text/plain",
    "zip": "application/zip", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
}
IMAGE_MAGIC = [(b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif")]
# 형식별 파일 앞 바이트 (내용 확인). ZIP 기반(xlsx·docx·pptx·hwpx·zip) / OLE(xls·doc·ppt·hwp) / PDF
ZIP_MAGIC, OLE_MAGIC = b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAGIC_BY_EXT = {"pdf": [b"%PDF"], "xlsx": [ZIP_MAGIC], "docx": [ZIP_MAGIC], "pptx": [ZIP_MAGIC], "hwpx": [ZIP_MAGIC], "zip": [ZIP_MAGIC],
                "xls": [OLE_MAGIC], "doc": [OLE_MAGIC], "ppt": [OLE_MAGIC], "hwp": [OLE_MAGIC]}

COLS = ("NOTICE_ID", "TITLE", "BODY", "LEVEL_CD", "START_DT", "END_DT", "USE_YN", "INS_USERID", "INS_DAY", "UPT_USERID", "UPT_DAY")
FILE_COLS = ("NOTICE_ID", "FILE_NO", "KIND_CD", "FILE_NM", "MIME_TYPE", "FILE_SIZE", "FILE_DATA", "INS_DAY")
CMT_COLS = ("CMT_ID", "NOTICE_ID", "PARENT_ID", "USR_ID", "USR_NM", "BODY", "DEL_YN", "INS_DAY", "UPT_DAY")
_cache: tuple[float, list[dict]] | None = None
_lock = threading.Lock()


def _ins_sql(table: str, cols: tuple[str, ...]) -> str:
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c.lower() for c in cols)})"


tables = Tables(ORA_TABLE, FILE_TABLE, CMT_TABLE)
# 2차 (db/alter_erp_web_admin_ops_2.sql): 공지 대상 · 상단 고정 · 필독 컬럼과 읽음 기록. 없으면 '전체 대상 · 고정/필독 없음' 으로 동작
READ_TABLE = "T_ERP_WEB_NOTICE_READ"
EXT_COLS = ("TARGET_JSON", "PIN_YN", "MUST_ACK_YN")
ext = Tables(READ_TABLE, columns={"T_ERP_WEB_NOTICE 컬럼(TARGET_JSON · PIN_YN · MUST_ACK_YN)":
                                  f"SELECT TARGET_JSON, PIN_YN, MUST_ACK_YN FROM {ORA_TABLE} WHERE 1 = 0"},
             ddl="db/alter_erp_web_admin_ops_2.sql")
TARGET_TYPES = {"all": "전체", "pages": "메뉴 권한자", "brands": "브랜드 담당자", "users": "특정 사용자"}


def _cols() -> tuple[str, ...]:
    return COLS + (EXT_COLS if ext.ready() else ())


def _norm(rows: list[dict]) -> list[dict]:
    for r in rows:
        r.setdefault("target_json", None)
        r["pin_yn"] = r.get("pin_yn") or "N"
        r["must_ack_yn"] = r.get("must_ack_yn") or "N"
    return rows


def _target_of(r: dict) -> dict:
    try:
        t = json.loads(r.get("target_json") or "null") or {}
    except ValueError:
        t = {}
    typ = t.get("type") if t.get("type") in TARGET_TYPES else "all"
    vals = [str(v) for v in (t.get("values") or [])] if typ != "all" else []
    return {"type": typ, "values": vals}


def _target_label(t: dict) -> str:
    if t["type"] == "all":
        return "전체"
    if t["type"] == "pages":
        from . import auth

        return "메뉴: " + ", ".join(auth.PAGE_LABELS.get(v, v) for v in t["values"])
    if t["type"] == "brands":
        return "브랜드: " + ", ".join(t["values"])
    return f"사용자 {len(t['values'])}명"


def targeted(t: dict, me: dict) -> bool:
    """me(effective 사용자)가 공지 대상인지. 브랜드 대상은 '모든 브랜드' 권한 사용자도 포함"""
    if t["type"] == "all":
        return True
    if t["type"] == "pages":
        return any(p in (me.get("pages") or []) for p in t["values"])
    if t["type"] == "brands":
        brands = me.get("brands")
        return brands is None or any(b in brands for b in t["values"])
    return me.get("id") in t["values"]


def _bad(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"message": msg, "code": "BAD_REQUEST" if status == 400 else "NOT_FOUND"})


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _ymd(v: str | None) -> str | None:
    s = (v or "").replace("-", "").strip()
    try:
        return datetime.strptime(s, "%Y%m%d").strftime("%Y%m%d") if s else None
    except ValueError:
        return None


def _iso(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if v and len(v) >= 8 else v


def _fmt14(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}" if v and len(v) >= 12 else v


def _today() -> str:
    return date.today().strftime("%Y%m%d")


# ----------------------------------------------------------------------------
# 저장소 공통
# ----------------------------------------------------------------------------
def _q(sql: str, params: dict | None = None) -> list[dict]:
    """조회 (열 이름은 소문자). LOB 은 연결이 열린 동안 읽는다."""
    with db.timed(sql, params), db.get_pool().acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [d[0].lower() for d in cur.description]
        return [{c: (v.read() if hasattr(v, "read") else v) for c, v in zip(cols, r)} for r in cur.fetchall()]


def _exec(sql: str, params: dict) -> int:
    return db.execute(sql, params)


def _all() -> list[dict]:
    if not tables.ready():
        return []
    return _norm(_q(f"SELECT {', '.join(_cols())} FROM {ORA_TABLE} ORDER BY START_DT DESC, INS_DAY DESC"))


def _status(r: dict, today: str) -> str:
    if r["use_yn"] != "Y":
        return "off"
    if today < r["start_dt"]:
        return "scheduled"
    if today > r["end_dt"]:
        return "ended"
    return "active"


def _visible(r: dict, me: dict | None, today: str) -> bool:
    """사용자는 게시가 시작된 사용 중 공지(지난 공지 포함) 중 자기가 대상인 것만, 관리자는 모두"""
    if me and me.get("role") == "ADMIN":
        return True
    return r["use_yn"] == "Y" and r["start_dt"] <= today and (me is None or targeted(_target_of(r), me))


def _file_meta(ids: list[str]) -> dict[str, list[dict]]:
    if not ids:
        return {}
    binds = {f"n{i}": v for i, v in enumerate(ids)}
    inn = ", ".join(":" + k for k in binds)
    rows = _q(f"SELECT NOTICE_ID, FILE_NO, KIND_CD, FILE_NM, MIME_TYPE, FILE_SIZE FROM {FILE_TABLE} WHERE NOTICE_ID IN ({inn}) ORDER BY FILE_NO",
              binds)
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["notice_id"], []).append({"no": int(r["file_no"]), "kind": r["kind_cd"], "name": r["file_nm"],
                                                   "type": r["mime_type"], "size": int(r["file_size"])})
    return out


def _comment_counts(ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    binds = {f"n{i}": v for i, v in enumerate(ids)}
    inn = ", ".join(":" + k for k in binds)
    rows = _q(f"SELECT NOTICE_ID, COUNT(*) AS CNT FROM {CMT_TABLE} WHERE NOTICE_ID IN ({inn}) AND DEL_YN = 'N' GROUP BY NOTICE_ID", binds)
    return {r["notice_id"]: int(r["cnt"]) for r in rows}


def _out(r: dict, today: str, files: list[dict] | None = None, comments: int | None = None) -> dict:
    files = files or []
    return {"id": r["notice_id"], "title": r["title"], "body": r["body"] or "", "level": r["level_cd"],
            "levelLabel": LEVELS.get(r["level_cd"], r["level_cd"]), "start": _iso(r["start_dt"]), "end": _iso(r["end_dt"]),
            "use": r["use_yn"] == "Y", "status": _status(r, today),
            "createdBy": r["ins_userid"], "createdAt": _fmt14(r["ins_day"]), "updatedBy": r["upt_userid"], "updatedAt": _fmt14(r["upt_day"]),
            "images": [f for f in files if f["kind"] == "image"], "files": [f for f in files if f["kind"] == "file"],
            "commentCount": comments or 0, "target": {**_target_of(r), "label": _target_label(_target_of(r))},
            "pin": r.get("pin_yn") == "Y", "mustAck": r.get("must_ack_yn") == "Y"}


def _with_extras(rows: list[dict], today: str) -> list[dict]:
    ids = [r["notice_id"] for r in rows]
    files, cmts = _file_meta(ids), _comment_counts(ids)
    return [_out(r, today, files.get(r["notice_id"]), cmts.get(r["notice_id"])) for r in rows]


def _clear() -> None:
    global _cache
    with _lock:
        _cache = None


def _sort(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda x: x["start"] or "", reverse=True)          # 시작일 최신 순
    rows.sort(key=lambda x: LEVEL_ORDER.get(x["level"], 9))          # 중요 → 주의 → 안내 (안정 정렬)
    return rows


def _my_reads(usr_id: str) -> dict[str, dict]:
    if not ext.ready():
        return {}
    return {r["notice_id"]: r for r in _q(f"SELECT NOTICE_ID, READ_DAY, ACK_DAY FROM {READ_TABLE} WHERE USR_ID = :u", {"u": usr_id})}


def active_for(me: dict) -> list[dict]:
    """로그인 사용자 팝업: 오늘 게시 중이고 그 사용자가 대상인 공지 + 읽음 · 필독 확인 여부"""
    rows = [dict(n) for n in active() if targeted(n["target"], me)]
    reads = _my_reads(me["id"]) if rows else {}
    for n in rows:
        r = reads.get(n["id"])
        n["read"] = bool(r)
        n["acked"] = bool(r and r.get("ack_day"))
    return rows


def active(today: date | None = None) -> list[dict]:
    """오늘 게시 중인 공지 (대상 구분 전 전체). 중요 → 주의 → 안내, 시작일 최신 순. 30초 캐시."""
    global _cache
    now = time.time()
    t = (today or date.today()).strftime("%Y%m%d")
    with _lock:
        hit = _cache
    if today is None and hit and hit[0] > now:
        return hit[1]
    rows = _sort(_with_extras([r for r in _all() if _status(r, t) == "active"], t))
    if today is None:
        with _lock:
            _cache = (now + CACHE_TTL, rows)
    return rows


def board(me: dict, q: str | None = None) -> dict:
    """공지사항 게시판: 상단 고정 → 게시 중(중요 순) → 지난 공지(최신 순). 관리자는 예정 · 사용 안 함 · 대상 밖 공지도 본다."""
    if not tables.ready():
        return {"notices": [], "total": 0, "table": tables.status()}
    t = _today()
    rows = [r for r in _all() if _visible(r, me, t)]
    k = (q or "").strip().lower()
    if k:
        rows = [r for r in rows if k in (r["title"] or "").lower() or k in (r["body"] or "").lower()]
    items = _with_extras(rows[:300], t)
    pinned = _sort([x for x in items if x["pin"] and x["status"] == "active"])
    act = _sort([x for x in items if x["status"] == "active" and not x["pin"]])
    rest = [x for x in items if x["status"] != "active"]
    reads = _my_reads(me["id"])
    for x in pinned + act + rest:
        x["body"] = x["body"][:120]
        x["read"] = x["id"] in reads
        x["acked"] = bool(reads.get(x["id"], {}).get("ack_day"))
    return {"notices": pinned + act + rest, "total": len(rows), "table": tables.status()}


def _get(notice_id: str) -> dict | None:
    tables.require()
    rows = _norm(_q(f"SELECT {', '.join(_cols())} FROM {ORA_TABLE} WHERE NOTICE_ID = :nid", {"nid": notice_id}))
    return rows[0] if rows else None


def _get_visible(me: dict, notice_id: str) -> dict:
    r = _get(notice_id)
    if not r or not _visible(r, me, _today()):
        _bad("공지를 찾을 수 없습니다.", 404)
    return r


def detail(me: dict, notice_id: str) -> dict:
    r = _get_visible(me, notice_id)
    t = _today()
    out = _with_extras([r], t)[0]
    out["comments"] = _comments(me, notice_id)
    mark_read(me, [notice_id])
    rd = _my_reads(me["id"]).get(notice_id)
    out["read"], out["acked"] = bool(rd), bool(rd and rd.get("ack_day"))
    return {"notice": out, "commentMax": COMMENT_MAX}


# ----------------------------------------------------------------------------
# 읽음 · 필독 확인
# ----------------------------------------------------------------------------
_MERGE_READ = f"""MERGE INTO {READ_TABLE} T USING (SELECT :nid AS NOTICE_ID, :u AS USR_ID FROM DUAL) S
    ON (T.NOTICE_ID = S.NOTICE_ID AND T.USR_ID = S.USR_ID)
    WHEN MATCHED THEN UPDATE SET ACK_DAY = NVL(T.ACK_DAY, :ack)
    WHEN NOT MATCHED THEN INSERT (NOTICE_ID, USR_ID, READ_DAY, ACK_DAY) VALUES (:nid, :u, :d, :ack)"""


def mark_read(me: dict, ids: list[str], ack: bool = False) -> int:
    """읽음(처음 본 시각) · 필독 확인 기록. 미리보기(관리자가 다른 사용자 화면을 보는 중)에는 남기지 않는다."""
    if not ids or me.get("viewAs") or not ext.ready():
        return 0
    t, now, n = _today(), _now14(), 0
    rows = {r["notice_id"]: r for r in _all()}
    for nid in dict.fromkeys(str(x) for x in ids[:50]):
        r = rows.get(nid)
        if not r or not _visible(r, me, t):
            continue
        _save_read(nid, me["id"], now, now if ack else None)
        n += 1
    return n


def _save_read(nid: str, usr: str, day: str, ack: str | None) -> None:
    db.execute(_MERGE_READ, {"nid": nid, "u": usr, "d": day, "ack": ack})


def acknowledge(me: dict, notice_id: str) -> dict:
    if not ext.ready():
        _bad(ext.message())
    r = _get_visible(me, notice_id)
    if r.get("must_ack_yn") != "Y":
        _bad("필독 공지가 아닙니다.")
    mark_read(me, [notice_id], ack=True)
    return {"ok": True}


def _target_users(t: dict) -> list[dict]:
    """공지 대상인 사용 중 계정 (관리자 화면 읽음 현황)"""
    from . import auth

    st = userdb.get_settings()
    out = []
    for u in userdb.list_users():
        e = auth.effective(u, st)
        if e["active"] and targeted(t, e):
            out.append({"id": e["id"], "name": e["name"], "lastLoginAt": u.get("last_login_at")})
    return out


def read_status(notice_id: str) -> dict:
    """관리자: 대상자별 읽음 · 확인 시각 (대상이 아닌데 읽은 사람도 함께)"""
    r = _get(notice_id)
    if r is None:
        _bad("공지를 찾을 수 없습니다.", 404)
    if not ext.ready():
        return {"ready": False, "table": ext.status(), "users": [], "counts": None}
    reads = {x["usr_id"]: x for x in _q(f"SELECT USR_ID, READ_DAY, ACK_DAY FROM {READ_TABLE} WHERE NOTICE_ID = :n", {"n": notice_id})}
    target = _target_of(r)
    users = _target_users(target)
    ids = {u["id"] for u in users}
    names = {u["usr_id"]: u["usr_nm"] for u in userdb.list_users()}
    rows = [{**u, "target": True, "readAt": _fmt14(reads.get(u["id"], {}).get("read_day")),
             "ackAt": _fmt14(reads.get(u["id"], {}).get("ack_day"))} for u in users]
    rows += [{"id": k, "name": names.get(k, k), "lastLoginAt": None, "target": False, "readAt": _fmt14(v["read_day"]),
              "ackAt": _fmt14(v["ack_day"])} for k, v in reads.items() if k not in ids]
    rows.sort(key=lambda x: (not x["target"], x["readAt"] is not None, x["name"] or ""))
    return {"ready": True, "mustAck": r.get("must_ack_yn") == "Y", "target": {**target, "label": _target_label(target)},
            "counts": {"target": len(users), "read": sum(1 for x in rows if x["target"] and x["readAt"]),
                       "ack": sum(1 for x in rows if x["target"] and x["ackAt"])},
            "users": rows}


def _read_counts() -> dict[str, tuple[int, int]]:
    if not ext.ready():
        return {}
    return {r["notice_id"]: (int(r["cnt"]), int(r["acks"])) for r in _q(
        f"SELECT NOTICE_ID, COUNT(*) AS CNT, COUNT(ACK_DAY) AS ACKS FROM {READ_TABLE} GROUP BY NOTICE_ID")}


def list_all() -> dict:
    t = _today()
    rows = _with_extras(_all()[:300], t)
    counts = _read_counts()
    for n in rows:
        n["readCount"], n["ackCount"] = counts.get(n["id"], (0, 0))
    return {"notices": rows, "levels": LEVELS, "table": tables.status(), "ext": ext.status(), "targetTypes": TARGET_TYPES,
            "titleMax": TITLE_MAX, "bodyMax": BODY_MAX,
            "limits": {"attach": MAX_ATTACH, "attachMb": MAX_ATTACH_BYTES // 1024 // 1024, "images": MAX_IMAGES,
                       "imageMb": MAX_IMAGE_BYTES // 1024 // 1024, "attachTypes": sorted(ATTACH_TYPES)}}


# ----------------------------------------------------------------------------
# 첨부 · 이미지
# ----------------------------------------------------------------------------
def _sniff_image(data: bytes) -> str | None:
    for magic, mime in IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _decode(f: dict, limit: int, what: str) -> bytes:
    raw = f.get("data")
    if not isinstance(raw, str):
        _bad(f"{what} 형식이 올바르지 않습니다.")
    b64 = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    if len(b64) > limit * 4 // 3 + 16:
        _bad(f"{what} 하나는 {limit // 1024 // 1024}MB 까지입니다.")
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        _bad(f"{what} 데이터를 읽을 수 없습니다.")
    if not data or len(data) > limit:
        _bad(f"{what} 하나는 {limit // 1024 // 1024}MB 까지입니다.")
    return data


def _new_files(body: dict) -> list[dict]:
    """[{kind: image|file, name, data(base64/data URL)}] → 검증한 파일"""
    raw = body.get("newFiles") or []
    if not isinstance(raw, list):
        _bad("첨부 형식이 올바르지 않습니다.")
    out = []
    for i, f in enumerate(raw, 1):
        if not isinstance(f, dict):
            _bad("첨부 형식이 올바르지 않습니다.")
        kind = "image" if f.get("kind") == "image" else "file"
        name = os.path.basename(str(f.get("name") or "")).strip()[:100]
        if kind == "image":
            data = _decode(f, MAX_IMAGE_BYTES, "이미지")
            mime = _sniff_image(data)
            if not mime:
                _bad("본문 이미지는 PNG · JPG · GIF · WEBP 만 넣을 수 있습니다.")
            name = name or f"image{i}.{mime.split('/')[1]}"
        else:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in ATTACH_TYPES:
                _bad(f"첨부할 수 없는 형식입니다: {name or '(이름 없음)'} — {', '.join(sorted(ATTACH_TYPES))}")
            data = _decode(f, MAX_ATTACH_BYTES, "첨부파일")
            magics = MAGIC_BY_EXT.get(ext)
            img = _sniff_image(data) if ext in ("png", "jpg", "jpeg", "gif", "webp") else None
            if (magics and not any(data.startswith(m) for m in magics)) or (ext in ("png", "jpg", "jpeg", "gif", "webp") and not img):
                _bad(f"파일 내용이 확장자와 맞지 않습니다: {name}")
            if ext in ("txt", "csv") and b"\x00" in data[:4096]:
                _bad(f"파일 내용이 확장자와 맞지 않습니다: {name}")
            mime = img or ATTACH_TYPES[ext]
        out.append({"kind_cd": kind, "file_nm": name, "mime_type": mime, "file_size": len(data), "file_data": data})
    return out


def _save_files(notice_id: str, keep: set[int] | None, new: list[dict], existing: list[dict]) -> None:
    """keep(남길 기존 파일 번호) 밖의 기존 파일은 지우고, 새 파일은 이어지는 번호로 넣는다"""
    kept = [f for f in existing if keep is None or f["no"] in keep]
    for kind, label, mx in (("file", "첨부파일", MAX_ATTACH), ("image", "본문 이미지", MAX_IMAGES)):
        n = sum(1 for f in kept if f["kind"] == kind) + sum(1 for f in new if f["kind_cd"] == kind)
        if n > mx:
            _bad(f"{label}는 최대 {mx}개까지입니다.")
    drop = [f["no"] for f in existing if f not in kept]
    nxt = max([f["no"] for f in existing], default=0) + 1
    now = _now14()
    with db.get_pool().acquire() as conn, conn.cursor() as cur:
        for no in drop:
            cur.execute(f"DELETE FROM {FILE_TABLE} WHERE NOTICE_ID = :nid AND FILE_NO = :no", {"nid": notice_id, "no": no})
        for i, f in enumerate(new):
            cur.setinputsizes(file_data=oracledb.DB_TYPE_BLOB)
            cur.execute(_ins_sql(FILE_TABLE, FILE_COLS), {**f, "notice_id": notice_id, "file_no": nxt + i, "ins_day": now})
        conn.commit()


def get_file(me: dict, notice_id: str, no: int) -> tuple[bytes, str, str, str]:
    """(데이터, 형식, 파일명, 종류) — 공지를 볼 수 있는 사용자만"""
    _get_visible(me, notice_id)
    rows = _q(f"SELECT FILE_DATA, MIME_TYPE, FILE_NM, KIND_CD FROM {FILE_TABLE} WHERE NOTICE_ID = :nid AND FILE_NO = :no",
              {"nid": notice_id, "no": int(no)})
    if not rows:
        _bad("첨부파일을 찾을 수 없습니다.", 404)
    r = rows[0]
    return bytes(r["file_data"]), r["mime_type"], r["file_nm"], r["kind_cd"]


# ----------------------------------------------------------------------------
# 공지 등록 · 수정 · 삭제 (관리자)
# ----------------------------------------------------------------------------
def _validate(body: dict) -> dict:
    title = str(body.get("title") or "").strip()
    text = str(body.get("body") or "").strip()
    level = str(body.get("level") or "info")
    start, end = _ymd(body.get("start")), _ymd(body.get("end"))
    if not title:
        _bad("제목을 입력하세요.")
    if len(title) > TITLE_MAX:
        _bad(f"제목은 {TITLE_MAX}자 이내로 입력하세요.")
    if len(text) > BODY_MAX or len(text.encode("utf-8")) > 4000:
        _bad(f"내용은 {BODY_MAX}자 이내로 입력하세요.")
    if level not in LEVELS:
        _bad("구분이 올바르지 않습니다.")
    if not start or not end:
        _bad("게시 시작일과 종료일을 입력하세요.")
    if start > end:
        _bad("종료일이 시작일보다 빠릅니다.")
    if (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days >= MAX_SPAN_DAYS:
        _bad(f"게시 기간은 {MAX_SPAN_DAYS}일 이내로 정하세요.")
    out = {"title": title, "body": text or None, "level_cd": level, "start_dt": start, "end_dt": end,
           "use_yn": "N" if body.get("use") is False else "Y"}
    target = body.get("target") or {"type": "all"}
    if not isinstance(target, dict) or target.get("type", "all") not in TARGET_TYPES:
        _bad("공지 대상이 올바르지 않습니다.")
    typ = target.get("type", "all")
    vals = [str(v).strip() for v in (target.get("values") or []) if str(v).strip()] if typ != "all" else []
    if typ != "all" and not vals:
        _bad(f"공지 대상({TARGET_TYPES[typ]})을 하나 이상 고르세요.")
    pin, must = bool(body.get("pin")), bool(body.get("mustAck"))
    if not ext.ready():
        if typ != "all" or pin or must:
            _bad(f"공지 대상 · 상단 고정 · 필독은 {ext.ddl} 실행 후 쓸 수 있습니다.")
    else:
        tj = json.dumps({"type": typ, "values": sorted(set(vals))}, ensure_ascii=False) if typ != "all" else None
        if tj and len(tj.encode("utf-8")) > 2000:
            _bad("공지 대상이 너무 많습니다 (사용자 대상은 100명 이내로 골라 주세요).")
        out.update({"target_json": tj, "pin_yn": "Y" if pin else "N", "must_ack_yn": "Y" if must else "N"})
    return out


def _snap(r: dict | None, files: list[dict] | None = None) -> dict | None:
    if r is None:
        return None
    return {"title": r["title"], "level": r["level_cd"], "start": r["start_dt"], "end": r["end_dt"], "use": r["use_yn"],
            "body": (r["body"] or "")[:200], "files": [f["name"] for f in files or []], "target": _target_label(_target_of(r)),
            "pin": r.get("pin_yn"), "mustAck": r.get("must_ack_yn")}


def save(admin: dict, body: dict, notice_id: str | None = None) -> dict:
    tables.require()
    v = _validate(body)
    new = _new_files(body)
    now = _now14()
    before = _get(notice_id) if notice_id else None
    if notice_id and before is None:
        _bad("공지를 찾을 수 없습니다.", 404)
    existing = _file_meta([notice_id]).get(notice_id, []) if notice_id else []
    keep_raw = body.get("keepFiles")
    keep = None if keep_raw is None else {int(x) for x in keep_raw if str(x).isdigit()}
    if notice_id:
        _save_files(notice_id, keep, new, existing)    # 개수 검사가 먼저라 실패하면 본문도 바꾸지 않는다
        sets = {**v, "upt_userid": admin["id"], "upt_day": now}
        _exec(f"UPDATE {ORA_TABLE} SET {', '.join(f'{k.upper()} = :{k}' for k in sets)} WHERE NOTICE_ID = :nid", {**sets, "nid": notice_id})
    else:
        notice_id = uuid.uuid4().hex
        row = {"notice_id": notice_id, **v, "ins_userid": admin["id"], "ins_day": now, "upt_userid": admin["id"], "upt_day": now}
        for kind, label, mx in (("file", "첨부파일", MAX_ATTACH), ("image", "본문 이미지", MAX_IMAGES)):
            if sum(1 for f in new if f["kind_cd"] == kind) > mx:
                _bad(f"{label}는 최대 {mx}개까지입니다.")
        _exec(f"INSERT INTO {ORA_TABLE} ({', '.join(k.upper() for k in row)}) VALUES ({', '.join(':' + k for k in row)})", row)
        _save_files(notice_id, None, new, [])
    _clear()
    after = _get(notice_id)
    files = _file_meta([notice_id]).get(notice_id, [])
    audit.record(admin, "NOTICE_SAVE", f"공지 · {v['title']}"[:100], before=_snap(before, existing), after=_snap(after, files))
    return {"notice": _with_extras([after], _today())[0]}


def delete(admin: dict, notice_id: str) -> dict:
    before = _get(notice_id)
    if before is None:
        _bad("공지를 찾을 수 없습니다.", 404)
    p = {"nid": notice_id}
    if ext.ready():
        _exec(f"DELETE FROM {READ_TABLE} WHERE NOTICE_ID = :nid", p)
    _exec(f"DELETE FROM {CMT_TABLE} WHERE NOTICE_ID = :nid", p)
    _exec(f"DELETE FROM {FILE_TABLE} WHERE NOTICE_ID = :nid", p)
    _exec(f"DELETE FROM {ORA_TABLE} WHERE NOTICE_ID = :nid", p)
    _clear()
    audit.record(admin, "NOTICE_DELETE", f"공지 · {before['title']}"[:100], summary="공지 삭제 (첨부 · 댓글 포함)")
    return {"ok": True}


# ----------------------------------------------------------------------------
# 댓글 · 대댓글
# ----------------------------------------------------------------------------
def _comment_rows(notice_id: str) -> list[dict]:
    return _q(f"SELECT {', '.join(CMT_COLS)} FROM {CMT_TABLE} WHERE NOTICE_ID = :nid ORDER BY INS_DAY, CMT_ID", {"nid": notice_id})


def _comments(me: dict, notice_id: str) -> list[dict]:
    """댓글 트리: [{..., replies: [...]}]. 삭제된 댓글은 답글이 있을 때만 '삭제된 댓글' 로 남는다."""
    rows = _comment_rows(notice_id)
    admin = me.get("role") == "ADMIN"

    def out(r: dict) -> dict:
        deleted = r["del_yn"] == "Y"
        return {"id": r["cmt_id"], "parentId": r["parent_id"], "userId": None if deleted else r["usr_id"],
                "userName": None if deleted else (r["usr_nm"] or r["usr_id"]), "body": "" if deleted else (r["body"] or ""),
                "deleted": deleted, "createdAt": _fmt14(r["ins_day"]), "edited": r["upt_day"] != r["ins_day"] and not deleted,
                "canEdit": not deleted and r["usr_id"] == me["id"], "canDelete": not deleted and (r["usr_id"] == me["id"] or admin)}

    roots = [out(r) | {"replies": []} for r in rows if not r["parent_id"]]
    by_id = {c["id"]: c for c in roots}
    for r in rows:
        if r["parent_id"] and r["parent_id"] in by_id and r["del_yn"] != "Y":
            by_id[r["parent_id"]]["replies"].append(out(r))
    return [c for c in roots if not c["deleted"] or c["replies"]]


def _comment_text(body: dict) -> str:
    text = str(body.get("body") or "").strip()
    if not text:
        _bad("댓글 내용을 입력하세요.")
    if len(text) > COMMENT_MAX or len(text.encode("utf-8")) > 4000:
        _bad(f"댓글은 {COMMENT_MAX}자 이내로 입력하세요.")
    return text


def add_comment(me: dict, notice_id: str, body: dict) -> dict:
    _get_visible(me, notice_id)
    text = _comment_text(body)
    parent = str(body.get("parentId") or "").strip() or None
    if parent:
        rows = {r["cmt_id"]: r for r in _comment_rows(notice_id)}
        p = rows.get(parent)
        if not p or p["del_yn"] == "Y":
            _bad("답글을 달 댓글을 찾을 수 없습니다.", 404)
        parent = p["parent_id"] or p["cmt_id"]          # 답글의 답글은 같은 댓글 아래로 (1단계)
    now = _now14()
    row = {"cmt_id": f"{time.time_ns():020d}{uuid.uuid4().hex[:8]}", "notice_id": notice_id,   # 시각 순 ID (같은 초 정렬)
           "parent_id": parent, "usr_id": me["id"],
           "usr_nm": str(me.get("name") or "")[:30] or None, "body": text, "del_yn": "N", "ins_day": now, "upt_day": now}
    _exec(_ins_sql(CMT_TABLE, CMT_COLS), row)
    _clear()
    return {"comments": _comments(me, notice_id)}


def _own_comment(me: dict, notice_id: str, cmt_id: str) -> dict:
    _get_visible(me, notice_id)
    r = next((x for x in _comment_rows(notice_id) if x["cmt_id"] == cmt_id), None)
    if not r or r["del_yn"] == "Y":
        _bad("댓글을 찾을 수 없습니다.", 404)
    return r


def edit_comment(me: dict, notice_id: str, cmt_id: str, body: dict) -> dict:
    r = _own_comment(me, notice_id, cmt_id)
    if r["usr_id"] != me["id"]:
        _bad("본인 댓글만 수정할 수 있습니다.", 403)
    _exec(f"UPDATE {CMT_TABLE} SET BODY = :b, UPT_DAY = :d WHERE CMT_ID = :c",
          {"b": _comment_text(body), "d": _now14(), "c": cmt_id})
    return {"comments": _comments(me, notice_id)}


def delete_comment(me: dict, notice_id: str, cmt_id: str) -> dict:
    r = _own_comment(me, notice_id, cmt_id)
    if r["usr_id"] != me["id"] and me.get("role") != "ADMIN":
        _bad("본인 댓글만 삭제할 수 있습니다.", 403)
    has_replies = any(x["parent_id"] == cmt_id and x["del_yn"] != "Y" for x in _comment_rows(notice_id))
    if has_replies:   # 답글이 있으면 '삭제된 댓글' 로 남겨 답글 흐름을 유지
        _exec(f"UPDATE {CMT_TABLE} SET DEL_YN = 'Y', BODY = NULL, UPT_DAY = :d WHERE CMT_ID = :c", {"d": _now14(), "c": cmt_id})
    else:
        _exec(f"DELETE FROM {CMT_TABLE} WHERE CMT_ID = :c", {"c": cmt_id})
        if r["parent_id"]:  # 삭제된 부모 댓글의 마지막 답글이었으면 부모도 정리
            rest = [x for x in _comment_rows(notice_id) if x["parent_id"] == r["parent_id"]]
            parent = next((x for x in _comment_rows(notice_id) if x["cmt_id"] == r["parent_id"]), None)
            if parent and parent["del_yn"] == "Y" and not rest:
                _exec(f"DELETE FROM {CMT_TABLE} WHERE CMT_ID = :c", {"c": parent["cmt_id"]})
    if me.get("role") == "ADMIN" and r["usr_id"] != me["id"]:
        audit.record(me, "NOTICE_DELETE", "공지 댓글", summary=f"{r['usr_id']} 댓글 삭제: {(r['body'] or '')[:100]}")
    _clear()
    return {"comments": _comments(me, notice_id)}


# ----------------------------------------------------------------------------
# 점검 모드
# ----------------------------------------------------------------------------
MAINT_NOTICE_MIN = 60   # 예약 점검 시작 몇 분 전부터 사용자에게 예고 배너


def _now_hm() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def maintenance() -> dict:
    """on: 지금 막고 있는지 (직접 켬 또는 예약 시간 안). manual: 직접 켬. start/until: 예약 (until 은 직접 켤 때 종료 예정 안내로도 쓴다)"""
    s = userdb.get_settings()
    start, until = s.get("maintenance_start"), s.get("maintenance_until")
    now = _now_hm()
    scheduled_now = bool(start and until and start <= now < until)
    return {"on": bool(s.get("maintenance_on")) or scheduled_now, "manual": bool(s.get("maintenance_on")),
            "scheduledNow": scheduled_now, "message": s.get("maintenance_msg") or DEFAULT_MAINT_MSG,
            "start": start, "until": until, "scheduled": bool(start and until and now < until)}


def upcoming_maintenance() -> dict | None:
    """예약 점검이 MAINT_NOTICE_MIN 분 안에 시작하면 모든 사용자에게 예고 (상단 배너)"""
    m = maintenance()
    if not (m["start"] and m["until"]) or m["on"]:
        return None
    lim = (datetime.now() + timedelta(minutes=MAINT_NOTICE_MIN)).strftime("%Y-%m-%d %H:%M")
    if _now_hm() < m["start"] <= lim:
        return {"start": m["start"], "until": m["until"], "message": m["message"]}
    return None


def set_maintenance(admin: dict, body: dict) -> dict:
    """{on: 지금 직접 켜기/끄기, message, until: 종료(예정), start: 예약 시작}. start+until 이면 그 시간에 자동으로 켜지고 꺼진다."""
    on = bool(body.get("on"))
    msg = str(body.get("message") or "").strip() or None
    until = str(body.get("until") or "").strip() or None
    start = str(body.get("start") or "").strip() or None
    if msg and len(msg) > 300:
        _bad("안내 문구는 300자 이내로 입력하세요.")
    for v, label in ((until, "종료 예정"), (start, "예약 시작")):
        if v and not _valid_until(v):
            _bad(f"{label} 시각 형식이 올바르지 않습니다 (예: 2026-10-10 15:00).")
    if start and not until:
        _bad("예약하려면 종료 시각도 입력하세요.")
    if start and until and start >= until:
        _bad("종료 시각이 시작 시각보다 늦어야 합니다.")
    if start and until <= _now_hm():
        _bad("이미 지난 시간으로는 예약할 수 없습니다.")
    before = maintenance()
    userdb.save_settings({"maintenance_on": on, "maintenance_msg": msg, "maintenance_until": until, "maintenance_start": start},
                         admin["id"])
    after = maintenance()
    what = "켜기" if on else f"예약 {start} ~ {until}" if start else "끄기"
    audit.record(admin, "MAINTENANCE", f"점검 모드 {what}", before=before, after=after)
    return after


def _valid_until(v: str) -> bool:
    try:
        datetime.strptime(v, "%Y-%m-%d %H:%M")
        return True
    except ValueError:
        return False


def blocked_message() -> str | None:
    """점검 모드면 일반 사용자에게 보여줄 문구, 아니면 None"""
    m = maintenance()
    if not m["on"]:
        return None
    return m["message"] + (f" (종료 예정 {m['until']})" if m["until"] else "")


def upcoming_end(days: int = 3) -> list[dict]:
    """관리자 홈: 며칠 안에 끝나는 게시 중 공지"""
    lim = (date.today() + timedelta(days=days)).isoformat()
    return [n for n in active() if (n["end"] or "") <= lim]
