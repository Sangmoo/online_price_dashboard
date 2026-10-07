"""Claude 조회 도구: 재고 재배치 추천 메뉴와 같은 계산 (조회 · 추천만, ERP 에 등록하지 않음).

- recommend_store_rt: 매장 간 RT 추천 (stock_rt.recommend — 자동 RT 검색 규칙)
- recommend_wh_allocation: 창고 → 매장 배분 추천 (wh_alloc.recommend — 판매분 자동보충 규칙)
- get_auto_rt_stats: 자동 RT 요청 결과 현황 (완료 · 취소 · '지시가능매장없음')
- check_auto_rt_settings: 자동 RT 설정 점검 (보낼 수 있는데 지정가능수 0 · 부족한 매장과 권장값)
- pick_store_rt_rows: 매장 간 RT 추천에서 조건에 맞는 행을 골라 [화면에서 열고 선택] 카드 (관리자는 화면에서 확인 후 직접 지시)
- get_rt_performance: RT 성과 (본사지시 RT 수락 · 거부 · 미처리, 거부 사유, 받은 매장 7일 내 판매 전환)
- get_pending_rt: 매장이 아직 처리하지 않은 RT 요청 (처리할 매장별 · 경과 시간 · 본사지시 자동거부 임박)
- recommend_wh_return: 창고 회수 추천 (창고 부족 상품을 판매 없는 매장 재고에서 회수)
- get_aging_stock: 장기 미판매 재고 (매장 × 스타일, 미판매 일수 구간 · 매장별 · 스타일별)
- get_stock_turnover: 재고 회전 (재고일수 · 판매율 · 품절 위험 · 과다, 매장 · 팀 · 스타일별)
- get_initial_alloc_accuracy: 초도 배분 적중률 (초도 배분 대비 N일 판매 · 무판매 · 소진 · 적중률)
- open_stock_rt_screen: 대화로 화면 열기 — 조건을 정리해 대화창에 [화면에서 열기] 카드를 띄운다 (누르면 그 조건으로 화면을 열고 계산)
결과는 화면과 같은 캐시를 써서, 화면에서 본 조건이면 바로 돌려준다. 브랜드 데이터 권한(allowed)을 그대로 적용한다.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import stock_ctl as sc
from . import stock_rt, wh_alloc

_BRAND = {"type": "string", "description": "브랜드 하나: 쉬즈미스 · 리스트 · 시스티나 (또는 S · T · A). 생략 시 권한 있는 첫 브랜드"}
_FROM = {"type": "string", "description": "판매 기간 시작 YYYYMMDD (기간은 최대 31일)"}
_TO = {"type": "string", "description": "판매 기간 끝 YYYYMMDD"}
_SEASONS = {"type": "array", "items": {"type": "string"},
            "description": "시즌 이름 또는 코드 (봄 · 여름 · 가을 · 겨울 · 가을기획 · 겨울사입 … / C0073 …)"}
_TEAMS = {"type": "array", "items": {"type": "string"}, "description": "팀 이름 (예: 쉬즈1팀, 리스트3팀)"}
_VIEW = {"type": "string", "enum": ["summary", "rows", "unfilled", "shops"],
         "description": "summary=요약(기본) · rows=추천 행 · unfilled=못 채운 수요 · shops=많이 보내는/받는 매장"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "recommend_store_rt",
        "description": (
            "매장 간 RT(재고 이동) 추천을 '재고 재배치 추천 > 매장 간 RT' 화면과 같은 계산으로 조회합니다. "
            "'판매됐는데 재고 없는 매장에 어디서 보내면 돼?', '자동 RT 취소된 요청 채울 매장', '안 팔리는 재고 어디로 옮기면 좋아?' 같은 질문에 씁니다. "
            "받는 매장 = 기간(기본 최근 7일, 최대 31일) 판매가 있는데 지금 재고 0 이하인 매장×상품 + 기간 중 자동 RT 가 '지시가능매장없음'으로 취소된 요청. "
            "보내는 매장 = 같은 RT 그룹의 재고 매장 중 ERP 자동 RT 규칙(이동중 · 요청중 · 최소보유재고 뺀 남는 재고, 최초/최종 출고 경과일, 매장등급, "
            "수불제어 · 자동RT 제외 스타일, 오늘 같은 상품 지정)을 통과한 매장. 기본 순서는 기간 판매가 적은 매장부터(order=auto 면 자동 RT 순서). "
            "apply_auto_rt_limits=true 면 자동 RT 하루 지정가능수 · 요청가능수까지 적용합니다(지정가능수 0 매장이 많아 추천이 크게 줄어듦). "
            "추천일 뿐 ERP 에 RT 를 등록하지 않는다고 답에 밝히세요. 계산은 10~40초 걸릴 수 있습니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": _FROM, "date_to": _TO,
                "plan_yy": {"type": "array", "items": {"type": "string"}, "description": "기획년도 YYYY (생략 시 전체)"},
                "seasons": _SEASONS, "prdt_cd": {"type": "string", "description": "품번 (앞부분만 넣어도 됨)"},
                "teams": {**_TEAMS, "description": "받는 매장 팀 이름 (예: 쉬즈1팀)"},
                "per": {"type": "integer", "minimum": 1, "maximum": 3, "description": "받는 매장 상품당 수량 (기본 1)"},
                "order": {"type": "string", "enum": list(stock_rt.ORDERS), "description": "slow=안 팔리는 매장 우선(기본) · auto=자동 RT 순서"},
                "sender_max": {"type": "integer", "minimum": 0, "maximum": 1000, "description": "보내는 매장당 최대 수량 (0=제한 없음)"},
                "apply_auto_rt_limits": {"type": "boolean", "description": "자동 RT 하루 한도 적용 (기본 false)"},
                "shop_id": {"type": "string", "description": "이 매장이 보내거나 받는 행만 (매장코드)"},
                "view": _VIEW,
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "행 수 (기본 30)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "recommend_wh_allocation",
        "description": (
            "창고 → 매장 배분(판매분 자동보충) 추천을 '재고 재배치 추천 > 창고 → 매장 배분' 화면과 같은 계산으로 조회합니다. "
            "'어제 판매분 보충하면 어느 매장에 몇 장 가?', '이 품번 창고 재고로 판매분 채울 수 있어?', '보충 부족한 상품' 같은 질문에 씁니다. "
            "ERP 판매분 자동보충(SP_AUTO_DVID)과 같은 규칙: 판매보충기준(최소판매율 · 매장재고상한 · 창고재고하한)에 맞는 상품, "
            "창고 배분 가능 = 창고 재고 − 출고지시 미명세 − 미확정 배분의뢰 − 창고재고하한, 매장 순서 = 유통형태 · 판매율 · 매장등급, "
            "1차 완불 → 2차 일반 판매 수량만큼 매장재고상한까지. 기본 기간은 어제 하루(최대 31일). "
            "use_recent_run=true(기본)면 그 브랜드의 가장 최근 판매분 자동보충 실행 조건(창고 · 기준 · 등급 그룹 · 기획년도 · 시즌 · 팀 · 품군)을 쓰고, "
            "주어진 값만 바꿉니다. 오늘 이미 실행된 자동보충의 미확정 의뢰는 창고 가용에서 빠지므로 '추가로 더 보낼 수 있는 양'입니다. "
            "추천일 뿐 ERP 에 배분의뢰를 등록하지 않는다고 답에 밝히세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": _FROM, "date_to": _TO,
                "use_recent_run": {"type": "boolean", "description": "최근 자동보충 실행 조건으로 시작 (기본 true)"},
                "warehouse": {"type": "string", "description": "창고코드 (예: IN 이천정상창고)"},
                "base_id": {"type": "string", "description": "판매보충기준 ID"},
                "plan_yy": {"type": "array", "items": {"type": "string"}, "description": "기획년도 YYYY"},
                "seasons": _SEASONS, "teams": _TEAMS,
                "prdt_cd": {"type": "string", "description": "품번 (앞부분만 넣어도 됨)"},
                "rate": {"type": "number", "description": "배수 (판매 수량 × 배수, 기본 1)"},
                "shop_id": {"type": "string", "description": "이 매장 배분 행만"},
                "view": {"type": "string", "enum": ["summary", "rows", "skus", "short", "shops"],
                         "description": "summary=요약(기본) · rows=배분 행 · skus=상품별 · short=부족한 상품 · shops=많이 받는 매장"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "행 수 (기본 30)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "get_auto_rt_stats",
        "description": (
            "자동 RT 요청 결과 현황(T_AUTO_RT): 기간 · 브랜드의 요청 수, 결과별(완료 · 이동중 · 요청중 · 최종거부 · 취소) 건수, "
            "'지시가능매장없음'으로 취소된 비율, 일별 추이, 취소가 많은 매장 · 품번 상위 10. "
            "'자동 RT 얼마나 실패해?', '지시가능매장없음 많은 매장' 같은 질문에 씁니다. 기본 최근 7일, 최대 31일."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"brand": _BRAND, "date_from": _FROM, "date_to": _TO},
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "check_auto_rt_settings",
        "description": (
            "자동 RT 설정 점검: 매장 간 RT 추천(하루 한도 없이, 기본 최근 7일)에서 보낼 수 있는 매장마다 자동 RT 지정가능수(ASIGN_ABLE_QTY, 하루), "
            "기간 중 실제 지정 수, 이번 추천으로 보낼 수량, 자동 RT 취소('지시가능매장없음') 요청을 채울 수 있었던 수량, 권장 지정가능수를 보여 줍니다. "
            "권장 = 올림((기간 실제 지정 수 + 취소 요청 채움 수량) ÷ 기간 일수). '자동 RT 왜 실패해?', '지정가능수 어느 매장 바꿔야 해?', "
            "'자동 RT 설정 점검' 같은 질문에 씁니다. 지정가능수 0 매장은 재고가 있어도 자동 RT 보내는 매장으로 지정되지 않는 게 주된 실패 원인입니다. "
            "설정 변경은 ERP(T_SHOP_RT_GRP_DETL)에서 하며 이 도구는 바꾸지 않습니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": _FROM, "date_to": _TO,
                "only": {"type": "string", "enum": ["problem", "all"], "description": "problem=지정가능수 0 · 부족 매장만(기본) · all=전체"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "행 수 (기본 30)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "open_stock_rt_screen",
        "description": (
            "'재고 재배치 추천' 화면을 사용자가 말한 조건으로 열어 줍니다 ('리스트 겨울 니트 2주 RT 화면으로 보여줘', '쉬즈미스 창고 배분 화면 열어줘'). "
            "대화창에 [화면에서 열기] 카드가 나가고 사용자가 누르면 그 조건으로 화면이 열리고 계산까지 합니다. 열었다고 말하지 말고 카드를 누르라고 안내하세요. "
            "결과 숫자를 대화로 바로 알려 달라는 질문이면 recommend_store_rt · recommend_wh_allocation 을 쓰고, 화면으로 보고 싶다고 하면 이 도구를 씁니다. "
            "tab=rt(매장 간 RT, 기본) · alloc(창고 → 매장 배분). 품번 앞부분(prdt_cd)으로 아이템을 좁힐 수 있습니다(예: 니트는 품번 규칙을 모르면 생략하고 시즌만). "
            "기간을 말하지 않으면 화면 기본값(RT 최근 7일 · 배분 어제)을 씁니다. '2주'면 오늘 포함 14일."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tab": {"type": "string", "enum": ["rt", "alloc"], "description": "rt=매장 간 RT(기본) · alloc=창고 → 매장 배분"},
                "brand": _BRAND, "date_from": _FROM, "date_to": _TO,
                "plan_yy": {"type": "array", "items": {"type": "string"}, "description": "기획년도 YYYY"},
                "seasons": _SEASONS, "teams": _TEAMS, "prdt_cd": {"type": "string", "description": "품번 (앞부분만 넣어도 됨)"},
                "per": {"type": "integer", "minimum": 1, "maximum": 3, "description": "RT: 받는 상품당 수량"},
                "order": {"type": "string", "enum": list(stock_rt.ORDERS), "description": "RT: slow=안 팔리는 매장 우선 · auto=자동 RT 순서"},
                "apply_auto_rt_limits": {"type": "boolean", "description": "RT: 자동 RT 하루 한도 적용"},
                "warehouse": {"type": "string", "description": "배분: 창고코드"},
                "rate": {"type": "number", "description": "배분: 배수"},
                "view": {"type": "string", "enum": ["rows", "unfilled", "shops", "stats", "check", "short", "skus"],
                         "description": "처음 보여 줄 결과: RT=rows · unfilled · shops · stats(자동 RT 현황) · check(설정 점검) / 배분=rows · short(창고 부족) · skus · shops"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOLS += [
    {
        "name": "pick_store_rt_rows",
        "description": (
            "매장 간 RT 추천(recommend_store_rt 와 같은 계산) 중 사용자가 말한 기준에 맞는 행만 골라, 대화창에 [화면에서 열고 선택] 카드를 띄웁니다. "
            "'자동RT 취소 2회 이상, 판매 3장 이상인 것만 골라줘', '완불 대기만 골라줘', '쉬즈1팀 받는 매장만 골라줘' 같은 요청에 씁니다. "
            "카드를 누르면 화면이 같은 조건으로 열리고 그 행들이 선택(체크)됩니다. ERP 등록은 관리자가 화면에서 [본사지시 RT 지시]를 직접 눌러야 합니다 — "
            "등록했다고 말하지 말고, 고른 건수 · 수량과 기준을 알려 주세요. 기준: min_fail_cnt=받는 매장 자동RT 취소 횟수 이상, "
            "min_receiver_sales=받는 매장 기간 판매 이상, max_sender_sales=보내는 매장 기간 판매 이하, why=사유(자동RT 취소 · 완불 대기 · 판매 후 품절), "
            "from_shop_ids · to_shop_ids=매장코드, min_qty=행 수량 이상."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": _FROM, "date_to": _TO,
                "plan_yy": {"type": "array", "items": {"type": "string"}, "description": "기획년도 YYYY (생략 시 전체)"},
                "seasons": _SEASONS, "prdt_cd": {"type": "string", "description": "품번 (앞부분만 넣어도 됨)"},
                "teams": {**_TEAMS, "description": "받는 매장 팀 이름 (계산 조건)"},
                "per": {"type": "integer", "minimum": 1, "maximum": 3}, "order": {"type": "string", "enum": list(stock_rt.ORDERS)},
                "apply_auto_rt_limits": {"type": "boolean"},
                "min_fail_cnt": {"type": "integer", "minimum": 0, "description": "받는 매장 자동RT 취소 횟수 이상"},
                "min_receiver_sales": {"type": "integer", "minimum": 0, "description": "받는 매장 기간 판매 수량 이상"},
                "max_sender_sales": {"type": "integer", "minimum": 0, "description": "보내는 매장 기간 판매 수량 이하"},
                "why": {"type": "array", "items": {"type": "string", "enum": ["자동RT 취소", "완불 대기", "판매 후 품절"]}, "description": "추천 사유"},
                "from_shop_ids": {"type": "array", "items": {"type": "string"}, "description": "보내는 매장코드"},
                "to_shop_ids": {"type": "array", "items": {"type": "string"}, "description": "받는 매장코드"},
                "min_qty": {"type": "integer", "minimum": 1, "description": "행 수량 이상"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "get_rt_performance",
        "description": (
            "RT 성과: 지시일 기간(기본 최근 14일, 최대 31일)의 본사지시 RT 가 매장에서 어떻게 처리됐는지 — 수락 · 거부 · 3일 무응답 자동거부 · 미처리 · 취소 수량, "
            "수락률, 평균 처리 시간(확정→매장 처리), 거부 사유, 받은 매장이 수락 후 7일 안에 그 상품을 판매한 비율(판매 전환). "
            "scope=web(이 화면에서 지시한 것, 기본) · all(본사지시 전체). view=senders(보내는 매장별) · receivers(받는 매장별) · reasons(거부 사유) · days(일별). "
            "'지난주 RT 성과 어땠어?', '어느 매장이 RT 거부를 많이 해?', 'RT 보낸 거 팔렸어?' 같은 질문에 씁니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": {"type": "string", "description": "지시일 시작 YYYYMMDD"}, "date_to": {"type": "string", "description": "지시일 끝 YYYYMMDD"},
                "scope": {"type": "string", "enum": ["web", "all"]},
                "view": {"type": "string", "enum": ["summary", "senders", "receivers", "reasons", "days"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOLS += [
    {
        "name": "get_pending_rt",
        "description": (
            "미처리 RT 현황: 매장이 아직 수락 · 거부하지 않은 RT 요청(T_SHOP_REQ 미처리) — 본사지시 · 자동 RT · 매장간, 요청일 최근 N일(기본 14). "
            "처리할 매장(보내는 매장)별 건수 · 가장 오래된 경과 시간 · 경과 구간(1일 미만 · 1~2일 · 2~3일 · 3일 이상), "
            "본사지시는 3일 무응답이면 자동거부되므로 48시간 넘은 건은 '자동거부 임박'. 행사 · 가상 매장은 기본 제외. "
            "'RT 처리 안 한 매장 어디야?', '자동거부 될 RT 있어?' 같은 질문에 씁니다. view=shops(매장별, 기본) · teams · rows(요청 목록)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "days": {"type": "integer", "minimum": 1, "maximum": 31},
                "types": {"type": "array", "items": {"type": "string", "enum": ["본사지시", "자동 RT", "매장간"]}},
                "shop_id": {"type": "string", "description": "이 매장(처리할 매장) 요청만"},
                "view": {"type": "string", "enum": ["shops", "teams", "rows"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "recommend_wh_return",
        "description": (
            "창고 회수 추천: 창고 → 매장 배분(판매분 자동보충 규칙, recommend_wh_allocation 과 같은 조건 · 기본 최근 자동보충 실행 조건 · 어제)에서 "
            "창고 재고가 모자라 보충 못 하는 상품을, 최근 N일(기본 14) 그 상품 판매가 없는 매장 재고에서 창고로 회수하도록 추천합니다. "
            "폐점 · 비정상 매장 → 판매 이력 없는/오래된 매장 순. mode=need(부족 수량만큼, 기본) · all(판매 없는 재고 전부). "
            "'창고 부족한 거 어디서 회수하면 돼?', '회수 추천' 같은 질문에 씁니다. 추천일 뿐 ERP 에 반품 지시를 넣지 않는다고 밝히세요. "
            "view=summary · rows(회수 행) · skus(상품별)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": _FROM, "date_to": _TO, "seasons": _SEASONS,
                "prdt_cd": {"type": "string", "description": "품번 (앞부분만 넣어도 됨)"},
                "lookback_days": {"type": "integer", "minimum": 3, "maximum": 90, "description": "판매 없음 기준 기간 (기본 14일)"},
                "mode": {"type": "string", "enum": ["need", "all"]},
                "view": {"type": "string", "enum": ["summary", "rows", "skus"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "get_aging_stock",
        "description": (
            "장기 미판매 재고: 이번 달 매장 재고 중 그 매장에서 오래 팔리지 않은 재고(매장 × 스타일). 미판매 일수 = 오늘 − 최종판매일(판매 이력 없으면 최초출고일). "
            "min_days(기본 90) 이상을 장기 미판매로 봅니다. 구간별(30 · 60 · 90 · 180 · 365일) 수량 · 금액, 매장별 · 스타일별 장기 미판매 재고와 금액. "
            "기획년도 · 시즌 · 팀 · 품번으로 거를 수 있고 행사 · 가상 매장은 기본 제외. 처음 계산은 1~2분 걸릴 수 있습니다(이후 12시간 바로). "
            "'안 팔리는 재고 많은 매장', '1년 넘게 안 팔린 재고', '장기 재고 금액' 같은 질문에 씁니다. view=summary · shops · styles · detail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "min_days": {"type": "integer", "minimum": 7, "maximum": 1000},
                "plan_yy": {"type": "array", "items": {"type": "string"}}, "seasons": _SEASONS, "teams": _TEAMS,
                "prdt_cd": {"type": "string"}, "shop_id": {"type": "string", "description": "이 매장만 (detail 보기)"},
                "view": {"type": "string", "enum": ["summary", "shops", "styles", "detail"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOLS += [
    {
        "name": "get_stock_turnover",
        "description": (
            "재고 회전: 매장 × 스타일 재고를 최근 N일(기본 28) 판매 속도와 비교 — 재고일수 = 재고 ÷ 일평균 판매, 판매율 = 판매 ÷ (판매 + 재고). "
            "구간: 품절(재고 0 · 판매 있음) · 7일 미만(품절 위험) · 7~30 · 30~90 · 90~180 · 180일 넘음 · 판매 없음. "
            "'재고 많이 쌓인 매장', '품절 위험 상품', '재고일수 긴 팀', '회전 느린 스타일' 같은 질문에 씁니다. 행사 · 가상 매장 제외. "
            "view=summary · shops · teams · styles · short(품절 위험 매장 × 스타일) · over(과다)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "days": {"type": "integer", "enum": [7, 14, 28, 56, 91]},
                "plan_yy": {"type": "array", "items": {"type": "string"}}, "seasons": _SEASONS, "teams": _TEAMS, "prdt_cd": {"type": "string"},
                "shop_id": {"type": "string"}, "view": {"type": "string", "enum": ["summary", "shops", "teams", "styles", "short", "over"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "get_initial_alloc_accuracy",
        "description": (
            "초도 배분 적중률: 신상품 초도 배분(ERP 초도배분 · 확정)이 매장 판매와 얼마나 맞았는지 — 상품(품번 · 칼라) × 매장의 배분 대비 출고예정일부터 N일(기본 14) 판매. "
            "판매율 = 판매 ÷ 배분, 무판매 매장, 소진 매장(판매 ≥ 배분), 적중률 = Σ 매장 min(배분 비중, 판매 비중)×100 (판매 10장 미만 상품은 판단 보류). "
            "기본 기간은 N일이 다 지난 최근 30일 초도 배분. '초도 배분 잘 됐어?', '초도 적중률 낮은 상품', '초도 받고 안 팔린 매장' 같은 질문에 씁니다. "
            "view=summary · products · shops · types(유통형태별)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": _BRAND, "date_from": {"type": "string", "description": "초도 배분 의뢰일 시작 YYYYMMDD"},
                "date_to": {"type": "string", "description": "초도 배분 의뢰일 끝 YYYYMMDD"}, "window": {"type": "integer", "enum": [7, 14, 28]},
                "plan_yy": {"type": "array", "items": {"type": "string"}}, "seasons": _SEASONS,
                "view": {"type": "string", "enum": ["summary", "products", "shops", "types"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOL_LABELS = {"recommend_store_rt": "매장 간 RT 추천", "recommend_wh_allocation": "창고 → 매장 배분 추천", "get_auto_rt_stats": "자동 RT 현황",
               "check_auto_rt_settings": "자동 RT 설정 점검", "open_stock_rt_screen": "재고 재배치 화면 열기",
               "pick_store_rt_rows": "RT 추천 골라 선택", "get_rt_performance": "RT 성과", "get_pending_rt": "미처리 RT 현황",
               "recommend_wh_return": "창고 회수 추천", "get_aging_stock": "장기 미판매 재고", "get_stock_turnover": "재고 회전",
               "get_initial_alloc_accuracy": "초도 배분 적중률"}
TOOL_NAMES = {t["name"] for t in TOOLS}


class StockToolError(ValueError):
    pass


def _http(ex: HTTPException) -> StockToolError:
    d = ex.detail
    return StockToolError(d.get("message", str(d)) if isinstance(d, dict) else str(d))


def _str(inp: dict, key: str) -> str | None:
    v = inp.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise StockToolError(f"{key} 는 문자열입니다.")
    return v.strip() or None


def _list(inp: dict, key: str) -> list[str]:
    v = inp.get(key)
    if v in (None, "", []):
        return []
    if isinstance(v, str):
        v = [x for x in v.split(",")]
    if not isinstance(v, list) or not all(isinstance(x, (str, int)) for x in v):
        raise StockToolError(f"{key} 는 문자열 목록입니다.")
    return [str(x).strip() for x in v if str(x).strip()]


def _int(inp: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = inp.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise StockToolError(f"{key} 는 {lo}~{hi} 정수입니다.")
    return v


def _bool(inp: dict, key: str, default: bool) -> bool:
    v = inp.get(key, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise StockToolError(f"{key} 는 true/false 입니다.")
    return v


def _seasons(names: list[str]) -> list[str]:
    codes = sc.code_names("C007")
    by_name = {v: k for k, v in codes.items()}
    out = []
    for n in names:
        c = n.upper() if n.upper() in codes else by_name.get(n)
        if not c:
            raise StockToolError(f"시즌 '{n}' 을 모릅니다. {', '.join(codes.values())} 중에서 고르세요.")
        out.append(c)
    return out


def _teams(names: list[str]) -> list[str]:
    teams = sc.team_names()
    by_name = {v: k for k, v in teams.items()}
    out = []
    for n in names:
        c = n if n in teams else by_name.get(n)
        if not c:
            raise StockToolError(f"팀 '{n}' 을 모릅니다 (예: 쉬즈1팀, 리스트3팀).")
        out.append(c)
    return out


def _table(cols: list[tuple], rows: list[dict]) -> dict:
    return {"columns": [{"key": k, "label": label} for k, label, *_ in cols], "rows": rows}


def run(name: str, inp: dict, *, allowed: list[str] | None) -> dict:
    try:
        if name == "recommend_store_rt":
            return _rt(inp, allowed)
        if name == "recommend_wh_allocation":
            return _alloc(inp, allowed)
        if name == "get_auto_rt_stats":
            return _stats(inp, allowed)
        if name == "check_auto_rt_settings":
            return _check(inp, allowed)
        if name == "open_stock_rt_screen":
            return _open(inp, allowed)
        if name == "pick_store_rt_rows":
            return _pick(inp, allowed)
        if name == "get_rt_performance":
            return _perf(inp, allowed)
        if name == "get_pending_rt":
            return _pending(inp, allowed)
        if name == "recommend_wh_return":
            return _return(inp, allowed)
        if name == "get_aging_stock":
            return _aging(inp, allowed)
        if name == "get_stock_turnover":
            return _turnover(inp, allowed)
        if name == "get_initial_alloc_accuracy":
            return _initial(inp, allowed)
    except HTTPException as ex:
        raise _http(ex)
    raise StockToolError(f"알 수 없는 도구: {name}")


def _rt(inp: dict, allowed: list[str] | None) -> dict:
    view = _str(inp, "view") or "summary"
    if view not in ("summary", "rows", "unfilled", "shops"):
        raise StockToolError("view 는 summary, rows, unfilled, shops 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    shop = (_str(inp, "shop_id") or "").upper() or None
    d = stock_rt.recommend(_str(inp, "brand"), _str(inp, "date_from"), _str(inp, "date_to"), _list(inp, "plan_yy"),
                           _seasons(_list(inp, "seasons")), _str(inp, "prdt_cd"), _teams(_list(inp, "teams")),
                           _int(inp, "per", 1, 1, 3), _bool(inp, "apply_auto_rt_limits", False), _str(inp, "order") or "slow",
                           _int(inp, "sender_max", 0, 0, 1000), allowed=allowed)
    s = d["summary"]
    rows = [r for r in d["rows"] if not shop or shop in (r["fromShopId"], r["toShopId"])]
    unfilled = [u for u in d["unfilled"] if not shop or u["shopId"] == shop]
    result: dict[str, Any] = {
        "condition": stock_rt.cond_text(d), "asOf": d["asOf"], "note": "조회 · 추천만 (ERP 에 RT 등록 안 됨)",
        "receivers": s["receivers"], "needQty": s["needQty"], "filledReceivers": s["filledReceivers"], "recommendedRows": s["recRows"],
        "recommendedQty": s["recQty"], "senderShops": s["senders"], "receivingShops": s["receivingShops"],
        "autoRtCanceledRequests": s["failRequests"], "autoRtCanceledFilled": s["failFilled"], "unfilled": s["unfilled"],
        "unfilledByReason": {d["reasonNames"][k]: v for k, v in s["unfilledBy"].items() if v},
        "senderExcludedByRule": {d["ruleNames"][k]: v for k, v in s["senderExcluded"].items() if v},
        "receiversSkipped": {"RT 그룹 없음 · 정상 매장 아님": s["skipped"]["noGroup"], "자동RT 반입 수불제어": s["skipped"]["recvCtl"]},
    }
    if shop:
        result["shopFilter"] = {"shopId": shop, "sendRows": sum(1 for r in rows if r["fromShopId"] == shop),
                                "receiveRows": sum(1 for r in rows if r["toShopId"] == shop), "unfilled": len(unfilled)}
    if view == "unfilled":
        result["rows"] = unfilled[:limit]
        return {"result": result, "table": _table(stock_rt.UNFILLED_COLS, unfilled[:limit])}
    if view == "shops":
        result["topSenders"], result["topReceivers"] = d["topSenders"], d["topReceivers"]
        return {"result": result, "table": _table([("shopId", "매장"), ("shopNm", "매장명"), ("qty", "보내는 수량")], d["topSenders"])}
    result["rows"] = rows[:limit] if view == "rows" else rows[:10]
    return {"result": result, "table": _table(stock_rt.RT_COLS, rows[:limit if view == "rows" else 30])}


def _alloc(inp: dict, allowed: list[str] | None) -> dict:
    view = _str(inp, "view") or "summary"
    if view not in ("summary", "rows", "skus", "short", "shops"):
        raise StockToolError("view 는 summary, rows, skus, short, shops 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    brand = sc.brand_code(_str(inp, "brand"), allowed)
    args: dict[str, Any] = {}
    run_used = None
    if _bool(inp, "use_recent_run", True):
        runs = wh_alloc.recent_runs(brand, 1)
        if runs:
            run_used = runs[0]
            args = {"wh": run_used["wh"], "base": run_used["base"], "grd_grp": run_used["grdGrp"], "plan_yy": run_used["planYy"],
                    "seasons": run_used["seasons"], "prdt_grps": run_used["prdtGrps"], "items": run_used["items"],
                    "prdt": run_used["prdt"], "teams": run_used["teams"], "rate": run_used["rate"]}
    for key, val in (("wh", _str(inp, "warehouse")), ("base", _str(inp, "base_id")), ("prdt", _str(inp, "prdt_cd"))):
        if val:
            args[key] = val
    if _list(inp, "plan_yy"):
        args["plan_yy"] = _list(inp, "plan_yy")
    if _list(inp, "seasons"):
        args["seasons"] = _seasons(_list(inp, "seasons"))
    if _list(inp, "teams"):
        args["teams"] = _teams(_list(inp, "teams"))
    if inp.get("rate") is not None:
        if isinstance(inp["rate"], bool) or not isinstance(inp["rate"], (int, float)):
            raise StockToolError("rate 는 숫자입니다.")
        args["rate"] = inp["rate"]
    d = wh_alloc.recommend(brand, frm=_str(inp, "date_from"), to=_str(inp, "date_to"), allowed=allowed, **args)
    s = d["summary"]
    shop = (_str(inp, "shop_id") or "").upper() or None
    rows = [r for r in d["rows"] if not shop or r["shopId"] == shop]
    result: dict[str, Any] = {
        "condition": wh_alloc.cond_text(d), "asOf": d["asOf"], "note": "조회 · 추천만 (ERP 에 배분의뢰 등록 안 됨)",
        "recentRunUsed": {k: run_used[k] for k in ("seq", "at", "ignored")} if run_used else None,
        "skus": s["skus"], "allocSkus": s["allocSkus"], "allocQty": s["allocQty"], "allocFullPay": s["allocFp"], "shops": s["shops"],
        "demandQty": s["demand"], "shortQty": s["short"], "skusWithoutWarehouseStock": s["noStockSkus"],
        "skippedByControl": s["ctlRows"],
    }
    if view == "skus" or view == "short":
        skus = sorted(d["skus"], key=lambda x: -x["short"]) if view == "short" else d["skus"]
        skus = [x for x in skus if view != "short" or x["short"] > 0]
        result["rows"] = skus[:limit]
        return {"result": result, "table": _table(wh_alloc.SKU_COLS, skus[:limit])}
    if view == "shops":
        result["topShops"] = d["topShops"]
        return {"result": result, "table": _table([("shopId", "매장"), ("shopNm", "매장명"), ("qty", "배분 수량")], d["topShops"])}
    result["rows"] = rows[:limit] if view == "rows" else rows[:10]
    return {"result": result, "table": _table(wh_alloc.ALLOC_COLS, rows[:limit if view == "rows" else 30])}


def _stats(inp: dict, allowed: list[str] | None) -> dict:
    d = stock_rt.auto_rt_stats(_str(inp, "brand"), _str(inp, "date_from"), _str(inp, "date_to"), allowed)
    return {"result": d, "table": {"columns": [{"key": "day", "label": "요청일"}, {"key": "total", "label": "요청"},
                                               {"key": "done", "label": "완료"}, {"key": "fail", "label": "지시가능매장없음 취소"}],
                                   "rows": d["days"]}}


def _check(inp: dict, allowed: list[str] | None) -> dict:
    only = _str(inp, "only") or "problem"
    if only not in ("problem", "all"):
        raise StockToolError("only 는 problem 또는 all 입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    d = stock_rt.setting_check({"brand": _str(inp, "brand"), "frm": _str(inp, "date_from"), "to": _str(inp, "date_to")}, allowed)
    rows = [r for r in d["rows"] if only == "all" or r["status"] != "적정"]
    result = {"brand": d["brandNm"], "period": f"{d['from']} ~ {d['to']} ({d['days']}일)", "asOf": d["asOf"], **d["summary"],
              "rule": "권장 지정가능수 = 올림((기간 실제 지정 수 + 자동RT 취소 요청 채움 수량) ÷ 기간 일수)",
              "note": "설정 변경은 ERP 매장 RT 그룹 설정(T_SHOP_RT_GRP_DETL.ASIGN_ABLE_QTY)에서 합니다", "rows": rows[:limit]}
    return {"result": result, "table": _table(stock_rt.CHECK_COLS, rows[:limit])}


def _ymd_iso(v: str | None, label: str) -> str | None:
    if not v:
        return None
    s = v.replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise StockToolError(f"{label} 는 YYYYMMDD 입니다.")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _open(inp: dict, allowed: list[str] | None) -> dict:
    tab = _str(inp, "tab") or "rt"
    if tab not in ("rt", "alloc"):
        raise StockToolError("tab 은 rt 또는 alloc 입니다.")
    brand = sc.brand_code(_str(inp, "brand"), allowed)
    view = _str(inp, "view")
    views = ("rows", "unfilled", "shops", "stats", "check") if tab == "rt" else ("rows", "short", "skus", "shops")
    if view and view not in views:
        raise StockToolError(f"view 는 {', '.join(views)} 중 하나입니다.")
    frm, to = _ymd_iso(_str(inp, "date_from"), "date_from"), _ymd_iso(_str(inp, "date_to"), "date_to")
    if frm or to:
        sc.period((frm or to).replace("-", ""), (to or frm).replace("-", ""), 7)       # 기간 규칙(최대 31일 · 미래 불가) 확인
    seasons = _seasons(_list(inp, "seasons"))
    teams = _teams(_list(inp, "teams"))
    plan_yy = _list(inp, "plan_yy")
    prdt = sc.prdt_prefix(_str(inp, "prdt_cd"))
    cond: dict[str, Any] = {}
    if frm or to:
        cond["dateFrom"], cond["dateTo"] = frm or to, to or frm
    if plan_yy:
        cond["planYy"] = plan_yy
    if seasons:
        cond["seasons"] = seasons
    if teams:
        cond["teams"] = teams
    if prdt:
        cond["prdt"] = prdt
    if tab == "rt":
        if inp.get("per") is not None:
            cond["per"] = _int(inp, "per", 1, 1, 3)
        if _str(inp, "order"):
            if inp["order"] not in stock_rt.ORDERS:
                raise StockToolError("order 는 slow 또는 auto 입니다.")
            cond["order"] = inp["order"]
        if inp.get("apply_auto_rt_limits") is not None:
            cond["limits"] = _bool(inp, "apply_auto_rt_limits", False)
    else:
        if _str(inp, "warehouse"):
            cond["wh"] = _str(inp, "warehouse").upper()
        if inp.get("rate") is not None:
            if isinstance(inp["rate"], bool) or not isinstance(inp["rate"], (int, float)) or not 0 < inp["rate"] <= 10:
                raise StockToolError("rate 는 0 보다 크고 10 이하인 숫자입니다.")
            cond["rate"] = inp["rate"]
    s_nm, t_nm = sc.code_names("C007"), sc.team_names()
    label = {"rt": "매장 간 RT", "alloc": "창고 → 매장 배분"}[tab]
    lines = [f"브랜드: {sc.BRAND_CODES[brand]} · {label}"]
    if "dateFrom" in cond:
        lines.append(f"판매 기간: {cond['dateFrom']} ~ {cond['dateTo']}")
    else:
        lines.append("판매 기간: 화면 기본값 (" + ("최근 7일" if tab == "rt" else "어제") + ")")
    if tab == "alloc":
        lines.append("배분 조건: 최근 판매분 자동보충 실행 조건에서 시작")
    for k, nm, f in (("planYy", "기획년도", lambda v: ", ".join(v)), ("seasons", "시즌", lambda v: ", ".join(s_nm.get(x, x) for x in v)),
                     ("teams", "팀", lambda v: ", ".join(t_nm.get(x, x) for x in v)), ("prdt", "품번", lambda v: f"{v}…"),
                     ("per", "받는 상품당", lambda v: f"{v}장"), ("order", "순서", lambda v: stock_rt.ORDERS[v]),
                     ("limits", "자동 RT 하루 한도", lambda v: "적용" if v else "미적용"), ("wh", "창고", str), ("rate", "배수", str)):
        if k in cond:
            lines.append(f"{nm}: {f(cond[k])}")
    if view:
        lines.append(f"처음 보기: {view}")
    payload = {"tab": tab, "brand": brand, "view": view, "run": True, "cond": cond}
    return {
        "result": {"opened": False, "instruction": "아직 화면을 열지 않았습니다. 대화창 카드의 [화면에서 열기]를 누르면 이 조건으로 화면이 열리고 계산합니다.",
                   "conditions": lines},
        "action": {"actionKind": "open_stock", "title": f"재고 재배치 추천 화면 · {sc.BRAND_CODES[brand]} {label}", "items": [payload],
                   "lines": lines, "warnings": []},
    }


PICK_MAX = 5000      # 한 번에 고르는 최대 행 (화면은 전체 행을 100행씩 넘겨 본다)


def _pick(inp: dict, allowed: list[str] | None) -> dict:
    d = stock_rt.recommend(_str(inp, "brand"), _str(inp, "date_from"), _str(inp, "date_to"), _list(inp, "plan_yy"),
                           _seasons(_list(inp, "seasons")), _str(inp, "prdt_cd"), _teams(_list(inp, "teams")),
                           _int(inp, "per", 1, 1, 3), _bool(inp, "apply_auto_rt_limits", False), _str(inp, "order") or "slow", 0, allowed=allowed)
    fail = _int(inp, "min_fail_cnt", 0, 0, 1000)
    rsales = _int(inp, "min_receiver_sales", 0, 0, 100000)
    ssales = inp.get("max_sender_sales")
    if ssales is not None:
        ssales = _int(inp, "max_sender_sales", 0, 0, 100000)
    whys = _list(inp, "why")
    if any(w not in ("자동RT 취소", "완불 대기", "판매 후 품절") for w in whys):
        raise StockToolError("why 는 자동RT 취소 · 완불 대기 · 판매 후 품절 중에서 고르세요.")
    froms = {x.upper() for x in _list(inp, "from_shop_ids")}
    tos = {x.upper() for x in _list(inp, "to_shop_ids")}
    min_qty = _int(inp, "min_qty", 1, 1, 1000)
    rows = [r for r in d["rows"] if r["toFailCnt"] >= fail and r["toSales"] >= rsales and (ssales is None or r["fromSales"] <= ssales)
            and (not whys or r["why"] in whys) and (not froms or r["fromShopId"] in froms) and (not tos or r["toShopId"] in tos) and r["qty"] >= min_qty]
    crit = []
    if fail:
        crit.append(f"자동RT 취소 {fail}회 이상")
    if rsales:
        crit.append(f"받는 매장 판매 {rsales}장 이상")
    if ssales is not None:
        crit.append(f"보내는 매장 판매 {ssales}장 이하")
    if whys:
        crit.append("사유 " + "·".join(whys))
    if froms:
        crit.append("보내는 매장 " + ",".join(sorted(froms)))
    if tos:
        crit.append("받는 매장 " + ",".join(sorted(tos)))
    if min_qty > 1:
        crit.append(f"수량 {min_qty}장 이상")
    label = " · ".join(crit) or "전체"
    qty = sum(r["qty"] for r in rows)
    c = d["cond"]
    cond = {"dateFrom": d["from"], "dateTo": d["to"], "planYy": c["planYy"], "seasons": c["seasons"], "teams": c["teams"], "prdt": c["prdt"] or "",
            "per": d["per"], "order": d["order"], "senderMax": d["senderMax"], "limits": d["limits"]}
    result: dict[str, Any] = {
        "condition": stock_rt.cond_text(d), "criteria": label, "picked": len(rows), "pickedQty": qty, "recommendedRows": len(d["rows"]),
        "note": "아직 선택 · 등록하지 않았습니다. 대화창 카드의 [화면에서 열고 선택]을 누르면 화면에서 이 행들이 체크되고, 관리자가 확인 후 [본사지시 RT 지시]를 눌러야 ERP 에 들어갑니다.",
        "rows": rows[:10],
    }
    if len(rows) > PICK_MAX:
        result["warning"] = f"조건에 맞는 행이 {len(rows):,}건이라 앞쪽 {PICK_MAX:,}건만 고릅니다. 기준을 더 좁혀 보세요."
        rows = rows[:PICK_MAX]
        qty = sum(r["qty"] for r in rows)
    out: dict = {"result": result, "table": _table(stock_rt.RT_COLS, rows[:30])}
    if rows:
        lines = [f"계산 조건: {stock_rt.cond_text(d)}", f"고른 기준: {label}", f"선택: {len(rows):,}건 · {qty:,}장 (추천 {len(d['rows']):,}건 중)"]
        out["action"] = {"actionKind": "open_stock", "title": f"매장 간 RT 추천 골라 선택 · {d['brandNm']} {len(rows):,}건",
                         "items": [{"tab": "rt", "brand": d["brand"], "view": "rows", "run": True, "cond": cond,
                                    "select": {"keys": [[r["prdtCd"], r["colorCd"], r["sizeCd"], r["fromShopId"], r["toShopId"]] for r in rows],
                                               "label": label}}],
                         "lines": lines, "warnings": [result["warning"]] if result.get("warning") else []}
    return out


def _perf(inp: dict, allowed: list[str] | None) -> dict:
    from . import stock_perf

    view = _str(inp, "view") or "summary"
    if view not in ("summary", "senders", "receivers", "reasons", "days"):
        raise StockToolError("view 는 summary, senders, receivers, reasons, days 중 하나입니다.")
    limit = _int(inp, "limit", 20, 1, 200)
    d = stock_perf.performance(_str(inp, "brand"), _str(inp, "date_from"), _str(inp, "date_to"), _str(inp, "scope") or "web", allowed)
    result: dict[str, Any] = {"brand": d["brandNm"], "period": f"{d['from']} ~ {d['to']}", "scope": "이 화면에서 지시" if d["scope"] == "web" else "본사지시 전체",
                              **d["summary"], "soldDays": d["soldDays"],
                              "soldRateNote": "판매 전환은 수락 건 중 받은 매장이 수락일부터 7일 안에 같은 상품을 판매한 비율. maturedSold/maturedAccepted 는 7일이 지난 건만",
                              "topReasons": d["reasons"][:8]}
    if d["summary"]["total"] == 0 and d["scope"] == "web":
        result["hint"] = "이 화면에서 지시한 RT 가 없습니다. 본사지시 전체를 보려면 scope=all."
    if view == "reasons":
        return {"result": result, "table": {"columns": [{"key": "reason", "label": "거부 사유"}, {"key": "qty", "label": "수량"}], "rows": d["reasons"][:limit]}}
    if view == "days":
        return {"result": result, "table": {"columns": [{"key": k, "label": v} for k, v in (("day", "지시일"), ("total", "지시"), ("accepted", "수락"),
                                                                                             ("denied", "거부"), ("pending", "미처리"))], "rows": d["days"]}}
    rows = d["receivers" if view == "receivers" else "senders"][:limit]
    from .stock_perf import PERF_COLS

    return {"result": {**result, "rows": rows[:10]}, "table": _table(PERF_COLS, rows)}


def _pending(inp: dict, allowed: list[str] | None) -> dict:
    from . import stock_pending

    view = _str(inp, "view") or "shops"
    if view not in ("shops", "teams", "rows"):
        raise StockToolError("view 는 shops, teams, rows 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    names = {v: k for k, v in stock_pending.TYPES.items()}
    tps = _list(inp, "types")
    if any(t not in names for t in tps):
        raise StockToolError("types 는 본사지시 · 자동 RT · 매장간 중에서 고르세요.")
    d = stock_pending.board(_str(inp, "brand"), _int(inp, "days", 14, 1, 31), [names[t] for t in tps] or None, False, allowed)
    shop = (_str(inp, "shop_id") or "").upper() or None
    result: dict[str, Any] = {"brand": d["brandNm"], "period": f"{d['from']} ~ {d['to']}", "asOf": d["asOf"], **d["summary"],
                              "byType": {d["typeNames"][k]: v for k, v in d["summary"]["byType"].items()},
                              "byAge": {a["name"]: d["summary"]["byAge"][a["key"]] for a in d["ages"]},
                              "note": f"본사지시는 3일 무응답이면 자동거부 — {d['urgentHours']}시간 넘은 본사지시 = urgent (자동거부 임박). 행사 · 가상 매장 제외"}
    if view == "rows" or shop:
        rows = [r for r in d["rows"] if not shop or r["fromShopId"] == shop][:limit]
        return {"result": {**result, "rows": rows[:20]}, "table": _table(stock_pending.PENDING_COLS, rows)}
    rows = (d["teams"] if view == "teams" else d["shops"])[:limit]
    return {"result": {**result, "rows": rows[:20]}, "table": _table(stock_pending.SHOP_COLS, rows)}


def _alloc_args_from(inp: dict, allowed: list[str] | None) -> dict:
    """recommend_wh_allocation 과 같은 시작 조건 (최근 판매분 자동보충 실행 조건 + 주어진 값)"""
    brand = sc.brand_code(_str(inp, "brand"), allowed)
    args: dict[str, Any] = {"brand": brand, "frm": _str(inp, "date_from"), "to": _str(inp, "date_to")}
    runs = wh_alloc.recent_runs(brand, 1)
    if runs:
        r = runs[0]
        args.update({"wh": r["wh"], "base": r["base"], "grd_grp": r["grdGrp"], "plan_yy": r["planYy"], "seasons": r["seasons"],
                     "prdt_grps": r["prdtGrps"], "items": r["items"], "prdt": r["prdt"], "teams": r["teams"], "rate": r["rate"]})
    if _list(inp, "seasons"):
        args["seasons"] = _seasons(_list(inp, "seasons"))
    if _str(inp, "prdt_cd"):
        args["prdt"] = _str(inp, "prdt_cd")
    return args


def _return(inp: dict, allowed: list[str] | None) -> dict:
    from . import stock_return

    view = _str(inp, "view") or "summary"
    if view not in ("summary", "rows", "skus"):
        raise StockToolError("view 는 summary, rows, skus 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    mode = _str(inp, "mode") or "need"
    d = stock_return.recommend(_alloc_args_from(inp, allowed), _int(inp, "lookback_days", 14, 3, 90), mode, allowed)
    result: dict[str, Any] = {"brand": d["brandNm"], "warehouse": d["wh"], "allocPeriod": f"{d['from']} ~ {d['to']}", "asOf": d["asOf"],
                              "noSaleSince": d["salesFrom"], "mode": d["modeNm"], **d["summary"],
                              "note": "추천만 (ERP 에 반품 지시를 넣지 않음). 받아야 하는 매장 · 최근 판매 매장 · 행사 · 가상 매장은 회수 후보에서 뺌",
                              "topShops": d["topShops"][:10]}
    if view == "skus":
        return {"result": {**result, "rows": d["skus"][:20]}, "table": _table(stock_return.RETURN_SKU_COLS, d["skus"][:limit])}
    return {"result": {**result, "rows": d["rows"][:10 if view == "summary" else 20]},
            "table": _table(stock_return.RETURN_COLS, d["rows"][:limit if view == "rows" else 30])}


def _aging(inp: dict, allowed: list[str] | None) -> dict:
    from . import stock_aging

    view = _str(inp, "view") or "summary"
    if view not in ("summary", "shops", "styles", "detail"):
        raise StockToolError("view 는 summary, shops, styles, detail 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    d = stock_aging.report(_str(inp, "brand"), _int(inp, "min_days", 90, 7, 1000), _list(inp, "plan_yy"), _seasons(_list(inp, "seasons")),
                           _teams(_list(inp, "teams")), _str(inp, "prdt_cd"), False, allowed)
    shop = (_str(inp, "shop_id") or "").upper() or None
    result: dict[str, Any] = {"brand": d["brandNm"], "minDays": d["minDays"], "stockAsOf": d["asOf"], **d["summary"],
                              "buckets": [{"name": b["name"], "qty": b["qty"], "amt": b["amt"]} for b in d["buckets"]],
                              "note": "미판매 일수 = 오늘 − 그 매장 최종판매일(없으면 최초출고일). 금액 = ERP 재고금액. 행사 · 가상 매장 제외"}
    if view == "detail" or shop:
        rows = [r for r in d["detail"] if not shop or r["shopId"] == shop][:limit]
        return {"result": {**result, "rows": rows[:20]}, "table": _table(stock_aging.AGING_COLS, rows)}
    if view == "styles":
        return {"result": {**result, "rows": d["styles"][:20]}, "table": _table(stock_aging.AGING_STYLE_COLS, d["styles"][:limit])}
    return {"result": {**result, "rows": d["shops"][:10 if view == "summary" else 20]},
            "table": _table(stock_aging.AGING_SHOP_COLS, d["shops"][:limit if view == "shops" else 30])}


def _turnover(inp: dict, allowed: list[str] | None) -> dict:
    from . import stock_turnover as tv

    view = _str(inp, "view") or "summary"
    if view not in ("summary", "shops", "teams", "styles", "short", "over"):
        raise StockToolError("view 는 summary, shops, teams, styles, short, over 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    days = inp.get("days") or 28
    d = tv.report(_str(inp, "brand"), days, _list(inp, "plan_yy"), _seasons(_list(inp, "seasons")), _teams(_list(inp, "teams")),
                  _str(inp, "prdt_cd"), False, allowed)
    shop = (_str(inp, "shop_id") or "").upper() or None
    names = dict(tv.CLASSES)
    result: dict[str, Any] = {"brand": d["brandNm"], "salesDays": d["days"], "stockAsOf": d["stockAsOf"], **d["summary"],
                              "classes": [{"name": c["name"], "rows": c["rows"], "stock": c["stock"], "sales": c["sales"]} for c in d["classes"]],
                              "note": "재고일수 = 재고 ÷ (기간 판매 ÷ 기간 일수). 매장 × 스타일 기준, 행사 · 가상 매장 제외"}
    if view in ("short", "over") or shop:
        want = tv.SHORT if view == "short" else tv.OVER if view == "over" else tv.SHORT | tv.OVER
        rows = [{**x, "clsNm": names[x["cls"]]} for x in d["detail"] if x["cls"] in want and (not shop or x["shopId"] == shop)][:limit]
        return {"result": {**result, "rows": rows[:20]}, "table": _table(tv.TURN_DETAIL_COLS, rows)}
    if view == "styles":
        return {"result": {**result, "rows": d["styles"][:20]}, "table": _table(tv.TURN_STYLE_COLS, d["styles"][:limit])}
    if view == "teams":
        cols = [("team", "팀"), ("shops", "매장 수"), ("stock", "재고"), ("sales", "기간 판매"), ("cover", "재고일수"), ("sellThru", "판매율(%)"),
                ("short", "품절 위험"), ("over", "과다")]
        return {"result": {**result, "rows": d["teams"]}, "table": _table(cols, d["teams"])}
    return {"result": {**result, "rows": d["shops"][:10 if view == "summary" else 20]},
            "table": _table(tv.TURN_COLS, d["shops"][:limit if view == "shops" else 30])}


def _initial(inp: dict, allowed: list[str] | None) -> dict:
    from . import stock_initial as si

    view = _str(inp, "view") or "summary"
    if view not in ("summary", "products", "shops", "types"):
        raise StockToolError("view 는 summary, products, shops, types 중 하나입니다.")
    limit = _int(inp, "limit", 30, 1, 200)
    d = si.analyze(_str(inp, "brand"), _str(inp, "date_from"), _str(inp, "date_to"), inp.get("window") or 14, _list(inp, "plan_yy"),
                   _seasons(_list(inp, "seasons")), False, True, allowed)
    result: dict[str, Any] = {"brand": d["brandNm"], "allocPeriod": f"{d['from']} ~ {d['to']}", "salesWindowDays": d["window"], **d["summary"],
                              "types": d["types"], "immatureExcluded": d["immature"],
                              "note": "적중률 = Σ 매장 min(배분 비중, 판매 비중)×100 (100 이면 판매 비중대로 배분). 판매 10장 미만 상품은 적중률 없음. "
                                      "출고예정일부터 판매를 셈. 행사 · 가상 매장 제외"}
    if view == "shops":
        return {"result": {**result, "rows": d["shops"][:20]}, "table": _table(si.INIT_SHOP_COLS, d["shops"][:limit])}
    if view == "types":
        cols = [("shopType", "유통형태"), ("alloc", "초도 배분"), ("sold", "기간 판매"), ("sellThru", "판매율(%)"), ("zero", "무판매"), ("soldOut", "소진")]
        return {"result": result, "table": _table(cols, d["types"])}
    rows = d["products"][:limit if view == "products" else 30]
    return {"result": {**result, "rows": rows[:10 if view == "summary" else 20]}, "table": _table(si.INIT_PROD_COLS, rows)}
