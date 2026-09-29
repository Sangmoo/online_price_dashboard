"""Claude 대화형 데이터 어시스턴트 (도구 호출 + 스트리밍 + 사용자별 대화 기록/사용량 한도)."""
from __future__ import annotations

import json
import time
import uuid
from datetime import date
from typing import Iterator

import anthropic

from . import config, logs, store, usage, userdb

_log = logs.get("ai")
from .chat_tools import TOOL_LABELS, ToolInputError, data_scopes, run_tool, tools_for

MAX_TOOL_ROUNDS = 10
MAX_ATTEMPTS = 3  # 서버 혼잡(overloaded) 등 일시 오류 재시도 횟수
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """당신은 사내 웹 서비스 'ERP 영업 관리'의 데이터 분석 어시스턴트입니다.
이 서비스의 세 가지 데이터만 다루며, 각 데이터는 전용 조회 도구로만 조회할 수 있습니다.

[A] 온라인 가격 (메뉴: 대시보드, 일자별 상세) — 도구: list_collection_dates, aggregate_prices, search_price_rows
원천: T_SELECT_ONLINE_MNG_R (온라인 쇼핑몰별 상품 가격 수집 결과)
- DT(수집일, YYYYMMDD), PRDT_CD(상품코드), PRICE(기준가), DC_PRICE(사이트_할인가)
- 할인율(%) = (기준가 - 사이트_할인가) / 기준가 * 100  (도구 결과의 DC_RATE)
- MALL_NM(사이트명), RMK(매장정보: 모델번호/업체명/판매자 등), TITLE(사이트 상품명), INS_DAY(수집시간), NAVER_PAY_SELL_NO(판매자ID)
- 한 번의 조회 기간은 최대 31일입니다.

[B] 매장 재고 실사계획 (메뉴: 데이터 관리 > 매장 재고 실사계획) — 도구: aggregate_invt_plans, search_invt_plans
원천: T_SHOP_INVT_PLAN (매장별 재고 실사 계획. 삭제된 계획은 제외됨)
- 매장코드·브랜드·유통·매장명, 전년/당년 매출(백만원)·증감율, 주소·지역(시도)·권역
- 최종실사일, 전실사유형(교체/정기/오픈/폐점)·전실사결과, 경과일(최종실사일부터 오늘까지 일수), 재고 수량(등록일 기준)
- 실사예정(메모), 업체 예상 비용(기본료·실사예상액, 원), 실사예정일(비어 있으면 '미정'), 비고, 연2회 실사 매장 여부
- 관리등급, 정산 팀구분(1팀/2팀/미지정), 매니저 성함·전화번호, 매장번호

[C] 월별 매장별 판매 집계 (메뉴: 판매 분석 > 월별 매장별 판매 집계) — 도구: aggregate_sales, search_sales
원천: T_CLOSE_SALE_BASE (마감 매출 기초 데이터. 한 행 = 판매년월·매장·상품·색상·사이즈 단위 판매)
- MAKE_YYMM(판매년월), 팀, 매장코드·매장명, 기획년도, 시즌(봄/봄기획/여름/여름기획/가을/가을기획/겨울/겨울기획)
- 품군, 아이템, 수수료구분, 판매형태(정상/세일 등), 상품·색상·사이즈, 생산형태, 상품구분, 악세사리·온라인 판매 구분
- 수량, 최초가, 판매단가, 실판단가, 실판금액(원), 할인금액(원), 제조원가(V+, 단가)
- 판매년월 기간(ym_from~ym_to)은 반드시 지정하며 최대 36개월입니다. 반품은 수량·금액이 음수로 들어 있을 수 있습니다.
- 매출은 '실판금액 합계'를 기준으로 합니다. 할인율·원가율처럼 도구에 없는 비율은 반환된 합계로 계산하고 계산식을 밝힙니다.

답변 원칙:
1. 반드시 도구로 조회한 결과만 근거로 답합니다. 일반 지식, 추측, 외부 정보로 수치를 만들지 않습니다.
2. 이 서비스의 데이터(A, B, C)와 무관한 질문(일반 상식, 코딩, 다른 업무 시스템 등)에는 답하지 말고, 이 서비스 데이터로 가능한 분석을 짧게 제안합니다.
3. 대화마다 [화면 컨텍스트]로 오늘 날짜, 사용자가 보고 있는 화면, 사용자가 조회 권한을 가진 데이터가 주어집니다.
   권한이 없는 데이터는 조회할 수 없으며, 요청받으면 해당 메뉴 권한이 필요하다고 안내합니다.
4. 질문이 어느 데이터에 관한 것인지 불분명하면 사용자가 보고 있는 화면의 데이터를 우선합니다.
5. 날짜가 명시되지 않으면 화면의 조회 조건을 쓰고, 그것도 없으면 온라인 가격은 가장 최근 수집일, 실사계획은 전체, 판매 집계는 지난달을 대상으로 합니다.
6. 사용한 조회 조건(기간·필터)을 답변에 명확히 밝힙니다.
7. 한국어로 간결하게 답하고, 여러 항목 비교는 마크다운 표로 정리합니다. 금액은 천 단위 콤마와 '원'(매출은 '백만원')을 붙입니다.
8. 사이트·상품별 순위를 비교할 때는 표본이 너무 적은 그룹을 min_rows 로 제외할지 판단하고, 그 기준을 밝힙니다.
9. 조회한 표는 화면에 별도로 표시되어 엑셀 다운로드와 차트 보기가 가능하므로, 긴 목록은 핵심 상위 항목만 본문에 요약합니다.
"""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # ANTHROPIC_API_KEY 는 .env 에서 로드됨


# ----------------------------------------------------------------------------
# 대화 기록 (사용자별 SQLite 저장)
# ----------------------------------------------------------------------------
def list_conversations(usr_id: str) -> list[dict]:
    return store.rows(
        "SELECT id, title, created_at AS createdAt, updated_at AS updatedAt FROM conversations "
        "WHERE usr_id=? ORDER BY updated_at DESC LIMIT 100",
        (usr_id,),
    )


def get_conversation(usr_id: str, conv_id: str) -> dict | None:
    r = store.row("SELECT id, title, display, updated_at FROM conversations WHERE id=? AND usr_id=?", (conv_id, usr_id))
    if not r:
        return None
    return {"id": r["id"], "title": r["title"], "messages": json.loads(r["display"]), "updatedAt": r["updated_at"]}


def delete_conversation(usr_id: str, conv_id: str) -> None:
    store.execute("DELETE FROM conversations WHERE id=? AND usr_id=?", (conv_id, usr_id))


def rename_conversation(usr_id: str, conv_id: str, title: str) -> None:
    store.execute("UPDATE conversations SET title=? WHERE id=? AND usr_id=?", (title.strip()[:80], conv_id, usr_id))


def _load_or_create(usr_id: str, conv_id: str | None, first_text: str) -> tuple[str, str, list, list]:
    if conv_id:
        r = store.row("SELECT * FROM conversations WHERE id=? AND usr_id=?", (conv_id, usr_id))
        if r:
            return r["id"], r["title"], json.loads(r["api_messages"]), json.loads(r["display"])
    new_id = uuid.uuid4().hex
    title = " ".join(first_text.split())[:40]
    store.execute("INSERT INTO conversations(id, usr_id, title) VALUES(?,?,?)", (new_id, usr_id, title))
    return new_id, title, [], []


def _save(conv_id: str, api_messages: list, display: list) -> None:
    store.execute(
        "UPDATE conversations SET api_messages=?, display=?, updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(api_messages, ensure_ascii=False, default=str),
         json.dumps(display, ensure_ascii=False, default=str), conv_id),
    )


# ----------------------------------------------------------------------------
# 스트리밍 대화
# ----------------------------------------------------------------------------
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _context_text(ctx: dict | None, me: dict) -> str:
    sc = data_scopes(me)
    allowed = [n for n, ok in (("온라인 가격(A)", sc["price"]), ("매장 재고 실사계획(B)", sc["invt"]),
                               ("월별 매장별 판매 집계(C)", sc["sale"])) if ok]
    parts = [f"오늘 날짜: {date.today():%Y%m%d}", f"조회 권한이 있는 데이터: {', '.join(allowed) or '없음'}"]
    if ctx:
        view = ctx.get("view")
        if view == "dashboard" and ctx.get("start") and ctx.get("end"):
            parts.append(f"보고 있는 화면: 온라인 가격 대시보드, 기간 {ctx['start']} ~ {ctx['end']}")
        elif view == "detail" and ctx.get("dt"):
            parts.append(f"보고 있는 화면: 온라인 가격 일자별 상세, 수집일 {ctx['dt']}")
        elif view == "invt_plan":
            cond = []
            if ctx.get("lastFrom") or ctx.get("lastTo"):
                cond.append(f"최종실사일 {ctx.get('lastFrom', '')}~{ctx.get('lastTo', '')}")
            if ctx.get("planFilter") in ("set", "unset"):
                cond.append("실사예정일 " + ("확정" if ctx["planFilter"] == "set" else "미정"))
            if ctx.get("twiceOnly") == "Y":
                cond.append("연2회 매장만")
            if ctx.get("q"):
                cond.append(f"검색어 '{ctx['q']}'")
            parts.append("보고 있는 화면: 매장 재고 실사계획" + (f" (조건: {', '.join(cond)})" if cond else " (조건 없음)"))
        elif view == "sale_monthly" and ctx.get("ymFrom"):
            cond = [f"판매년월 {ctx['ymFrom'].replace('-', '')}~{ctx.get('ymTo', '').replace('-', '')}"]
            if ctx.get("shops"):
                cond.append(f"매장코드 {ctx['shops']}")
            if ctx.get("planYys"):
                cond.append(f"기획년도 {ctx['planYys']}")
            if ctx.get("seasons"):
                cond.append(f"시즌 {ctx['seasons']}")
            parts.append("보고 있는 화면: 월별 매장별 판매 집계 (조건: " + ", ".join(cond) + ")")
        elif view == "admin":
            parts.append("보고 있는 화면: 관리자")
    return "[화면 컨텍스트] " + " / ".join(parts)


class _Display:
    """스트림 이벤트를 화면 표시용 구조로 누적 (대화 기록 복원용, 프론트 로직과 동일)."""

    def __init__(self, parts: list):
        self.parts = parts

    def apply(self, e: dict) -> None:
        t = e["type"]
        if t == "text_start":
            self.parts.append({"kind": "text", "text": ""})
        elif t == "text":
            if self.parts and self.parts[-1]["kind"] == "text":
                self.parts[-1]["text"] += e["text"]
            else:
                self.parts.append({"kind": "text", "text": e["text"]})
        elif t == "tool":
            self.parts.append({"kind": "tool", "id": e["id"], "label": e["label"], "status": "running"})
        elif t == "tool_done":
            for p in self.parts:
                if p["kind"] == "tool" and p["id"] == e["id"]:
                    p["status"] = "ok" if e["ok"] else "fail"
        elif t == "table":
            self.parts.append({"kind": "table", **{k: v for k, v in e.items() if k != "type"}})
        elif t in ("notice", "error"):
            self.parts.append({"kind": "notice", "text": e["message"], "error": t == "error"})


def _retryable(ex: Exception) -> bool:
    if isinstance(ex, anthropic.APIConnectionError):
        return True
    if isinstance(ex, anthropic.APIStatusError):
        return ex.status_code in (429, 500, 502, 503, 504, 529) or "overloaded" in str(ex).lower()
    return False


def _friendly(ex: Exception) -> str:
    if isinstance(ex, anthropic.AuthenticationError):
        return "Claude API 키 인증에 실패했습니다. 관리자에게 문의하세요."
    if isinstance(ex, anthropic.RateLimitError):
        return "요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."
    if isinstance(ex, anthropic.APIConnectionError):
        return "Claude API 에 연결할 수 없습니다. 네트워크를 확인하세요."
    if "overloaded" in str(ex).lower():
        return "Claude 서버가 일시적으로 혼잡합니다. 잠시 후 다시 시도해 주세요."
    if isinstance(ex, anthropic.APIStatusError):
        return f"Claude API 오류 ({ex.status_code}): {ex.message}"
    return f"오류가 발생했습니다: {ex}"


def _stream_round(client: anthropic.Anthropic, kwargs: dict, emit):
    """모델 호출 1회(스트리밍). 텍스트가 나가기 전의 일시 오류는 재시도. 최종 메시지를 반환."""
    for attempt in range(MAX_ATTEMPTS):
        sent_text = False
        try:
            with client.beta.messages.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        sent_text = True
                        yield emit({"type": "text", "text": event.delta.text})
                    elif event.type == "content_block_start" and event.content_block.type == "text":
                        yield emit({"type": "text_start"})
                return stream.get_final_message()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as ex:
            if sent_text or attempt == MAX_ATTEMPTS - 1 or not _retryable(ex):
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def stream_chat(me: dict, conv_id: str | None, text: str, ctx: dict | None) -> Iterator[str]:
    usr_id = me["id"]
    blocked = usage.check_can_ask(me)
    tools = tools_for(me)
    if not blocked and not tools:
        blocked = "AI가 조회할 수 있는 메뉴 권한이 없습니다. 관리자에게 메뉴 권한을 요청하세요."
    if blocked:
        _log.info("질문 차단 user=%s 사유=%s", usr_id, blocked)
        yield _sse({"type": "error", "message": blocked, "code": "LIMIT"})
        yield _sse({"type": "usage", **usage.usage_summary(me)})
        yield _sse({"type": "done"})
        return

    conv_id, title, messages, display = _load_or_create(usr_id, conv_id, text)
    yield _sse({"type": "conversation", "id": conv_id, "title": title})
    question_id = usage.record_question(usr_id, conv_id)
    answered = False

    settings = userdb.get_settings()
    model = settings.get("model") or config.ANTHROPIC_MODEL
    effort = settings.get("effort") or config.ANTHROPIC_EFFORT
    cost_limit = me["ai"]["dailyCostUsd"]

    checkpoint = len(messages)
    display.append({"role": "user", "text": text})
    assistant: dict = {"role": "assistant", "parts": []}
    display.append(assistant)
    view = _Display(assistant["parts"])

    def emit(event: dict) -> str:
        view.apply(event)
        return _sse(event)

    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": _context_text(ctx, me)},
            {"type": "text", "text": text},
        ],
    })
    _save(conv_id, messages, display)  # 질문 즉시 기록 (중간에 연결이 끊겨도 남도록)

    client = _client()
    started = time.perf_counter()
    cost_before = usage.today_usage(usr_id)["costUsd"]
    _log.info("질문 user=%s conv=%s model=%s effort=%s view=%s len=%d", usr_id, conv_id, model, effort,
              (ctx or {}).get("view", "-"), len(text))
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            final = yield from _stream_round(client, dict(
                model=model,
                max_tokens=16000,
                system=[{"type": "text", "text": SYSTEM_PROMPT}],
                tools=tools,
                messages=messages,
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ), emit)
            answered = True

            usage.record_call(usr_id, conv_id, final.model, final.usage)
            messages.append({"role": "assistant", "content": [b.to_dict() for b in final.content]})

            if final.stop_reason == "refusal":
                yield emit({"type": "error", "message": "요청이 안전 정책에 의해 거절되었습니다. 질문을 바꿔서 다시 시도해 주세요."})
                break
            if final.stop_reason == "max_tokens":
                yield emit({"type": "notice", "message": "답변이 길어 일부가 잘렸습니다. 범위를 좁혀 다시 질문해 주세요."})
                break
            if final.stop_reason != "tool_use":
                break
            _save(conv_id, messages[:-1], display)  # tool_result 전까지는 직전 완결 상태로 저장

            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                yield emit({"type": "tool", "id": block.id, "name": block.name,
                            "label": TOOL_LABELS.get(block.name, block.name), "input": block.input})
                t0 = time.perf_counter()
                try:
                    out = run_tool(block.name, block.input, me)
                    _log.info("도구 %s user=%s %.1fs 입력=%s", block.name, usr_id, time.perf_counter() - t0,
                              json.dumps(block.input, ensure_ascii=False, default=str)[:500])
                    content, is_error = json.dumps(out["result"], ensure_ascii=False, default=str), False
                    if out.get("table") and out["table"]["rows"]:
                        yield emit({"type": "table", "id": block.id,
                                    "title": _table_title(block.name, block.input), **out["table"]})
                    yield emit({"type": "tool_done", "id": block.id, "ok": True})
                except ToolInputError as ex:
                    _log.info("도구 입력 오류 %s user=%s: %s", block.name, usr_id, ex)
                    content, is_error = f"입력 오류: {ex}", True
                    yield emit({"type": "tool_done", "id": block.id, "ok": False})
                except Exception as ex:  # DB 오류 등은 모델에 알려 재시도/안내하게 함
                    _log.exception("도구 실패 %s user=%s 입력=%s", block.name, usr_id,
                                   json.dumps(block.input, ensure_ascii=False, default=str)[:500])
                    content, is_error = f"조회 실패: {ex}", True
                    yield emit({"type": "tool_done", "id": block.id, "ok": False})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
            _save(conv_id, messages, display)

            # 도구 루프 도중 일일 비용 한도에 도달하면 중단
            if usage.today_usage(usr_id)["costUsd"] >= cost_limit:
                yield emit({"type": "notice",
                            "message": f"오늘 AI 사용 비용 한도(${cost_limit:.2f})에 도달해 답변을 중단했습니다."})
                break
        else:
            yield emit({"type": "notice", "message": "조회 단계가 너무 많아 중단했습니다. 질문을 나눠서 해 주세요."})
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as ex:
        _log.error("Claude API 오류 user=%s conv=%s answered=%s: %s", usr_id, conv_id, answered, str(ex)[:300])
        del messages[checkpoint:]
        if not answered:  # 답변을 전혀 받지 못한 질문은 일일 질문 수에서 제외
            usage.cancel_question(question_id)
        yield emit({"type": "error", "message": _friendly(ex)})
    finally:
        # 중간에 끊겨 tool_use 에 대응하는 tool_result 가 없으면 다음 요청이 400 이 되므로 제거
        last = messages[-1] if messages else None
        if last and last["role"] == "assistant" and any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in last["content"]
        ):
            messages.pop()
        _save(conv_id, messages, display)
        _log.info("답변 완료 user=%s conv=%s %.1fs 비용=$%.4f answered=%s", usr_id, conv_id, time.perf_counter() - started,
                  usage.today_usage(usr_id)["costUsd"] - cost_before, answered)

    yield _sse({"type": "usage", **usage.usage_summary(me)})
    yield _sse({"type": "done"})


def _table_title(name: str, inp: dict) -> str:
    if name in ("aggregate_invt_plans", "search_invt_plans"):
        cond = [f"{k}={v}" for k, v in inp.items()
                if k not in ("group_by", "order_by", "order_dir", "limit") and v not in (None, "")]
        cond_s = f" · {', '.join(cond)}" if cond else ""
        if name == "aggregate_invt_plans":
            gb = ", ".join(inp.get("group_by") or []) or "전체"
            return f"실사계획 집계 ({gb}){cond_s}"
        return f"실사계획 검색{cond_s}"
    if name in ("aggregate_sales", "search_sales"):
        cond = [f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in inp.items()
                if k not in ("ym_from", "ym_to", "group_by", "order_by", "order_dir", "limit") and v not in (None, "", [])]
        cond_s = f" · {', '.join(cond)}" if cond else ""
        rng = f"{inp.get('ym_from', '')}~{inp.get('ym_to', '')}"
        if name == "aggregate_sales":
            gb = ", ".join(inp.get("group_by") or []) or "전체"
            return f"판매 집계 ({gb}) · {rng}{cond_s}"
        return f"판매 행 검색 · {rng}{cond_s}"
    rng = f"{inp.get('date_from', '')}~{inp.get('date_to', '')}"
    if name == "aggregate_prices":
        gb = ", ".join(inp.get("group_by") or []) or "전체"
        return f"집계 ({gb}) · {rng}"
    return f"원본 검색 · {rng}"
