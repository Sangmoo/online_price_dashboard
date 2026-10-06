"""관리자 > 계정 정리: 오래 로그인하지 않은 계정 · 권한은 있는데 쓰지 않는 메뉴를 찾아, 관리자가 확인한 뒤 골라서 정리한다.

자동으로 바꾸지 않는다. 정리는 사용자 설정 저장(admin.save_user)과 같은 검증 · 변경 이력으로 하고, 최고 관리자와 본인은 제외한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException

from . import admin, auth, menu_usage

PERIODS = (30, 60, 90, 180)


def _bad(msg: str):
    raise HTTPException(status_code=400, detail={"message": msg, "code": "BAD_REQUEST"})


def report(me: dict, days: int = 90) -> dict:
    """정리 후보: (1) days 일 넘게 로그인하지 않은 사용 중 계정 (2) days 일 동안 한 번도 열지 않은 메뉴 권한"""
    days = days if days in PERIODS else 90
    users = admin.list_users()
    cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    usage = {u["id"]: u for u in menu_usage.report(days, users)["users"]}
    labels = auth.PAGE_LABELS
    idle, unused = [], []
    for u in users:
        if u["superAdmin"] or u["id"] == me["id"] or not u["active"]:
            continue
        last = u.get("lastLoginAt")
        if not last or last < cut:
            idle.append({"id": u["id"], "name": u["name"], "role": u["role"], "lastLoginAt": last,
                         "createdAt": u.get("createdAt"), "pages": [labels.get(p, p) for p in u["pages"] if p in auth.PAGES],
                         "idleDays": (datetime.now() - datetime.strptime(last[:10], "%Y-%m-%d")).days if last else None})
        pages = [p for p in usage.get(u["id"], {}).get("unusedPages", []) if p in auth.PAGES]
        if pages:
            unused.append({"id": u["id"], "name": u["name"], "lastLoginAt": last,
                           "pages": [{"key": p, "label": labels.get(p, p)} for p in pages],
                           "keep": [labels.get(p, p) for p in u["pages"] if p in auth.PAGES and p not in pages]})
    idle.sort(key=lambda x: x["lastLoginAt"] or "")
    return {"days": days, "periods": list(PERIODS), "idle": idle, "unused": unused}


def apply(me: dict, body: dict) -> dict:
    """{deactivate: [사용자ID], revoke: [{id, pages: [메뉴]}]} — 고른 것만 정리"""
    deactivate = [str(x) for x in body.get("deactivate") or []]
    revoke = body.get("revoke") or []
    if not deactivate and not revoke:
        _bad("정리할 항목을 고르세요.")
    users = {u["id"]: u for u in admin.list_users()}
    done = {"deactivated": [], "revoked": [], "skipped": []}

    def ok(uid: str) -> str | None:
        if uid not in users:
            return "등록되지 않은 사용자"
        if users[uid]["superAdmin"]:
            return "최고 관리자"
        if uid == me["id"]:
            return "본인 계정"
        return None

    for uid in dict.fromkeys(deactivate):
        why = ok(uid)
        if why:
            done["skipped"].append({"id": uid, "reason": why})
            continue
        admin.save_user(me, uid, {"active": False})
        done["deactivated"].append(uid)
    for item in revoke:
        uid = str((item or {}).get("id") or "")
        drop = {str(p) for p in (item or {}).get("pages") or []}
        why = ok(uid)
        if why or not drop:
            done["skipped"].append({"id": uid, "reason": why or "회수할 메뉴 없음"})
            continue
        keep = [p for p in users[uid]["pages"] if p in auth.PAGES and p not in drop]
        admin.save_user(me, uid, {"pages": keep})
        done["revoked"].append({"id": uid, "pages": sorted(drop)})
    return done
