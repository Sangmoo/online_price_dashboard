"""운영: 로그 보관 정리, 서버 상태 요약, 새 월 마감 알림, AI 표 전체 엑셀 상한·권한, 보관 기간 설정 검증."""
import os
import time

import pytest

from app import chat_service, chat_tools, logs, mv_refresh, server_status, tool_limits

DAY = 86400


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logs, "APP_LOG", tmp_path / "app.log")
    monkeypatch.setattr(server_status, "SERVICE_LOG", tmp_path / "service.log")
    monkeypatch.setattr(server_status, "_cache", {})
    return tmp_path


def _file(path, text="x", age_days=0.0):
    path.write_text(text, encoding="utf-8")
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))
    return path


def test_cleanup_deletes_only_old_rotated_files(log_dir):
    cur = _file(log_dir / "app.log", age_days=30)            # 현재 파일은 오래돼도 지우지 않음
    old = _file(log_dir / "app.log.2026-09-01", age_days=28)
    old_err = _file(log_dir / "error.log.1", age_days=10)     # 이전(크기 교체) 방식 파일도 정리
    recent = _file(log_dir / "app.log.2026-09-27", age_days=2)
    r = logs.cleanup(7)
    assert sorted(r["deleted"]) == ["app.log.2026-09-01", "error.log.1"] and r["keepDays"] == 7
    assert cur.exists() and recent.exists() and not old.exists() and not old_err.exists()


def test_cleanup_size_cap(log_dir, monkeypatch):
    monkeypatch.setattr(logs, "MAX_TOTAL_BYTES", 25)
    a = _file(log_dir / "app.log.2026-09-26", "a" * 10, age_days=3)
    b = _file(log_dir / "app.log.2026-09-27", "b" * 10, age_days=2)
    _file(log_dir / "app.log", "c" * 10)
    logs.cleanup(30)
    assert not a.exists() and b.exists()  # 오래된 것부터 지워 상한 이하로


def test_server_status_summarizes_logs(log_dir):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 20 * DAY))
    _file(log_dir / "app.log", "\n".join([
        f"{now} INFO  erp.request  user=250016 GET /api/sale-dashboard?ym=202608 200 120ms",
        f"{now} WARNING erp.request  user=250016 GET /api/sale-monthly 200 6200ms",
        f"{now} ERROR erp.request  user=250016 GET /api/x 500 30ms",
        f"{now} WARNING erp.sql      느린 query 4.50s | binds=['m0'] | SELECT 1 FROM T_CLOSE_SALE_BASE",
        f"{now} WARNING erp.sql      느린 query 3.50s | binds=['m0'] | SELECT 1 FROM T_CLOSE_SALE_BASE",
        f"{now} ERROR erp.sql      query 실패 0.01s ORA-00942: 없음 | binds=[] | SELECT * FROM NOPE",
        f"{old} INFO  erp.request  user=1 GET /api/old 200 99999ms",   # 기간 밖
    ]) + "\n")
    _file(log_dir / "service.log", "\n".join([
        f"{now} INFO  서버 시작 (pid=1)",
        f"{now} ERROR 서버 재시작 예정: 응답 없음(멈춤), 400초 실행, 5초 후 다시 시작 (server-console.log 확인)",
        f"{now} INFO  재시작 요청으로 서버를 다시 시작합니다 (배포).",
    ]) + "\n")
    s = server_status.status(7, 7)
    assert s["requests"]["count"] == 3 and s["requests"]["errors5xx"] == 1 and s["requests"]["slow"] == 1
    assert s["requests"]["slowPaths"] == [{"path": "/api/sale-monthly", "count": 1, "maxMs": 6200}]
    top = s["slowSql"]["top"][0]
    assert (s["slowSql"]["count"], top["count"], top["maxSec"], top["avgSec"]) == (2, 2, 4.5, 4.0)
    assert s["sqlErrors"]["count"] == 1 and "ORA-00942" in s["sqlErrors"]["recent"][0]["error"]
    assert s["errors"]["count"] == 2
    assert (s["supervisor"]["crashRestarts"], s["supervisor"]["deployRestarts"]) == (1, 1)
    assert s["keepDays"] == 7 and s["server"]["uptimeSec"] >= 0


def test_freshness_uses_cached_mv_state(monkeypatch):
    from app import chat_tools_sale as cts

    monkeypatch.setattr(cts, "mv_state", lambda: {"base_max": "202609", "mv_max": "202608", "last_refresh": None})
    f = mv_refresh.freshness()
    assert f["behind"] and f["baseMaxMonth"] == "202609" and f["mvMaxMonth"] == "202608"
    monkeypatch.setattr(cts, "mv_state", lambda: {"base_max": "202608", "mv_max": "202608", "last_refresh": None})
    assert mv_refresh.freshness()["behind"] is False


def test_tool_row_cap_only_inside_full_export():
    assert chat_tools._limit({"limit": 5000}, 50) == 200
    with tool_limits.full_export() as n:
        assert chat_tools._limit({"limit": n}, 50) == tool_limits.FULL_EXPORT_MAX
    assert chat_tools._limit({"limit": 5000}, 50) == 200  # 끝나면 원래대로


def test_export_full_reruns_same_tool_with_permission_check(monkeypatch):
    seen = {}

    def fake_run(name, inp, me):
        seen.update(name=name, inp=inp, cap=tool_limits.cap(200))
        if "invt_plan" not in me["pages"]:
            raise chat_tools.ToolInputError("권한 없음")
        return {"result": {"total_matched": 3}, "table": {"columns": [{"key": "A", "label": "가"}], "rows": [{"A": 1}] * 3,
                                                           "totalMatched": 3}}

    monkeypatch.setattr(chat_service, "run_tool", fake_run)
    out = chat_service.export_full("search_invt_plans", {"q": "강남", "limit": 30}, {"id": "1", "pages": ["invt_plan"]})
    assert seen == {"name": "search_invt_plans", "inp": {"q": "강남", "limit": 100_000}, "cap": 100_000}
    assert len(out["rows"]) == 3 and out["capped"] is False
    with pytest.raises(chat_tools.ToolInputError, match="권한"):
        chat_service.export_full("search_invt_plans", {}, {"id": "2", "pages": []})
    with pytest.raises(chat_tools.ToolInputError, match="지원하지"):
        chat_service.export_full("get_sales_dashboard", {}, {"id": "1", "pages": ["sale_dashboard"]})


def test_truncated_detection():
    assert chat_service._truncated({"result": {"truncated": True}, "table": {"rows": [1]}})
    assert chat_service._truncated({"result": {}, "table": {"rows": [1, 2], "totalMatched": 10}})
    assert not chat_service._truncated({"result": {"truncated": False}, "table": {"rows": [1], "totalMatched": 1}})


def test_log_keep_days_validation(monkeypatch, audit_capture):
    from fastapi import HTTPException

    from app import admin, userdb

    saved, cleaned = {}, []
    monkeypatch.setattr(userdb, "get_settings", lambda: {"log_keep_days": saved.get("log_keep_days", 7), "ai_enabled": True,
                                                         "default_daily_questions": 10, "default_daily_cost_usd": 2.0,
                                                         "model": None, "effort": None})
    monkeypatch.setattr(userdb, "save_settings", lambda values, by: saved.update(values))
    monkeypatch.setattr(logs, "cleanup", lambda d: cleaned.append(d) or {})
    with pytest.raises(HTTPException):
        admin.save_settings({"logKeepDays": 0}, {"id": "250016"})
    out = admin.save_settings({"logKeepDays": 14}, {"id": "250016"})
    assert out["logKeepDays"] == 14 and cleaned == [14]
    assert audit_capture[-1]["target"] == "운영 설정"
