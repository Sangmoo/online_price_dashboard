"""관리자 운영 기능: 다운로드 이력 · 공지(게시 기간 · 첨부 · 본문 이미지 · 댓글/대댓글 · 게시판) · 점검 모드 차단 ·
작업 실행 기록 · DB 스케줄 조회 · 관리자 홈 · 테이블이 없을 때 안내. Oracle 은 메모리 DB 로 흉내 낸다 (fake_oracle)."""
import base64
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app import admin_home, auth, downloads, jobs, notices, tables, userdb

ADMIN = {"id": "900001", "name": "관리자", "role": "ADMIN", "ip": "10.0.0.1"}
USER = {"id": "900002", "name": "사용자", "role": "USER", "ip": "10.0.0.2"}
USER2 = {"id": "900003", "name": "사용자2", "role": "USER", "ip": "10.0.0.3"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PDF = b"%PDF-1.4\n" + b"x" * 40
XLSX = b"PK\x03\x04" + b"x" * 40


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------- 테이블이 없을 때
def test_tables_missing_message(monkeypatch):
    """앱이 쓰는 이름으로 직접 조회해 본다: SS10 에 테이블이 있어도 SS10DEV 동의어가 없으면 '쓸 수 없음'"""
    logged = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, p=None):
            if "T_B" in sql:
                raise RuntimeError("ORA-00942: table or view does not exist")

        def fetchall(self):
            return []

    class Pool:
        def acquire(self):
            class C:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def cursor(self):
                    return Cur()
            return C()

    monkeypatch.setattr(tables.db, "get_pool", lambda: Pool())
    monkeypatch.setattr(tables.db, "timed", lambda *a, **k: logged.append(a))   # 오류 로그를 남기는 경로는 쓰지 않는다
    t = tables.Tables("T_A", "T_B")
    assert t.missing() == ["T_B"] and not t.ready() and logged == []
    with pytest.raises(HTTPException) as ex:
        t.require()
    assert ex.value.status_code == 503 and ex.value.detail["code"] == "TABLE_MISSING"
    msg = ex.value.detail["message"]
    assert "db/create_erp_web_admin_ops.sql" in msg and "CREATE SYNONYM SS10DEV.T_B FOR SS10.T_B;" in msg


def test_without_tables_nothing_saved_locally(real_records, monkeypatch):
    monkeypatch.setattr(tables.Tables, "missing", lambda self: ["T_X"])        # 운영 테이블이 없는 상태
    downloads.record(USER, "table", "x")                                       # 건너뜀 (서버 로컬에도 안 남김)
    jobs.record("housekeeping", 0, 1, "ok")
    db = real_records.conn
    assert db.execute("SELECT COUNT(*) FROM T_ERP_WEB_DOWNLOAD_LOG").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM T_ERP_WEB_JOB_RUN").fetchone()[0] == 0
    r = downloads.report(30)
    assert r["table"]["ready"] is False and r["rows"] == [] and r["table"]["ddl"] == "db/create_erp_web_admin_ops.sql"
    notices._clear()
    assert notices.active() == [] and notices.board(USER)["table"]["ready"] is False
    with pytest.raises(HTTPException) as ex:
        notices.save(ADMIN, {"title": "a", "start": _day(0), "end": _day(0)})
    assert ex.value.detail["code"] == "TABLE_MISSING"
    assert all(j["status"] == "unknown" for j in jobs._app_jobs(7))


# ---------------------------------------------------------------------------- 다운로드 이력
def test_download_record_and_report(real_records):
    downloads.record(USER, "online_detail", "온라인가격수집_20261007", {"dt": "20261007", "q": None, "shops": "T15602"}, size=1234)
    downloads.record(USER, "manager_phone", "매장 S31019 매니저 연락처", {"shopId": "S31019"}, rows=1)
    downloads.record(ADMIN, "table", "판매집계", {"columns": ["매장", "실판금액"]}, rows=50)
    r = downloads.report(30, names={"900002": "사용자"})
    assert r["total"] == 3 and r["table"]["ready"] is True
    u = r["byUser"][0]
    assert (u["id"], u["name"], u["count"], u["sensitive"]) == ("900002", "사용자", 2, 1)
    first = next(x for x in r["rows"] if x["kind"] == "online_detail")
    assert first["params"] == {"dt": "20261007", "shops": "T15602"}      # 빈 조건은 빼고 저장
    assert first["ip"] == "10.0.0.2" and first["bytes"] == 1234 and first["kindLabel"] == "온라인 가격 일자별 상세"
    assert downloads.report(30, usr="900001")["total"] == 1
    assert downloads.report(30, kind="manager_phone")["rows"][0]["sensitive"] is True
    assert downloads.today_summary()["today"] == 3


def test_download_purge(real_records):
    downloads.record(USER, "table", "old")
    real_records.conn.execute("UPDATE T_ERP_WEB_DOWNLOAD_LOG SET DL_DAY = '20240101000000'")
    downloads.record(USER, "table", "new")
    assert downloads.purge() == 1
    assert [x["title"] for x in downloads.report(365)["rows"]] == ["new"]


# ---------------------------------------------------------------------------- 공지 · 게시 기간
def test_notice_period_board_and_order(fake_oracle):
    notices.save(ADMIN, {"title": "지난 공지", "start": _day(-5), "end": _day(-1)})
    notices.save(ADMIN, {"title": "예정 공지", "start": _day(1), "end": _day(3)})
    notices.save(ADMIN, {"title": "안내", "level": "info", "start": _day(-1), "end": _day(0)})
    imp = notices.save(ADMIN, {"title": "중요 점검", "body": "10/10 13시", "level": "important", "start": _day(0), "end": _day(0)})
    notices.save(ADMIN, {"title": "꺼 둔 공지", "start": _day(0), "end": _day(5), "use": False})
    notices._clear()
    assert [n["title"] for n in notices.active()] == ["중요 점검", "안내"]       # 오늘 게시 중만, 중요 먼저 (종료일 당일 포함)
    assert [n["title"] for n in notices.board(USER)["notices"]] == ["중요 점검", "안내", "지난 공지"]   # 사용자: 예정·사용 안 함 제외
    assert len(notices.board(ADMIN)["notices"]) == 5
    assert [n["title"] for n in notices.board(USER, "점검")["notices"]] == ["중요 점검"]
    statuses = {n["title"]: n["status"] for n in notices.list_all()["notices"]}
    assert statuses == {"지난 공지": "ended", "예정 공지": "scheduled", "안내": "active", "중요 점검": "active", "꺼 둔 공지": "off"}
    with pytest.raises(HTTPException):          # 사용자는 예정 공지 상세를 못 본다
        notices.detail(USER, next(n["id"] for n in notices.board(ADMIN)["notices"] if n["title"] == "예정 공지"))
    nid = imp["notice"]["id"]
    notices.save(ADMIN, {"title": "중요 점검(변경)", "level": "important", "start": _day(0), "end": _day(1)}, nid)
    assert notices.active()[0]["title"] == "중요 점검(변경)"                   # 저장하면 캐시를 비운다
    notices.delete(ADMIN, nid)
    assert [n["title"] for n in notices.active()] == ["안내"]


@pytest.mark.parametrize("body,msg", [
    ({"title": "", "start": "2026-10-01", "end": "2026-10-02"}, "제목"),
    ({"title": "a", "start": "2026-10-05", "end": "2026-10-01"}, "종료일"),
    ({"title": "a", "start": "2026-10-01"}, "시작일과 종료일"),
    ({"title": "a", "start": "2026-01-01", "end": "2027-06-01"}, "366일"),
    ({"title": "a", "level": "urgent", "start": "2026-10-01", "end": "2026-10-01"}, "구분"),
    ({"title": "a" * 101, "start": "2026-10-01", "end": "2026-10-01"}, "100자"),
])
def test_notice_validation(fake_oracle, body, msg):
    with pytest.raises(HTTPException) as ex:
        notices.save(ADMIN, body)
    assert msg in ex.value.detail["message"]


# ---------------------------------------------------------------------------- 첨부 · 본문 이미지
def test_notice_files_and_images(fake_oracle):
    n = notices.save(ADMIN, {"title": "첨부", "start": _day(0), "end": _day(0), "newFiles": [
        {"kind": "file", "name": "안내문.pdf", "data": b64(PDF)},
        {"kind": "file", "name": "목록.xlsx", "data": "data:application/octet-stream;base64," + b64(XLSX)},
        {"kind": "image", "name": "", "data": "data:image/png;base64," + b64(PNG)},          # 클립보드 붙여넣기 (이름 없음)
    ]})["notice"]
    assert [f["name"] for f in n["files"]] == ["안내문.pdf", "목록.xlsx"] and n["images"][0]["name"] == "image3.png"
    data, mime, name, kind = notices.get_file(USER, n["id"], n["images"][0]["no"])
    assert data == PNG and mime == "image/png" and kind == "image"
    assert notices.get_file(USER, n["id"], 1)[1] == "application/pdf"
    # 수정: 첫 첨부만 남기고 새 첨부 2개 → 3개 (최대)
    n2 = notices.save(ADMIN, {"title": "첨부", "start": _day(0), "end": _day(0), "keepFiles": [1, 3], "newFiles": [
        {"kind": "file", "name": "a.hwp", "data": b64(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 10)},
        {"kind": "file", "name": "b.txt", "data": b64("메모".encode())}]}, n["id"])["notice"]
    assert [f["name"] for f in n2["files"]] == ["안내문.pdf", "a.hwp", "b.txt"] and len(n2["images"]) == 1
    with pytest.raises(HTTPException) as ex:     # 4번째 첨부
        notices.save(ADMIN, {"title": "첨부", "start": _day(0), "end": _day(0), "newFiles": [{"kind": "file", "name": "c.pdf", "data": b64(PDF)}]},
                     n["id"])
    assert "최대 3개" in ex.value.detail["message"]
    assert len(notices.detail(ADMIN, n["id"])["notice"]["files"]) == 3      # 실패하면 그대로


@pytest.mark.parametrize("f,msg", [
    ({"kind": "file", "name": "run.exe", "data": b64(b"MZ" + b"x" * 10)}, "첨부할 수 없는 형식"),
    ({"kind": "file", "name": "가짜.pdf", "data": b64(b"MZ" + b"x" * 10)}, "확장자와 맞지 않습니다"),
    ({"kind": "file", "name": "가짜.png", "data": b64(PDF)}, "확장자와 맞지 않습니다"),
    ({"kind": "image", "name": "x.png", "data": b64(PDF)}, "PNG · JPG"),
    ({"kind": "image", "name": "x.png", "data": "!!!"}, "읽을 수 없습니다"),
])
def test_notice_file_rejected(fake_oracle, f, msg):
    with pytest.raises(HTTPException) as ex:
        notices.save(ADMIN, {"title": "a", "start": _day(0), "end": _day(0), "newFiles": [f]})
    assert msg in ex.value.detail["message"]


def test_notice_file_size_limit(fake_oracle, monkeypatch):
    monkeypatch.setattr(notices, "MAX_ATTACH_BYTES", 50)
    with pytest.raises(HTTPException) as ex:
        notices.save(ADMIN, {"title": "a", "start": _day(0), "end": _day(0), "newFiles": [{"kind": "file", "name": "a.pdf", "data": b64(PDF + b"x" * 60)}]})
    assert "MB 까지" in ex.value.detail["message"]


# ---------------------------------------------------------------------------- 댓글 · 대댓글
def test_comments_and_replies(fake_oracle):
    nid = notices.save(ADMIN, {"title": "댓글", "start": _day(0), "end": _day(0)})["notice"]["id"]
    c1 = notices.add_comment(USER, nid, {"body": "첫 댓글"})["comments"][0]
    tree = notices.add_comment(USER2, nid, {"body": "답글", "parentId": c1["id"]})["comments"]
    reply = tree[0]["replies"][0]
    tree = notices.add_comment(USER, nid, {"body": "답글의 답글", "parentId": reply["id"]})["comments"]
    assert [r["body"] for r in tree[0]["replies"]] == ["답글", "답글의 답글"]          # 1단계: 같은 댓글 아래로
    assert tree[0]["canEdit"] is True and tree[0]["replies"][0]["canEdit"] is False    # USER 기준
    assert notices.active()[0]["commentCount"] == 3
    with pytest.raises(HTTPException):
        notices.edit_comment(USER2, nid, c1["id"], {"body": "남의 댓글 수정"})
    notices.edit_comment(USER, nid, c1["id"], {"body": "고친 댓글"})
    with pytest.raises(HTTPException):
        notices.delete_comment(USER2, nid, c1["id"])
    tree = notices.delete_comment(USER, nid, c1["id"])["comments"]                      # 답글이 있으면 '삭제된 댓글' 로 남김
    assert tree[0]["deleted"] is True and tree[0]["body"] == "" and len(tree[0]["replies"]) == 2
    view = notices.detail(USER2, nid)["notice"]["comments"]
    assert view[0]["replies"][0]["canDelete"] is True and view[0]["replies"][1]["canDelete"] is False
    notices.delete_comment(ADMIN, nid, view[0]["replies"][1]["id"])                     # 관리자는 남의 댓글 삭제 가능
    tree = notices.delete_comment(USER2, nid, view[0]["replies"][0]["id"])["comments"]
    assert tree == []                                                                     # 마지막 답글이 지워지면 삭제된 부모도 정리
    with pytest.raises(HTTPException):
        notices.add_comment(USER, nid, {"body": "   "})
    with pytest.raises(HTTPException):
        notices.add_comment(USER, nid, {"body": "x", "parentId": "없는댓글"})
    notices.add_comment(USER, nid, {"body": "남김"})
    notices.delete(ADMIN, nid)                                                            # 공지를 지우면 첨부·댓글도
    assert fake_oracle.conn.execute("SELECT COUNT(*) FROM T_ERP_WEB_NOTICE_COMMENT").fetchone()[0] == 0


# ---------------------------------------------------------------------------- 점검 모드
@pytest.fixture
def settings(monkeypatch):
    st = dict(userdb.DEFAULT_SETTINGS)
    monkeypatch.setattr(userdb, "get_settings", lambda: dict(st))
    monkeypatch.setattr(userdb, "save_settings", lambda values, by: st.update(values) or dict(st))
    return st


def test_maintenance_blocks_users_not_admins(fake_oracle, settings):
    assert notices.blocked_message() is None
    auth._check_maintenance(USER)                                            # 꺼져 있으면 통과
    notices.set_maintenance(ADMIN, {"on": True, "message": "DB 작업 중입니다.", "until": "2026-10-10 15:00"})
    with pytest.raises(HTTPException) as ex:
        auth._check_maintenance(USER)
    assert ex.value.status_code == 503 and ex.value.detail["code"] == "MAINTENANCE"
    assert ex.value.detail["message"] == "DB 작업 중입니다. (종료 예정 2026-10-10 15:00)"
    auth._check_maintenance(ADMIN)                                           # 관리자는 들어온다
    notices.set_maintenance(ADMIN, {"on": False})
    auth._check_maintenance(USER)
    with pytest.raises(HTTPException):
        notices.set_maintenance(ADMIN, {"on": True, "until": "내일"})


def test_maintenance_default_message(settings):
    settings["maintenance_on"] = True
    assert notices.blocked_message() == notices.DEFAULT_MAINT_MSG


# ---------------------------------------------------------------------------- 작업 실행 기록 · 스케줄
def test_jobs_track_records_ok_and_error(real_records, monkeypatch):
    with jobs.track("housekeeping") as run:
        run.detail = "정리 3건"
    with pytest.raises(RuntimeError):
        with jobs.track("housekeeping"):
            raise RuntimeError("디스크 오류")
    jobs.record("prewarm", datetime.now().timestamp() - 5, datetime.now().timestamp(), "ok", "서버 시작", None)
    monkeypatch.setattr(jobs, "_cursor_rows", lambda f, a: (_ for _ in ()).throw(RuntimeError("ORA-06550: PLS-00201")))
    jobs.clear_cache()
    o = jobs.overview(7)
    hk = next(j for j in o["app"] if j["key"] == "housekeeping")
    assert hk["status"] == "error" and hk["failures"] == 1 and hk["count"] == 2
    assert hk["last"]["detail"] == "디스크 오류" and hk["lastOk"]["detail"] == "정리 3건"
    assert next(j for j in o["app"] if j["key"] == "prewarm")["last"]["sec"] == 5
    assert next(j for j in o["app"] if j["key"] == "mv_refresh")["status"] == "never"
    assert o["db"]["ready"] is False and "create_erp_web_admin_ops.sql" in o["db"]["error"]
    assert all(j["status"] == "unknown" for j in o["db"]["jobs"])
    assert "정리 작업" in o["summary"]["problemNames"] and o["summary"]["appReady"] is True


def test_db_jobs_status(real_records, monkeypatch):
    jobs.clear_cache()
    future = (datetime.now() + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
    past = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    def fake(func, args):
        if func == jobs.SCHED_FUNC_JOBS:
            return [{"JOB_NAME": "JOB_FILL_ONLINE_SHOP_ID", "ENABLED": "TRUE", "STATE": "SCHEDULED", "RUN_COUNT": 3, "FAILURE_COUNT": 1,
                     "REPEAT_INTERVAL": "FREQ=DAILY", "LAST_START": past, "NEXT_RUN": future},
                    {"JOB_NAME": "JOB_LOAD_CLOSE_SALE_BASE", "ENABLED": "TRUE", "STATE": "SCHEDULED", "RUN_COUNT": 0, "FAILURE_COUNT": 0,
                     "REPEAT_INTERVAL": "FREQ=MONTHLY", "LAST_START": None, "NEXT_RUN": past}]
        return [{"JOB_NAME": "JOB_FILL_ONLINE_SHOP_ID", "STATUS": "FAILED", "ERROR_NO": 1, "ACTUAL_START": past, "LOG_DATE": past,
                 "DURATION_SEC": 12, "ADDITIONAL_INFO": "ORA-00001"},
                {"JOB_NAME": "JOB_FILL_ONLINE_SHOP_ID", "STATUS": "SUCCEEDED", "ERROR_NO": 0, "ACTUAL_START": past, "LOG_DATE": past,
                 "DURATION_SEC": 30, "ADDITIONAL_INFO": None}]
    monkeypatch.setattr(jobs, "_cursor_rows", fake)
    monkeypatch.setattr(jobs, "_check_result", lambda name: {"label": "확인", "warn": False})
    d = {j["key"]: j for j in jobs.overview(14)["db"]["jobs"]}
    fill, load = d["JOB_FILL_ONLINE_SHOP_ID"], d["JOB_LOAD_CLOSE_SALE_BASE"]
    assert fill["status"] == "error" and fill["last"]["detail"] == "ORA-00001" and fill["failures"] == 1 and fill["runs"][1]["sec"] == 30
    assert load["status"] == "overdue"                                         # 다음 실행 시각이 1시간 넘게 지남


# ---------------------------------------------------------------------------- 관리자 홈
def test_admin_home_isolates_card_errors(monkeypatch):
    monkeypatch.setattr(admin_home, "_cache", None)
    cards = {k: (lambda k=k: {"ok": k}) for k in admin_home.CARDS}
    cards["server"] = lambda: (_ for _ in ()).throw(RuntimeError("로그 파일 없음"))
    monkeypatch.setattr(admin_home, "CARDS", cards)
    out = admin_home.overview(fresh=True)
    assert out["server"] == {"error": "로그 파일 없음"} and out["feedback"] == {"ok": "feedback"} and out["generatedAt"]
