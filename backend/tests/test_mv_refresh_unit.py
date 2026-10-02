"""사전 집계 뷰 수동 갱신: 백그라운드 실행, 동시 실행 방지, 캐시 비우기, 변경 이력, 실패 처리. DB 는 가짜로 대체."""
import threading
import time

import pytest

from app import mv_refresh, sale_dashboard, sale_monthly


@pytest.fixture
def fake(monkeypatch):
    gate = threading.Event()
    calls = []
    snaps = iter([{"lastRefresh": "2026-09-29 14:23:43", "staleness": "STALE", "rows": 24170, "maxMonth": "202608"},
                  {"lastRefresh": "2026-10-05 09:00:00", "staleness": "FRESH", "rows": 24700, "maxMonth": "202609"}])
    monkeypatch.setattr(mv_refresh, "_snapshot", lambda: next(snaps))

    def refresh():
        calls.append(1)
        gate.wait(5)

    monkeypatch.setattr(mv_refresh, "_refresh", refresh)
    from app import prewarm

    warmed = []
    monkeypatch.setattr(prewarm, "after_refresh", lambda: warmed.append(1))  # 실제 DB 계산 대신
    monkeypatch.setattr(mv_refresh, "_state", {"status": "idle", "started": None, "finished": None, "by": None, "error": None,
                                               "elapsedSec": None})
    return gate, calls


def _wait(status):
    for _ in range(100):
        if mv_refresh.state()["status"] == status:
            return
        time.sleep(0.05)
    raise AssertionError(mv_refresh.state())


def test_refresh_runs_once_clears_caches_and_records(fake, audit_capture):
    gate, calls = fake
    sale_dashboard._cache["202608"] = (time.time() + 60, {})
    sale_monthly._stats_cache[("x",)] = (time.time() + 60, {})
    s = mv_refresh.start({"id": "250016", "ip": "10.0.0.1"})
    assert s["status"] == "running" and s["by"] == "250016"
    assert mv_refresh.start({"id": "170046"})["by"] == "250016"  # 진행 중에 또 눌러도 새로 시작하지 않음
    gate.set()
    _wait("done")
    assert len(calls) == 1
    assert sale_dashboard._cache == {} and sale_monthly._stats_cache == {}  # 새 데이터 바로 반영
    rec = audit_capture[-1]
    assert rec["action"] == "MV_REFRESH" and "최신 월 202608 → 202609" in rec["summary"] and "24,170 → 24,700" in rec["summary"]


def test_refresh_failure_reported(fake, audit_capture, monkeypatch):
    def boom():
        raise RuntimeError("ORA-01031: insufficient privileges")

    monkeypatch.setattr(mv_refresh, "_refresh", boom)
    mv_refresh.start({"id": "250016"})
    _wait("error")
    st = mv_refresh.state()
    assert "ORA-01031" in st["error"] and st["finished"]
    assert audit_capture[-1]["action"] == "MV_REFRESH" and "실패" in audit_capture[-1]["summary"]
