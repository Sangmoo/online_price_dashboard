"""FastAPI 엔트리포인트."""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import logs, sql_trace

logs.setup()  # 다른 모듈보다 먼저: import 중 발생하는 로그도 파일에 남도록

from . import admin, appdb, auth, downloads, brand_scope, chat_service, menu_usage, config, data_service as ds, invt_plan, mv_refresh, sale_dashboard, sale_monthly, server_status, store, usage, userdb  # noqa: E402
from .auth import current_user, require_admin, require_page  # noqa: E402

_log = logs.get("request")
logs.get("app").info("서버 시작 (port=%s)", config.API_PORT)

store.init()
logs.get("app").info("운영 데이터 저장소: %s", appdb.backend_name())  # Oracle 이면 첫 사용 시 SQLite 내용 1회 이전
sale_monthly.cleanup_exports()  # 재시작 전 남은 엑셀 임시 파일 정리
_moved = userdb.migrate_from_sqlite(store)  # 1회: 이전 SQLite 사용자/설정 → Oracle
if _moved:
    logs.get("app").info("사용자 권한을 Oracle 로 이전했습니다: %s", ", ".join(_moved))
try:  # 새 메뉴 '판매 현황' 을 판매 집계 메뉴가 있는 기존 사용자에게 1회 부여 (테스트 실행 시에는 하지 않음)
    _granted = ([] if os.getenv("ERP_NO_AUTO_MIGRATE") == "1" else
                userdb.grant_page_once("_MIGR_PAGE_SALE_DASHBOARD", "sale_dashboard", "sale_monthly"))
    if _granted:
        logs.get("app").info("판매 현황 메뉴를 부여했습니다: %s", ", ".join(_granted))
except Exception:  # noqa: BLE001
    logs.get("app").exception("판매 현황 메뉴 1회 부여 실패")



def _housekeeping() -> None:
    """6시간마다: 보관 기간이 지난 로그 파일·엑셀 임시 파일·완료된 문의의 첨부 이미지 정리 (보관 기간은 관리자 설정)"""
    time.sleep(30)
    from . import downloads, feedback, jobs

    while True:
        try:
            with jobs.track("housekeeping") as run:
                logs.cleanup(userdb.get_settings().get("log_keep_days") or logs.DEFAULT_KEEP_DAYS)
                sale_monthly.cleanup_exports()
                img = feedback.purge_images(userdb.get_settings().get("feedback_img_keep_months"))
                dl = downloads.purge()
                jobs.purge()
                run.detail = f"문의 이미지 {img.get('deleted', 0) if isinstance(img, dict) else 0}건 · 다운로드 이력 {dl}건 정리"
        except Exception:  # noqa: BLE001
            logs.get("app").exception("정리 작업 실패")
        time.sleep(6 * 3600)


if os.getenv("ERP_NO_AUTO_MIGRATE") != "1":
    threading.Thread(target=_housekeeping, daemon=True, name="housekeeping").start()
    from . import prewarm  # noqa: E402

    threading.Thread(target=prewarm.loop, daemon=True, name="prewarm").start()

app = FastAPI(title="ERP 영업 관리 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Session-Expires"],
)


@app.middleware("http")
async def session_header(request: Request, call_next):
    """인증된 요청이면 연장된 세션 만료시각을 헤더로 알려준다 (프론트 세션 타이머 동기화). API 요청은 1줄씩 로그."""
    start = time.perf_counter()
    trace = sql_trace.begin()   # 관리자 '사용 쿼리': 이 요청에서 실행된 SQL 을 사용자 · 요청 단위로 묶는다
    try:
        response = await call_next(request)
    except Exception:
        sql_trace.end(trace)
        _log.exception("처리 실패 user=%s %s %s", getattr(request.state, "usr_id", "-"), request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": {"message": "서버 오류가 발생했습니다. 잠시 후 다시 시도하세요.",
                                                                  "code": "SERVER_ERROR"}})
    sql_trace.end(trace)
    exp = getattr(request.state, "session_expires", None)
    if exp:
        response.headers["X-Session-Expires"] = str(exp)
    path = request.url.path
    if path.startswith("/api/") and path not in ("/api/health", "/api/auth/touch"):
        sec = time.perf_counter() - start
        level = 40 if response.status_code >= 500 else 30 if sec >= logs.SLOW_REQUEST_SEC else 20
        qs = f"?{request.url.query}" if request.url.query else ""
        _log.log(level, "user=%s %s %s%s %s %.0fms", getattr(request.state, "usr_id", "-"), request.method, path,
                 qs[:300], response.status_code, sec * 1000)
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail), "code": "ERROR"}
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _bad_request(ex: ValueError):
    raise HTTPException(status_code=400, detail={"message": str(ex), "code": "BAD_REQUEST"})


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type=XLSX,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "started": server_status.STARTED_AT}  # deploy.bat 이 새로 뜬 서버인지 확인


# ----------------------------------------------------------------------------
# 인증
# ----------------------------------------------------------------------------
class LoginBody(BaseModel):
    id: str
    password: str


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    token, me = auth.login(body.id, body.password, _client_ip(request), request.headers.get("user-agent"))
    response.set_cookie(
        auth.SESSION_COOKIE, token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/",
    )
    return {"user": me, "sessionTtl": auth.SESSION_TTL}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"user": user, "usage": usage.usage_summary(user), "sessionTtl": auth.SESSION_TTL}


@app.post("/api/auth/touch")
def touch(user: dict = Depends(current_user)):
    """화면 조작(클릭/입력)만 있고 API 호출이 없을 때 세션을 연장하기 위한 호출."""
    return {"sessionExpiresAt": user["sessionExpiresAt"]}


# ----------------------------------------------------------------------------
# 개인 환경설정
# ----------------------------------------------------------------------------
PREF_KEYS = {"detail.columns", "ui.accent", "ui.theme", "invt.view"}
ACCENTS = ("indigo", "teal", "graphite", "ocean", "forest", "wine")   # 마이페이지 강조 색상 (frontend/src/palette.ts 와 같게)


@app.get("/api/prefs/{key}")
def get_pref(key: str, user: dict = Depends(current_user)):
    if key not in PREF_KEYS:
        raise HTTPException(404, {"message": "알 수 없는 설정", "code": "NOT_FOUND"})
    return {"value": appdb.pref_get(user["id"], key)}


@app.put("/api/prefs/{key}")
def put_pref(key: str, body: dict, user: dict = Depends(current_user)):
    if key not in PREF_KEYS:
        raise HTTPException(404, {"message": "알 수 없는 설정", "code": "NOT_FOUND"})
    if key == "ui.accent" and body.get("value") not in ACCENTS:
        raise HTTPException(400, {"message": f"색상은 {', '.join(ACCENTS)} 중 하나입니다.", "code": "BAD_REQUEST"})
    if key == "invt.view" and body.get("value") not in ("list", "calendar"):
        raise HTTPException(400, {"message": "보기 방식은 list, calendar 중 하나입니다.", "code": "BAD_REQUEST"})
    if key == "ui.theme" and body.get("value") not in ("light", "dark"):
        raise HTTPException(400, {"message": "화면 모드는 light, dark 중 하나입니다.", "code": "BAD_REQUEST"})
    try:
        appdb.pref_set(user["id"], key, body.get("value"))
    except ValueError as ex:
        _bad_request(ex)
    return {"ok": True}


# ----------------------------------------------------------------------------
# 데이터 (페이지 권한 필요)
# ----------------------------------------------------------------------------
@app.get("/api/dates")
def dates(_: dict = Depends(current_user)):
    return {"dates": ds.available_dates()}


@app.get("/api/dashboard")
def dashboard(start: str, end: str, _: dict = Depends(require_page("dashboard"))):
    try:
        return ds.dashboard(start, end)
    except ValueError as ex:
        _bad_request(ex)


@app.get("/api/rows")
def rows(
    dt: str,
    page: int = 1,
    size: int = 100,
    sort: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    q: str | None = None,
    mall: str | None = None,
    minRate: float | None = None,
    maxRate: float | None = None,
    shops: str | None = None,
    _: dict = Depends(require_page("detail")),
):
    try:
        return ds.day_rows(dt, page, size, sort, order, q, mall, minRate, maxRate, shops)
    except ValueError as ex:
        _bad_request(ex)


@app.get("/api/rows/export")
def rows_export(
    dt: str,
    sort: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    q: str | None = None,
    mall: str | None = None,
    minRate: float | None = None,
    maxRate: float | None = None,
    cols: str | None = None,
    shops: str | None = None,
    me: dict = Depends(require_page("detail")),
):
    try:
        content = ds.export_day(dt, sort, order, q, mall, minRate, maxRate, cols.split(",") if cols else None, shops)
    except ValueError as ex:
        _bad_request(ex)
    downloads.record(me, "online_detail", f"온라인가격수집_{dt}", {"dt": dt, "q": q, "mall": mall, "minRate": minRate,
                                                                   "maxRate": maxRate, "shops": shops, "sort": sort}, size=len(content))
    return _xlsx_response(content, f"온라인가격수집_{dt}.xlsx")


class TableExport(BaseModel):
    title: str = "조회결과"
    columns: list[dict]
    rows: list[dict]


@app.post("/api/export/table")
def export_table(body: TableExport, me: dict = Depends(current_user)):
    cols = [(c["key"], c.get("label", c["key"])) for c in body.columns if "key" in c]
    content = ds.write_xlsx("조회결과", cols, body.rows)
    safe = "".join(ch for ch in body.title if ch not in '\\/:*?"<>|').strip() or "조회결과"
    downloads.record(me, "table", safe, {"columns": [c[1] for c in cols][:20]}, rows=len(body.rows), size=len(content))
    return _xlsx_response(content, f"{safe}.xlsx")


class FullExport(BaseModel):
    tool: str
    input: dict
    title: str = "AI 조회결과"


@app.post("/api/chat/export-full")
def chat_export_full(body: FullExport, user: dict = Depends(current_user)):
    """AI 답변 표가 잘렸을 때 같은 조건의 전체 결과(최대 10만 행) 엑셀"""
    try:
        t = chat_service.export_full(body.tool, body.input, user)
    except chat_service.ToolInputError as ex:
        raise HTTPException(status_code=400, detail={"message": str(ex), "code": "BAD_REQUEST"})
    cols = [(c["key"], c.get("label", c["key"])) for c in t["columns"] if "key" in c and c["key"] != "URL"]
    content = ds.write_xlsx("조회결과", cols, t["rows"])
    safe = "".join(ch for ch in body.title if ch not in '\\/:*?"<>|').strip()[:80] or "AI 조회결과"
    suffix = f"_상위{t['max']:,}행" if t["capped"] else ""
    downloads.record(user, "ai_full", safe, {"tool": body.tool, "input": body.input}, rows=len(t["rows"]), size=len(content))
    return _xlsx_response(content, f"{safe}{suffix}.xlsx")


# ----------------------------------------------------------------------------
# AI 대화 (사용자별 기록 / 한도)
# ----------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    conversationId: str | None = None
    context: dict | None = None


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request, user: dict = Depends(current_user)):
    msg = req.message.strip()
    if not msg:
        raise HTTPException(400, {"message": "메시지가 비어 있습니다.", "code": "BAD_REQUEST"})
    if len(msg) > 2000:
        raise HTTPException(400, {"message": "질문은 2,000자 이내로 입력하세요.", "code": "BAD_REQUEST"})
    menu_usage.record(user["id"], menu_usage.AI_PAGE)
    return StreamingResponse(
        chat_service.stream_chat(user, req.conversationId, msg, req.context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "X-Session-Expires": str(request.state.session_expires)},
    )


@app.get("/api/chat/usage")
def chat_usage(user: dict = Depends(current_user)):
    return usage.usage_summary(user)


@app.get("/api/chat/conversations")
def conversations(user: dict = Depends(current_user)):
    return {"conversations": chat_service.list_conversations(user["id"])}


@app.get("/api/chat/conversations/{conv_id}")
def conversation(conv_id: str, user: dict = Depends(current_user)):
    c = chat_service.get_conversation(user["id"], conv_id)
    if not c:
        raise HTTPException(404, {"message": "대화를 찾을 수 없습니다.", "code": "NOT_FOUND"})
    return c


class RenameBody(BaseModel):
    title: str


@app.patch("/api/chat/conversations/{conv_id}")
def rename_conversation(conv_id: str, body: RenameBody, user: dict = Depends(current_user)):
    chat_service.rename_conversation(user["id"], conv_id, body.title)
    return {"ok": True}


@app.delete("/api/chat/conversations/{conv_id}")
def delete_conversation(conv_id: str, user: dict = Depends(current_user)):
    chat_service.delete_conversation(user["id"], conv_id)
    return {"ok": True}


class FavoriteBody(BaseModel):
    text: str


@app.get("/api/chat/favorites")
def favorites(user: dict = Depends(current_user)):
    return {"favorites": appdb.fav_list(user["id"])}


@app.post("/api/chat/favorites")
def add_favorite(body: FavoriteBody, user: dict = Depends(current_user)):
    text = " ".join(body.text.split())[:500]
    if not text:
        raise HTTPException(400, {"message": "내용이 비어 있습니다.", "code": "BAD_REQUEST"})
    appdb.fav_add(user["id"], text)
    return favorites(user)


@app.delete("/api/chat/favorites/{fav_id}")
def delete_favorite(fav_id: int, user: dict = Depends(current_user)):
    appdb.fav_delete(user["id"], fav_id)
    return favorites(user)


# ----------------------------------------------------------------------------
# 관리자
# ----------------------------------------------------------------------------
@app.get("/api/admin/users")
def admin_users(q: str | None = None, _: dict = Depends(require_admin)):
    return {"users": admin.list_users(q), "pages": admin.page_meta(),
            "superAdminId": config.SUPER_ADMIN_ID, "brandOptions": admin.brand_options(), "brandReady": userdb.brand_table_ready()}


@app.get("/api/admin/directory")
def admin_directory(q: str, _: dict = Depends(require_admin)):
    return {"users": admin.directory_search(q)}


@app.post("/api/admin/users")
def admin_create_user(body: dict, me: dict = Depends(require_admin)):
    return {"user": admin.create_user(me, body)}


@app.put("/api/admin/users/{usr_id}")
def admin_save_user(usr_id: str, body: dict, me: dict = Depends(require_admin)):
    return {"user": admin.save_user(me, usr_id, body)}


@app.put("/api/admin/permissions")
def admin_save_permissions(body: dict, me: dict = Depends(require_admin)):
    return {"users": admin.save_permissions(me, body.get("changes"))}


@app.get("/api/admin/audit")
def admin_audit(action: str | None = None, q: str | None = None, days: int = 90, _: dict = Depends(require_admin)):
    return admin.audit_log(action, q, days)


@app.get("/api/admin/data-status")
def admin_data_status(_: dict = Depends(require_admin)):
    return admin.data_status()


class MenuOpen(BaseModel):
    page: str


@app.post("/api/usage/menu")
def usage_menu_open(body: MenuOpen, user: dict = Depends(current_user)):
    """메뉴를 열 때 화면이 알린다 (관리자 > 메뉴 이용 통계). 권한 있는 메뉴만 기록."""
    if body.page in user["pages"]:
        menu_usage.record(user["id"], body.page)
    return {"ok": True}


@app.post("/api/feedback")
def feedback_create(body: dict, me: dict = Depends(current_user)):
    """화면 내 문의·오류 신고 (현재 화면·조회 조건·최근 오류가 context 로 함께 온다)"""
    from . import feedback

    return feedback.create(me, body)


@app.get("/api/feedback/mine")
def feedback_mine(me: dict = Depends(current_user)):
    from . import feedback

    rows = feedback.mine(me["id"])
    feedback.mark_seen(me["id"])  # 창을 열어 답변을 봤으므로 '새 답변' 표시를 지운다
    return {"rows": rows, "limits": feedback.limits()}


@app.get("/api/feedback/badge")
def feedback_badge(me: dict = Depends(current_user)):
    """화면 배지 (주기 확인: 화면은 X-Background 로 보내 세션을 연장하지 않는다)"""
    from . import feedback

    return feedback.badge(me)


@app.get("/api/feedback/{fb_id}/files/{no}")
def feedback_file(fb_id: str, no: int, me: dict = Depends(current_user)):
    """첨부 이미지 (작성자 본인 또는 관리자)"""
    from . import feedback

    data, mime, name = feedback.get_file(fb_id, no, me)
    return Response(content=data, media_type=mime, headers={
        "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})


@app.get("/api/admin/feedback")
def admin_feedback(status: str | None = None, _: dict = Depends(require_admin)):
    from . import feedback

    return feedback.list_all(status)


@app.put("/api/admin/feedback/{fb_id}")
def admin_feedback_answer(fb_id: str, body: dict, me: dict = Depends(require_admin)):
    from . import feedback

    return feedback.answer(me, fb_id, body)


@app.get("/api/admin/menu-usage")
def admin_menu_usage(days: int = 30, _: dict = Depends(require_admin)):
    return menu_usage.report(days, admin.list_users())


@app.get("/api/admin/ai-tool-stats")
def admin_ai_tool_stats(days: int = 7, _: dict = Depends(require_admin)):
    """AI 도구별 호출·실패·응답 시간, 모델 선택 (서버 로그 기준)"""
    from . import ai_tool_stats

    return {**ai_tool_stats.report(days), "keepDays": userdb.get_settings().get("log_keep_days") or logs.DEFAULT_KEEP_DAYS}


@app.get("/api/admin/server-status")
def admin_server_status(days: int = 7, _: dict = Depends(require_admin)):
    return server_status.status(days, userdb.get_settings().get("log_keep_days"))


@app.post("/api/admin/logs/cleanup")
def admin_logs_cleanup(_: dict = Depends(require_admin)):
    return logs.cleanup(userdb.get_settings().get("log_keep_days") or logs.DEFAULT_KEEP_DAYS)


@app.get("/api/admin/backup")
def admin_backup(me: dict = Depends(require_admin)):
    """설정 백업 파일 (JSON)"""
    import json as _json

    from . import backup

    body = _json.dumps(backup.export(me), ensure_ascii=False, indent=1).encode("utf-8")
    name = f"ERP영업관리_설정백업_{time.strftime('%Y%m%d_%H%M')}.json"
    downloads.record(me, "settings_backup", name, size=len(body))
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.post("/api/admin/restore/preview")
def admin_restore_preview(body: dict, _: dict = Depends(require_admin)):
    from . import backup

    return backup.preview(body.get("data"))


@app.post("/api/admin/restore/apply")
def admin_restore_apply(body: dict, me: dict = Depends(require_admin)):
    from . import backup

    return backup.apply(me, body.get("data"), body.get("sections") or [])


@app.get("/api/admin/data-freshness")
def admin_data_freshness(_: dict = Depends(require_admin)):
    """관리자 상단 배너 (주기 확인): 새 월 마감 · 점검 모드 켜짐"""
    from . import notices

    return {**mv_refresh.freshness(), "maintenance": notices.maintenance()}


@app.get("/api/admin/data-status/refresh")
def admin_mv_refresh_state(_: dict = Depends(require_admin)):
    from . import mv_refresh

    return {"refresh": mv_refresh.state()}


@app.post("/api/admin/data-status/refresh")
def admin_mv_refresh(me: dict = Depends(require_admin)):
    return admin.refresh_mv(me)


@app.get("/api/admin/ai-tools")
def admin_ai_tools(_: dict = Depends(require_admin)):
    return admin.ai_tools_overview()


@app.put("/api/admin/ai-tools/builtin/{name}")
def admin_ai_tool_builtin(name: str, body: dict, me: dict = Depends(require_admin)):
    return admin.save_builtin_tool(me, name, body)


@app.post("/api/admin/ai-tools/test")
def admin_ai_tool_test(body: dict, _: dict = Depends(require_admin)):
    return admin.test_custom_tool(body)


@app.post("/api/admin/ai-tools")
def admin_ai_tool_create(body: dict, me: dict = Depends(require_admin)):
    return admin.save_custom_tool(me, body)


@app.put("/api/admin/ai-tools/{name}")
def admin_ai_tool_update(name: str, body: dict, me: dict = Depends(require_admin)):
    return admin.save_custom_tool(me, body, name)


@app.delete("/api/admin/ai-tools/{name}")
def admin_ai_tool_delete(name: str, me: dict = Depends(require_admin)):
    return admin.delete_custom_tool(me, name)


@app.get("/api/admin/settings")
def admin_get_settings(_: dict = Depends(require_admin)):
    return admin.get_settings()


@app.put("/api/admin/settings")
def admin_put_settings(body: dict, me: dict = Depends(require_admin)):
    return admin.save_settings(body, me)


@app.get("/api/admin/usage")
def admin_usage(days: int = 30, _: dict = Depends(require_admin)):
    return admin.usage_report(days)


@app.get("/api/admin/logins")
def admin_logins(limit: int = 200, q: str | None = None, _: dict = Depends(require_admin)):
    return {"logins": admin.login_log(limit, q), "locks": admin.locks()}


@app.delete("/api/admin/locks/{usr_id}")
def admin_unlock(usr_id: str, me: dict = Depends(require_admin)):
    admin.unlock(me, usr_id)
    return {"ok": True}


@app.get("/api/admin/sessions")
def admin_sessions(_: dict = Depends(require_admin)):
    return {"sessions": admin.sessions()}


@app.get("/api/admin/logs")
def admin_logs(level: str = "INFO", q: str | None = None, category: str | None = None, limit: int = 300,
               _: dict = Depends(require_admin)):
    return {"logs": logs.tail(level, q, category, limit), "slowSqlSec": logs.SLOW_SQL_SEC}


@app.delete("/api/admin/sessions/{sid}")
def admin_kill_session(sid: str, me: dict = Depends(require_admin)):
    admin.kill_session(me, sid)
    return {"ok": True}


# ----------------------------------------------------------------------------
# 관리자 홈 · 스케줄/배치 · 다운로드 이력 · 공지/점검 모드
# ----------------------------------------------------------------------------
@app.get("/api/admin/home")
def admin_home(fresh: bool = False, _: dict = Depends(require_admin)):
    from . import admin_home as home

    return home.overview(fresh)


@app.get("/api/admin/jobs")
def admin_jobs(days: int = 14, fresh: bool = False, _: dict = Depends(require_admin)):
    from . import jobs

    if fresh:
        jobs.clear_cache()
    return jobs.overview(days)


@app.put("/api/admin/downloads/alert-settings")
def admin_download_alert_settings(body: dict, me: dict = Depends(require_admin)):
    """대량 다운로드 알림 기준 {count, phone, rows}"""
    return downloads.save_alert_settings(me, body)


# ---- 권한 묶음 · 계정 정리 · 사용자 화면 미리보기 ----
@app.get("/api/admin/roles")
def admin_roles(_: dict = Depends(require_admin)):
    from . import roles

    return roles.list_roles()


@app.post("/api/admin/roles")
def admin_role_create(body: dict, me: dict = Depends(require_admin)):
    from . import roles

    return roles.save(me, body)


@app.put("/api/admin/roles/{role_id}")
def admin_role_update(role_id: str, body: dict, me: dict = Depends(require_admin)):
    from . import roles

    return roles.save(me, body, role_id)


@app.delete("/api/admin/roles/{role_id}")
def admin_role_delete(role_id: str, me: dict = Depends(require_admin)):
    from . import roles

    return roles.delete(me, role_id)


@app.post("/api/admin/roles/{role_id}/apply")
def admin_role_apply(role_id: str, body: dict, me: dict = Depends(require_admin)):
    from . import roles

    return roles.apply(me, role_id, body.get("userIds") or [])


@app.get("/api/admin/cleanup")
def admin_cleanup(days: int = 90, me: dict = Depends(require_admin)):
    from . import cleanup

    return cleanup.report(me, days)


@app.post("/api/admin/cleanup/apply")
def admin_cleanup_apply(body: dict, me: dict = Depends(require_admin)):
    from . import cleanup

    return cleanup.apply(me, body)


@app.get("/api/admin/view-as/{usr_id}")
def admin_view_as(usr_id: str, resume: bool = False, me: dict = Depends(require_admin)):
    """사용자 화면 미리보기 시작: 대상 사용자 권한(읽기 전용)으로 화면을 그릴 정보. 이후 요청은 X-View-As 헤더로"""
    from . import audit

    target = auth.view_as_user(me, usr_id)
    target["viewAs"] = {"by": me["id"], "byName": me["name"]}
    target["sessionExpiresAt"] = me["sessionExpiresAt"]
    if not resume:   # 미리보기를 연 뒤 새로고침으로 다시 불러올 때는 이력을 또 남기지 않는다
        audit.record(me, "VIEW_AS", f"{target['name']}({usr_id})", summary=f"{target['name']}({usr_id}) 화면 미리보기 (읽기 전용)")
    return {"user": target, "usage": usage.usage_summary(target), "sessionTtl": auth.SESSION_TTL}


@app.get("/api/admin/queries")
def admin_queries(page: str, me: dict = Depends(require_admin)):
    """사용 쿼리: 메뉴의 기능별 SQL — 내가 최근 조회할 때 실제 실행된 쿼리(값 채움) + 코드 기준"""
    from . import sql_catalog

    return sql_catalog.page(page, me["id"])


# ---- 마이페이지 ----
@app.get("/api/me/overview")
def my_overview(me: dict = Depends(current_user)):
    """마이페이지: 내 권한 · 오늘 AI 사용 · 마지막 로그인 · 적용된 권한 묶음 · 최근 30일 내 다운로드"""
    from . import roles

    u = userdb.get_user(me["id"]) or {}
    try:
        role = roles.role_of(me["id"])
    except Exception:  # noqa: BLE001 - 권한 묶음 테이블 문제로 마이페이지가 막히지 않게
        role = None
    dl = downloads.report(30, usr=me["id"], limit=20) if downloads.tables.ready() else None
    return {
        "user": me, "usage": usage.usage_summary(me), "lastLoginAt": u.get("last_login_at"), "createdAt": u.get("created_at"),
        "pages": [{"key": p, "label": auth.PAGE_LABELS.get(p, "관리자" if p == "admin" else p)} for p in me["pages"]],
        "role": role, "accents": list(ACCENTS),
        "downloads": {"total": dl["total"], "rows": dl["rows"]} if dl else None,
    }


@app.get("/api/admin/downloads")
def admin_downloads(days: int = 30, usr: str | None = None, kind: str | None = None, _: dict = Depends(require_admin)):
    names = {u["id"]: u["name"] for u in admin.list_users()}
    return downloads.report(days, usr, kind, names)


@app.get("/api/admin/notices")
def admin_notices(_: dict = Depends(require_admin)):
    from . import notices

    return {**notices.list_all(), "maintenance": notices.maintenance()}


@app.get("/api/admin/notices/{notice_id}/reads")
def admin_notice_reads(notice_id: str, _: dict = Depends(require_admin)):
    """공지 대상자별 읽음 · 필독 확인 현황"""
    from . import notices

    return notices.read_status(notice_id)


@app.post("/api/admin/notices")
def admin_notice_create(body: dict, me: dict = Depends(require_admin)):
    from . import notices

    return notices.save(me, body)


@app.put("/api/admin/notices/{notice_id}")
def admin_notice_update(notice_id: str, body: dict, me: dict = Depends(require_admin)):
    from . import notices

    return notices.save(me, body, notice_id)


@app.delete("/api/admin/notices/{notice_id}")
def admin_notice_delete(notice_id: str, me: dict = Depends(require_admin)):
    from . import notices

    return notices.delete(me, notice_id)


@app.put("/api/admin/maintenance")
def admin_maintenance(body: dict, me: dict = Depends(require_admin)):
    """점검 모드 켜기/끄기 {on, message, until} — 켜면 관리자 외 사용자는 로그인·사용이 막힌다"""
    from . import notices

    return notices.set_maintenance(me, body)


@app.get("/api/notices")
def notices_active(me: dict = Depends(current_user)):
    """오늘 게시 중이고 내가 대상인 공지 (로그인 후 팝업) + 곧 시작하는 예약 점검 예고"""
    from . import notices

    return {"notices": notices.active_for(me), "maintenance": notices.upcoming_maintenance()}


@app.post("/api/notices/read")
def notices_read(body: dict, me: dict = Depends(current_user)):
    """팝업으로 본 공지 읽음 기록"""
    from . import notices

    return {"marked": notices.mark_read(me, [str(x) for x in (body.get("ids") or [])][:50])}


@app.post("/api/notices/{notice_id}/ack")
def notice_ack(notice_id: str, me: dict = Depends(current_user)):
    """필독 공지 [확인]"""
    from . import notices

    return notices.acknowledge(me, notice_id)


@app.get("/api/notices/board")
def notices_board(q: str | None = None, me: dict = Depends(current_user)):
    """공지사항 게시판 (게시가 시작된 공지, 지난 공지 포함 · 관리자는 전체)"""
    from . import notices

    return notices.board(me, q)


@app.get("/api/notices/{notice_id}")
def notice_detail(notice_id: str, me: dict = Depends(current_user)):
    from . import notices

    return notices.detail(me, notice_id)


@app.get("/api/notices/{notice_id}/files/{no}")
def notice_file(notice_id: str, no: int, me: dict = Depends(current_user)):
    """본문 이미지는 화면에 바로 보이고(inline), 첨부파일은 내려받기(attachment)"""
    from . import notices

    data, mime, name, kind = notices.get_file(me, notice_id, no)
    disp = "inline" if kind == "image" else "attachment"
    return Response(content=data, media_type=mime, headers={
        "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(name)}"})


@app.post("/api/notices/{notice_id}/comments")
def notice_comment_add(notice_id: str, body: dict, me: dict = Depends(current_user)):
    from . import notices

    return notices.add_comment(me, notice_id, body)


@app.put("/api/notices/{notice_id}/comments/{cmt_id}")
def notice_comment_edit(notice_id: str, cmt_id: str, body: dict, me: dict = Depends(current_user)):
    from . import notices

    return notices.edit_comment(me, notice_id, cmt_id, body)


@app.delete("/api/notices/{notice_id}/comments/{cmt_id}")
def notice_comment_delete(notice_id: str, cmt_id: str, me: dict = Depends(current_user)):
    from . import notices

    return notices.delete_comment(me, notice_id, cmt_id)


# ----------------------------------------------------------------------------
# 데이터 관리 > 매장 재고 실사계획
# ----------------------------------------------------------------------------
invt_page = require_page("invt_plan")


# ----------------------------------------------------------------------------
# 월별 매장별 판매 집계 (T_CLOSE_SALE_BASE)
# ----------------------------------------------------------------------------
sale_page = require_page("sale_monthly")
mall_page = require_page("mall_shop")


@app.get("/api/mall-shops")
def mall_shop_list(days: int = 7, _: dict = Depends(mall_page)):
    """판매처 매장 연결: 최근 수집에 나온 사이트·판매자번호 조합과 매핑"""
    from . import mall_shop

    return mall_shop.listing(days)


@app.get("/api/mall-shops/shops")
def mall_shop_shops(_: dict = Depends(mall_page)):
    from . import mall_shop

    return {"shops": mall_shop.shop_options()}


@app.put("/api/mall-shops")
def mall_shop_save(body: dict, me: dict = Depends(mall_page)):
    """매핑 저장 [{mallNm, sellNo, shopId(빈 값이면 해제), useYn, rmk}]"""
    from . import mall_shop

    return mall_shop.save(me, body.get("items"))


@app.post("/api/rows/fill-shop")
def rows_fill_shop(me: dict = Depends(mall_page)):
    """일자별 상세 [매장코드 채우기]: 최근 7일(당일 포함) 수집 행 SHOP_ID 를 판매처 매장 연결로 채움 (매핑 관리 권한 필요)"""
    from . import mall_shop

    if "detail" not in me["pages"]:
        raise HTTPException(status_code=403, detail={"message": "'일자별 상세' 페이지 권한이 없습니다.", "code": "FORBIDDEN"})
    return mall_shop.fill_shop_ids(me)
sale_dash_page = require_page("sale_dashboard")


def _dash_args(ym: str | None = Query(None), from_: str | None = Query(None, alias="from"), cmp: str | None = None,
               cmpFrom: str | None = None, cmpTo: str | None = None, brand: str | None = None) -> dict:  # noqa: N803
    return {"ym": ym, "frm": from_, "cmp": cmp, "cmp_from": cmpFrom, "cmp_to": cmpTo, "brand": brand}


@app.get("/api/sale-dashboard")
def sale_dashboard_get(args: dict = Depends(_dash_args), me: dict = Depends(sale_dash_page)):
    return sale_dashboard.dashboard(**args, allowed=brand_scope.brands_of(me))


@app.get("/api/sale-dashboard/export")
def sale_dashboard_export(args: dict = Depends(_dash_args), me: dict = Depends(sale_dash_page)):
    from . import sale_dashboard_report as rpt

    from . import sale_products

    allowed = brand_scope.brands_of(me)
    d = sale_dashboard.dashboard(**args, full=True, allowed=allowed)
    try:
        pr = sale_products.analyze(**args, allowed=allowed)
    except Exception:  # noqa: BLE001 - 상품 집계가 실패해도 나머지 보고서는 만든다
        logs.get("app").exception("보고용 엑셀 상품 시트 생략")
        pr = None
    content = rpt.build(d, pr)
    downloads.record(me, "sale_report", rpt.filename(d).removesuffix(".xlsx"), {k: v for k, v in args.items() if v}, size=len(content))
    return _xlsx_response(content, rpt.filename(d))


@app.get("/api/sale-dashboard/products")
def sale_dashboard_products(args: dict = Depends(_dash_args), me: dict = Depends(sale_dash_page)):
    """상품 순위 · 아이템/품군 비교 · 판매형태 구성 (판매 현황과 같은 조건, 따로 불러 화면이 먼저 뜨게)"""
    from . import sale_products

    return sale_products.analyze(**args, allowed=brand_scope.brands_of(me))


@app.get("/api/sale-dashboard/season")
def sale_dashboard_season(ym: str | None = None, brand: str | None = None, planYy: str | None = None,  # noqa: N803
                          season: str | None = None, me: dict = Depends(sale_dash_page)):
    """시즌 판매 진척: 시즌 월 누적 판매 vs 전년 같은 시즌의 같은 시점 (기준 월·브랜드는 판매 현황과 같게)"""
    from . import sale_season

    return sale_season.progress(ym, brand, brand_scope.brands_of(me), planYy, season)


@app.get("/api/sale-dashboard/season/items")
def sale_dashboard_season_items(ym: str | None = None, brand: str | None = None, planYy: str | None = None,  # noqa: N803
                                season: str | None = None, me: dict = Depends(sale_dash_page)):
    """시즌 판매 진척 아이템별 (아이템마다 누적 · 전년 같은 시점 · 진척률)"""
    from . import sale_season

    return sale_season.items(ym, brand, brand_scope.brands_of(me), planYy, season)


@app.get("/api/sale-dashboard/sale-heavy-shops")
def sale_dashboard_sale_heavy(args: dict = Depends(_dash_args), includeEvent: bool = False,  # noqa: N803
                              me: dict = Depends(sale_dash_page)):
    """세일 비중이 같은 브랜드 평균보다 높은 매장 (판매 현황과 같은 조건)"""
    from . import sale_mix

    return sale_mix.heavy_shops(**args, allowed=brand_scope.brands_of(me), include_event=includeEvent)


@app.get("/api/sale-dashboard/online-alerts")
def sale_dashboard_online_alerts(args: dict = Depends(_dash_args), me: dict = Depends(sale_dash_page)):
    """온라인 할인 주의 상품: 매장 상위 상품 중 최근 온라인 할인율이 오른 상품 (온라인 가격 메뉴 권한도 필요)"""
    from . import online_alerts

    if not set(me["pages"]) & {"dashboard", "detail"}:
        raise HTTPException(403, {"message": "온라인 가격 메뉴 권한이 필요합니다.", "code": "FORBIDDEN"})
    return online_alerts.alerts(**args, allowed=brand_scope.brands_of(me))


@app.get("/api/products/{prdt_cd}/insight")
def product_insight(prdt_cd: str, me: dict = Depends(current_user)):
    """상품 팝업: 온라인 가격(온라인 가격 메뉴 권한) + 매장 판매(판매 메뉴 권한)를 품번으로 이어서 보여준다."""
    import re

    from . import sale_products

    cd = (prdt_cd or "").strip().upper()
    if not re.match(r"^[A-Z0-9_-]{2,20}$", cd):
        raise HTTPException(400, {"message": "품번이 올바르지 않습니다.", "code": "BAD_REQUEST"})
    pages = set(me["pages"])
    can_price, can_sale = bool(pages & {"dashboard", "detail"}), bool(pages & {"sale_dashboard", "sale_monthly"})
    if not (can_price or can_sale):
        raise HTTPException(403, {"message": "온라인 가격 또는 판매 메뉴 권한이 필요합니다.", "code": "FORBIDDEN"})
    out: dict = {"prdtCd": cd}
    if can_price:
        out["online"] = ds.product_online(cd)
    if can_sale:
        last = sale_monthly._shift_ym(time.strftime("%Y%m"), -1)
        months = [sale_monthly._shift_ym(last, -i) for i in range(11, -1, -1)]
        out["sales"] = sale_products.product_sales(cd, months, brand_scope.teams_of(me))
        try:  # 많이 팔린 매장 · 팀 (최근 3개월)
            out["shops"] = sale_products.product_shops(cd, months[-3:], brand_scope.teams_of(me))
        except Exception:  # noqa: BLE001 - 매장 분포가 실패해도 나머지는 보여준다
            logs.get("app").exception("상품 팝업 매장 분포 실패 %s", cd)
        try:  # 같은 기획년도·시즌·아이템 품번 사이 순위
            sib = sale_products.product_siblings(cd, brand_scope.teams_of(me))
            if sib:
                out["siblings"] = sib
        except Exception:  # noqa: BLE001
            logs.get("app").exception("상품 팝업 같은 아이템 비교 실패 %s", cd)
    return out


@app.get("/api/sale-dashboard/shops/{shop_id}/trend")
def sale_dashboard_trend(shop_id: str, me: dict = Depends(sale_dash_page)):
    return sale_monthly.shop_trend(shop_id, teams=brand_scope.teams_of(me))


@app.get("/api/sale-monthly/options")
def sale_options(_: dict = Depends(sale_page)):
    return sale_monthly.options()


@app.get("/api/sale-monthly")
def sale_search(ymFrom: str, ymTo: str, shops: str | None = None, planYys: str | None = None,
                seasons: str | None = None, page: int = 1, total: bool = True, me: dict = Depends(sale_page)):
    return sale_monthly.search(ymFrom, ymTo, shops, planYys, seasons, page, total, teams=brand_scope.teams_of(me))


@app.get("/api/sale-monthly/summary")
def sale_summary(ymFrom: str, ymTo: str, dim: str = "month", shops: str | None = None, planYys: str | None = None,
                 seasons: str | None = None, me: dict = Depends(sale_page)):
    return sale_monthly.summary(ymFrom, ymTo, shops, planYys, seasons, dim, teams=brand_scope.teams_of(me))


@app.get("/api/sale-monthly/shops/{shop_id}/trend")
def sale_shop_trend(shop_id: str, me: dict = Depends(sale_page)):
    return sale_monthly.shop_trend(shop_id, teams=brand_scope.teams_of(me))


@app.get("/api/sale-monthly/dsct")
def sale_dsct(ymFrom: str, ymTo: str, shops: str | None = None, planYys: str | None = None,
              seasons: str | None = None, me: dict = Depends(sale_page)):
    return sale_monthly.dsct_total(ymFrom, ymTo, shops, planYys, seasons, teams=brand_scope.teams_of(me))


class SaleExportReq(BaseModel):
    ymFrom: str
    ymTo: str
    shops: str | None = None
    planYys: str | None = None
    seasons: str | None = None


@app.post("/api/sale-monthly/exports")
def sale_export_start(req: SaleExportReq, me: dict = Depends(sale_page)):
    return sale_monthly.start_export(me["id"], req.ymFrom, req.ymTo, req.shops, req.planYys, req.seasons,
                                     teams=brand_scope.teams_of(me))


@app.get("/api/sale-monthly/exports/current")
def sale_export_current(me: dict = Depends(sale_page)):
    return {"job": sale_monthly.current_export(me["id"])}


@app.get("/api/sale-monthly/exports/{job_id}")
def sale_export_status(job_id: str, me: dict = Depends(sale_page)):
    return sale_monthly.export_status(me["id"], job_id)


@app.delete("/api/sale-monthly/exports/{job_id}")
def sale_export_cancel(job_id: str, me: dict = Depends(sale_page)):
    return sale_monthly.cancel_export(me["id"], job_id)


@app.get("/api/sale-monthly/exports/{job_id}/file")
def sale_export_file(job_id: str, me: dict = Depends(sale_page)):
    path, name = sale_monthly.export_file(me["id"], job_id)
    job = sale_monthly._jobs.get(job_id) or {}
    downloads.record(me, "sale_monthly", name, job.get("cond"), rows=job.get("total"), size=os.path.getsize(path))
    return FileResponse(path, media_type=XLSX,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.get("/api/sale-monthly/shops")
def sale_shops(q: str, me: dict = Depends(sale_page)):
    shops = invt_plan.search_shops(q)
    teams = brand_scope.teams_of(me)
    if teams is not None:  # 브랜드 권한: 허용 브랜드에서 판매 기록이 있는 매장만
        allowed = sale_monthly.brand_shop_ids(teams)
        shops = [s for s in shops if s["shopId"] in allowed]
    return {"shops": shops}


@app.get("/api/invt-plans/options")
def invt_options(_: dict = Depends(invt_page)):
    return invt_plan.options()


@app.get("/api/invt-plans")
def invt_list(_: dict = Depends(invt_page)):
    return {"plans": invt_plan.list_plans()}


@app.get("/api/invt-plans/export")
def invt_export(ids: str | None = None, me: dict = Depends(invt_page)):
    plans = invt_plan.list_plans()
    if ids:  # 화면에서 필터·정렬된 순서 그대로 내보내기
        order = {int(x): i for i, x in enumerate(ids.split(",")) if x.strip().isdigit()}
        plans = sorted((p for p in plans if p["planId"] in order), key=lambda p: order[p["planId"]])
    content = invt_plan.export_xlsx(plans)
    downloads.record(me, "invt_plan", "매장재고실사계획", {"selected": len(plans) if ids else "전체"}, rows=len(plans), size=len(content))
    return _xlsx_response(content, "매장재고실사계획.xlsx")


@app.get("/api/invt-plans/shops")
def invt_shops(q: str, _: dict = Depends(invt_page)):
    return {"shops": invt_plan.search_shops(q)}


@app.get("/api/invt-plans/shops/{shop_id}")
def invt_shop_detail(shop_id: str, _: dict = Depends(invt_page)):
    return invt_plan.shop_detail(shop_id)


# ----------------------------------------------------------------------------
# 데이터 관리 > 재고 재배치 추천 (매장 간 RT · 창고 → 매장 배분 추천, 관리자는 ERP 지시 · 의뢰 등록 · 삭제)
# ----------------------------------------------------------------------------
stock_page = require_page("stock_rt")


def _rt_args(brand: str | None = None, dateFrom: str | None = None, dateTo: str | None = None, planYy: str | None = None,  # noqa: N803
             seasons: str | None = None, prdt: str | None = None, teams: str | None = None, per: int = 1, limits: bool = False,
             order: str = "slow", senderMax: int = 0) -> dict:  # noqa: N803
    return {"brand": brand, "frm": dateFrom, "to": dateTo, "plan_yy": planYy, "seasons": seasons, "prdt": prdt, "teams": teams,
            "per": per, "limits": limits, "order": order, "sender_max": senderMax}


def _alloc_args(brand: str | None = None, wh: str | None = None, dateFrom: str | None = None, dateTo: str | None = None,  # noqa: N803
                base: str | None = None, grdGrp: str | None = None, planYy: str | None = None, seasons: str | None = None,  # noqa: N803
                prdtGrps: str | None = None, items: str | None = None, prdt: str | None = None, teams: str | None = None,  # noqa: N803
                rate: float = 1) -> dict:
    return {"brand": brand, "wh": wh, "frm": dateFrom, "to": dateTo, "base": base, "grd_grp": grdGrp, "plan_yy": planYy,
            "seasons": seasons, "prdt_grps": prdtGrps, "items": items, "prdt": prdt, "teams": teams, "rate": rate}


def _json_gz(request: Request, obj) -> Response:
    """큰 JSON(추천 전체 행 수천 ~ 수만 건)을 gzip 으로 보낸다 — 화면에서 100행씩 넘겨 보며 전체를 고르고 검색할 수 있게"""
    import gzip
    import json

    data = json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    if len(data) > 20000 and "gzip" in (request.headers.get("accept-encoding") or ""):
        return Response(gzip.compress(data, 5), media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(data, media_type="application/json")


@app.get("/api/stock-rt/options")
def stock_rt_options(brand: str | None = None, me: dict = Depends(stock_page)):
    """조건 선택지: 브랜드(권한) · 시즌 · 팀 · 창고 · 판매보충기준 · 등급 그룹 · 최근 판매분 자동보충 실행 조건"""
    from . import stock_ctl, wh_alloc

    out = wh_alloc.options(brand, brand_scope.brands_of(me))
    return {**out, "defaultSeasons": stock_ctl.default_seasons(), "defaultPlanYy": stock_ctl.default_plan_years(),
            "today": stock_ctl.today(), "maxDays": stock_ctl.MAX_DAYS, "canWrite": me["role"] == "ADMIN"}


@app.get("/api/stock-rt/rt")
def stock_rt_recommend(request: Request, args: dict = Depends(_rt_args), refresh: bool = False, me: dict = Depends(stock_page)):
    """매장 간 RT 추천 (자동 RT 규칙, 최대 31일). 전체 행을 gzip 으로 보내고 화면은 100행씩 넘겨 본다"""
    from . import stock_rt

    d = stock_rt.recommend(**args, allowed=brand_scope.brands_of(me), refresh=refresh)
    return _json_gz(request, {**d, "rowsTotal": len(d["rows"]), "unfilledTotal": len(d["unfilled"])})


@app.get("/api/stock-rt/rt/export")
def stock_rt_export(args: dict = Depends(_rt_args), me: dict = Depends(stock_page)):
    from . import stock_rt

    d = stock_rt.recommend(**args, allowed=brand_scope.brands_of(me))
    content = stock_rt.export_xlsx(d)
    downloads.record(me, "stock_rt", "매장간RT추천", {k: v for k, v in args.items() if v not in (None, "", 0, False)},
                     rows=len(d["rows"]), size=len(content))
    return _xlsx_response(content, f"매장간RT추천_{d['brandNm']}_{d['to']}.xlsx")


@app.get("/api/stock-rt/rt/stats")
def stock_rt_stats(brand: str | None = None, dateFrom: str | None = None, dateTo: str | None = None,  # noqa: N803
                   me: dict = Depends(stock_page)):
    """자동 RT 요청 결과 현황 (기간 · 브랜드)"""
    from . import stock_rt

    return stock_rt.auto_rt_stats(brand, dateFrom, dateTo, brand_scope.brands_of(me))


@app.get("/api/stock-rt/alloc")
def stock_alloc_recommend(request: Request, args: dict = Depends(_alloc_args), refresh: bool = False, me: dict = Depends(stock_page)):
    """창고 → 매장 배분 추천 (판매분 자동보충 규칙, 최대 31일). 전체 행을 gzip 으로 (후보 매장 전체 allRows 는 상품별 팝업에서)"""
    from . import wh_alloc

    d = wh_alloc.recommend(**args, allowed=brand_scope.brands_of(me), refresh=refresh)
    out = {k: v for k, v in d.items() if k != "allRows"}
    return _json_gz(request, {**out, "rowsTotal": len(d["rows"]), "skusTotal": len(d["skus"]), "shortRowsTotal": len(d["shortRows"])})


@app.get("/api/stock-rt/alloc/candidates")
def stock_alloc_candidates(prdtCd: str, colorCd: str, sizeCd: str, args: dict = Depends(_alloc_args),  # noqa: N803
                           me: dict = Depends(stock_page)):
    """한 상품의 후보 매장 전체와 순서 (배분 안 된 매장 · 수불제어 매장 포함)"""
    from . import wh_alloc

    d = wh_alloc.recommend(**args, allowed=brand_scope.brands_of(me))
    return {"rows": [r for r in d["allRows"] if (r["prdtCd"], r["colorCd"], r["sizeCd"]) == (prdtCd, colorCd, sizeCd)],
            "sku": next((s for s in d["skus"] if (s["prdtCd"], s["colorCd"], s["sizeCd"]) == (prdtCd, colorCd, sizeCd)), None)}


@app.get("/api/stock-rt/alloc/export")
def stock_alloc_export(args: dict = Depends(_alloc_args), me: dict = Depends(stock_page)):
    from . import wh_alloc

    d = wh_alloc.recommend(**args, allowed=brand_scope.brands_of(me))
    content = wh_alloc.export_xlsx(d)
    downloads.record(me, "stock_rt", "창고배분추천", {k: v for k, v in args.items() if v not in (None, "", 0, False)},
                     rows=len(d["rows"]), size=len(content))
    return _xlsx_response(content, f"창고배분추천_{d['brandNm']}_{d['to']}.xlsx")


# ---- ERP 등록 · 삭제 (본사지시 RT 지시 · 배분의뢰). 지금은 관리자만 — 나중에 일반 사용자에게 열 때는 stock_writer 만 바꾸면 된다
def stock_writer(request: Request) -> dict:
    """ERP 에 넣는 INS_USERID 는 로그인한 사번(me["id"]). 다른 사용자 화면 미리보기 중에는 그 사람 사번으로 들어가므로 막는다"""
    me = stock_page(request)
    if ">" in str(getattr(getattr(request, "state", None), "usr_id", "") or ""):
        raise auth.AuthError(403, "사용자 화면 미리보기 중에는 ERP 에 등록 · 삭제할 수 없습니다.", "FORBIDDEN")
    if me["role"] != "ADMIN":
        raise auth.AuthError(403, "ERP 등록 · 삭제는 관리자만 할 수 있습니다.", "FORBIDDEN")
    return me


@app.post("/api/stock-rt/rt/preview")
def stock_rt_write_preview(body: dict, args: dict = Depends(_rt_args), me: dict = Depends(stock_writer)):
    """고른 RT 추천 행을 지금 재고로 다시 확인 (등록하지 않음)"""
    from . import stock_write

    p = stock_write.rt_preview(args, body.get("keys"), brand_scope.brands_of(me))
    return {k: v for k, v in p.items() if k != "rows"}


@app.post("/api/stock-rt/rt/register")
def stock_rt_write_register(body: dict, args: dict = Depends(_rt_args), me: dict = Depends(stock_writer)):
    """본사지시 RT 지시 등록 (T_INDC_RT, 미확정) — 확정은 ERP 에서 매장이 한다"""
    from . import stock_write

    return stock_write.rt_register(me, args, body.get("keys"), body.get("indcDt"), brand_scope.brands_of(me))


@app.get("/api/stock-rt/rt/registered")
def stock_rt_registered(brand: str | None = None, dateFrom: str | None = None, dateTo: str | None = None,  # noqa: N803
                        me: dict = Depends(stock_writer)):
    from . import stock_write

    return stock_write.rt_list(brand, dateFrom, dateTo, brand_scope.brands_of(me))


@app.post("/api/stock-rt/rt/delete")
def stock_rt_write_delete(body: dict, me: dict = Depends(stock_writer)):
    from . import stock_write

    return stock_write.rt_delete(me, body.get("brand"), body.get("ids"), brand_scope.brands_of(me))


@app.get("/api/stock-rt/alloc/seqns")
def stock_alloc_seqns(brand: str | None = None, askDt: str | None = None, me: dict = Depends(stock_writer)):  # noqa: N803
    from . import stock_write

    return stock_write.alloc_seqns(brand, askDt, brand_scope.brands_of(me))


@app.post("/api/stock-rt/alloc/preview")
def stock_alloc_write_preview(body: dict, args: dict = Depends(_alloc_args), me: dict = Depends(stock_writer)):
    from . import stock_write

    p = stock_write.alloc_preview(args, body.get("keys"), brand_scope.brands_of(me))
    return {k: v for k, v in p.items() if k != "rows"}


@app.post("/api/stock-rt/alloc/register")
def stock_alloc_write_register(body: dict, args: dict = Depends(_alloc_args), me: dict = Depends(stock_writer)):
    """출고의뢰 등록 (T_DELV_ASK, 판매분의뢰(자동) · 미확정) — 확정 · 출고지시는 ERP 에서"""
    from . import stock_write

    return stock_write.alloc_register(me, args, body.get("keys"), body.get("askDt"), body.get("askSeqn"), body.get("delvPreDt"),
                                      brand_scope.brands_of(me))


@app.get("/api/stock-rt/alloc/registered")
def stock_alloc_registered(brand: str | None = None, dateFrom: str | None = None, dateTo: str | None = None,  # noqa: N803
                           me: dict = Depends(stock_writer)):
    from . import stock_write

    return stock_write.alloc_list(brand, dateFrom, dateTo, brand_scope.brands_of(me))


@app.post("/api/stock-rt/alloc/delete")
def stock_alloc_write_delete(body: dict, me: dict = Depends(stock_writer)):
    from . import stock_write

    return stock_write.alloc_delete(me, body.get("brand"), body.get("keys"), brand_scope.brands_of(me))


@app.get("/api/stock-rt/rt/setting-check")
def stock_rt_setting_check(args: dict = Depends(_rt_args), me: dict = Depends(stock_page)):
    """자동 RT 설정 점검: 보낼 수 있는 매장의 지정가능수(ASIGN_ABLE_QTY) · 실제 지정 수 · 권장값 (추천은 하루 한도 없이)"""
    from . import stock_rt

    return stock_rt.setting_check(args, brand_scope.brands_of(me))


@app.get("/api/stock-rt/rt/setting-check/export")
def stock_rt_setting_export(args: dict = Depends(_rt_args), me: dict = Depends(stock_page)):
    from . import stock_ctl, stock_rt

    d = stock_rt.setting_check(args, brand_scope.brands_of(me))
    s = d["summary"]
    notes = [f"자동 RT 설정 점검 ({d['asOf']} 기준 · {d['brandNm']} · {d['from']} ~ {d['to']})",
             f"보내는 매장 {s['senders']}곳 중 지정가능수 0 {s['blockedShops']}곳 · 부족 {s['lowShops']}곳 — 권장 = 올림((기간 실제 지정 + 자동RT 취소 채움) ÷ 기간 일수)"]
    content = stock_ctl.xlsx([("자동 RT 설정 점검", notes, stock_rt.CHECK_COLS, d["rows"])])
    downloads.record(me, "stock_rt", "자동RT설정점검", {"brand": d["brand"], "from": d["from"], "to": d["to"]}, rows=len(d["rows"]), size=len(content))
    return _xlsx_response(content, f"자동RT설정점검_{d['brandNm']}_{d['to']}.xlsx")


@app.get("/api/stock-rt/rt/performance")
def stock_rt_performance(brand: str | None = None, dateFrom: str | None = None, dateTo: str | None = None, scope: str = "web",  # noqa: N803
                         refresh: bool = False, includeVirtual: bool = False, me: dict = Depends(stock_page)):  # noqa: N803
    """RT 성과: 본사지시 RT 의 매장 수락 · 거부 · 미처리, 거부 사유, 받은 매장 7일 내 판매 전환 (행사 · 가상 매장은 기본 제외)"""
    from . import stock_perf

    return stock_perf.performance(brand, dateFrom, dateTo, scope, brand_scope.brands_of(me), refresh=refresh, include_virtual=includeVirtual)


@app.get("/api/stock-rt/rt/performance/export")
def stock_rt_performance_export(brand: str | None = None, dateFrom: str | None = None, dateTo: str | None = None, scope: str = "web",  # noqa: N803
                                includeVirtual: bool = False, me: dict = Depends(stock_page)):  # noqa: N803
    from . import stock_perf

    d = stock_perf.performance(brand, dateFrom, dateTo, scope, brand_scope.brands_of(me), include_virtual=includeVirtual)
    content = stock_perf.export_xlsx(d)
    downloads.record(me, "stock_rt", "RT성과", {"brand": d["brand"], "from": d["from"], "to": d["to"], "scope": scope},
                     rows=len(d["senders"]), size=len(content))
    return _xlsx_response(content, f"RT성과_{d['brandNm']}_{d['to']}.xlsx")


@app.get("/api/stock-rt/alloc/short-rt")
def stock_alloc_short_rt(request: Request, args: dict = Depends(_alloc_args), refresh: bool = False, me: dict = Depends(stock_page)):
    """창고 부족 → 매장 간 RT 로 채우기 추천 (같은 창고 배분 조건의 창고 부족 행)"""
    from . import stock_rt

    return _json_gz(request, stock_rt.fill_shortage(args, brand_scope.brands_of(me), refresh=refresh))


@app.post("/api/stock-rt/alloc/short-rt/preview")
def stock_alloc_short_rt_preview(body: dict, args: dict = Depends(_alloc_args), me: dict = Depends(stock_writer)):
    from . import stock_write

    p = stock_write.rt_preview(args, body.get("keys"), brand_scope.brands_of(me), source="short")
    return {k: v for k, v in p.items() if k != "rows"}


@app.post("/api/stock-rt/alloc/short-rt/register")
def stock_alloc_short_rt_register(body: dict, args: dict = Depends(_alloc_args), me: dict = Depends(stock_writer)):
    """창고 부족 채우기 → 본사지시 RT 지시 등록 (T_INDC_RT 미확정)"""
    from . import stock_write

    return stock_write.rt_register(me, args, body.get("keys"), body.get("indcDt"), brand_scope.brands_of(me), source="short")


# ---- 미처리 RT 현황 · 창고 회수 추천 · 장기 미판매 재고
def _codes(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x]


@app.get("/api/stock-rt/pending")
def stock_pending_board(brand: str | None = None, days: int = 14, types: str | None = None, includeVirtual: bool = False,  # noqa: N803
                        refresh: bool = False, me: dict = Depends(stock_page)):
    """매장이 아직 처리하지 않은 RT 요청 (본사지시 · 자동 RT · 매장간), 처리할 매장별 · 경과 시간별"""
    from . import stock_pending

    return stock_pending.board(brand, days, _codes(types) or None, includeVirtual, brand_scope.brands_of(me), refresh)


@app.get("/api/stock-rt/pending/export")
def stock_pending_export(brand: str | None = None, days: int = 14, types: str | None = None, includeVirtual: bool = False,  # noqa: N803
                         me: dict = Depends(stock_page)):
    from . import stock_pending

    d = stock_pending.board(brand, days, _codes(types) or None, includeVirtual, brand_scope.brands_of(me))
    content = stock_pending.export_xlsx(d)
    downloads.record(me, "stock_rt", "미처리RT현황", {"brand": d["brand"], "days": days}, rows=len(d["rows"]), size=len(content))
    return _xlsx_response(content, f"미처리RT현황_{d['brandNm']}_{d['to']}.xlsx")


@app.get("/api/stock-rt/return")
def stock_return_recommend(request: Request, args: dict = Depends(_alloc_args), lookback: int = 14, mode: str = "need", refresh: bool = False,
                           me: dict = Depends(stock_page)):
    """창고 회수 추천: 창고 부족 상품을 최근 판매 없는 매장 재고에서 회수 (추천만)"""
    from . import stock_return

    return _json_gz(request, stock_return.recommend(args, lookback, mode, brand_scope.brands_of(me), refresh))


@app.get("/api/stock-rt/return/export")
def stock_return_export(args: dict = Depends(_alloc_args), lookback: int = 14, mode: str = "need", me: dict = Depends(stock_page)):
    from . import stock_return

    d = stock_return.recommend(args, lookback, mode, brand_scope.brands_of(me))
    content = stock_return.export_xlsx(d)
    downloads.record(me, "stock_rt", "창고회수추천", {"brand": d["brand"], "lookback": lookback, "mode": mode}, rows=len(d["rows"]), size=len(content))
    return _xlsx_response(content, f"창고회수추천_{d['brandNm']}_{d['to']}.xlsx")


def _aging_args(brand: str | None = None, minDays: int = 90, planYy: str | None = None, seasons: str | None = None,  # noqa: N803
                teams: str | None = None, prdt: str | None = None, includeVirtual: bool = False) -> dict:  # noqa: N803
    return {"brand": brand, "min_days": minDays, "plan_yy": planYy, "seasons": seasons, "teams": teams, "prdt": prdt,
            "include_virtual": includeVirtual}


@app.get("/api/stock-rt/aging")
def stock_aging_report(request: Request, args: dict = Depends(_aging_args), refresh: bool = False, me: dict = Depends(stock_page)):
    """장기 미판매 재고 (매장 × 스타일, 미판매 일수 구간 · 매장별 · 스타일별)"""
    from . import stock_aging

    return _json_gz(request, stock_aging.report(**args, allowed=brand_scope.brands_of(me), refresh=refresh))


@app.get("/api/stock-rt/aging/skus")
def stock_aging_skus(shopId: str, prdtCd: str, brand: str | None = None, me: dict = Depends(stock_page)):  # noqa: N803
    from . import stock_aging

    return {"rows": stock_aging.skus(brand, shopId, prdtCd, brand_scope.brands_of(me))}


@app.get("/api/stock-rt/aging/export")
def stock_aging_export(args: dict = Depends(_aging_args), me: dict = Depends(stock_page)):
    from . import stock_aging

    d = stock_aging.report(**args, allowed=brand_scope.brands_of(me))
    content = stock_aging.export_xlsx(d)
    downloads.record(me, "stock_rt", "장기미판매재고", {"brand": d["brand"], "minDays": d["minDays"]}, rows=len(d["detail"]), size=len(content))
    return _xlsx_response(content, f"장기미판매재고_{d['brandNm']}_{d['minDays']}일.xlsx")


SHOP_PROFILE_PAGES = ("sale_dashboard", "sale_monthly", "invt_plan")


@app.get("/api/shops/{shop_id}/profile")
def shop_profile(shop_id: str, ctx: str | None = None, me: dict = Depends(current_user)):
    """매장 정보 팝업: 기본 정보·담당 영업직원(판매·실사계획 메뉴 권한), 월별 목표(판매 메뉴), 실사 일정·매니저(실사계획 메뉴).
    ctx=invt: 실사계획 화면에서 연 경우 — 실사계획은 브랜드 권한 대상이 아니므로 매장 정보는 거르지 않는다 (목표는 판매 데이터라 거름)."""
    from . import shop_info

    pages = set(me["pages"])
    if not pages & set(SHOP_PROFILE_PAGES):
        raise HTTPException(403, {"message": "매장 정보를 볼 수 있는 메뉴 권한이 없습니다.", "code": "FORBIDDEN"})
    allowed = brand_scope.brands_of(me)
    out: dict = {"shop": shop_info.profile(shop_id, None if ctx == "invt" and "invt_plan" in pages else allowed)}
    sid = out["shop"]["shopId"]
    if pages & {"sale_dashboard", "sale_monthly"}:
        last = sale_monthly._shift_ym(time.strftime("%Y%m"), -1)
        months = [sale_monthly._shift_ym(last, -i) for i in range(11, -1, -1)]
        out["goals"] = shop_info.goals_by_month(sid, months, allowed)
        try:  # 판매형태 구성 · 주력 아이템 (최근 12개월)
            out["mix"] = sale_monthly.shop_mix(sid, teams=brand_scope.teams_of(me))
        except Exception:  # noqa: BLE001
            logs.get("app").exception("매장 팝업 판매 구성 실패 %s", sid)
    if "invt_plan" in pages:
        keys = ("planId", "invtPlanDt", "invtPlanNote", "lastInvtDt", "prevInvtType", "shopRankNm", "stockQty", "twiceYearYn")
        out["invtPlans"] = [{k: p.get(k) for k in keys} for p in invt_plan.list_plans() if p.get("shopId") == sid]
        out["managers"] = [m for m in invt_plan.shop_managers(sid) if m["current"]]
        if any(m.get("smasrHp") for m in out["managers"]):
            downloads.record(me, "manager_phone", f"매장 {sid} 매니저 연락처", {"shopId": sid, "screen": "매장 정보 팝업"},
                             rows=len(out["managers"]))
    return out


@app.get("/api/invt-plans/shops/{shop_id}/sales-trend")
def invt_shop_trend(shop_id: str, _: dict = Depends(invt_page)):
    """실사계획 화면의 매장 판매 추이 (실사계획 메뉴 권한으로 해당 매장 월별 합계만 제공)."""
    return sale_monthly.shop_trend(shop_id)


@app.get("/api/invt-plans/shops/{shop_id}/managers")
def invt_shop_managers(shop_id: str, me: dict = Depends(invt_page)):
    rows = invt_plan.shop_managers(shop_id)
    if any(m.get("smasrHp") for m in rows):
        downloads.record(me, "manager_phone", f"매장 {shop_id} 매니저 연락처", {"shopId": shop_id, "screen": "실사계획 매니저 불러오기"},
                         rows=len(rows))
    return {"managers": rows}


@app.post("/api/invt-plans")
def invt_create(body: dict, user: dict = Depends(invt_page)):
    return {"plan": invt_plan.create_plan(user["id"], body)}


@app.put("/api/invt-plans/{plan_id}")
def invt_update(plan_id: int, body: dict, user: dict = Depends(invt_page)):
    return {"plan": invt_plan.update_plan(user["id"], plan_id, body)}


class DeleteIds(BaseModel):
    ids: list[int]


@app.post("/api/invt-plans/delete")
def invt_delete(body: DeleteIds, user: dict = Depends(invt_page)):
    return {"deleted": invt_plan.delete_plans(user["id"], body.ids)}


# ----------------------------------------------------------------------------
# 엑셀 업로드로 한 번에 등록 (실사계획 · 판매처 매장 연결): 양식 → 미리보기 → 저장
# ----------------------------------------------------------------------------
@app.get("/api/invt-plans/upload-template")
def invt_upload_template(_: dict = Depends(invt_page)):
    from . import uploads

    return _xlsx_response(uploads.invt_template(), "실사계획_업로드_양식.xlsx")


@app.post("/api/invt-plans/upload/preview")
def invt_upload_preview(body: dict, _: dict = Depends(invt_page)):
    from . import uploads

    return uploads.invt_preview(body)


@app.post("/api/invt-plans/upload/apply")
def invt_upload_apply(body: dict, user: dict = Depends(invt_page)):
    from . import uploads

    return uploads.invt_apply(user, body)


@app.get("/api/mall-shops/upload-template")
def mall_upload_template(_: dict = Depends(mall_page)):
    from . import uploads

    return _xlsx_response(uploads.mall_template(), "판매처매장연결_업로드_양식.xlsx")


@app.post("/api/mall-shops/upload/preview")
def mall_upload_preview(body: dict, _: dict = Depends(mall_page)):
    from . import uploads

    return uploads.mall_preview(body)


@app.post("/api/mall-shops/upload/apply")
def mall_upload_apply(body: dict, me: dict = Depends(mall_page)):
    from . import uploads

    return uploads.mall_apply(me, body)


# ----------------------------------------------------------------------------
# 관리자 > 쿼리 성능 · 실행 계획
# ----------------------------------------------------------------------------
@app.get("/api/admin/perf")
def admin_perf(days: int = 7, _: dict = Depends(require_admin)):
    from . import sql_perf

    return sql_perf.report(days)


@app.post("/api/admin/perf/clear")
def admin_perf_clear(_: dict = Depends(require_admin)):
    from . import sql_perf

    return sql_perf.clear()


@app.post("/api/admin/sql/explain")
def admin_sql_explain(body: dict, _: dict = Depends(require_admin)):
    """실행 계획 (쿼리는 실행하지 않음): 실제 계획(커서 캐시) + 예상 계획(EXPLAIN PLAN)"""
    from . import sql_perf

    return sql_perf.explain(str(body.get("sql") or ""))


# 프론트 빌드 결과(frontend/dist)가 있으면 같은 포트에서 함께 서비스 (로컬 배포용)
DIST = config.ROOT_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, {"message": "Not Found", "code": "NOT_FOUND"})
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
