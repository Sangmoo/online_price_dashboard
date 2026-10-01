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

from . import logs

logs.setup()  # 다른 모듈보다 먼저: import 중 발생하는 로그도 파일에 남도록

from . import admin, appdb, auth, brand_scope, chat_service, menu_usage, config, data_service as ds, invt_plan, mv_refresh, sale_dashboard, sale_monthly, server_status, store, usage, userdb  # noqa: E402
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
    """6시간마다: 보관 기간이 지난 로그 파일·엑셀 임시 파일 정리 (보관 일수는 관리자 설정, 기본 7일)"""
    time.sleep(30)
    while True:
        try:
            logs.cleanup(userdb.get_settings().get("log_keep_days") or logs.DEFAULT_KEEP_DAYS)
            sale_monthly.cleanup_exports()
        except Exception:  # noqa: BLE001
            logs.get("app").exception("정리 작업 실패")
        time.sleep(6 * 3600)


if os.getenv("ERP_NO_AUTO_MIGRATE") != "1":
    threading.Thread(target=_housekeeping, daemon=True, name="housekeeping").start()

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
PREF_KEYS = {"detail.columns"}


@app.get("/api/prefs/{key}")
def get_pref(key: str, user: dict = Depends(current_user)):
    if key not in PREF_KEYS:
        raise HTTPException(404, {"message": "알 수 없는 설정", "code": "NOT_FOUND"})
    return {"value": appdb.pref_get(user["id"], key)}


@app.put("/api/prefs/{key}")
def put_pref(key: str, body: dict, user: dict = Depends(current_user)):
    if key not in PREF_KEYS:
        raise HTTPException(404, {"message": "알 수 없는 설정", "code": "NOT_FOUND"})
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


@app.get("/api/admin/menu-usage")
def admin_menu_usage(days: int = 30, _: dict = Depends(require_admin)):
    return menu_usage.report(days, admin.list_users())


@app.get("/api/admin/server-status")
def admin_server_status(days: int = 7, _: dict = Depends(require_admin)):
    return server_status.status(days, userdb.get_settings().get("log_keep_days"))


@app.post("/api/admin/logs/cleanup")
def admin_logs_cleanup(_: dict = Depends(require_admin)):
    return logs.cleanup(userdb.get_settings().get("log_keep_days") or logs.DEFAULT_KEEP_DAYS)


@app.get("/api/admin/data-freshness")
def admin_data_freshness(_: dict = Depends(require_admin)):
    return mv_refresh.freshness()


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
# 데이터 관리 > 매장 재고 실사계획
# ----------------------------------------------------------------------------
invt_page = require_page("invt_plan")


# ----------------------------------------------------------------------------
# 월별 매장별 판매 집계 (T_CLOSE_SALE_BASE)
# ----------------------------------------------------------------------------
sale_page = require_page("sale_monthly")
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

    d = sale_dashboard.dashboard(**args, full=True, allowed=brand_scope.brands_of(me))
    return _xlsx_response(rpt.build(d), rpt.filename(d))


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
    if "invt_plan" in pages:
        keys = ("planId", "invtPlanDt", "invtPlanNote", "lastInvtDt", "prevInvtType", "shopRankNm", "stockQty", "twiceYearYn")
        out["invtPlans"] = [{k: p.get(k) for k in keys} for p in invt_plan.list_plans() if p.get("shopId") == sid]
        out["managers"] = [m for m in invt_plan.shop_managers(sid) if m["current"]]
    return out


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
