"""Claude 조회 도구: 데이터 관리 > 매장 재고 실사계획 (T_SHOP_INVT_PLAN).

chat_tools 와 같은 원칙: 모델은 SQL 을 쓰지 않고, 화이트리스트된 컬럼·조건·집계만 파라미터로 지정한다.
삭제(소프트 삭제)된 계획은 항상 제외한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import db
from . import tool_limits
from . import invt_plan as ip

TABLE = ip.TABLE
MAX_LIMIT = 200

ELAPSED_SQL = ("CASE WHEN REGEXP_LIKE(LAST_INVT_DT, '^[0-9]{8}$') "
               "THEN TRUNC(SYSDATE) - TO_DATE(LAST_INVT_DT, 'YYYYMMDD') END")

# 그룹핑 가능 컬럼 (별칭 → SQL)
GROUP_COLS = {
    "BRD_NM": "BRD_NM",
    "SHOP_FORM_NM": "SHOP_FORM_NM",
    "REGION_NM": "REGION_NM",
    "AREA_NM": "AREA_NM",
    "STLM_TEAM": "STLM_TEAM",
    "PREV_INVT_TYPE": "PREV_INVT_TYPE",
    "SHOP_RANK_NM": "SHOP_RANK_NM",
    "TWICE_YEAR_YN": "TWICE_YEAR_YN",
    "PLAN_MONTH": "SUBSTR(INVT_PLAN_DT, 1, 6)",      # 실사예정 월 (NULL = 미정)
    "LAST_INVT_YEAR": "SUBSTR(LAST_INVT_DT, 1, 4)",  # 최종실사 연도
}
METRICS = {
    "PLAN_CNT": "COUNT(*)",
    "SHOP_CNT": "COUNT(DISTINCT SHOP_ID)",
    "PLAN_SET_CNT": "COUNT(INVT_PLAN_DT)",
    "PLAN_UNSET_CNT": "SUM(CASE WHEN INVT_PLAN_DT IS NULL THEN 1 ELSE 0 END)",
    "TWICE_YEAR_CNT": "SUM(CASE WHEN TWICE_YEAR_YN = 'Y' THEN 1 ELSE 0 END)",
    "BASE_FEE_SUM": "SUM(BASE_FEE)",
    "EXPECT_AMT_SUM": "SUM(EXPECT_AMT)",
    "TOTAL_COST_SUM": "SUM(NVL(BASE_FEE, 0) + NVL(EXPECT_AMT, 0))",
    "STOCK_QTY_SUM": "SUM(STOCK_QTY)",
    "AVG_ELAPSED_DAYS": f"ROUND(AVG({ELAPSED_SQL}), 0)",
    "MAX_ELAPSED_DAYS": f"MAX({ELAPSED_SQL})",
    "PREV_SALE_SUM_MIL": "ROUND(SUM(PREV_SALE_AMT) / 1000000)",
    "CURR_SALE_SUM_MIL": "ROUND(SUM(CURR_SALE_AMT) / 1000000)",
}
LABELS = {
    "BRD_NM": "브랜드", "SHOP_FORM_NM": "유통", "REGION_NM": "권역", "AREA_NM": "지역", "STLM_TEAM": "정산 팀구분",
    "PREV_INVT_TYPE": "전실사유형", "SHOP_RANK_NM": "관리등급", "TWICE_YEAR_YN": "연2회", "PLAN_MONTH": "실사예정월",
    "LAST_INVT_YEAR": "최종실사연도",
    "PLAN_CNT": "계획 건수", "SHOP_CNT": "매장 수", "PLAN_SET_CNT": "예정일 확정", "PLAN_UNSET_CNT": "예정일 미정",
    "TWICE_YEAR_CNT": "연2회 매장", "BASE_FEE_SUM": "기본료 합계", "EXPECT_AMT_SUM": "실사예상액 합계",
    "TOTAL_COST_SUM": "업체 예상 비용 합계", "STOCK_QTY_SUM": "재고 수량 합계", "AVG_ELAPSED_DAYS": "평균 경과일",
    "MAX_ELAPSED_DAYS": "최대 경과일", "PREV_SALE_SUM_MIL": "전년 매출 합계(백만원)", "CURR_SALE_SUM_MIL": "당년 매출 합계(백만원)",
}

# 원본 행 조회 컬럼 (별칭, SQL, 라벨)
ROW_COLS: list[tuple[str, str, str]] = [
    ("PLAN_ID", "PLAN_ID", "계획ID"),
    ("SHOP_ID", "SHOP_ID", "매장코드"),
    ("BRD_NM", "BRD_NM", "브랜드"),
    ("SHOP_FORM_NM", "SHOP_FORM_NM", "유통"),
    ("SHOP_NM", "SHOP_NM", "매장명"),
    ("PREV_SALE_MIL", "ROUND(PREV_SALE_AMT / 1000000)", "전년 매출(백만원)"),
    ("CURR_SALE_MIL", "ROUND(CURR_SALE_AMT / 1000000)", "당년 매출(백만원)"),
    ("SALE_RATE", "ROUND((CURR_SALE_AMT / NULLIF(PREV_SALE_AMT, 0) - 1) * 100, 1)", "증감율(%)"),
    ("ADDR", "ADDR", "주소"),
    ("AREA_NM", "AREA_NM", "지역"),
    ("REGION_NM", "REGION_NM", "권역"),
    ("LAST_INVT_DT", "LAST_INVT_DT", "최종실사일"),
    ("PREV_INVT_TYPE", "PREV_INVT_TYPE", "전실사유형"),
    ("PREV_INVT_RESULT", "PREV_INVT_RESULT", "전실사결과"),
    ("ELAPSED_DAYS", ELAPSED_SQL, "경과일"),
    ("STOCK_QTY", "STOCK_QTY", "재고 수량"),
    ("INVT_PLAN_NOTE", "INVT_PLAN_NOTE", "실사예정"),
    ("BASE_FEE", "BASE_FEE", "기본료"),
    ("EXPECT_AMT", "EXPECT_AMT", "실사예상액"),
    ("INVT_PLAN_DT", "INVT_PLAN_DT", "실사예정일"),
    ("RMK", "RMK", "비고"),
    ("TWICE_YEAR_YN", "TWICE_YEAR_YN", "연2회"),
    ("SHOP_RANK_NM", "SHOP_RANK_NM", "관리등급"),
    ("STLM_TEAM", "STLM_TEAM", "정산 팀구분"),
    ("SMASR_NM", "SMASR_NM", "매니저"),
    ("SMASR_HP", "SMASR_HP", "매니저 전화"),
    ("SHOP_TEL", "SHOP_TEL", "매장번호"),
]
ROW_SQL = {a: s for a, s, _ in ROW_COLS}

_FILTER_PROPS: dict[str, Any] = {
    "shop_id": {"type": "string", "description": "매장코드 정확히 일치 (예: S31019)"},
    "shop_nm": {"type": "string", "description": "매장명 부분 일치"},
    "brd_nm": {"type": "string", "enum": ["쉬즈미스", "리스트", "시스티나"], "description": "브랜드"},
    "shop_form_nm": {"type": "string", "description": "유통 부분 일치 (예: 백화점, 아울렛)"},
    "region_nm": {"type": "string", "enum": ip.REGIONS, "description": "권역"},
    "area_nm": {"type": "string", "enum": ip.AREAS, "description": "지역(시도)"},
    "stlm_team": {"type": "string", "enum": ip.STLM_TEAMS + ["미지정"], "description": "정산 팀구분"},
    "prev_invt_type": {"type": "string", "enum": ip.INVT_TYPES, "description": "전실사유형"},
    "plan_status": {"type": "string", "enum": ["set", "unset"], "description": "set=실사예정일 확정, unset=미정"},
    "plan_dt_from": {"type": "string", "description": "실사예정일 시작 YYYYMMDD"},
    "plan_dt_to": {"type": "string", "description": "실사예정일 종료 YYYYMMDD"},
    "last_invt_from": {"type": "string", "description": "최종실사일 시작 YYYYMMDD"},
    "last_invt_to": {"type": "string", "description": "최종실사일 종료 YYYYMMDD"},
    "min_elapsed_days": {"type": "integer", "description": "최종실사일로부터 경과일 하한 (이상)"},
    "twice_year": {"type": "boolean", "description": "true=연2회 실사 매장만, false=연2회 아닌 매장만"},
    "keyword": {"type": "string", "description": "매장명·주소·실사예정·비고·매니저 부분 일치"},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "aggregate_invt_plans",
        "description": (
            "매장 재고 실사계획(데이터 관리 메뉴)을 필터링한 뒤 그룹별로 집계합니다. group_by 를 비우면 전체 합계 1행. "
            "지표(계획 건수, 매장 수, 예정일 확정/미정, 연2회 매장 수, 기본료·실사예상액·업체 예상 비용 합계, 재고 합계, "
            "평균/최대 경과일, 전년/당년 매출 합계)가 항상 함께 반환됩니다. 금액 단위는 원(매출은 백만원)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPS,
                "group_by": {"type": "array", "items": {"type": "string", "enum": list(GROUP_COLS)},
                             "description": "그룹핑 컬럼 (0~3개). PLAN_MONTH=실사예정월(YYYYMM), LAST_INVT_YEAR=최종실사연도"},
                "order_by": {"type": "string", "enum": list(GROUP_COLS) + list(METRICS)},
                "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 50)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "search_invt_plans",
        "description": (
            "매장 재고 실사계획의 개별 행을 조회합니다. 반환: 매장코드·브랜드·유통·매장명·전년/당년 매출(백만원)·증감율·주소·지역·권역·"
            "최종실사일·전실사유형/결과·경과일·재고·실사예정·기본료·실사예상액·실사예정일(NULL=미정)·비고·연2회·관리등급·정산팀·매니저·매장번호. "
            "total_matched 에 전체 일치 건수가 포함됩니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPS,
                "order_by": {"type": "string", "enum": list(ROW_SQL)},
                "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 30)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]

TOOL_LABELS = {
    "aggregate_invt_plans": "실사계획 집계",
    "search_invt_plans": "실사계획 검색",
}


class InvtToolError(ValueError):
    pass


def _text(inp: dict, name: str) -> str | None:
    v = inp.get(name)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise InvtToolError(f"{name} 는 문자열이어야 합니다.")
    return v.strip()


def _date(inp: dict, name: str) -> str | None:
    v = _text(inp, name)
    if v is None:
        return None
    v = v.replace("-", "")
    try:
        datetime.strptime(v, "%Y%m%d")
    except ValueError:
        raise InvtToolError(f"{name} 는 YYYYMMDD 형식이어야 합니다.")
    return v


def _enum(inp: dict, name: str) -> str | None:
    v = _text(inp, name)
    allowed = _FILTER_PROPS[name].get("enum")
    if v is not None and allowed and v not in allowed:
        raise InvtToolError(f"{name} 는 {allowed} 중 하나입니다.")
    return v


def _where(inp: dict) -> tuple[str, dict]:
    conds = ["DEL_DAY IS NULL"]
    p: dict[str, Any] = {}
    if (v := _text(inp, "shop_id")) is not None:
        conds.append("SHOP_ID = :shop_id")
        p["shop_id"] = v.upper()
    if (v := _text(inp, "shop_nm")) is not None:
        conds.append("INSTR(SHOP_NM, :shop_nm) > 0")
        p["shop_nm"] = v
    if (v := _enum(inp, "brd_nm")) is not None:
        conds.append("BRD_NM = :brd_nm")
        p["brd_nm"] = v
    if (v := _text(inp, "shop_form_nm")) is not None:
        conds.append("INSTR(SHOP_FORM_NM, :shop_form_nm) > 0")
        p["shop_form_nm"] = v
    for key, col in (("region_nm", "REGION_NM"), ("area_nm", "AREA_NM"), ("prev_invt_type", "PREV_INVT_TYPE")):
        if (v := _enum(inp, key)) is not None:
            conds.append(f"{col} = :{key}")
            p[key] = v
    if (v := _enum(inp, "stlm_team")) is not None:
        if v == "미지정":
            conds.append("STLM_TEAM IS NULL")
        else:
            conds.append("STLM_TEAM = :stlm_team")
            p["stlm_team"] = v
    if (v := _enum(inp, "plan_status")) is not None:
        conds.append("INVT_PLAN_DT IS NOT NULL" if v == "set" else "INVT_PLAN_DT IS NULL")
    for key, col, op in (("plan_dt_from", "INVT_PLAN_DT", ">="), ("plan_dt_to", "INVT_PLAN_DT", "<="),
                         ("last_invt_from", "LAST_INVT_DT", ">="), ("last_invt_to", "LAST_INVT_DT", "<=")):
        if (v := _date(inp, key)) is not None:
            conds.append(f"{col} {op} :{key}")
            p[key] = v
    if (v := inp.get("min_elapsed_days")) is not None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise InvtToolError("min_elapsed_days 는 정수여야 합니다.")
        conds.append(f"{ELAPSED_SQL} >= :min_elapsed")
        p["min_elapsed"] = int(v)
    if (v := inp.get("twice_year")) is not None:
        if not isinstance(v, bool):
            raise InvtToolError("twice_year 는 true/false 입니다.")
        conds.append("TWICE_YEAR_YN = :twice")
        p["twice"] = "Y" if v else "N"
    if (v := _text(inp, "keyword")) is not None:
        conds.append("(INSTR(SHOP_NM, :kw) > 0 OR INSTR(ADDR, :kw) > 0 OR INSTR(INVT_PLAN_NOTE, :kw) > 0 "
                     "OR INSTR(RMK, :kw) > 0 OR INSTR(SMASR_NM, :kw) > 0)")
        p["kw"] = v
    return " AND ".join(conds), p


def _limit(inp: dict, default: int) -> int:
    v = inp.get("limit", default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise InvtToolError("limit 는 정수여야 합니다.")
    return max(1, min(int(v), tool_limits.cap(MAX_LIMIT)))  # 전체 엑셀일 때만 상한 확대


def _dir(inp: dict) -> str:
    d = inp.get("order_dir", "desc")
    if d not in ("asc", "desc"):
        raise InvtToolError("order_dir 는 asc 또는 desc 입니다.")
    return d.upper()


def _clean(rows: list[dict]) -> list[dict]:
    return [{k: (v if isinstance(v, str) or v is None else ip._num(v)) for k, v in r.items()} for r in rows]


def run(name: str, inp: dict) -> dict:
    if name == "aggregate_invt_plans":
        where, p = _where(inp)
        group_by = inp.get("group_by") or []
        if not isinstance(group_by, list) or any(g not in GROUP_COLS for g in group_by) or len(group_by) > 3:
            raise InvtToolError(f"group_by 는 {list(GROUP_COLS)} 중 최대 3개입니다.")
        group_by = list(dict.fromkeys(group_by))
        order_by = inp.get("order_by") or ("PLAN_CNT" if group_by else None)
        if order_by is not None and order_by not in METRICS and order_by not in group_by:
            raise InvtToolError("order_by 는 지표이거나 group_by 에 포함된 컬럼이어야 합니다.")
        limit = _limit(inp, 50)
        select = [f"{GROUP_COLS[g]} AS {g}" for g in group_by] + [f"{e} AS {a}" for a, e in METRICS.items()]
        sql = f"SELECT {', '.join(select)} FROM {TABLE} WHERE {where}"
        if group_by:
            sql += " GROUP BY " + ", ".join(GROUP_COLS[g] for g in group_by)
        if order_by:
            sql += f" ORDER BY {order_by} {_dir(inp)} NULLS LAST"
        rows = _clean(db.query_dicts(f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit + 1}", p))
        truncated = len(rows) > limit
        rows = rows[:limit]
        cols = group_by + list(METRICS)
        return {
            "result": {"row_count": len(rows), "truncated": truncated, "rows": rows,
                       "note": "PLAN_MONTH/실사예정일이 NULL 이면 미정"},
            "table": {"columns": [{"key": c, "label": LABELS[c]} for c in cols], "rows": rows},
        }

    if name == "search_invt_plans":
        where, p = _where(inp)
        order_by = inp.get("order_by") or "INVT_PLAN_DT"
        if order_by not in ROW_SQL:
            raise InvtToolError("order_by 값이 올바르지 않습니다.")
        order_dir = _dir(inp) if "order_dir" in inp else "ASC"
        limit = _limit(inp, 30)
        total = db.query(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}", p)[1][0][0]
        select = ", ".join(f"{s} AS {a}" for a, s, _ in ROW_COLS)
        rows = _clean(db.query_dicts(
            f"SELECT * FROM (SELECT {select} FROM {TABLE} WHERE {where} "
            f"ORDER BY {ROW_SQL[order_by]} {order_dir} NULLS LAST, SHOP_ID) WHERE ROWNUM <= {limit}", p))
        return {
            "result": {"total_matched": int(total), "returned": len(rows), "rows": rows},
            "table": {"columns": [{"key": a, "label": l} for a, _, l in ROW_COLS], "rows": rows,
                      "totalMatched": int(total)},
        }

    raise InvtToolError(f"알 수 없는 도구: {name}")
