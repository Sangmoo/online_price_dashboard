"""관리자 변경 이력: 요약 문장, 기록/조회, 관리자 작업별 기록."""
import pytest

from app import admin, ai_tools, audit
from app.audit import record as real_record  # autouse 캡처 이전의 실제 기록 함수

BASE_TOOL = {"name": "shop_top", "label": "매장 상위", "description": "판매년월의 매출 상위 매장을 조회합니다.", "page": "sale_monthly",
             "sql": "SELECT SHOP_ID FROM T_SHOP WHERE SHOP_ID = :ym", "params": [{"name": "ym", "type": "string", "required": True}], "maxRows": 10}


def test_diff_summary_readable():
    s = audit.diff_summary({"role": "USER", "pages": ["dashboard", "detail"], "daily_questions": None, "active": True},
                           {"role": "ADMIN", "pages": ["detail", "dashboard"], "daily_questions": 5, "active": False})
    assert s == "권한: USER → ADMIN / 일일 질문 한도: 기본값 → 5 / 계정 사용: 예 → 아니오"  # 메뉴 순서만 바뀐 건 변경 아님
    assert audit.diff_summary({"pages": ["dashboard"]}, {"pages": ["dashboard", "sale_monthly"]}) == \
        "메뉴 권한: 대시보드 → 대시보드, 월별 매장별 판매 집계"


def test_record_and_search_local(temp_store, monkeypatch):
    monkeypatch.setattr(audit, "use_oracle", lambda: False)
    adm = {"id": "250016", "ip": "10.0.0.1"}
    real_record(adm, "USER_UPDATE", "170046", {"daily_questions": None}, {"daily_questions": 5})
    real_record(adm, "USER_UPDATE", "170046", {"daily_questions": 5}, {"daily_questions": 5})  # 변경 없음 → 기록 안 함
    real_record(adm, "LOCK_RELEASE", "170046", summary="170046 로그인 잠금 해제")
    rows = audit.search()
    assert [r["action"] for r in rows] == ["LOCK_RELEASE", "USER_UPDATE"]
    assert rows[1]["summary"] == "일일 질문 한도: 기본값 → 5" and rows[1]["ip"] == "10.0.0.1"
    assert rows[1]["before"] == {"daily_questions": None} and rows[1]["actionLabel"] == "사용자 설정 변경"
    assert len(audit.search(action="LOCK_RELEASE")) == 1 and len(audit.search(q="질문")) == 1


def test_admin_actions_are_recorded(audit_capture, monkeypatch, temp_store):
    users = {"170046": {"usr_id": "170046", "usr_nm": "조병민", "role": "USER", "pages": '["dashboard"]', "ai_enabled": 1,
                        "daily_questions": None, "daily_cost_usd": None, "active": 1}}

    def update_user(uid, values, by):
        u = users[uid]
        if "pages" in values:
            import json
            u["pages"] = json.dumps(values["pages"])
        for k in ("role", "daily_questions"):
            if k in values:
                u[k] = values[k]

    monkeypatch.setattr(admin.userdb, "get_user", lambda uid, fresh=False: users.get(uid))
    monkeypatch.setattr(admin.userdb, "update_user", update_user)
    monkeypatch.setattr(admin, "list_users", lambda q=None: [{"id": u} for u in users])
    adm = {"id": "250016", "ip": "10.0.0.1"}
    admin.save_user(adm, "170046", {"dailyQuestions": 5})
    admin.save_permissions(adm, [{"id": "170046", "pages": ["dashboard", "sale_monthly"]}])
    monkeypatch.setattr(ai_tools, "_use_oracle", lambda: False)
    ai_tools.invalidate()
    admin.save_custom_tool(adm, dict(BASE_TOOL))
    admin.save_custom_tool(adm, {**BASE_TOOL, "maxRows": 20}, "shop_top")
    admin.delete_custom_tool(adm, "shop_top")
    ai_tools.invalidate()
    acts = [(c["action"], c["target"]) for c in audit_capture]
    assert acts == [("USER_UPDATE", "170046"), ("PERM_UPDATE", "170046"), ("TOOL_CREATE", "shop_top"),
                    ("TOOL_UPDATE", "shop_top"), ("TOOL_DELETE", "shop_top")]
    assert audit_capture[0]["before"]["daily_questions"] is None and audit_capture[0]["after"]["daily_questions"] == 5
    assert audit_capture[1]["after"] == {"pages": ["dashboard", "sale_monthly"]}
    assert audit_capture[3]["before"]["maxRows"] == 10 and audit_capture[3]["after"]["maxRows"] == 20
