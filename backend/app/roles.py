"""관리자 > 권한 묶음 (역할 템플릿): 메뉴 권한 · 브랜드 권한 · AI 사용/한도를 이름 붙여 묶어 두고 사용자에게 한 번에 적용한다.

- 적용은 사용자 설정 저장(admin.save_user)과 같은 검증 · 변경 이력으로 한다. 최고 관리자 · 관리자 권한(ADMIN/USER)은 바꾸지 않는다.
- 사용자마다 마지막으로 적용한 묶음을 기억한다 (T_ERP_WEB_ROLE_USER). 묶음을 고칠 때 '적용한 사용자에게 다시 반영' 을 고를 수 있다.
저장소: Oracle T_ERP_WEB_ROLE / T_ERP_WEB_ROLE_USER (db/alter_erp_web_admin_ops_2.sql). 테이블이 없으면 화면에 DDL 안내.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import HTTPException

from . import admin, audit, auth, db, userdb
from .tables import Tables

ROLE_TABLE = "T_ERP_WEB_ROLE"
MEMBER_TABLE = "T_ERP_WEB_ROLE_USER"
tables = Tables(ROLE_TABLE, MEMBER_TABLE, ddl="db/alter_erp_web_admin_ops_2.sql")
CONF_KEYS = ("pages", "brands", "aiEnabled", "dailyQuestions", "dailyCostUsd", "dailyBriefings")


def _bad(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"message": msg, "code": "BAD_REQUEST" if status == 400 else "NOT_FOUND"})


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _fmt14(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}" if v and len(v) >= 12 else v


def _conf(raw: dict) -> dict:
    """사용자 저장과 같은 규칙으로 검증한 설정 {pages, brands(None=모든 브랜드), aiEnabled, dailyQuestions, dailyCostUsd}"""
    body = {k: raw[k] for k in CONF_KEYS if k in raw}
    if not body.get("pages"):
        _bad("메뉴 권한을 하나 이상 고르세요.")
    if "brands" not in body:
        body["brands"] = None
    v = admin._validate("__role__", body)   # 검증만 (저장 안 함)
    return {"pages": v["pages"], "brands": v.get("brands") or None, "aiEnabled": bool(v.get("ai_enabled", True)),
            "dailyQuestions": v.get("daily_questions"), "dailyCostUsd": v.get("daily_cost_usd"),
            "dailyBriefings": v.get("daily_briefings")}


def _rows() -> list[dict]:
    return db.query_dicts(f"SELECT ROLE_ID, ROLE_NM, DESCR, CONF_JSON, INS_USERID, INS_DAY, UPT_USERID, UPT_DAY FROM {ROLE_TABLE} ORDER BY ROLE_NM")


def _members() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in db.query_dicts(f"SELECT USR_ID, ROLE_ID, APPLY_DAY, APPLY_USERID FROM {MEMBER_TABLE}"):
        out.setdefault(r["ROLE_ID"], []).append({"id": r["USR_ID"], "appliedAt": _fmt14(r["APPLY_DAY"]), "by": r["APPLY_USERID"]})
    return out


def _out(r: dict, members: list[dict], names: dict[str, str], labels: dict[str, str]) -> dict:
    conf = json.loads(r["CONF_JSON"])
    return {"id": r["ROLE_ID"], "name": r["ROLE_NM"], "description": r["DESCR"] or "", "conf": conf,
            "pageLabels": [labels.get(p, p) for p in conf.get("pages", [])],
            "members": [{**m, "name": names.get(m["id"], m["id"])} for m in members],
            "updatedBy": r["UPT_USERID"], "updatedAt": _fmt14(r["UPT_DAY"])}


def list_roles() -> dict:
    base = {"table": tables.status(), "pages": admin.page_meta(), "brandOptions": admin.brand_options(),
            "brandReady": userdb.brand_table_ready()}
    if not tables.ready():
        return {**base, "roles": []}
    names = {u["usr_id"]: u["usr_nm"] for u in userdb.list_users()}
    labels = auth.PAGE_LABELS
    members = _members()
    return {**base, "roles": [_out(r, members.get(r["ROLE_ID"], []), names, labels) for r in _rows()]}


def _get(role_id: str) -> dict:
    rows = db.query_dicts(f"SELECT ROLE_ID, ROLE_NM, DESCR, CONF_JSON, INS_USERID, INS_DAY, UPT_USERID, UPT_DAY FROM {ROLE_TABLE} "
                          "WHERE ROLE_ID = :r", {"r": role_id})
    if not rows:
        _bad("권한 묶음을 찾을 수 없습니다.", 404)
    return rows[0]


def save(adm: dict, body: dict, role_id: str | None = None) -> dict:
    """{name, description, conf: {...}, reapply: bool} 등록 · 수정. reapply 면 이 묶음을 적용한 사용자에게 다시 반영"""
    tables.require()
    name = str(body.get("name") or "").strip()
    desc = str(body.get("description") or "").strip() or None
    if not name or len(name) > 30:
        _bad("묶음 이름은 1~30자로 입력하세요.")
    if desc and len(desc) > 150:
        _bad("설명은 150자 이내로 입력하세요.")
    conf = _conf(body.get("conf") or {})
    dup = [r for r in _rows() if r["ROLE_NM"] == name and r["ROLE_ID"] != role_id]
    if dup:
        _bad(f"같은 이름의 묶음이 있습니다: {name}")
    now, cj = _now14(), json.dumps(conf, ensure_ascii=False)
    before = None
    if role_id:
        before = _get(role_id)
        db.execute(f"UPDATE {ROLE_TABLE} SET ROLE_NM = :n, DESCR = :d, CONF_JSON = :c, UPT_USERID = :u, UPT_DAY = :t WHERE ROLE_ID = :r",
                   {"n": name, "d": desc, "c": cj, "u": adm["id"], "t": now, "r": role_id})
    else:
        role_id = uuid.uuid4().hex
        db.execute(f"""INSERT INTO {ROLE_TABLE} (ROLE_ID, ROLE_NM, DESCR, CONF_JSON, INS_USERID, INS_DAY, UPT_USERID, UPT_DAY)
                       VALUES (:r, :n, :d, :c, :u, :t, :u, :t)""", {"r": role_id, "n": name, "d": desc, "c": cj, "u": adm["id"], "t": now})
    audit.record(adm, "ROLE_SAVE", f"권한 묶음 · {name}",
                 before=json.loads(before["CONF_JSON"]) | {"name": before["ROLE_NM"]} if before else None, after=conf | {"name": name})
    result = {"id": role_id, "reapplied": None}
    if role_id and body.get("reapply"):
        ids = [m["id"] for m in _members().get(role_id, [])]
        if ids:
            result["reapplied"] = apply(adm, role_id, ids)
    return result


def delete(adm: dict, role_id: str) -> dict:
    tables.require()
    r = _get(role_id)
    db.execute(f"DELETE FROM {MEMBER_TABLE} WHERE ROLE_ID = :r", {"r": role_id})
    db.execute(f"DELETE FROM {ROLE_TABLE} WHERE ROLE_ID = :r", {"r": role_id})
    audit.record(adm, "ROLE_DELETE", f"권한 묶음 · {r['ROLE_NM']}", summary="권한 묶음 삭제 (사용자 권한은 그대로)")
    return {"ok": True}


_MERGE_MEMBER = f"""MERGE INTO {MEMBER_TABLE} T USING (SELECT :u AS USR_ID FROM DUAL) S ON (T.USR_ID = S.USR_ID)
    WHEN MATCHED THEN UPDATE SET ROLE_ID = :r, APPLY_DAY = :t, APPLY_USERID = :by
    WHEN NOT MATCHED THEN INSERT (USR_ID, ROLE_ID, APPLY_DAY, APPLY_USERID) VALUES (:u, :r, :t, :by)"""


def _remember(usr_id: str, role_id: str, by: str) -> None:
    db.execute(_MERGE_MEMBER, {"u": usr_id, "r": role_id, "t": _now14(), "by": by})


def apply(adm: dict, role_id: str, user_ids: list[str]) -> dict:
    """묶음을 사용자들에게 적용 (메뉴 · 브랜드 · AI). 최고 관리자는 건너뛴다. 한 명 실패가 나머지를 막지 않는다."""
    tables.require()
    if not isinstance(user_ids, list) or not user_ids:
        _bad("적용할 사용자를 고르세요.")
    r = _get(role_id)
    conf = json.loads(r["CONF_JSON"])
    applied, skipped = [], []
    for uid in dict.fromkeys(str(x) for x in user_ids[:500]):
        if auth.is_super_admin(uid):
            skipped.append({"id": uid, "reason": "최고 관리자는 모든 권한을 가집니다."})
            continue
        try:
            admin.save_user(adm, uid, {k: conf.get(k) for k in CONF_KEYS})
            _remember(uid, role_id, adm["id"])
            applied.append(uid)
        except HTTPException as ex:
            skipped.append({"id": uid, "reason": ex.detail.get("message") if isinstance(ex.detail, dict) else str(ex.detail)})
    return {"applied": applied, "skipped": skipped, "role": r["ROLE_NM"]}


def role_of(usr_id: str) -> dict | None:
    """마이페이지 · 사용자 목록: 마지막으로 적용된 묶음 이름"""
    if not tables.ready():
        return None
    rows = db.query_dicts(f"""SELECT R.ROLE_NM, M.APPLY_DAY FROM {MEMBER_TABLE} M JOIN {ROLE_TABLE} R ON R.ROLE_ID = M.ROLE_ID
                               WHERE M.USR_ID = :u""", {"u": usr_id})
    return {"name": rows[0]["ROLE_NM"], "appliedAt": _fmt14(rows[0]["APPLY_DAY"])} if rows else None
