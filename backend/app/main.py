"""FastAPI 엔트리포인트."""
from __future__ import annotations

import time
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import logs

logs.setup()  # 다른 모듈보다 먼저: import 중 발생하는 로그도 파일에 남도록

from . import admin, auth, chat_service, config, data_service as ds, invt_plan, sale_monthly, store, usage, userdb  # noqa: E402
from .auth import current_user, require_admin, require_page  # noqa: E402

_log = logs.get("request")
logs.get("app").info("서버 시작 (port=%s)", config.API_PORT)

store.init()
sale_monthly.cleanup_exports()  # 재시작 전 남은 엑셀 임시 파일 정리
_moved = userdb.migrate_from_sqlite(store)  # 1회: 이전 SQLite 사용자/설정 → Oracle
if _moved:
    logs.get("app").info("사용자 권한을 Oracle 로 이전했습니다: %s", ", ".join(_moved))

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
    try:
        response = await call_next(request)
    except Exception:
        _log.exception("처리 실패 user=%s %s %s", getattr(request.state, "usr_id", "-"), request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": {"message": "서버 오류가 발생했습니다. 잠시 후 다시 시도하세요.",
                                                                  "code": "SERVER_ERROR"}})
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
    return {"ok": True}


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
PREF_KEYS = {"detail.columns"}


@app.get("/api/prefs/{key}")
def get_pref(key: str, user: dict = Depends(current_user)):
    if key not in PREF_KEYS:
        raise HTTPException(404, {"message": "알 수 없는 설정", "code": "NOT_FOUND"})
    return {"value": store.get_pref(user["id"], key)}


@app.put("/api/prefs/{key}")
def put_pref(key: str, body: dict, user: dict = Depends(current_user)):
    if key not in PREF_KEYS:
        raise HTTPException(404, {"message": "알 수 없는 설정", "code": "NOT_FOUND"})
    store.set_pref(user["id"], key, body.get("value"))
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
    _: dict = Depends(require_page("detail")),
):
    try:
        return ds.day_rows(dt, page, size, sort, order, q, mall, minRate, maxRate)
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
    _: dict = Depends(require_page("detail")),
):
    try:
        content = ds.export_day(dt, sort, order, q, mall, minRate, maxRate, cols.split(",") if cols else None)
    except ValueError as ex:
        _bad_request(ex)
    return _xlsx_response(content, f"온라인가격수집_{dt}.xlsx")


class TableExport(BaseModel):
    title: str = "조회결과"
    columns: list[dict]
    rows: list[dict]


@app.post("/api/export/table")
def export_table(body: TableExport, _: dict = Depends(current_user)):
    cols = [(c["key"], c.get("label", c["key"])) for c in body.columns if "key" in c]
    content = ds.write_xlsx("조회결과", cols, body.rows)
    safe = "".join(ch for ch in body.title if ch not in '\\/:*?"<>|').strip() or "조회결과"
    return _xlsx_response(content, f"{safe}.xlsx")


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
    return {"favorites": store.rows("SELECT id, text, created_at AS createdAt FROM favorites WHERE usr_id=? ORDER BY id DESC",
                                    (user["id"],))}


@app.post("/api/chat/favorites")
def add_favorite(body: FavoriteBody, user: dict = Depends(current_user)):
    text = " ".join(body.text.split())[:500]
    if not text:
        raise HTTPException(400, {"message": "내용이 비어 있습니다.", "code": "BAD_REQUEST"})
    store.execute("INSERT OR IGNORE INTO favorites(usr_id, text) VALUES(?,?)", (user["id"], text))
    return favorites(user)


@app.delete("/api/chat/favorites/{fav_id}")
def delete_favorite(fav_id: int, user: dict = Depends(current_user)):
    store.execute("DELETE FROM favorites WHERE id=? AND usr_id=?", (fav_id, user["id"]))
    return favorites(user)


# ----------------------------------------------------------------------------
# 관리자
# ----------------------------------------------------------------------------
@app.get("/api/admin/users")
def admin_users(q: str | None = None, _: dict = Depends(require_admin)):
    return {"users": admin.list_users(q), "pages": admin.page_meta(),
            "superAdminId": config.SUPER_ADMIN_ID}


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
    return admin.save_settings(body, by=me["id"])


@app.get("/api/admin/usage")
def admin_usage(days: int = 30, _: dict = Depends(require_admin)):
    return admin.usage_report(days)


@app.get("/api/admin/logins")
def admin_logins(limit: int = 200, q: str | None = None, _: dict = Depends(require_admin)):
    return {"logins": admin.login_log(limit, q), "locks": admin.locks()}


@app.delete("/api/admin/locks/{usr_id}")
def admin_unlock(usr_id: str, _: dict = Depends(require_admin)):
    admin.unlock(usr_id)
    return {"ok": True}


@app.get("/api/admin/sessions")
def admin_sessions(_: dict = Depends(require_admin)):
    return {"sessions": admin.sessions()}


@app.get("/api/admin/logs")
def admin_logs(level: str = "INFO", q: str | None = None, category: str | None = None, limit: int = 300,
               _: dict = Depends(require_admin)):
    return {"logs": logs.tail(level, q, category, limit), "slowSqlSec": logs.SLOW_SQL_SEC}


@app.delete("/api/admin/sessions/{sid}")
def admin_kill_session(sid: str, _: dict = Depends(require_admin)):
    admin.kill_session(sid)
    return {"ok": True}


# ----------------------------------------------------------------------------
# 데이터 관리 > 매장 재고 실사계획
# ----------------------------------------------------------------------------
invt_page = require_page("invt_plan")


# ----------------------------------------------------------------------------
# 월별 매장별 판매 집계 (T_CLOSE_SALE_BASE)
# ----------------------------------------------------------------------------
sale_page = require_page("sale_monthly")


@app.get("/api/sale-monthly/options")
def sale_options(_: dict = Depends(sale_page)):
    return sale_monthly.options()


@app.get("/api/sale-monthly")
def sale_search(ymFrom: str, ymTo: str, shops: str | None = None, planYys: str | None = None,
                seasons: str | None = None, page: int = 1, total: bool = True, _: dict = Depends(sale_page)):
    return sale_monthly.search(ymFrom, ymTo, shops, planYys, seasons, page, total)


@app.get("/api/sale-monthly/summary")
def sale_summary(ymFrom: str, ymTo: str, dim: str = "month", shops: str | None = None, planYys: str | None = None,
                 seasons: str | None = None, _: dict = Depends(sale_page)):
    return sale_monthly.summary(ymFrom, ymTo, shops, planYys, seasons, dim)


@app.get("/api/sale-monthly/shops/{shop_id}/trend")
def sale_shop_trend(shop_id: str, _: dict = Depends(sale_page)):
    return sale_monthly.shop_trend(shop_id)


@app.get("/api/sale-monthly/dsct")
def sale_dsct(ymFrom: str, ymTo: str, shops: str | None = None, planYys: str | None = None,
              seasons: str | None = None, _: dict = Depends(sale_page)):
    return sale_monthly.dsct_total(ymFrom, ymTo, shops, planYys, seasons)


class SaleExportReq(BaseModel):
    ymFrom: str
    ymTo: str
    shops: str | None = None
    planYys: str | None = None
    seasons: str | None = None


@app.post("/api/sale-monthly/exports")
def sale_export_start(req: SaleExportReq, me: dict = Depends(sale_page)):
    return sale_monthly.start_export(me["id"], req.ymFrom, req.ymTo, req.shops, req.planYys, req.seasons)


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
    return FileResponse(path, media_type=XLSX,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.get("/api/sale-monthly/shops")
def sale_shops(q: str, _: dict = Depends(sale_page)):
    return {"shops": invt_plan.search_shops(q)}


@app.get("/api/invt-plans/options")
def invt_options(_: dict = Depends(invt_page)):
    return invt_plan.options()


@app.get("/api/invt-plans")
def invt_list(_: dict = Depends(invt_page)):
    return {"plans": invt_plan.list_plans()}


@app.get("/api/invt-plans/export")
def invt_export(ids: str | None = None, _: dict = Depends(invt_page)):
    plans = invt_plan.list_plans()
    if ids:  # 화면에서 필터·정렬된 순서 그대로 내보내기
        order = {int(x): i for i, x in enumerate(ids.split(",")) if x.strip().isdigit()}
        plans = sorted((p for p in plans if p["planId"] in order), key=lambda p: order[p["planId"]])
    return _xlsx_response(invt_plan.export_xlsx(plans), "매장재고실사계획.xlsx")


@app.get("/api/invt-plans/shops")
def invt_shops(q: str, _: dict = Depends(invt_page)):
    return {"shops": invt_plan.search_shops(q)}


@app.get("/api/invt-plans/shops/{shop_id}")
def invt_shop_detail(shop_id: str, _: dict = Depends(invt_page)):
    return invt_plan.shop_detail(shop_id)


@app.get("/api/invt-plans/shops/{shop_id}/sales-trend")
def invt_shop_trend(shop_id: str, _: dict = Depends(invt_page)):
    """실사계획 화면의 매장 판매 추이 (실사계획 메뉴 권한으로 해당 매장 월별 합계만 제공)."""
    return sale_monthly.shop_trend(shop_id)


@app.get("/api/invt-plans/shops/{shop_id}/managers")
def invt_shop_managers(shop_id: str, _: dict = Depends(invt_page)):
    return {"managers": invt_plan.shop_managers(shop_id)}


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
