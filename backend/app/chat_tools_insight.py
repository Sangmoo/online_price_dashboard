"""Claude 조회 도구: 판매 현황 화면의 분석 기능을 화면과 같은 계산으로.

- get_season_progress: 시즌 판매 진척 (sale_season.progress) — 판매 현황 또는 월별 판매 집계 메뉴
- find_online_discount_alerts: 온라인 할인 주의 상품 (online_alerts.alerts) — 판매 메뉴 + 온라인 가격 메뉴 둘 다
- get_product_insight: 품번 하나의 온라인 가격 + 매장 판매 + 많이 팔린 매장 — 권한 있는 쪽만 담는다
브랜드 데이터 권한은 화면과 같이 적용한다 (allowed / teams).
"""
from __future__ import annotations

import re
import time
from typing import Any

from fastapi import HTTPException

from . import data_service as ds
from . import online_alerts, sale_products, sale_season
from . import sale_dashboard as sd
from .sale_monthly import SEASONS, _shift_ym

TOOLS_SALE: list[dict[str, Any]] = [
    {
        "name": "get_season_progress",
        "description": (
            "시즌(기획년도+시즌) 판매 진척을 판매 현황 화면의 '시즌 판매 진척'과 같은 계산으로 조회합니다. "
            "'26년 가을 시즌 지금 어디쯤이야', '작년 여름 시즌보다 잘 팔리고 있어?', '이번 시즌 진척률' 같은 질문에 씁니다. "
            "결과: 시즌 시작 월부터 기준 월(ym)까지 월별·누적 실판금액과 수량, 전년 같은 시즌의 같은 시점(12개월 전 같은 달) 누적, "
            "증감률, 진척률(올해 누적 ÷ 전년 시즌 최종 누적), 할인율, 최근 12개월 판매가 있는 시즌 선택지. "
            "plan_yy 와 season 을 함께 주면 그 시즌, 생략하면 기준 월에 가장 많이 팔린 시즌입니다. "
            "시즌은 " + "/".join(SEASONS) + ". 여러 시즌을 비교하려면 시즌마다 한 번씩 호출하세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ym": {"type": "string", "description": "기준 판매년월 YYYYMM (생략 시 최근 마감 월)"},
                "plan_yy": {"type": "string", "description": "기획년도 YYYY (season 과 함께)"},
                "season": {"type": "string", "enum": SEASONS, "description": "시즌 (plan_yy 와 함께)"},
                "brand": {"type": "string", "description": "브랜드 하나 (쉬즈미스·리스트·시스티나, 생략 시 전체)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOLS_ALERT: list[dict[str, Any]] = [
    {
        "name": "find_online_discount_alerts",
        "description": (
            "매장에서 잘 팔리는 상품 중 최근 온라인 할인율이 크게 오른 상품을 찾습니다 (판매 현황 화면의 '온라인 할인 주의 상품'과 같은 기준). "
            "'요즘 온라인에서 할인 많이 들어간 잘 팔리는 상품', '상위 상품 중 온라인 가격 내려간 거' 같은 질문에 씁니다. "
            f"대상: 기간(ym_from~ym, 생략 시 최근 마감 월)의 매장 실판금액 상위 {sale_products.ALERT_TOP_N}개 상품. "
            f"온라인: 오늘 기준 최근 {online_alerts.RECENT_DAYS}일 평균 할인율 vs 그 전 {online_alerts.BASE_DAYS}일 평균 할인율. "
            f"주의(flag): rise = {online_alerts.ALERT_DIFF}%p 이상 상승, new = 이전 수집 없이 최근 {online_alerts.ALERT_NEW}% 이상 할인. "
            "only_alerts=false 면 상위 상품 전체와 온라인 할인율을 돌려줍니다. 온라인 할인율 = (기준가-할인가)/기준가, 매장 할인율 = 할인금액/(실판금액+할인금액)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ym": {"type": "string", "description": "매장 판매 기간 끝 월 YYYYMM (생략 시 최근 마감 월)"},
                "ym_from": {"type": "string", "description": "매장 판매 기간 시작 월 YYYYMM (생략 시 ym 한 달, 최대 12개월)"},
                "brand": {"type": "string", "description": "브랜드 하나 (생략 시 전체)"},
                "only_alerts": {"type": "boolean", "description": "주의 상품만 (기본 true)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOLS_PRODUCT: list[dict[str, Any]] = [
    {
        "name": "get_product_insight",
        "description": (
            "품번 하나를 상품 팝업과 같은 내용으로 한 번에 조회합니다: 온라인 가격(최근 31일 일별 평균 할인율·최저가, 마지막 수집일의 사이트별 가격), "
            "매장 판매(최근 12개월 월별 수량·실판금액·할인율), 많이 팔린 매장·팀(최근 3개월). "
            "'TWWJKQ72020 온라인 가격이랑 매장 판매 어때?', '이 상품 어느 매장에서 많이 팔려?' 같은 품번 하나에 대한 질문에 씁니다. "
            "사용자 메뉴 권한에 따라 온라인 쪽(온라인 가격 메뉴) 또는 매장 쪽(판매 메뉴)만 담길 수 있습니다. "
            "여러 상품 비교나 기간 조건이 필요하면 aggregate_prices / aggregate_sales 를 쓰세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prdt_cd": {"type": "string", "description": "품번(상품코드) 정확히"},
                "parts": {"type": "array", "items": {"type": "string", "enum": ["online", "sales", "shops"]},
                          "description": "받을 부분 (생략 시 권한 있는 전부)"},
            },
            "required": ["prdt_cd"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOLS = TOOLS_SALE + TOOLS_ALERT + TOOLS_PRODUCT
TOOL_LABELS = {"get_season_progress": "시즌 판매 진척", "find_online_discount_alerts": "온라인 할인 주의 상품",
               "get_product_insight": "상품 종합"}
_YM = re.compile(r"^\d{4}-?(0[1-9]|1[0-2])$")
_CD = re.compile(r"^[A-Z0-9_-]{2,20}$")


class InsightToolError(ValueError):
    pass


def _ym(inp: dict, key: str) -> str | None:
    v = inp.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str) or not _YM.match(v.strip()):
        raise InsightToolError(f"{key} 는 YYYYMM 형식입니다.")
    return v.strip().replace("-", "")


def _text(inp: dict, key: str) -> str | None:
    v = inp.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise InsightToolError(f"{key} 는 문자열입니다.")
    return v.strip() or None


def _http(ex: HTTPException) -> InsightToolError:
    d = ex.detail
    return InsightToolError(d.get("message", str(d)) if isinstance(d, dict) else str(d))


def run(name: str, inp: dict, *, allowed: list[str] | None, teams: list[str] | None, can_price: bool, can_sale: bool) -> dict:
    try:
        if name == "get_season_progress":
            return _season(inp, allowed)
        if name == "find_online_discount_alerts":
            return _alerts(inp, allowed)
        if name == "get_product_insight":
            return _product(inp, teams, can_price, can_sale)
    except HTTPException as ex:
        raise _http(ex)
    raise InsightToolError(f"알 수 없는 도구: {name}")


def _season(inp: dict, allowed: list[str] | None) -> dict:
    yy, season = _text(inp, "plan_yy"), _text(inp, "season")
    if bool(yy) != bool(season):
        raise InsightToolError("plan_yy 와 season 은 함께 주거나 둘 다 생략합니다.")
    if yy and not re.match(r"^\d{4}$", yy):
        raise InsightToolError("plan_yy 는 YYYY 형식입니다.")
    if season and season not in SEASONS:
        raise InsightToolError(f"season 은 {SEASONS} 중 하나입니다.")
    d = sale_season.progress(_ym(inp, "ym"), _text(inp, "brand"), allowed, yy, season)
    if not d.get("planYy"):
        return {"result": {"note": "최근 12개월 판매가 있는 시즌이 없습니다.", "asOf": d["toLabel"]}, "table": None}
    rows = [{"ym": m["label"], "prevYm": f"{m['prevYm'][:4]}-{m['prevYm'][4:]}", "amt": m["amt"], "cum": m["cum"],
             "prevAmt": m["prevAmt"], "prevCum": m["prevCum"]} for m in d["months"]]
    result = {
        "season": f"{d['planYy']} {d['season']}", "compareSeason": f"{d['prevPlanYy']} {d['season']}", "asOf": d["toLabel"],
        "seasonStart": d["startLabel"], "monthsElapsed": d["step"], "brand": d["brand"] or "전체", "source": d["source"],
        "basis": "같은 시점 = 전년 같은 달까지 누적. 진척률 = 올해 누적 ÷ 전년 시즌 최종 누적(전년 시즌 판매 전체). "
                 "cum 이 null 인 달은 아직 오지 않은 달(전년 흐름만 있음). 금액은 실판금액(원)",
        "kpi": d["kpi"], "months": rows,
        "seasonOptions": [f"{o['planYy']} {o['season']}" for o in d["options"]],
    }
    cols = [("ym", "판매년월"), ("prevYm", "전년 같은 달"), ("amt", "월 실판금액"), ("cum", "누적"), ("prevAmt", "전년 월 실판금액"),
            ("prevCum", "전년 누적")]
    return {"result": result, "table": {"columns": [{"key": k, "label": v} for k, v in cols], "rows": rows}}


def _alerts(inp: dict, allowed: list[str] | None) -> dict:
    only = inp.get("only_alerts")
    if only is not None and not isinstance(only, bool):
        raise InsightToolError("only_alerts 는 true/false 입니다.")
    d = online_alerts.alerts(_ym(inp, "ym"), _ym(inp, "ym_from"), None, None, None, _text(inp, "brand"), allowed)
    if d.get("unavailable"):
        raise InsightToolError(d["unavailable"])
    rows = [{"storeRank": r["rank"], "prdtCd": r["prdtCd"], "itemNm": r["itemNm"], "prdtGrpNm": r["prdtGrpNm"],
             "storeAmt": r["storeAmt"], "storeQty": r["storeQty"], "storeDsctRate": r["storeDsctRate"],
             "onlineRecentRate": (r["online"] or {}).get("recentRate"), "onlineBaseRate": (r["online"] or {}).get("baseRate"),
             "diff": r["diff"], "onlineLowPrice": (r["online"] or {}).get("lowPrice"), "malls": (r["online"] or {}).get("malls"),
             "flag": r["flag"]} for r in d["rows"] if r["flag"] or only is False]
    result = {
        "storePeriod": d["period"], "brand": d["brand"] or "전체",
        "onlineRecent": f"{d['recentFrom']}부터 {d['recentDays']}일", "onlineBase": f"{d['baseFrom']}부터 {d['baseDays']}일",
        "rule": f"매장 실판금액 상위 {d['total']}개 중 온라인 최근 평균 할인율이 이전보다 {d['alertDiff']}%p 이상 상승(rise) "
                f"또는 이전 수집 없이 최근 {d['alertNew']}% 이상(new)",
        "alertCount": d["alertCount"], "withOnline": d["withOnline"], "rows": rows,
    }
    cols = [("storeRank", "매장 순위"), ("prdtCd", "품번"), ("itemNm", "아이템"), ("storeAmt", "매장 실판금액"),
            ("storeDsctRate", "매장 할인율(%)"), ("onlineRecentRate", "온라인 최근 할인율(%)"), ("onlineBaseRate", "온라인 이전 할인율(%)"),
            ("diff", "변화(%p)"), ("onlineLowPrice", "최근 최저가"), ("malls", "사이트 수")]
    return {"result": result, "table": {"columns": [{"key": k, "label": v} for k, v in cols], "rows": rows}}


def _product(inp: dict, teams: list[str] | None, can_price: bool, can_sale: bool) -> dict:
    cd = (_text(inp, "prdt_cd") or "").upper()
    if not _CD.match(cd):
        raise InsightToolError("prdt_cd 는 품번(영문 대문자·숫자 2~20자)입니다.")
    parts = inp.get("parts") or ["online", "sales", "shops"]
    if not isinstance(parts, list) or any(p not in ("online", "sales", "shops") for p in parts):
        raise InsightToolError("parts 는 online, sales, shops 중에서 고릅니다.")
    result: dict[str, Any] = {"prdtCd": cd}
    notes = []
    table = None
    last = _shift_ym(time.strftime("%Y%m"), -1)
    months = [_shift_ym(last, -i) for i in range(11, -1, -1)]
    if "online" in parts:
        if can_price:
            on = ds.product_online(cd)
            daily = on["daily"]
            result["online"] = {
                "title": on["title"], "lastCollected": on["lastDt"], "days": len(daily),
                "firstAvgDcRate": daily[0]["avgDcRate"] if daily else None, "lastAvgDcRate": daily[-1]["avgDcRate"] if daily else None,
                "lowestDcPrice": min((x["minDcPrice"] for x in daily if x["minDcPrice"]), default=None),
                "daily": daily[-14:], "mallsOnLastDay": on["malls"],
                "basis": "최근 31일 수집, 할인율 = (기준가-할인가)/기준가. daily 는 최근 14일만",
            }
            if not daily:
                notes.append("최근 31일 온라인 수집 기록이 없습니다.")
        else:
            notes.append("온라인 가격 메뉴 권한이 없어 온라인 가격은 뺐습니다.")
    if "sales" in parts or "shops" in parts:
        if not can_sale:
            notes.append("판매 메뉴 권한이 없어 매장 판매는 뺐습니다.")
        else:
            if "sales" in parts:
                sa = sale_products.product_sales(cd, months, teams)
                result["sales"] = {"itemNm": sa["itemNm"], "prdtGrpNm": sa["prdtGrpNm"], "source": sa["source"], "months": sa["months"],
                                   "totalQty": sum(m["qty"] for m in sa["months"]), "totalAmt": sum(m["amt"] for m in sa["months"])}
                table = {"columns": [{"key": "ym", "label": "판매년월"}, {"key": "qty", "label": "수량"}, {"key": "amt", "label": "실판금액"},
                                     {"key": "dsctRate", "label": "할인율(%)"}], "rows": sa["months"]}
            if "shops" in parts:
                sh = sale_products.product_shops(cd, months[-3:], teams)
                result["shops"] = {"period": f"{sd.ym_label(sh['from'])}~{sd.ym_label(sh['to'])}", "shopCount": sh["shopCount"],
                                   "qty": sh["qty"], "amt": sh["amt"], "top10Share": sh["topShare"], "topShops": sh["shops"],
                                   "teams": sh["teams"]}
                if table is None:
                    table = {"columns": [{"key": k, "label": v} for k, v in (("shopId", "매장코드"), ("shopNm", "매장명"), ("team", "팀"),
                                                                              ("qty", "수량"), ("amt", "실판금액"), ("share", "비중(%)"))],
                             "rows": sh["shops"]}
    if notes:
        result["notes"] = notes
    if not any(k in result for k in ("online", "sales", "shops")):
        raise InsightToolError(" ".join(notes) or "조회할 수 있는 부분이 없습니다.")
    return {"result": result, "table": table}
