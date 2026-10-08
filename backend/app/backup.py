"""관리 설정 백업 · 복원 (관리자 > 설정 백업).

담는 것: 사용자(권한 · 메뉴 · 브랜드 · AI 사용 · 일일 한도 · 사용 여부), 전역 설정, AI 도구(기본 도구 설정 · 관리자 정의 도구).
담지 않는 것: 비밀번호(사내 계정 T_USR 로 확인하므로 앱에 없음), 세션, 대화 기록, 로그, 변경 이력.

복원은 미리보기(무엇이 추가·변경되는지)를 먼저 보여주고, 적용은 평소 관리자 기능(사용자 추가·저장, 설정 저장, AI 도구 저장)을
그대로 거친다 → 입력 검증 · 변경 이력이 같고, 사번 확인에 실패한 사용자 등은 건너뛰고 사유를 알려준다.
파일에 없는 사용자·도구는 지우지 않는다. 최고 관리자는 복원 대상에서 뺀다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from . import admin, ai_tools, audit, auth, userdb

APP_ID = "erp-sales-web"
VERSION = 1
SECTIONS = ("users", "settings", "aiTools")
USER_KEYS = ("role", "pages", "brands", "aiEnabled", "dailyQuestions", "dailyCostUsd", "dailyBriefings", "active")
SETTING_KEYS = ("aiEnabled", "defaultDailyQuestions", "defaultDailyCostUsd", "defaultDailyBriefings", "model", "effort", "logKeepDays", "autoModel", "simpleModel", "feedbackImageKeepMonths")
CUSTOM_KEYS = ("label", "description", "page", "sql", "params", "maxRows", "enabled")


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


def _users_now() -> dict[str, dict]:
    out = {}
    for u in userdb.list_users():
        out[u["usr_id"]] = {
            "id": u["usr_id"], "name": u["usr_nm"], "role": u["role"], "pages": json.loads(u["pages"] or "[]"),
            "brands": json.loads(u.get("brands") or "[]") or None, "aiEnabled": bool(u["ai_enabled"]),
            "dailyQuestions": u["daily_questions"], "dailyCostUsd": u["daily_cost_usd"], "dailyBriefings": u.get("daily_briefings"),
            "active": bool(u["active"]),
        }
    return out


def _settings_now() -> dict:
    s = admin.get_settings()
    return {k: s.get(k) for k in SETTING_KEYS if k in s}


def _tools_now() -> dict:
    snap = ai_tools.snapshot()
    return {
        "builtin": {n: {"enabled": b.get("enabled", True), "extraDesc": b.get("extraDesc", ""), "description": b.get("description") or None}
                    for n, b in snap["builtin"].items()},
        "custom": [{"name": c["name"], **{k: c[k] for k in CUSTOM_KEYS}} for c in snap["custom"]],
    }


def export(me: dict) -> dict:
    return {"app": APP_ID, "version": VERSION, "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "createdBy": me["id"],
            "users": list(_users_now().values()), "settings": _settings_now(), "aiTools": _tools_now()}


def _check(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("app") != APP_ID:
        _bad("이 서비스의 설정 백업 파일이 아닙니다.")
    if data.get("version") != VERSION:
        _bad(f"지원하지 않는 백업 버전입니다 ({data.get('version')}).")
    return data


def _norm_user(u: dict) -> dict:
    b = u.get("brands")
    return {"role": u.get("role"), "pages": sorted(u.get("pages") or []), "brands": sorted(b) if b else None,
            "aiEnabled": bool(u.get("aiEnabled", True)), "dailyQuestions": u.get("dailyQuestions"),
            "dailyCostUsd": float(u["dailyCostUsd"]) if u.get("dailyCostUsd") is not None else None,
            "dailyBriefings": u.get("dailyBriefings"), "active": bool(u.get("active", True))}


def preview(data: Any) -> dict:
    data = _check(data)
    now_users = _users_now()
    file_users = {str(u.get("id")): u for u in data.get("users") or [] if isinstance(u, dict) and u.get("id")}
    added, changed, same, skipped = [], [], 0, []
    for uid, fu in file_users.items():
        if auth.is_super_admin(uid):
            skipped.append({"id": uid, "name": fu.get("name"), "reason": "최고 관리자는 복원하지 않음"})
            continue
        cur = now_users.get(uid)
        if not cur:
            added.append({"id": uid, "name": fu.get("name")})
            continue
        a, b = _norm_user(cur), _norm_user(fu)
        diff = {k: {"before": a[k], "after": b[k]} for k in USER_KEYS if a[k] != b[k] and (k in fu or k != "dailyBriefings")}
        if diff:
            changed.append({"id": uid, "name": cur["name"], "diff": diff})
        else:
            same += 1
    not_in_file = [{"id": u["id"], "name": u["name"]} for uid, u in now_users.items() if uid not in file_users]

    s_now, s_file = _settings_now(), data.get("settings") or {}
    s_changed = [{"key": k, "before": s_now.get(k), "after": s_file[k]} for k in SETTING_KEYS
                 if k in s_file and k in s_now and s_file[k] != s_now.get(k)]

    t_now, t_file = _tools_now(), data.get("aiTools") or {}
    b_changed = [{"name": n, "before": t_now["builtin"].get(n), "after": v} for n, v in (t_file.get("builtin") or {}).items()
                 if v != t_now["builtin"].get(n, {"enabled": True, "extraDesc": "", "description": None})]
    now_custom = {c["name"]: c for c in t_now["custom"]}
    c_added, c_changed = [], []
    for c in t_file.get("custom") or []:
        cur = now_custom.get(c.get("name"))
        if not cur:
            c_added.append({"name": c.get("name"), "label": c.get("label")})
        elif any(cur.get(k) != c.get(k) for k in CUSTOM_KEYS):
            c_changed.append({"name": c.get("name"), "label": c.get("label"), "keys": [k for k in CUSTOM_KEYS if cur.get(k) != c.get(k)]})
    return {
        "file": {"createdAt": data.get("createdAt"), "createdBy": data.get("createdBy")},
        "users": {"added": added, "changed": changed, "same": same, "notInFile": not_in_file, "skipped": skipped},
        "settings": {"changed": s_changed},
        "aiTools": {"builtinChanged": b_changed, "customAdded": c_added, "customChanged": c_changed},
    }


def _user_body(u: dict) -> dict:
    return {"role": u.get("role"), "pages": [p for p in (u.get("pages") or []) if p in auth.PAGES], "brands": u.get("brands") or None,
            "aiEnabled": bool(u.get("aiEnabled", True)), "dailyQuestions": u.get("dailyQuestions"),
            "dailyCostUsd": u.get("dailyCostUsd"), "active": bool(u.get("active", True)),
            **({"dailyBriefings": u.get("dailyBriefings")} if "dailyBriefings" in u else {})}


def apply(me: dict, data: Any, sections: list[str]) -> dict:
    data = _check(data)
    if not sections or any(s not in SECTIONS for s in sections):
        _bad(f"복원할 항목은 {list(SECTIONS)} 중에서 고릅니다.")
    plan = preview(data)
    done: dict[str, list] = {"applied": [], "failed": []}

    def attempt(label: str, fn) -> None:
        try:
            fn()
            done["applied"].append(label)
        except HTTPException as ex:
            done["failed"].append({"item": label, "reason": ex.detail.get("message") if isinstance(ex.detail, dict) else str(ex.detail)})
        except Exception as ex:  # noqa: BLE001
            done["failed"].append({"item": label, "reason": str(ex).splitlines()[0][:200]})

    if "users" in sections:
        file_users = {str(u.get("id")): u for u in data.get("users") or [] if isinstance(u, dict)}
        for a in plan["users"]["added"]:
            u = file_users[a["id"]]
            attempt(f"사용자 추가 {a['name'] or ''}({a['id']})", lambda u=u: admin.create_user(me, {"id": u["id"], **_user_body(u)}))
        for c in plan["users"]["changed"]:
            u = file_users[c["id"]]
            body = {k: v for k, v in _user_body(u).items() if k in c["diff"]}
            attempt(f"사용자 변경 {c['name'] or ''}({c['id']})", lambda uid=c["id"], body=body: admin.save_user(me, uid, body))
    if "settings" in sections and plan["settings"]["changed"]:
        body = {x["key"]: x["after"] for x in plan["settings"]["changed"]}
        attempt(f"전역 설정 {len(body)}개", lambda: admin.save_settings(body, me))
    if "aiTools" in sections:
        tools = data.get("aiTools") or {}
        for b in plan["aiTools"]["builtinChanged"]:
            v = b["after"] or {}
            attempt(f"기본 도구 {b['name']}", lambda n=b["name"], v=v: admin.save_builtin_tool(
                me, n, {"enabled": v.get("enabled", True), "extraDesc": v.get("extraDesc", ""), "description": v.get("description")}))
        by_name = {c.get("name"): c for c in tools.get("custom") or []}
        for c in plan["aiTools"]["customAdded"]:
            attempt(f"AI 도구 추가 {c['name']}", lambda c=by_name[c["name"]]: admin.save_custom_tool(me, dict(c)))
        for c in plan["aiTools"]["customChanged"]:
            attempt(f"AI 도구 변경 {c['name']}", lambda c=by_name[c["name"]]: admin.save_custom_tool(me, dict(c), c["name"]))
    audit.record(me, "SETTINGS_RESTORE", (data.get("createdAt") or "")[:100], None, None,
                 summary=f"설정 복원 ({', '.join(sections)}) · 적용 {len(done['applied'])}건 · 실패 {len(done['failed'])}건 · "
                         f"백업 {data.get('createdAt')} ({data.get('createdBy')})")
    return done
