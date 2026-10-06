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
    return _q(f"SELECT {', '.join(COLS)} FROM {ORA_TABLE} ORDER BY START_DT DESC, INS_DAY DESC")


def _status(r: dict, today: str) -> str:
    if r["use_yn"] != "Y":
        return "off"
    if today < r["start_dt"]:
        return "scheduled"
    if today > r["end_dt"]:
        return "ended"
    return "active"


def _visible(r: dict, me: dict | None, today: str) -> bool:
    """사용자는 게시가 시작된 사용 중 공지(지난 공지 포함)만, 관리자는 모두"""
    if me and me.get("role") == "ADMIN":
        return True
    return r["use_yn"] == "Y" and r["start_dt"] <= today


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
            "commentCount": comments or 0}


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


def active(today: date | None = None) -> list[dict]:
    """오늘 게시 중인 공지 (로그인 후 팝업). 중요 → 주의 → 안내, 시작일 최신 순. 30초 캐시."""
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
    if not tables.ready():
        return {"notices": [], "total": 0, "table": tables.status()}
    """공지사항 게시판: 게시 중(중요 순) → 지난 공지(최신 순). 관리자는 예정 · 사용 안 함 공지도 본다."""
    t = _today()
    rows = [r for r in _all() if _visible(r, me, t)]
    k = (q or "").strip().lower()
    if k:
        rows = [r for r in rows if k in (r["title"] or "").lower() or k in (r["body"] or "").lower()]
    items = _with_extras(rows[:300], t)
    act = _sort([x for x in items if x["status"] == "active"])
    rest = [x for x in items if x["status"] != "active"]
    for x in act + rest:
        x["body"] = x["body"][:120]
    return {"notices": act + rest, "total": len(rows), "table": tables.status()}


def _get(notice_id: str) -> dict | None:
    tables.require()
    rows = _q(f"SELECT {', '.join(COLS)} FROM {ORA_TABLE} WHERE NOTICE_ID = :nid",
              {"nid": notice_id})
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
    return {"notice": out, "commentMax": COMMENT_MAX}


def list_all() -> dict:
    t = _today()
    rows = _with_extras(_all()[:300], t)
    return {"notices": rows, "levels": LEVELS, "table": tables.status(), "titleMax": TITLE_MAX, "bodyMax": BODY_MAX,
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
    return {"title": title, "body": text or None, "level_cd": level, "start_dt": start, "end_dt": end,
            "use_yn": "N" if body.get("use") is False else "Y"}


def _snap(r: dict | None, files: list[dict] | None = None) -> dict | None:
    if r is None:
        return None
    return {"title": r["title"], "level": r["level_cd"], "start": r["start_dt"], "end": r["end_dt"], "use": r["use_yn"],
            "body": (r["body"] or "")[:200], "files": [f["name"] for f in files or []]}


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
def maintenance() -> dict:
    s = userdb.get_settings()
    return {"on": bool(s.get("maintenance_on")), "message": s.get("maintenance_msg") or DEFAULT_MAINT_MSG,
            "until": s.get("maintenance_until")}


def set_maintenance(admin: dict, body: dict) -> dict:
    on = bool(body.get("on"))
    msg = str(body.get("message") or "").strip() or None
    until = str(body.get("until") or "").strip() or None
    if msg and len(msg) > 300:
        _bad("안내 문구는 300자 이내로 입력하세요.")
    if until and not _valid_until(until):
        _bad("종료 예정 시각 형식이 올바르지 않습니다 (예: 2026-10-10 15:00).")
    before = maintenance()
    userdb.save_settings({"maintenance_on": on, "maintenance_msg": msg, "maintenance_until": until}, admin["id"])
    after = maintenance()
    audit.record(admin, "MAINTENANCE", "점검 모드 " + ("켜기" if on else "끄기"), before=before, after=after)
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
