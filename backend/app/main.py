"""FastAPI 엔트리포인트."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, data_service as ds
from .chat_service import sessions, stream_chat

app = FastAPI(title="Online Price Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _bad_request(ex: ValueError):
    raise HTTPException(status_code=400, detail=str(ex))


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type=XLSX,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/dates")
def dates():
    return {"dates": ds.available_dates()}


@app.get("/api/dashboard")
def dashboard(start: str, end: str):
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
):
    try:
        return ds.day_rows(dt, page, size, sort, order, q, mall)
    except ValueError as ex:
        _bad_request(ex)


@app.get("/api/rows/export")
def rows_export(
    dt: str,
    sort: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    q: str | None = None,
    mall: str | None = None,
):
    try:
        content = ds.export_day(dt, sort, order, q, mall)
    except ValueError as ex:
        _bad_request(ex)
    return _xlsx_response(content, f"온라인가격수집_{dt}.xlsx")


class TableExport(BaseModel):
    title: str = "조회결과"
    columns: list[dict]
    rows: list[dict]


@app.post("/api/export/table")
def export_table(body: TableExport):
    cols = [(c["key"], c.get("label", c["key"])) for c in body.columns if "key" in c]
    content = ds.write_xlsx("조회결과", cols, body.rows)
    safe = "".join(ch for ch in body.title if ch not in '\\/:*?"<>|').strip() or "조회결과"
    return _xlsx_response(content, f"{safe}.xlsx")


class ChatRequest(BaseModel):
    message: str
    sessionId: str | None = None
    context: dict | None = None


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="메시지가 비어 있습니다.")
    return StreamingResponse(
        stream_chat(req.sessionId, req.message.strip(), req.context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/chat/{session_id}")
def chat_reset(session_id: str):
    sessions.reset(session_id)
    return {"ok": True}


# 프론트 빌드 결과(frontend/dist)가 있으면 같은 포트에서 함께 서비스 (로컬 배포용)
DIST = config.ROOT_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
