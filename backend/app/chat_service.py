"""Claude 대화형 데이터 어시스턴트 (도구 호출 + 스트리밍)."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import date
from typing import Iterator

import anthropic

from . import config
from .chat_tools import TOOL_LABELS, TOOLS, ToolInputError, run_tool

MAX_TOOL_ROUNDS = 10
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """당신은 온라인 가격 수집 데이터 분석 어시스턴트입니다.

데이터 원천: Oracle 테이블 T_SELECT_ONLINE_MNG_R (온라인 쇼핑몰별 상품 가격 수집 결과)
컬럼 의미:
- ONLINE_ID: 수집 작업 ID
- DT(수집일, YYYYMMDD), PRDT_CD(상품코드), PRICE(기준가), DC_PRICE(사이트_할인가)
- 할인율(%) = (기준가 - 사이트_할인가) / 기준가 * 100  (도구 결과의 DC_RATE)
- URL(상품 페이지), MALL_NM(사이트명), RMK(매장정보: 모델번호/업체명/판매자 등), TITLE(사이트 상품명)
- INS_DAY(수집시간, YYYYMMDDHHMI), NAVER_PAY_SELL_NO(판매자ID)

답변 원칙:
1. 반드시 제공된 도구로 조회한 이 데이터만 근거로 답합니다. 일반 지식, 추측, 외부 정보로 수치를 만들지 않습니다.
2. 데이터로 답할 수 없는 질문(이 데이터와 무관한 주제 포함)은 이 데이터로는 답할 수 없다고 짧게 안내하고, 대신 가능한 분석을 제안합니다.
3. 날짜가 명시되지 않으면 사용자가 보고 있는 화면의 기간을 쓰고, 그것도 없으면 가장 최근 수집일을 사용합니다. 한 번의 조회 기간은 최대 31일입니다.
4. 사용한 조회 기간과 조건을 답변에 명확히 밝힙니다.
5. 한국어로 간결하게 답하고, 여러 항목 비교는 마크다운 표로 정리합니다. 금액은 천 단위 콤마와 '원'을 붙입니다.
6. 사이트·상품별 순위를 비교할 때는 표본이 너무 적은 그룹을 min_rows 로 제외할지 판단하고, 그 기준을 밝힙니다.
7. 조회한 표는 화면에 별도로 표시되어 엑셀로 내려받을 수 있으므로, 긴 목록은 핵심 상위 항목만 본문에 요약합니다.
"""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # ANTHROPIC_API_KEY 는 .env 에서 로드됨


class _Sessions:
    def __init__(self):
        self._data: dict[str, list] = {}
        self._lock = threading.Lock()

    def get(self, sid: str | None) -> tuple[str, list]:
        with self._lock:
            if not sid or sid not in self._data:
                sid = sid or uuid.uuid4().hex
                self._data[sid] = []
                if len(self._data) > 200:  # 오래된 세션 정리
                    self._data.pop(next(iter(self._data)))
            return sid, self._data[sid]

    def reset(self, sid: str):
        with self._lock:
            self._data.pop(sid, None)


sessions = _Sessions()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _context_text(ctx: dict | None) -> str:
    parts = [f"오늘 날짜: {date.today():%Y%m%d}"]
    if ctx:
        if ctx.get("view") == "dashboard" and ctx.get("start") and ctx.get("end"):
            parts.append(f"사용자가 보고 있는 화면: 대시보드, 기간 {ctx['start']} ~ {ctx['end']}")
        elif ctx.get("view") == "detail" and ctx.get("dt"):
            parts.append(f"사용자가 보고 있는 화면: 일자별 상세, 수집일 {ctx['dt']}")
    return "[화면 컨텍스트] " + " / ".join(parts)


def stream_chat(session_id: str | None, text: str, ctx: dict | None) -> Iterator[str]:
    sid, messages = sessions.get(session_id)
    checkpoint = len(messages)
    yield _sse({"type": "session", "sessionId": sid})

    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": _context_text(ctx)},
            {"type": "text", "text": text},
        ],
    })

    client = _client()
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            with client.beta.messages.stream(
                model=config.ANTHROPIC_MODEL,
                max_tokens=16000,
                system=[{"type": "text", "text": SYSTEM_PROMPT}],
                tools=TOOLS,
                messages=messages,
                output_config={"effort": config.ANTHROPIC_EFFORT},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield _sse({"type": "text", "text": event.delta.text})
                    elif event.type == "content_block_start" and event.content_block.type == "text":
                        yield _sse({"type": "text_start"})
                final = stream.get_final_message()

            messages.append({"role": "assistant", "content": [b.to_dict() for b in final.content]})

            if final.stop_reason == "refusal":
                yield _sse({"type": "error", "message": "요청이 안전 정책에 의해 거절되었습니다. 질문을 바꿔서 다시 시도해 주세요."})
                break
            if final.stop_reason == "max_tokens":
                yield _sse({"type": "notice", "message": "답변이 길어 일부가 잘렸습니다. 범위를 좁혀 다시 질문해 주세요."})
                break
            if final.stop_reason != "tool_use":
                break

            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                yield _sse({"type": "tool", "id": block.id, "name": block.name,
                            "label": TOOL_LABELS.get(block.name, block.name), "input": block.input})
                try:
                    out = run_tool(block.name, block.input)
                    content, is_error = json.dumps(out["result"], ensure_ascii=False, default=str), False
                    if out.get("table") and out["table"]["rows"]:
                        yield _sse({"type": "table", "id": block.id,
                                    "title": _table_title(block.name, block.input), **out["table"]})
                    yield _sse({"type": "tool_done", "id": block.id, "ok": True})
                except ToolInputError as ex:
                    content, is_error = f"입력 오류: {ex}", True
                    yield _sse({"type": "tool_done", "id": block.id, "ok": False})
                except Exception as ex:  # DB 오류 등은 모델에 알려 재시도/안내하게 함
                    content, is_error = f"조회 실패: {ex}", True
                    yield _sse({"type": "tool_done", "id": block.id, "ok": False})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        else:
            yield _sse({"type": "notice", "message": "조회 단계가 너무 많아 중단했습니다. 질문을 나눠서 해 주세요."})
    except anthropic.AuthenticationError:
        del messages[checkpoint:]
        yield _sse({"type": "error", "message": "Claude API 키 인증에 실패했습니다. .env 의 ANTHROPIC_API_KEY 를 확인하세요."})
    except anthropic.RateLimitError:
        del messages[checkpoint:]
        yield _sse({"type": "error", "message": "요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."})
    except anthropic.APIStatusError as ex:
        del messages[checkpoint:]
        yield _sse({"type": "error", "message": f"Claude API 오류 ({ex.status_code}): {ex.message}"})
    except anthropic.APIConnectionError:
        del messages[checkpoint:]
        yield _sse({"type": "error", "message": "Claude API 에 연결할 수 없습니다. 네트워크를 확인하세요."})
    yield _sse({"type": "done"})


def _table_title(name: str, inp: dict) -> str:
    rng = f"{inp.get('date_from', '')}~{inp.get('date_to', '')}"
    if name == "aggregate_prices":
        gb = ", ".join(inp.get("group_by") or []) or "전체"
        return f"집계 ({gb}) · {rng}"
    return f"원본 검색 · {rng}"
