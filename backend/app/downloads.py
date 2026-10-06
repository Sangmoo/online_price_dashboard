"""데이터 다운로드 · 민감 정보 조회 이력: 누가 언제 어떤 조건으로 엑셀을 받았는지, 매장 매니저 연락처를 조회했는지.

저장소: Oracle T_ERP_WEB_DOWNLOAD_LOG (db/create_erp_web_admin_ops.sql) 만 쓴다. 테이블이 없으면 기록을 건너뛰고
관리자 화면에 DDL 실행 안내를 보여준다. 기록 실패는 다운로드를 막지 않는다. 보관 기간이 지난 기록은 정리 작업이 지운다.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from . import db, logs
from .tables import Tables

_log = logs.get("app")
ORA_TABLE = "T_ERP_WEB_DOWNLOAD_LOG"
tables = Tables(ORA_TABLE)
KEEP_DAYS = 400   # 1년 + 여유
KINDS: dict[str, str] = {
    "online_detail": "온라인 가격 일자별 상세",
    "table": "화면 표 엑셀",
    "ai_full": "AI 결과 전체 엑셀",
    "sale_report": "판매 현황 보고용 엑셀",
    "sale_monthly": "월별 매장별 판매 집계",
    "invt_plan": "매장 재고 실사계획",
    "settings_backup": "설정 백업 파일",
    "manager_phone": "매장 매니저 연락처 조회",
}
SENSITIVE = {"manager_phone", "settings_backup"}
COLS = ("DL_ID", "DL_DAY", "USR_ID", "KIND_CD", "TITLE", "PARAMS", "ROW_CNT", "FILE_BYTES", "IP")
_INSERT = f"INSERT INTO {ORA_TABLE} ({', '.join(COLS)}) VALUES ({', '.join(':' + c.lower() for c in COLS)})"
_warned = 0.0


def cut_bytes(s: str | None, max_bytes: int) -> str | None:
    """UTF-8 바이트 기준으로 자른다 (Oracle VARCHAR2 바이트 길이)"""
    if s is None:
        return None
    b = s.encode("utf-8")
    return s if len(b) <= max_bytes else b[:max_bytes].decode("utf-8", errors="ignore")


def record(me: dict, kind: str, title: str | None = None, params: dict | None = None,
           rows: int | None = None, size: int | None = None) -> None:
    """다운로드 · 조회 1건 기록. 테이블이 없거나 실패해도 예외를 내지 않는다."""
    global _warned
    try:
        if not tables.ready():
            if time.time() - _warned > 3600:   # 1시간에 한 번만 알린다
                _warned = time.time()
                _log.warning("다운로드 이력을 남기지 못했습니다: %s", tables.message())
            return
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [], {})}
        usr = me.get("id")
        if me.get("viewAs"):   # 관리자가 다른 사용자 화면을 미리보는 중: 실제로 본 관리자 이름으로 남긴다
            usr = me["viewAs"]["by"]
            title = f"[미리보기 {me.get('id')}] {title or ''}"
        db.execute(_INSERT, {
            "dl_id": uuid.uuid4().hex, "dl_day": datetime.now().strftime("%Y%m%d%H%M%S"), "usr_id": str(usr or "-")[:20],
            "kind_cd": kind[:30], "title": cut_bytes(title, 300),
            "params": cut_bytes(json.dumps(clean, ensure_ascii=False, default=str), 2000) if clean else None,
            "row_cnt": rows, "file_bytes": size, "ip": cut_bytes(me.get("ip"), 45),
        })
    except Exception:  # noqa: BLE001 - 기록 실패가 다운로드를 막지 않게
        _log.exception("다운로드 이력 기록 실패 user=%s kind=%s", me.get("id"), kind)


def _fmt(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}" if v and len(v) >= 14 else v


def report(days: int = 30, usr: str | None = None, kind: str | None = None, names: dict[str, str] | None = None,
           limit: int = 500) -> dict:
    """관리자 화면: 기간 · 사용자 · 종류 조건의 기록 (최근 limit 건) + 사용자별 · 종류별 · 일별 합계"""
    days = max(1, min(int(days), 365))
    base = {"days": days, "table": tables.status(), "kinds": KINDS, "sensitiveKinds": sorted(SENSITIVE)}
    if not tables.ready():
        return {**base, "total": 0, "byUser": [], "byKind": [], "daily": [], "rows": [], "truncated": False, "alerts": [],
                "alertSettings": alert_settings()}
    if kind and kind not in KINDS:
        kind = None
    conds, p = ["DL_DAY >= :s"], {"s": (datetime.now() - timedelta(days=days - 1)).strftime("%Y%m%d") + "000000"}
    if (usr or "").strip():
        conds.append("USR_ID = :u")
        p["u"] = usr.strip()
    if kind:
        conds.append("KIND_CD = :k")
        p["k"] = kind
    rows = [{k.lower(): v for k, v in r.items()} for r in db.query_dicts(
        f"SELECT {', '.join(COLS)} FROM {ORA_TABLE} WHERE {' AND '.join(conds)} ORDER BY DL_DAY DESC", p)]
    names = names or {}
    by_user: dict[str, dict[str, Any]] = {}
    by_kind: dict[str, int] = defaultdict(int)
    daily: dict[str, int] = defaultdict(int)
    for r in rows:
        u = by_user.setdefault(r["usr_id"], {"id": r["usr_id"], "name": names.get(r["usr_id"], r["usr_id"]), "count": 0,
                                             "sensitive": 0, "rows": 0, "last": None, "kinds": defaultdict(int)})
        u["count"] += 1
        u["rows"] += int(r["row_cnt"] or 0)
        u["sensitive"] += r["kind_cd"] in SENSITIVE
        u["kinds"][r["kind_cd"]] += 1
        u["last"] = max(u["last"] or "", r["dl_day"])
        by_kind[r["kind_cd"]] += 1
        daily[r["dl_day"][:8]] += 1
    users = sorted(by_user.values(), key=lambda x: x["count"], reverse=True)
    for u in users:
        u["last"] = _fmt(u["last"])
        u["kinds"] = dict(u["kinds"])
    return {
        **base, "total": len(rows), "byUser": users, "alerts": alerts(names), "alertSettings": alert_settings(),
        "byKind": [{"kind": k, "label": KINDS.get(k, k), "count": n} for k, n in sorted(by_kind.items(), key=lambda x: -x[1])],
        "daily": [{"day": f"{d[:4]}-{d[4:6]}-{d[6:]}", "count": n} for d, n in sorted(daily.items())],
        "rows": [{"id": r["dl_id"], "at": _fmt(r["dl_day"]), "usrId": r["usr_id"], "name": names.get(r["usr_id"], r["usr_id"]),
                  "kind": r["kind_cd"], "kindLabel": KINDS.get(r["kind_cd"], r["kind_cd"]), "title": r["title"],
                  "params": json.loads(r["params"]) if r["params"] else None, "rows": r["row_cnt"], "bytes": r["file_bytes"],
                  "ip": r["ip"], "sensitive": r["kind_cd"] in SENSITIVE} for r in rows[:limit]],
        "truncated": len(rows) > limit,
    }


EXCEL_KINDS = set(KINDS) - SENSITIVE


def alert_settings() -> dict:
    from . import userdb

    st = userdb.get_settings()
    return {"count": int(st.get("dl_alert_count") or 10), "phone": int(st.get("dl_alert_phone") or 20),
            "rows": int(st.get("dl_alert_rows") or 100000)}


def save_alert_settings(adm: dict, body: dict) -> dict:
    from fastapi import HTTPException

    from . import audit, userdb

    vals = {}
    for key, skey, lo, hi in (("count", "dl_alert_count", 1, 1000), ("phone", "dl_alert_phone", 1, 1000), ("rows", "dl_alert_rows", 1000, 10_000_000)):
        v = body.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            raise HTTPException(400, {"message": f"알림 기준이 올바르지 않습니다 ({key}: {lo}~{hi:,})", "code": "BAD_REQUEST"})
        vals[skey] = v
    before = alert_settings()
    userdb.save_settings(vals, adm["id"])
    after = alert_settings()
    audit.record(adm, "SETTING_UPDATE", "대량 다운로드 알림 기준", before=before, after=after)
    return after


def alerts(names: dict[str, str] | None = None, now: datetime | None = None) -> list[dict]:
    """대량 다운로드 의심: 최근 1시간 엑셀 n건 이상 · 매니저 연락처 조회 n건 이상, 최근 24시간 한 번에 n행 이상 엑셀"""
    if not tables.ready():
        return []
    now = now or datetime.now()
    cfg = alert_settings()
    h1 = (now - timedelta(hours=1)).strftime("%Y%m%d%H%M%S")
    h24 = (now - timedelta(hours=24)).strftime("%Y%m%d%H%M%S")
    rows = [{k.lower(): v for k, v in r.items()} for r in db.query_dicts(
        f"SELECT {', '.join(COLS)} FROM {ORA_TABLE} WHERE DL_DAY >= :s ORDER BY DL_DAY DESC", {"s": h24})]
    names = names or {}
    out: list[dict] = []
    by_user: dict[str, dict[str, list]] = {}
    for r in rows:
        if r["dl_day"] >= h1:
            g = by_user.setdefault(r["usr_id"], {"excel": [], "phone": []})
            if r["kind_cd"] in EXCEL_KINDS:
                g["excel"].append(r)
            elif r["kind_cd"] == "manager_phone":
                g["phone"].append(r)
        if r["kind_cd"] in EXCEL_KINDS and (r["row_cnt"] or 0) >= cfg["rows"]:
            out.append({"usrId": r["usr_id"], "name": names.get(r["usr_id"], r["usr_id"]), "kind": "rows", "at": _fmt(r["dl_day"]),
                        "count": int(r["row_cnt"]), "message": f"한 번에 {int(r['row_cnt']):,}행 엑셀 ({r['title'] or KINDS.get(r['kind_cd'])})"})
    for uid, g in by_user.items():
        if len(g["excel"]) >= cfg["count"]:
            out.append({"usrId": uid, "name": names.get(uid, uid), "kind": "count", "at": _fmt(g["excel"][0]["dl_day"]),
                        "count": len(g["excel"]), "message": f"최근 1시간 엑셀 {len(g['excel'])}건"})
        if len(g["phone"]) >= cfg["phone"]:
            out.append({"usrId": uid, "name": names.get(uid, uid), "kind": "phone", "at": _fmt(g["phone"][0]["dl_day"]),
                        "count": len(g["phone"]), "message": f"최근 1시간 매니저 연락처 조회 {len(g['phone'])}건"})
    out.sort(key=lambda x: x["at"] or "", reverse=True)
    return out


def today_summary() -> dict:
    """관리자 홈: 오늘 · 최근 7일 건수와 최근 7일 가장 많이 받은 사용자"""
    week = report(7)
    today = datetime.now().strftime("%Y-%m-%d")
    top = week["byUser"][0] if week["byUser"] else None
    al = alerts({u["id"]: u["name"] for u in week["byUser"]})
    return {"ready": week["table"]["ready"], "alerts": len(al), "alertMessages": [f"{a['name']} · {a['message']}" for a in al[:3]],
            "today": sum(d["count"] for d in week["daily"] if d["day"] == today), "week": week["total"],
            "sensitiveWeek": sum(u["sensitive"] for u in week["byUser"]),
            "topUser": {"id": top["id"], "name": top["name"], "count": top["count"]} if top else None}


def purge(keep_days: int = KEEP_DAYS) -> int:
    if not tables.ready():
        return 0
    cut = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d") + "000000"
    return db.execute(f"DELETE FROM {ORA_TABLE} WHERE DL_DAY < :c", {"c": cut})
