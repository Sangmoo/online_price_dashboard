"""Claude 조회 도구: 판매 분석 > 판매 현황 대시보드.

화면(sale_dashboard.dashboard)과 같은 계산 결과를 그대로 돌려줘, AI 답변과 화면 숫자가 항상 일치한다.
월×매장 사전 집계 뷰로 계산되어 즉시 응답한다. 필요한 부분(sections)만 골라 받아 토큰을 아낀다.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from . import sale_dashboard as sd
from . import sale_products as sp

SECTIONS = {
    "kpi": "핵심 지표 (실판금액·비교 기준 대비·보조 비교·연 누계·수량·할인금액·원가율·판매 매장 수·목표금액·달성률)",
    "trend": "기준 월까지 최근 13개월 월별 실판금액 추이 (전년 같은 달·전년 대비·원가율·판매 매장 수)",
    "brands": "브랜드별 실적 (실판금액·비교 기간·증감·비중·원가율·매장 수·목표·달성률)",
    "teams": "팀별 실적 (실판금액·비교 기간·증감·원가율·매장 수·목표·달성률)",
    "top_shops": "실판금액 상위 10개 매장 (증감·원가율·목표 달성률)",
    "risers": "비교 기간 대비 성장률 상위 10개 매장 (비교 기간 월평균 1천만원 이상, 폐점·종료 매장 제외)",
    "fallers": "비교 기간 대비 하락률 상위 10개 매장 (비교 기간 월평균 1천만원 이상, 폐점·종료 매장 제외)",
    "laggards": "목표 달성률 하위 10개 매장 (목표가 있고 매출이 있는 영업 매장)",
    "products": "기간 안 상품(품번) 순위 상위 20 — 실판금액·수량·할인율 순 (품번은 시즌마다 새로 나와 전년 비교 없음)",
    "items": "아이템·품군별 실판금액·비교 기간 대비·비중·할인율 (상품의 전년 비교는 이 단위로)",
    "sales_types": "판매형태(행사/정상/정상50%/세일 등) 구성: 비중·비교 기간 대비·할인율·월별 비중",
}
PRODUCT_SECTIONS = {"products", "items", "sales_types"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_sales_dashboard",
        "description": (
            "판매 현황 대시보드(메뉴: 판매 분석 > 판매 현황)와 같은 기준으로 판매 요약을 조회합니다. "
            "'이번 달/지난달/특정 월·기간 판매 현황', '전년 대비·전월 대비', '올해 누계', '목표 대비 달성률', "
            "'브랜드별·팀별 실적', '매출 상위 매장', '많이 성장한/하락한 매장', '목표 미달 매장', '원가율' 같은 질문에 가장 먼저 쓰세요. "
            "화면과 숫자가 같습니다. ym(끝 월)을 생략하면 가장 최근 마감 월이고, ym_from 을 주면 ym_from~ym 기간 합계(최대 12개월)입니다. "
            "compare: yoy=전년 동기(기본), prev=직전 기간(한 달이면 전월), custom=compare_from~compare_to. "
            "brand 로 브랜드 하나만 볼 수 있습니다(쉬즈미스·리스트·시스티나. 쉬즈미스는 팀명 '쉬즈N팀', 나머지는 팀명에서 숫자·'팀'을 뺀 이름). "
            "sections 로 필요한 부분만 고르면 빠르고 간결합니다 (생략 시 kpi, trend, brands, top_shops). 선택지: "
            + "; ".join(f"{k}={v}" for k, v in SECTIONS.items())
            + ". 금액은 원, 비율은 %, 원가율 = 원가 금액(제조원가×수량) ÷ 실판금액, 할인율 = 할인금액 ÷ (실판금액 + 할인금액), "
            "달성률 = 목표가 있는 매장의 실판금액 ÷ 목표금액(T_SHOP_SELL_MGOAL, 매장 단위로 합산해 매장의 판매 브랜드로 집계). "
            "특정 매장들의 합계나 여러 달 매장 비교는 sum_sales_shop_month 를 쓰세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ym": {"type": "string", "description": "기준(끝) 판매년월 YYYYMM (생략 시 최근 마감 월)"},
                "ym_from": {"type": "string", "description": "기간 시작 판매년월 YYYYMM (생략 시 ym 한 달)"},
                "compare": {"type": "string", "enum": list(sd.CMP_KINDS), "description": "비교 기준 (기본 yoy)"},
                "compare_from": {"type": "string", "description": "compare=custom 일 때 비교 시작 월 YYYYMM"},
                "compare_to": {"type": "string", "description": "compare=custom 일 때 비교 끝 월 YYYYMM"},
                "brand": {"type": "string", "description": "브랜드 하나로 거르기 (생략 시 전체)"},
                "sections": {"type": "array", "items": {"type": "string", "enum": list(SECTIONS)},
                             "description": "받을 부분 (생략 시 kpi, trend, brands, top_shops)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOL_LABELS = {"get_sales_dashboard": "판매 현황"}
DEFAULT_SECTIONS = ["kpi", "trend", "brands", "top_shops"]
_YM = re.compile(r"^\d{4}-?(0[1-9]|1[0-2])$")


class DashToolError(ValueError):
    pass


def _ym_arg(inp: dict, key: str) -> str | None:
    v = inp.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str) or not _YM.match(v.strip()):
        raise DashToolError(f"{key} 는 YYYYMM 형식입니다.")
    return v.strip().replace("-", "")


def _shops(rows: list[dict]) -> list[dict]:
    keys = ("shopId", "shopNm", "brand", "team", "amt", "baseAmt", "change", "costRate", "goalAmt", "achieve")
    return [{"rank": i + 1, **{k: s.get(k) for k in keys}} for i, s in enumerate(rows)]


def _fmt(v, unit: str) -> str | None:
    if v is None:
        return None
    return f"{v:+d}{unit}" if unit == "개" else f"{v:+.1f}{unit}"


def _kpi_table(d: dict) -> list[dict]:
    k, base, extra = d["kpi"], d["base"], d["extra"]
    bl = f"{base['kindLabel']} {base['label']}"
    el = f"{extra['label']} {extra['period']}"
    rows = [
        ("실판금액(원)", k["amt"], bl, k["baseAmt"], _fmt(k["change"], "%")),
        ("실판금액(원)", k["amt"], el, k["extraAmt"], _fmt(k["extraChange"], "%")),
        (f"{d['ym'][:4]}년 누계(원)", k["ytdAmt"], "전년 같은 기간", k["prevYtdAmt"], _fmt(k["ytdYoy"], "%")),
        ("판매 수량", k["qty"], bl, k["baseQty"], _fmt(k["qtyChange"], "%")),
        ("할인금액(원)", k["dsct"], bl, k["baseDsct"], _fmt(k["dsctChange"], "%")),
        ("할인율(%)", k.get("dsctRate"), bl, k.get("baseDsctRate"), _fmt(k.get("dsctRateDiff"), "%p")),
        ("원가율(%)", k["costRate"], bl, k["baseCostRate"], _fmt(k["costRateDiff"], "%p")),
        ("판매 매장 수", k["shops"], bl, k["baseShops"], _fmt(k["shops"] - k["baseShops"], "개")),
    ]
    if k["goalAmt"]:
        rows.append(("목표 달성률(%)", k["achieve"], "목표금액(원)", k["goalAmt"],
                     None if k["goalGap"] is None else f"{k['goalGap']:+,}원"))
    return [{"ITEM": a, "CUR": b, "BASE_LABEL": c, "BASE": e, "CHANGE": f} for a, b, c, e, f in rows]


def run(name: str, inp: dict, allowed: list[str] | None = None) -> dict:
    """allowed: 브랜드 권한 (None = 모든 브랜드)"""
    if name != "get_sales_dashboard":
        raise DashToolError(f"알 수 없는 도구: {name}")
    ym, ym_from = _ym_arg(inp, "ym"), _ym_arg(inp, "ym_from")
    cmp_from, cmp_to = _ym_arg(inp, "compare_from"), _ym_arg(inp, "compare_to")
    compare = inp.get("compare") or "yoy"
    if compare not in sd.CMP_KINDS:
        raise DashToolError(f"compare 는 {list(sd.CMP_KINDS)} 중 하나입니다.")
    brand = inp.get("brand")
    if brand is not None and not isinstance(brand, str):
        raise DashToolError("brand 는 문자열입니다.")
    sections = inp.get("sections") or DEFAULT_SECTIONS
    if not isinstance(sections, list) or any(s not in SECTIONS for s in sections):
        raise DashToolError(f"sections 는 {list(SECTIONS)} 중에서 고릅니다.")
    sections = list(dict.fromkeys(sections))
    try:
        d = sd.dashboard(ym, ym_from, compare, cmp_from, cmp_to, brand, allowed=allowed)
        pr = (sp.analyze(ym, ym_from, compare, cmp_from, cmp_to, brand, allowed=allowed)
              if PRODUCT_SECTIONS & set(sections) else None)
    except HTTPException as ex:
        raise DashToolError(ex.detail.get("message", str(ex.detail)) if isinstance(ex.detail, dict) else str(ex.detail))

    result: dict[str, Any] = {
        "period": d["period"]["label"], "compareBase": f"{d['base']['kindLabel']} {d['base']['label']}",
        "secondaryCompare": f"{d['extra']['label']} {d['extra']['period']}", "brand": d["brand"] or "전체",
        "basis": "마감 매출(실판금액) 기준, 월×매장 사전 집계. 원가율 = 원가 금액(제조원가×수량) ÷ 실판금액. "
                 "baseAmt/change 는 비교 기준, extraAmt/extraChange 는 보조 비교",
        "availableMonths": d["months"][:24], "brandOptions": d["brandOptions"],
    }
    if "kpi" in sections:
        result["kpi"] = {**d["kpi"], "sellingShops": d["shopCounts"]["selling"], "newShops": d["shopCounts"]["new"]}
        if not d["hasGoals"]:
            result["goalNote"] = "이 기간의 목표 데이터가 없습니다."
    if "trend" in sections:
        result["trend"] = d["trend"]
    if "brands" in sections:
        result["brands"] = d["brands"]
    if "teams" in sections:
        result["teams"] = d["teams"]
    if "top_shops" in sections:
        result["topShops"] = _shops(d["topShops"])
    if "risers" in sections or "fallers" in sections:
        result["growthRule"] = (f"비교 기간 실판금액 {d['minBaseForGrowth']:,}원 이상 매장만, "
                                f"폐점·종료 표시 매장 {d['shopCounts']['closedExcluded']}개 제외")
    for sec, key in (("risers", "risers"), ("fallers", "fallers"), ("laggards", "laggards")):
        if sec in sections:
            result[key] = _shops(d[key])
    if pr is not None:
        if pr.get("unavailable"):
            result["productNote"] = pr["unavailable"]
        else:
            if "products" in sections:
                result["products"] = {k: v for k, v in pr["rankings"].items()}
                result["productRule"] = f"할인율 순위는 기간 실판금액 {pr['minAmtForDsctRank']:,}원 이상 상품만, 상품 수 {pr['productCount']:,}"
            if "items" in sections:
                result["items"], result["productGroups"] = pr["items"][:30], pr["groups"][:30]
            if "sales_types" in sections:
                result["salesTypes"], result["salesTypeTrend"] = pr["salesTypes"], pr["salesTypeTrend"]

    # 화면 표: 한 부분만 요청했으면 그 표, 아니면 핵심 지표 표
    only = sections[0] if len(sections) == 1 else "kpi"
    base_col = f"비교({d['base']['label']})"
    if only == "kpi":
        table = {"columns": [{"key": "ITEM", "label": "항목"}, {"key": "CUR", "label": d["period"]["label"]},
                             {"key": "BASE_LABEL", "label": "비교 기준"}, {"key": "BASE", "label": "비교 값"},
                             {"key": "CHANGE", "label": "증감"}], "rows": _kpi_table(d)}
    elif only == "trend":
        table = {"columns": [{"key": "ym", "label": "판매년월"}, {"key": "amt", "label": "실판금액"}, {"key": "prevAmt", "label": "전년 같은 달"},
                             {"key": "yoy", "label": "전년 대비(%)"}, {"key": "costRate", "label": "원가율(%)"}, {"key": "shops", "label": "매장 수"}],
                 "rows": d["trend"]}
    elif only in ("brands", "teams"):
        first = [{"key": "brand", "label": "브랜드"}] + ([{"key": "team", "label": "팀"}] if only == "teams" else [])
        table = {"columns": first + [{"key": "amt", "label": "실판금액"}, {"key": "baseAmt", "label": base_col},
                                     {"key": "change", "label": "증감(%)"}, {"key": "costRate", "label": "원가율(%)"},
                                     {"key": "shops", "label": "매장 수"}, {"key": "goalAmt", "label": "목표금액"},
                                     {"key": "achieve", "label": "달성률(%)"}], "rows": d[only]}
    elif only in PRODUCT_SECTIONS and (pr is None or pr.get("unavailable")):
        table = None
    elif only == "products":
        table = {"columns": [{"key": "prdtCd", "label": "품번"}, {"key": "itemNm", "label": "아이템"}, {"key": "prdtGrpNm", "label": "품군"},
                             {"key": "amt", "label": "실판금액"}, {"key": "qty", "label": "수량"}, {"key": "dsctRate", "label": "할인율(%)"},
                             {"key": "share", "label": "비중(%)"}], "rows": pr["rankings"]["amt"]}
    elif only in ("items", "sales_types"):
        rows = pr["items"] if only == "items" else pr["salesTypes"]
        table = {"columns": [{"key": "name", "label": "아이템" if only == "items" else "판매형태"}, {"key": "amt", "label": "실판금액"},
                             {"key": "baseAmt", "label": base_col}, {"key": "change", "label": "증감(%)"}, {"key": "share", "label": "비중(%)"},
                             {"key": "baseShare", "label": "비교 비중(%)"}, {"key": "dsctRate", "label": "할인율(%)"}], "rows": rows}
    else:
        key = {"top_shops": "topShops", "risers": "risers", "fallers": "fallers", "laggards": "laggards"}[only]
        table = {"columns": [{"key": "rank", "label": "순위"}, {"key": "shopNm", "label": "매장명"}, {"key": "shopId", "label": "매장코드"},
                             {"key": "brand", "label": "브랜드"}, {"key": "amt", "label": "실판금액"}, {"key": "baseAmt", "label": base_col},
                             {"key": "change", "label": "증감(%)"}, {"key": "goalAmt", "label": "목표금액"},
                             {"key": "achieve", "label": "달성률(%)"}], "rows": result[key]}
    return {"result": result, "table": table}
