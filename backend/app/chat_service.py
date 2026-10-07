"""Claude 대화형 데이터 어시스턴트 (도구 호출 + 스트리밍 + 사용자별 대화 기록/사용량 한도)."""
from __future__ import annotations

import json
import time
import uuid
from datetime import date
from typing import Iterator

import anthropic

from . import appdb, config, logs, model_router, tool_limits, usage, userdb

_log = logs.get("ai")
from .chat_tools import BUILTIN_NAMES, ToolInputError, data_scopes, run_tool, tool_label, tools_for

MAX_TOOL_ROUNDS = 10
MAX_ATTEMPTS = 3  # 서버 혼잡(overloaded) 등 일시 오류 재시도 횟수
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """당신은 사내 웹 서비스 'ERP 영업 관리'의 데이터 분석 어시스턴트입니다.
이 서비스의 데이터만 다루며, 각 데이터는 전용 조회 도구로만 조회할 수 있습니다.

[A] 온라인 가격 (메뉴: 대시보드, 일자별 상세) — 도구: list_collection_dates, aggregate_prices, search_price_rows
원천: T_SELECT_ONLINE_MNG_R (온라인 쇼핑몰별 상품 가격 수집 결과)
- DT(수집일, YYYYMMDD), PRDT_CD(상품코드), PRICE(기준가), DC_PRICE(사이트_할인가)
- 할인율(%) = (기준가 - 사이트_할인가) / 기준가 * 100  (도구 결과의 DC_RATE)
- MALL_NM(사이트명), RMK(매장정보: 모델번호/업체명/판매자 등), TITLE(사이트 상품명), INS_DAY(수집시간), NAVER_PAY_SELL_NO(판매자ID)
- SHOP_ID(매장코드): 판매처 매장 연결(사이트·판매자번호·브랜드 → 매장코드)로 수집 시 채워짐. 비어 있으면 아직 연결 전. 매장별 조회는 shop_ids, 매장별 집계는 group_by SHOP_ID
- 한 번의 조회 기간은 최대 31일입니다.

[B] 매장 재고 실사계획 (메뉴: 데이터 관리 > 매장 재고 실사계획) — 도구: aggregate_invt_plans, search_invt_plans
원천: T_SHOP_INVT_PLAN (매장별 재고 실사 계획. 삭제된 계획은 제외됨)
- 매장코드·브랜드·유통·매장명, 전년/당년 매출(백만원)·증감율, 주소·지역(시도)·권역
- 최종실사일, 전실사유형(교체/정기/오픈/폐점)·전실사결과, 경과일(최종실사일부터 오늘까지 일수), 재고 수량(등록일 기준)
- 실사예정(메모), 업체 예상 비용(기본료·실사예상액, 원), 실사예정일(비어 있으면 '미정'), 비고, 연2회 실사 매장 여부
- 관리등급, 정산 팀구분(1팀/2팀/미지정), 매니저 성함·전화번호, 매장번호

[C] 판매 (메뉴: 판매 분석 > 판매 현황, 월별 매장별 판매 집계) — 도구: get_sales_dashboard, sum_sales_shop_month, aggregate_sales, search_sales
원천: T_CLOSE_SALE_BASE (마감 매출 기초 데이터. 한 행 = 판매년월·매장·상품·색상·사이즈 단위 판매)
- '이번 달/지난달/특정 월·기간 판매 현황', 전년 동기·전월·직전 기간 대비, 연 누계, 목표 대비 달성률, 브랜드별·팀별 실적,
  매출 상위·성장·하락·목표 미달 매장, 원가율 요약은 get_sales_dashboard 를 먼저 씁니다. 판매 현황 화면과 같은 계산이라 숫자가
  화면과 일치합니다. 필요한 sections 만 요청하고, 기간(ym_from~ym)·비교 기준(compare)·브랜드(brand)는 질문에 맞게 줍니다.
  브랜드는 팀 이름에서 나옵니다(팀 쉬즈N팀 = 브랜드 쉬즈미스, 리스트N팀 = 리스트, 시스티나N팀 = 시스티나, 각 1~5팀). 브랜드명은 '쉬즈미스'로 씁니다. 성장·하락 순위는 비교 기간 월평균 1천만원 이상·폐점 제외 기준,
  목표는 매장별 판매목표(T_SHOP_SELL_MGOAL)를 매장의 판매 브랜드로 모은 값이고 달성률은 목표가 있는 매장 매출 기준임을 밝힙니다.
- 판매 현황 메뉴만 있는 사용자는 get_sales_dashboard 와 sum_sales_shop_month 만 쓸 수 있습니다(판매 행 조회는 월별 매장별 판매 집계 권한 필요).
- MAKE_YYMM(판매년월), 팀, 매장코드·매장명, 기획년도, 시즌(봄/봄기획/여름/여름기획/가을/가을기획/겨울/겨울기획)
- 품군, 아이템, 수수료구분, 판매형태(정상/세일 등), 상품·색상·사이즈, 생산형태, 상품구분, 악세사리·온라인 판매 구분
- 수량, 최초가, 판매단가, 실판단가, 실판금액(원), 할인금액(원), 제조원가(V+, 단가)
- 판매년월 기간(ym_from~ym_to)은 반드시 지정하며 최대 36개월입니다. 반품은 수량·금액이 음수로 들어 있을 수 있습니다.
- 월별·매장별·팀별 수량/실판금액/할인금액 합계처럼 판매년월·매장·팀만 쓰는 질문은 sum_sales_shop_month(사전 집계, 매우 빠름)를 먼저 씁니다.
- 베스트 상품·상품 순위, 아이템/품군 전년 비교, 판매형태(행사/정상/세일) 구성 질문은 get_sales_dashboard 의
  sections=products / items / sales_types 를 씁니다. 품번은 시즌마다 새로 나오므로 상품의 전년 비교는 아이템·품군 단위로 답합니다.
  시즌·기획년도·품군·아이템·판매형태 등이 조건이나 묶음에 들어가거나 상품 수·원가가 필요할 때만 aggregate_sales 를 씁니다.
- 시즌이 얼마나 팔렸는지·전년 같은 시즌 대비·진척률 질문은 get_season_progress 를 씁니다(화면의 시즌 판매 진척과 같은 계산,
  같은 시점 = 전년 같은 달까지 누적). 직접 누적을 계산하지 말고 도구 결과를 그대로 씁니다.
- 품번 하나의 온라인 가격과 매장 판매·많이 팔린 매장은 get_product_insight 한 번으로 조회합니다.
- 세일 비중이 브랜드 평균보다 높은 매장(할인 판매 의존 매장)은 find_sale_heavy_shops 를 씁니다.
- 잘 팔리는 상품의 온라인 할인 동향(온라인 할인율이 오른 상위 상품)은 find_online_discount_alerts 를 씁니다
  (판매 메뉴와 온라인 가격 메뉴 권한이 모두 있을 때만). 매장 판매 기간과 온라인 수집 기간(오늘 기준 최근 7일 vs 그 전 4주)이 다름을 밝힙니다.
- 매출은 '실판금액 합계'를 기준으로 합니다. 할인율·원가율처럼 도구에 없는 비율은 반환된 합계로 계산하고 계산식을 밝힙니다.

[E] 매장 정보 (판매·실사계획 메뉴 권한) — 도구: search_shops
- 매장의 브랜드·팀·담당 영업직원(사번·이름)·운영상태(정상/가폐점/폐점)·오픈일·폐점일. 기본은 영업 중 매장만입니다.
- '○○ 매장 담당자', '김○○ 담당 매장', '영업직원별 매장 수' 같은 질문에 쓰고, 담당자 기준 판매를 물으면
  search_shops 로 매장코드를 찾은 뒤 판매 도구(shop_ids)로 실적을 조회합니다.

[F] 판매처 매장 연결 (메뉴: 온라인 가격 > 판매처 매장 연결) — 도구: search_mall_shop_mappings, propose_mall_shop_mappings
- 온라인 가격 수집의 사이트(MALL_NM)·판매자번호·브랜드(품번 첫 글자 S/T/A, '*' = 공통)마다 매장코드를 연결한 표입니다.
  수집 프로그램이 이 연결로 T_SELECT_ONLINE_MNG_R.SHOP_ID 를 채웁니다. 온라인몰은 브랜드마다 매장코드가 다릅니다(예: 하프클럽 S51005/T51005/A51005).
- 연결을 등록·수정·해제해 달라는 요청은 propose_mall_shop_mappings 로 변경안을 만듭니다. 이 도구는 저장하지 않습니다.
  대화창에 [적용] 버튼이 있는 카드가 나가고 사용자가 눌러야 저장되므로, '아래 [적용]을 누르면 저장됩니다'라고 안내하고 저장했다고 말하지 않습니다.
  사이트명이 모호하거나 판매자번호가 여러 개면 먼저 search_mall_shop_mappings 로 확인하고, 경고(브랜드가 다른 매장 등)가 있으면 함께 알립니다.

[G] 재고 재배치 추천 (메뉴: 데이터 관리 > 재고 재배치 추천) — 도구: recommend_store_rt, recommend_wh_allocation, get_auto_rt_stats, check_auto_rt_settings, open_stock_rt_screen
- 매장 간 RT 추천(판매 후 품절 매장 ← 같은 RT 그룹의 안 팔리는 재고 매장)과 창고 → 매장 배분 추천(판매분 자동보충 규칙)을
  ERP 자동 RT · 판매분 자동보충과 같은 규칙으로 계산합니다. AI 는 조회 · 추천만 하며 ERP 에 RT · 배분의뢰를 등록하지 않는다고 밝힙니다 (등록은 화면에서 관리자가 [본사지시 RT 지시] · [배분의뢰 등록]으로).
- 기간은 최대 31일입니다. 매장 간 RT 는 기본 최근 7일 · 안 팔리는 매장 우선, 창고 배분은 기본 어제 하루 · 최근 자동보충 실행 조건입니다.
- 자동 RT 가 왜 실패하는지('지시가능매장없음')는 get_auto_rt_stats 와 recommend_store_rt 의 senderExcludedByRule 로 설명합니다.
  지정가능수 설정을 어느 매장에서 얼마나 바꿔야 하는지는 check_auto_rt_settings 로 답합니다 (설정 변경은 ERP 에서).
- 사용자가 '화면으로 보여줘 · 화면 열어줘'처럼 화면을 원하면 open_stock_rt_screen 으로 [화면에서 열기] 카드를 띄우고, 카드를 누르라고 안내합니다 (열었다고 말하지 않음).
- 계산에 10~40초 걸릴 수 있어, 같은 질문에서 조건을 바꿔 여러 번 부르지 말고 view · shop_id 로 필요한 부분만 봅니다.

[D] 관리자 정의 조회 도구 — 설명 끝에 '(관리자 정의 조회 도구 …)' 가 붙은 도구
- 관리자가 이 서비스 데이터 조회용으로 추가한 도구입니다. 도구 설명에 적힌 범위의 질문에 사용하고, 결과 컬럼명 그대로 해석하되 모호하면 그렇다고 밝힙니다.

답변 원칙:
1. 반드시 도구로 조회한 결과만 근거로 답합니다. 일반 지식, 추측, 외부 정보로 수치를 만들지 않습니다.
2. 이 서비스의 데이터(A, B, C, D, E, F, G)와 무관한 질문(일반 상식, 코딩, 다른 업무 시스템 등)에는 답하지 말고, 이 서비스 데이터로 가능한 분석을 짧게 제안합니다.
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
    return appdb.conv_list(usr_id)


def get_conversation(usr_id: str, conv_id: str) -> dict | None:
    r = appdb.conv_get(usr_id, conv_id)
    if not r:
        return None
    return {"id": r["id"], "title": r["title"], "messages": r["display"], "updatedAt": r["updated_at"]}


def delete_conversation(usr_id: str, conv_id: str) -> None:
    appdb.conv_delete(usr_id, conv_id)


def rename_conversation(usr_id: str, conv_id: str, title: str) -> None:
    appdb.conv_rename(usr_id, conv_id, title)


def _load_or_create(usr_id: str, conv_id: str | None, first_text: str) -> tuple[str, str, list, list]:
    if conv_id:
        r = appdb.conv_get(usr_id, conv_id)
        if r:
            return r["id"], r["title"], r["api_messages"], r["display"]
    new_id = uuid.uuid4().hex
    title = " ".join(first_text.split())[:40]
    appdb.conv_create(new_id, usr_id, title)
    return new_id, title, [], []


def _save(conv_id: str, api_messages: list, display: list) -> None:
    appdb.conv_save(conv_id, api_messages, display)


# ----------------------------------------------------------------------------
# 스트리밍 대화
# ----------------------------------------------------------------------------
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _context_text(ctx: dict | None, me: dict) -> str:
    sc = data_scopes(me)
    allowed = [n for n, ok in (("온라인 가격(A)", sc["price"]), ("매장 재고 실사계획(B)", sc["invt"]),
                               ("판매 현황(C)", sc["dash"] or sc["sale"]),
                               ("월별 매장별 판매 집계(C, 판매 행 조회 포함)", sc["sale"]), ("매장 정보·담당 영업직원(E)", sc["shop"]),
                               ("판매처 매장 연결(F)", sc["mall"]), ("재고 재배치 추천(G)", sc["stock"])) if ok]
    parts = [f"오늘 날짜: {date.today():%Y%m%d}", f"조회 권한이 있는 데이터: {', '.join(allowed) or '없음'}"]
    if (sc["dash"] or sc["sale"] or sc["stock"]) and me.get("brands"):
        parts.append(f"판매 데이터 브랜드 권한: {', '.join(me['brands'])} 만 조회됩니다 (도구 결과도 이 브랜드로만 계산됨). "
                     "전사·다른 브랜드 수치는 알 수 없다고 답하세요.")
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
        elif view == "sale_dashboard" and ctx.get("ym"):
            cond = [f"기간 {ctx.get('period') or ctx['ym']}", f"비교 {ctx.get('compare') or '전년 동기'}"]
            if ctx.get("brand"):
                cond.append(f"브랜드 {ctx['brand']}")
            parts.append("보고 있는 화면: 판매 현황 대시보드 (" + ", ".join(cond) + ")")
        elif view == "sale_monthly" and ctx.get("ymFrom"):
            cond = [f"판매년월 {ctx['ymFrom'].replace('-', '')}~{ctx.get('ymTo', '').replace('-', '')}"]
            if ctx.get("shops"):
                cond.append(f"매장코드 {ctx['shops']}")
            if ctx.get("planYys"):
                cond.append(f"기획년도 {ctx['planYys']}")
            if ctx.get("seasons"):
                cond.append(f"시즌 {ctx['seasons']}")
            parts.append("보고 있는 화면: 월별 매장별 판매 집계 (조건: " + ", ".join(cond) + ")")
        elif view == "stock_rt":
            tab = "창고 → 매장 배분" if ctx.get("tab") == "alloc" else "매장 간 RT"
            cond = [f"{k} {ctx[k]}" for k in ("brand", "period", "seasons", "prdt") if ctx.get(k)]
            parts.append(f"보고 있는 화면: 재고 재배치 추천 > {tab}" + (f" (조건: {', '.join(cond)})" if cond else ""))
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
            self.parts.append({"kind": "tool", "id": e["id"], "label": e["label"], "status": "running",
                               "name": e.get("name"), "input": e.get("input")})
        elif t == "tool_done":
            for p in self.parts:
                if p["kind"] == "tool" and p["id"] == e["id"]:
                    p["status"] = "ok" if e["ok"] else "fail"
        elif t == "table":
            self.parts.append({"kind": "table", **{k: v for k, v in e.items() if k != "type"}})
        elif t == "action":
            self.parts.append({"kind": "action", **{k: v for k, v in e.items() if k != "type"}})
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
    base_model = settings.get("model") or config.ANTHROPIC_MODEL
    base_effort = settings.get("effort") or config.ANTHROPIC_EFFORT
    # 모델 자동 선택(관리자 설정): 단순 조회는 저렴한 모델, 분석·판단은 기본 모델
    model, effort, route = model_router.choose(text, settings, base_model, base_effort)
    tool_errors = 0
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
    _log.info("질문 user=%s conv=%s model=%s effort=%s route=%s view=%s len=%d", usr_id, conv_id, model, effort, route,
              (ctx or {}).get("view", "-"), len(text))
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            def request(m: str, e: str) -> dict:
                return dict(model=m, max_tokens=16000, system=[{"type": "text", "text": SYSTEM_PROMPT}], tools=tools,
                            messages=messages, output_config={"effort": e}, cache_control={"type": "ephemeral"},
                            betas=[FALLBACK_BETA], fallbacks="default")

            try:
                final = yield from _stream_round(client, request(model, effort), emit)
            except anthropic.BadRequestError:
                # 자동 선택한 저렴한 모델이 요청을 받지 않으면(지원하지 않는 옵션 등) 기본 모델로 바로 다시
                if route != "simple" or model == base_model:
                    raise
                _log.warning("모델 전환 user=%s conv=%s %s 요청 거부 → %s", usr_id, conv_id, model, base_model, exc_info=True)
                model, effort, route = base_model, base_effort, "escalated"
                final = yield from _stream_round(client, request(model, effort), emit)
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
                            "label": tool_label(block.name), "input": block.input})
                t0 = time.perf_counter()
                try:
                    out = run_tool(block.name, block.input, me)
                    _log.info("도구 %s user=%s %.1fs 입력=%s", block.name, usr_id, time.perf_counter() - t0,
                              json.dumps(block.input, ensure_ascii=False, default=str)[:500])
                    content, is_error = json.dumps(out["result"], ensure_ascii=False, default=str), False
                    if out.get("table") and out["table"]["rows"]:
                        extra = {}
                        if block.name in FULL_EXPORT_TOOLS and _truncated(out):  # 잘린 표 → 화면에서 전체 결과 엑셀 가능
                            extra = {"truncated": True, "source": {"tool": block.name, "input": block.input}}
                        yield emit({"type": "table", "id": block.id,
                                    "title": _table_title(block.name, block.input), **out["table"], **extra})
                    if out.get("action"):  # 사용자 확인 후 저장하는 변경안 (예: 판매처 매장 연결) → 대화창에 [적용] 카드
                        yield emit({"type": "action", "id": block.id, **out["action"]})
                    yield emit({"type": "tool_done", "id": block.id, "ok": True})
                except ToolInputError as ex:
                    _log.info("도구 입력 오류 %s user=%s: %s", block.name, usr_id, ex)
                    tool_errors += 1
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

            # 저렴한 모델이 도구 입력을 거듭 틀리면 이 질문의 남은 과정은 기본 모델로
            if route == "simple" and model != base_model and tool_errors >= model_router.ESCALATE_AFTER_TOOL_ERRORS:
                _log.info("모델 전환 user=%s conv=%s %s → %s (도구 입력 오류 %d회)", usr_id, conv_id, model, base_model, tool_errors)
                model, effort, route = base_model, base_effort, "escalated"

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


# 행 수 제한(limit)이 있는 기본 조회 도구: AI 답변 표가 잘렸으면 같은 조건으로 전체(최대 10만 행)를 엑셀로 받을 수 있다
FULL_EXPORT_TOOLS = {"aggregate_prices", "search_price_rows", "aggregate_sales", "search_sales", "sum_sales_shop_month",
                     "aggregate_invt_plans", "search_invt_plans"}


def _truncated(out: dict) -> bool:
    t = out["table"]
    return bool(out["result"].get("truncated")) or int(t.get("totalMatched") or 0) > len(t["rows"])


def export_full(tool: str, inp: dict, me: dict) -> dict:
    """AI 답변 표의 전체 결과: 같은 도구·같은 조건을 행 수 상한만 늘려 다시 조회한다 (권한 확인은 run_tool 이 동일하게).
    반환: {"columns", "rows", "capped"(상한에 걸려 일부만인지)}"""
    if tool not in FULL_EXPORT_TOOLS or not isinstance(inp, dict):
        raise ToolInputError("전체 엑셀을 지원하지 않는 도구입니다.")
    t0 = time.perf_counter()
    with tool_limits.full_export() as n:
        out = run_tool(tool, {**inp, "limit": n}, me)
    table = out.get("table") or {"columns": [], "rows": []}
    capped = _truncated(out) if table["rows"] else False
    _log.info("AI 표 전체 엑셀 %s user=%s %d행 %.1fs", tool, me.get("id"), len(table["rows"]), time.perf_counter() - t0)
    return {"columns": table["columns"], "rows": table["rows"], "capped": capped, "max": n}


def _table_title(name: str, inp: dict) -> str:
    if name == "search_shops":
        cond = [f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in inp.items() if v not in (None, "", [], False)]
        return "매장 정보" + (f" · {', '.join(cond)}" if cond else "")
    if name in ("aggregate_invt_plans", "search_invt_plans"):
        cond = [f"{k}={v}" for k, v in inp.items()
                if k not in ("group_by", "order_by", "order_dir", "limit") and v not in (None, "")]
        cond_s = f" · {', '.join(cond)}" if cond else ""
        if name == "aggregate_invt_plans":
            gb = ", ".join(inp.get("group_by") or []) or "전체"
            return f"실사계획 집계 ({gb}){cond_s}"
        return f"실사계획 검색{cond_s}"
    if name == "get_sales_dashboard":
        ym = inp.get("ym") or "최근 마감 월"
        if inp.get("ym_from"):
            ym = f"{inp['ym_from']}~{ym}"
        secs = ", ".join(inp.get("sections") or []) or "요약"
        extra = [v for v in (inp.get("brand"), {"prev": "직전 기간 대비", "custom": "직접 선택 비교"}.get(inp.get("compare") or "")) if v]
        return f"판매 현황 · {ym}{' · ' + ', '.join(extra) if extra else ''} · {secs}"
    if name == "get_season_progress":
        s = f"{inp['plan_yy']} {inp['season']}" if inp.get("plan_yy") and inp.get("season") else "기본 시즌"
        return f"시즌 판매 진척 · {s} · {inp.get('ym') or '최근 마감 월'}{' · ' + inp['brand'] if inp.get('brand') else ''}"
    if name == "search_mall_shop_mappings":
        cond = [f"{k}={v}" for k, v in inp.items() if v not in (None, "")]
        return "판매처 매장 연결" + (f" · {', '.join(cond)}" if cond else "")
    if name == "propose_mall_shop_mappings":
        return f"판매처 매장 연결 변경안 · {len(inp.get('items') or [])}건 (적용 전)"
    if name == "find_sale_heavy_shops":
        return f"세일 비중 높은 매장 · {inp.get('ym') or '최근 마감 월'}{' · ' + inp['brand'] if inp.get('brand') else ''}"
    if name == "find_online_discount_alerts":
        ym = inp.get("ym") or "최근 마감 월"
        return f"온라인 할인 주의 상품 · 매장 {inp['ym_from'] + '~' if inp.get('ym_from') else ''}{ym}{' · ' + inp['brand'] if inp.get('brand') else ''}"
    if name in ("recommend_store_rt", "recommend_wh_allocation", "get_auto_rt_stats", "check_auto_rt_settings"):
        title = {"recommend_store_rt": "매장 간 RT 추천", "recommend_wh_allocation": "창고 → 매장 배분 추천", "get_auto_rt_stats": "자동 RT 현황",
                 "check_auto_rt_settings": "자동 RT 설정 점검"}[name]
        cond = [f"{k}={','.join(map(str, v)) if isinstance(v, list) else v}" for k, v in inp.items() if k not in ("limit",) and v not in (None, "", [])]
        return title + (f" · {', '.join(cond)}" if cond else "")
    if name == "get_product_insight":
        return f"상품 종합 · {inp.get('prdt_cd', '')}"
    if name in ("sum_sales_shop_month", "aggregate_sales", "search_sales"):
        cond = [f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in inp.items()
                if k not in ("ym_from", "ym_to", "group_by", "order_by", "order_dir", "limit") and v not in (None, "", [])]
        cond_s = f" · {', '.join(cond)}" if cond else ""
        rng = f"{inp.get('ym_from', '')}~{inp.get('ym_to', '')}"
        if name in ("aggregate_sales", "sum_sales_shop_month"):
            gb = ", ".join(inp.get("group_by") or []) or "전체"
            return f"{'판매 합계' if name == 'sum_sales_shop_month' else '판매 집계'} ({gb}) · {rng}{cond_s}"
        return f"판매 행 검색 · {rng}{cond_s}"
    if name not in BUILTIN_NAMES:  # 관리자 정의 도구
        args = ", ".join(f"{k}={v}" for k, v in inp.items() if v not in (None, ""))
        return f"{tool_label(name)}{' · ' + args if args else ''}"
    rng = f"{inp.get('date_from', '')}~{inp.get('date_to', '')}"
    if name == "aggregate_prices":
        gb = ", ".join(inp.get("group_by") or []) or "전체"
        return f"집계 ({gb}) · {rng}"
    return f"원본 검색 · {rng}"
