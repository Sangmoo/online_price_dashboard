"""Claude 조회 도구: 매장 정보 (브랜드 · 팀 · 담당 영업직원 · 운영상태 · 오픈/폐점일).

판매 현황 · 월별 매장별 판매 집계 · 매장 재고 실사계획 중 하나라도 권한이 있으면 쓸 수 있다.
브랜드 데이터 권한이 있는 사용자는 허용 브랜드 매장만 보인다.
"""
from __future__ import annotations

from typing import Any

from . import shop_info

MAX_ROWS = 300
GROUPS = {"REP": ("repNm", "담당 영업직원"), "TEAM": ("teamNm", "팀"), "BRAND": ("brand", "브랜드"), "STATUS": ("status", "운영상태")}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_shops",
        "description": (
            "매장 정보를 조회합니다: 매장코드·매장명·브랜드(쉬즈미스/리스트/시스티나)·팀·담당 영업직원(사번·이름)·운영상태(정상/가폐점/폐점)·오픈일·폐점일. "
            "'○○ 매장 담당자가 누구야', '김○○ 담당 매장', '쉬즈3팀 매장 목록', '영업직원별 담당 매장 수', '최근 오픈/폐점한 매장' 같은 질문에 씁니다. "
            "기본은 영업 중(정상·가폐점) 매장만이고, 폐점 매장까지 보려면 include_closed=true. "
            "group_by 를 주면 그 기준의 매장 수를 셉니다(REP=영업직원, TEAM=팀, BRAND=브랜드, STATUS=운영상태). "
            "판매 실적이 필요하면 이 도구로 매장코드를 찾은 뒤 판매 도구(sum_sales_shop_month, get_sales_dashboard)에 넘기세요. "
            "원천: T_SHOP_BRD + T_SHOP (회사 A01C01), 팀명 T_COMN_CD, 영업직원명 T_EMP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "shop_ids": {"type": "array", "items": {"type": "string"}, "description": "매장코드 목록 (정확히 일치)"},
                "shop_nm": {"type": "string", "description": "매장명 부분 일치"},
                "rep": {"type": "string", "description": "담당 영업직원 이름 부분 일치 또는 사번"},
                "team": {"type": "string", "description": "팀명 부분 일치 (예: 쉬즈3팀, 리스트)"},
                "brand": {"type": "string", "enum": list(shop_info.BRAND_CODES.values()), "description": "브랜드"},
                "include_closed": {"type": "boolean", "description": "폐점 매장 포함 (기본 false)"},
                "group_by": {"type": "string", "enum": list(GROUPS), "description": "매장 수 집계 기준 (생략 시 매장 목록)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOL_LABELS = {"search_shops": "매장 정보"}


class ShopToolError(ValueError):
    pass


def _text(inp: dict, key: str) -> str | None:
    v = inp.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ShopToolError(f"{key} 는 문자열입니다.")
    return v.strip() or None


def run(name: str, inp: dict, allowed: list[str] | None = None) -> dict:
    if name != "search_shops":
        raise ShopToolError(f"알 수 없는 도구: {name}")
    ids = inp.get("shop_ids")
    if ids is not None and (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(ids) > 500):
        raise ShopToolError("shop_ids 는 문자열 배열(최대 500개)입니다.")
    brand = _text(inp, "brand")
    if brand and brand not in shop_info.BRAND_CODES.values():
        raise ShopToolError(f"brand 는 {list(shop_info.BRAND_CODES.values())} 중 하나입니다.")
    if brand and allowed is not None and brand not in allowed:
        raise ShopToolError(f"'{brand}' 브랜드 조회 권한이 없습니다. 볼 수 있는 브랜드: {', '.join(allowed)}")
    group_by = inp.get("group_by")
    if group_by is not None and group_by not in GROUPS:
        raise ShopToolError(f"group_by 는 {list(GROUPS)} 중 하나입니다.")
    rows = shop_info.search(shop_ids=ids, shop_nm=_text(inp, "shop_nm"), rep=_text(inp, "rep"), team=_text(inp, "team"),
                            brand=brand, include_closed=bool(inp.get("include_closed")), allowed=allowed)
    scope = "폐점 포함 전체 매장" if inp.get("include_closed") else "영업 중(정상·가폐점) 매장"
    if group_by:
        key, label = GROUPS[group_by]
        counts: dict[str, set] = {}
        for r in rows:
            counts.setdefault(r[key] or "(없음)", set()).add(r["shopId"])
        out = sorted(({"GROUP": k, "SHOP_CNT": len(v)} for k, v in counts.items()), key=lambda x: -x["SHOP_CNT"])
        return {"result": {"scope": scope, "group_by": label, "groups": out, "total_shops": len({r["shopId"] for r in rows})},
                "table": {"columns": [{"key": "GROUP", "label": label}, {"key": "SHOP_CNT", "label": "매장 수"}], "rows": out}}
    total = len(rows)
    shown = [{"SHOP_ID": r["shopId"], "SHOP_NM": r["shopNm"], "BRAND": r["brand"], "TEAM_NM": r["teamNm"], "REP_ID": r["repId"],
              "REP_NM": r["repNm"], "STATUS": r["status"], "OPEN_DT": r["openDt"], "CLOSE_DT": r["closeDt"]} for r in rows[:MAX_ROWS]]
    cols = [("SHOP_ID", "매장코드"), ("SHOP_NM", "매장명"), ("BRAND", "브랜드"), ("TEAM_NM", "팀"), ("REP_ID", "영업직원 사번"),
            ("REP_NM", "담당 영업직원"), ("STATUS", "운영상태"), ("OPEN_DT", "오픈일"), ("CLOSE_DT", "폐점일")]
    return {"result": {"scope": scope, "total_matched": total, "returned": len(shown), "rows": shown},
            "table": {"columns": [{"key": k, "label": v} for k, v in cols], "rows": shown, "totalMatched": total}}
