"""설정 백업·복원: 파일 형식 확인, 미리보기(추가·변경·같음·최고 관리자 제외), 적용은 평소 관리자 기능을 거치고 실패는 사유와 함께."""
import copy

import pytest
from fastapi import HTTPException

from app import backup

USERS = {
    "170046": {"id": "170046", "name": "가", "role": "USER", "pages": ["sale_dashboard"], "brands": None, "aiEnabled": True,
               "dailyQuestions": None, "dailyCostUsd": None, "active": True},
    "250016": {"id": "250016", "name": "최고", "role": "ADMIN", "pages": [], "brands": None, "aiEnabled": True,
               "dailyQuestions": None, "dailyCostUsd": None, "active": True},
}
SETTINGS = {"aiEnabled": True, "defaultDailyQuestions": 10, "defaultDailyCostUsd": 2.0, "model": "claude-opus-5", "effort": "medium", "logKeepDays": 7}
TOOLS = {"builtin": {"search_sales": {"enabled": True, "extraDesc": "", "description": None}},
         "custom": [{"name": "my_tool", "label": "내 도구", "description": "d", "page": "sale_monthly", "sql": "SELECT 1 FROM DUAL",
                     "params": [], "maxRows": 100, "enabled": True}]}


@pytest.fixture
def env(monkeypatch, audit_capture):
    calls = []
    monkeypatch.setattr(backup, "_users_now", lambda: copy.deepcopy(USERS))
    monkeypatch.setattr(backup, "_settings_now", lambda: dict(SETTINGS))
    monkeypatch.setattr(backup, "_tools_now", lambda: copy.deepcopy(TOOLS))

    def create_user(me, body):
        if body["id"] == "999999":
            raise HTTPException(400, {"message": "사내 계정(T_USR)에 없는 사번입니다."})
        calls.append(("create", body["id"], body))

    monkeypatch.setattr(backup.admin, "create_user", create_user)
    monkeypatch.setattr(backup.admin, "save_user", lambda me, uid, body: calls.append(("save", uid, body)))
    monkeypatch.setattr(backup.admin, "save_settings", lambda body, me: calls.append(("settings", body)))
    monkeypatch.setattr(backup.admin, "save_builtin_tool", lambda me, n, body: calls.append(("builtin", n, body)))
    monkeypatch.setattr(backup.admin, "save_custom_tool", lambda me, body, name=None: calls.append(("custom", body["name"], name)))
    return calls, audit_capture


def _file():
    return {"app": backup.APP_ID, "version": backup.VERSION, "createdAt": "2026-10-02 10:00:00", "createdBy": "250016",
            "users": copy.deepcopy(list(USERS.values())), "settings": dict(SETTINGS), "aiTools": copy.deepcopy(TOOLS)}


def test_rejects_other_files(env):
    for bad in ({}, {"app": "other", "version": 1}, {"app": backup.APP_ID, "version": 99}):
        with pytest.raises(HTTPException):
            backup.preview(bad)


def test_same_file_has_no_changes(env):
    p = backup.preview(_file())
    assert p["users"]["same"] == 1 and p["users"]["skipped"][0]["id"] == "250016"
    assert not p["users"]["changed"] and not p["settings"]["changed"] and not p["aiTools"]["customChanged"]


def test_apply_goes_through_admin_functions(env):
    calls, audit_log = env
    f = _file()
    f["users"][0]["pages"] = ["sale_dashboard", "sale_monthly"]
    f["users"][0]["brands"] = ["리스트"]
    f["users"].append({"id": "170047", "name": "나", "role": "USER", "pages": ["invt_plan"], "brands": None})
    f["users"].append({"id": "999999", "name": "없음", "role": "USER", "pages": ["invt_plan"]})
    f["users"][1]["role"] = "USER"  # 최고 관리자는 바뀌지 않아야 함
    f["settings"]["defaultDailyQuestions"] = 20
    f["aiTools"]["builtin"]["search_sales"]["extraDesc"] = "추가 안내"
    f["aiTools"]["custom"][0]["sql"] = "SELECT 2 FROM DUAL"
    f["aiTools"]["custom"].append({**f["aiTools"]["custom"][0], "name": "new_tool"})
    out = backup.apply({"id": "250016"}, f, ["users", "settings", "aiTools"])
    assert ("save", "170046", {"pages": ["sale_dashboard", "sale_monthly"], "brands": ["리스트"]}) in calls
    assert any(c[0] == "create" and c[1] == "170047" for c in calls)
    assert not any(c[1] == "250016" for c in calls if len(c) > 1)
    assert ("settings", {"defaultDailyQuestions": 20}) in calls
    assert ("builtin", "search_sales", {"enabled": True, "extraDesc": "추가 안내", "description": None}) in calls
    assert ("custom", "my_tool", "my_tool") in calls and ("custom", "new_tool", None) in calls
    assert out["failed"] == [{"item": "사용자 추가 없음(999999)", "reason": "사내 계정(T_USR)에 없는 사번입니다."}]
    assert audit_log[-1]["action"] == "SETTINGS_RESTORE" and "실패 1건" in audit_log[-1]["summary"]


def test_apply_only_selected_sections(env):
    calls, _ = env
    f = _file()
    f["settings"]["defaultDailyQuestions"] = 30
    f["users"][0]["active"] = False
    backup.apply({"id": "250016"}, f, ["settings"])
    assert calls == [("settings", {"defaultDailyQuestions": 30})]
    with pytest.raises(HTTPException):
        backup.apply({"id": "250016"}, f, ["passwords"])
