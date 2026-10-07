"""Claude 조회 도구: 재고 재배치 추천 메뉴와 같은 계산 (조회 · 추천만, ERP 에 등록하지 않음).

- recommend_store_rt: 매장 간 RT 추천 (stock_rt.recommend — 자동 RT 검색 규칙)
- recommend_wh_allocation: 창고 → 매장 배분 추천 (wh_alloc.recommend — 판매분 자동보충 규칙)
- get_auto_rt_stats: 자동 RT 요청 결과 현황 (완료 · 취소 · '지시가능매장없음')
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
]
TOOL_LABELS = {"recommend_store_rt": "매장 간 RT 추천", "recommend_wh_allocation": "창고 → 매장 배분 추천", "get_auto_rt_stats": "자동 RT 현황"}
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
