"""Claude 가 호출하는 데이터 조회 도구.

모델이 SQL 을 직접 작성하지 않도록, 화이트리스트된 컬럼/연산만 허용하는
파라미터 기반 쿼리 빌더로 T_SELECT_ONLINE_MNG_R 만 조회한다.
재고 실사계획 도구는 chat_tools_invt 에 있고, 사용자 메뉴 권한에 따라 제공 여부가 결정된다(tools_for/run_tool).
"""
from __future__ import annotations

from typing import Any

from . import data_service as ds
from . import db

TABLE = ds.TABLE
DC_RATE_SQL = ds.DC_RATE_SQL
MAX_LIMIT = 200

GROUP_COLS = {
    "DT": "DT",
    "PRDT_CD": "PRDT_CD",
    "MALL_NM": "MALL_NM",
    "NAVER_PAY_SELL_NO": "NAVER_PAY_SELL_NO",
    "TITLE": "TITLE",
}
METRICS = {
    "ROW_CNT": "COUNT(*)",
    "PRDT_CNT": "COUNT(DISTINCT PRDT_CD)",
    "MALL_CNT": "COUNT(DISTINCT MALL_NM)",
    "SELLER_CNT": "COUNT(DISTINCT NAVER_PAY_SELL_NO)",
    "AVG_PRICE": "ROUND(AVG(PRICE), 0)",
    "AVG_DC_PRICE": "ROUND(AVG(DC_PRICE), 0)",
    "MIN_DC_PRICE": "MIN(DC_PRICE)",
    "MAX_DC_PRICE": "MAX(DC_PRICE)",
    "AVG_DC_RATE": f"ROUND(AVG({DC_RATE_SQL}), 2)",
    "MAX_DC_RATE": f"MAX({DC_RATE_SQL})",
    "MIN_DC_RATE": f"MIN({DC_RATE_SQL})",
}
METRIC_LABELS = {
    "DT": "수집일", "PRDT_CD": "상품코드", "MALL_NM": "사이트명", "NAVER_PAY_SELL_NO": "판매자ID", "TITLE": "TITLE",
    "ROW_CNT": "건수", "PRDT_CNT": "상품수", "MALL_CNT": "사이트수", "SELLER_CNT": "판매자수",
    "AVG_PRICE": "평균 기준가", "AVG_DC_PRICE": "평균 할인가", "MIN_DC_PRICE": "최저 할인가",
    "MAX_DC_PRICE": "최고 할인가", "AVG_DC_RATE": "평균 할인율(%)", "MAX_DC_RATE": "최대 할인율(%)",
    "MIN_DC_RATE": "최소 할인율(%)",
}
ROW_COLS = [k for k, _ in ds.COLUMNS]
ROW_LABELS = dict(ds.COLUMNS)

_FILTER_PROPS = {
    "date_from": {"type": "string", "description": "조회 시작 수집일 YYYYMMDD"},
    "date_to": {"type": "string", "description": "조회 종료 수집일 YYYYMMDD (시작일 포함 최대 31일)"},
    "prdt_cd": {"type": "string", "description": "상품코드. 정확히 일치. '%' 포함 시 LIKE 패턴(예: 'TAJT%')"},
    "mall_nm": {"type": "string", "description": "사이트명 부분 일치(대소문자 무시). 예: 'SSG', '쿠팡'"},
    "title_contains": {"type": "string", "description": "TITLE(상품명) 부분 일치"},
    "rmk_contains": {"type": "string", "description": "매장정보(RMK) 부분 일치"},
    "seller_id": {"type": "string", "description": "판매자ID(NAVER_PAY_SELL_NO) 정확히 일치"},
    "min_dc_rate": {"type": "number", "description": "할인율(%) 하한 (이상)"},
    "max_dc_rate": {"type": "number", "description": "할인율(%) 상한 (이하)"},
    "min_dc_price": {"type": "number", "description": "사이트 할인가 하한"},
    "max_dc_price": {"type": "number", "description": "사이트 할인가 상한"},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_collection_dates",
        "description": "데이터가 존재하는 수집일(DT) 목록과 일자별 수집 건수를 최근 순으로 반환합니다. 사용 가능한 날짜 범위를 모를 때 먼저 호출하세요.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "eager_input_streaming": True,
    },
    {
        "name": "aggregate_prices",
        "description": (
            "수집 데이터를 필터링한 뒤 지정 컬럼으로 그룹핑하여 집계합니다. "
            "group_by 를 비우면 전체 합계 1행을 반환합니다. 모든 지표(건수, 상품수, 사이트수, 판매자수, 평균/최저/최고 할인가, "
            "평균/최대/최소 할인율)가 항상 함께 반환됩니다. 할인율(%) = (기준가-사이트할인가)/기준가*100."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPS,
                "group_by": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(GROUP_COLS)},
                    "description": "그룹핑 컬럼 (0~3개)",
                },
                "order_by": {"type": "string", "enum": list(GROUP_COLS) + list(METRICS), "description": "정렬 기준"},
                "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                "min_rows": {"type": "integer", "description": "그룹별 최소 수집 건수(HAVING COUNT(*) >= n). 표본이 적은 그룹 제외용"},
                "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 50)"},
            },
            "required": ["date_from", "date_to"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "search_price_rows",
        "description": (
            "필터 조건에 맞는 개별 수집 행(원본 데이터)을 조회합니다. 반환 컬럼: ONLINE_ID, 수집일, 상품코드, 기준가, "
            "사이트_할인가, 할인율(%), 사이트명, TITLE, 매장정보, 수집시간, 판매자ID, URL. total_matched 에 전체 일치 건수가 포함됩니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPS,
                "order_by": {"type": "string", "enum": ROW_COLS, "description": "정렬 컬럼"},
                "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 30)"},
            },
            "required": ["date_from", "date_to"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]

TOOL_LABELS = {
    "list_collection_dates": "수집일 목록 조회",
    "aggregate_prices": "데이터 집계",
    "search_price_rows": "원본 데이터 검색",
}


class ToolInputError(ValueError):
    pass


def _build_where(inp: dict) -> tuple[str, dict]:
    if not isinstance(inp.get("date_from"), str) or not isinstance(inp.get("date_to"), str):
        raise ToolInputError("date_from, date_to (YYYYMMDD 문자열)는 필수입니다.")
    try:
        s, e = ds.validate_range(inp["date_from"], inp["date_to"])
    except ValueError as ex:
        raise ToolInputError(str(ex))
    conds = ["DT BETWEEN :d_from AND :d_to"]
    p: dict[str, Any] = {"d_from": s, "d_to": e}

    def text(name):
        v = inp.get(name)
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise ToolInputError(f"{name} 는 문자열이어야 합니다.")
        return v.strip()

    def number(name):
        v = inp.get(name)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ToolInputError(f"{name} 는 숫자여야 합니다.")
        return v

    if (v := text("prdt_cd")) is not None:
        conds.append("PRDT_CD LIKE :prdt" if "%" in v else "PRDT_CD = :prdt")
        p["prdt"] = v
    if (v := text("mall_nm")) is not None:
        conds.append("INSTR(UPPER(MALL_NM), UPPER(:mall)) > 0")
        p["mall"] = v
    if (v := text("title_contains")) is not None:
        conds.append("INSTR(UPPER(TITLE), UPPER(:title)) > 0")
        p["title"] = v
    if (v := text("rmk_contains")) is not None:
        conds.append("INSTR(UPPER(RMK), UPPER(:rmk)) > 0")
        p["rmk"] = v
    if (v := text("seller_id")) is not None:
        conds.append("NAVER_PAY_SELL_NO = :seller")
        p["seller"] = v
    if (v := number("min_dc_rate")) is not None:
        conds.append(f"{DC_RATE_SQL} >= :min_rate")
        p["min_rate"] = v
    if (v := number("max_dc_rate")) is not None:
        conds.append(f"{DC_RATE_SQL} <= :max_rate")
        p["max_rate"] = v
    if (v := number("min_dc_price")) is not None:
        conds.append("DC_PRICE >= :min_price")
        p["min_price"] = v
    if (v := number("max_dc_price")) is not None:
        conds.append("DC_PRICE <= :max_price")
        p["max_price"] = v
    return " AND ".join(conds), p


def _limit(inp: dict, default: int) -> int:
    v = inp.get("limit", default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ToolInputError("limit 는 정수여야 합니다.")
    return max(1, min(int(v), MAX_LIMIT))


def _order_dir(inp: dict) -> str:
    d = inp.get("order_dir", "desc")
    if d not in ("asc", "desc"):
        raise ToolInputError("order_dir 는 asc 또는 desc 입니다.")
    return d.upper()


def _clean(rows: list[dict]) -> list[dict]:
    return [{k: (v if isinstance(v, str) or v is None else ds._num(v)) for k, v in r.items()} for r in rows]


def _run_price_tool(name: str, inp: Any) -> dict:
    """온라인 가격 도구 실행. 반환: {"result": 모델에 전달할 dict, "table": 화면 표시용 표(옵션)}"""
    if not isinstance(inp, dict):
        raise ToolInputError("입력은 JSON 객체여야 합니다.")

    if name == "list_collection_dates":
        dates = ds.available_dates()
        return {"result": {"dates": dates}}

    if name == "aggregate_prices":
        where, p = _build_where(inp)
        group_by = inp.get("group_by") or []
        if not isinstance(group_by, list) or any(g not in GROUP_COLS for g in group_by) or len(group_by) > 3:
            raise ToolInputError(f"group_by 는 {list(GROUP_COLS)} 중 최대 3개입니다.")
        group_by = list(dict.fromkeys(group_by))
        order_by = inp.get("order_by") or ("ROW_CNT" if group_by else None)
        if order_by is not None and order_by not in GROUP_COLS and order_by not in METRICS:
            raise ToolInputError("order_by 값이 올바르지 않습니다.")
        if order_by in GROUP_COLS and order_by not in group_by:
            raise ToolInputError("order_by 로 그룹 컬럼을 쓰려면 group_by 에 포함되어야 합니다.")
        limit = _limit(inp, 50)
        select = [GROUP_COLS[g] for g in group_by] + [f"{expr} AS {alias}" for alias, expr in METRICS.items()]
        sql = f"SELECT {', '.join(select)} FROM {TABLE} WHERE {where}"
        if group_by:
            sql += " GROUP BY " + ", ".join(GROUP_COLS[g] for g in group_by)
            min_rows = inp.get("min_rows")
            if min_rows is not None:
                if isinstance(min_rows, bool) or not isinstance(min_rows, (int, float)):
                    raise ToolInputError("min_rows 는 정수여야 합니다.")
                sql += " HAVING COUNT(*) >= :min_rows"
                p["min_rows"] = int(min_rows)
        if order_by:
            sql += f" ORDER BY {order_by} {_order_dir(inp)} NULLS LAST"
        sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit + 1}"
        rows = _clean(db.query_dicts(sql, p))
        truncated = len(rows) > limit
        rows = rows[:limit]
        cols = group_by + list(METRICS)
        return {
            "result": {"row_count": len(rows), "truncated": truncated, "rows": rows},
            "table": {
                "columns": [{"key": c, "label": METRIC_LABELS[c]} for c in cols],
                "rows": rows,
            },
        }

    if name == "search_price_rows":
        where, p = _build_where(inp)
        order_by = inp.get("order_by") or "DC_RATE"
        if order_by not in ROW_COLS:
            raise ToolInputError("order_by 값이 올바르지 않습니다.")
        limit = _limit(inp, 30)
        total = db.query(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}", p)[1][0][0]
        sql = f"""
            SELECT * FROM (
                SELECT ONLINE_ID, DT, PRDT_CD, PRICE, DC_PRICE, {DC_RATE_SQL} AS DC_RATE, MALL_NM, TITLE,
                       RMK, INS_DAY, NAVER_PAY_SELL_NO, URL
                  FROM {TABLE} WHERE {where}
                 ORDER BY {order_by} {_order_dir(inp)} NULLS LAST
            ) WHERE ROWNUM <= {limit}
        """
        rows = _clean(db.query_dicts(sql, p))
        return {
            "result": {"total_matched": int(total), "returned": len(rows), "rows": rows},
            "table": {
                "columns": [{"key": c, "label": ROW_LABELS[c]} for c in ROW_COLS],
                "rows": rows,
                "totalMatched": int(total),
            },
        }

    raise ToolInputError(f"알 수 없는 도구: {name}")


# ----------------------------------------------------------------------------
# 도구 레지스트리 (메뉴 권한 연동)
# ----------------------------------------------------------------------------
from . import chat_tools_invt as invt  # noqa: E402
from . import chat_tools_sale as sale  # noqa: E402

PRICE_PAGES = {"dashboard", "detail"}   # 온라인 가격 데이터 메뉴
SALE_PAGES = {"sale_monthly"}           # 월별 매장별 판매 집계 메뉴
INVT_PAGES = {"invt_plan"}              # 매장 재고 실사계획 메뉴
TOOL_LABELS.update(invt.TOOL_LABELS)
TOOL_LABELS.update(sale.TOOL_LABELS)
_PRICE_TOOL_NAMES = {t["name"] for t in TOOLS}
_INVT_TOOL_NAMES = {t["name"] for t in invt.TOOLS}
_SALE_TOOL_NAMES = {t["name"] for t in sale.TOOLS}


def data_scopes(me: dict) -> dict[str, bool]:
    pages = set(me.get("pages") or [])
    return {"price": bool(pages & PRICE_PAGES), "invt": bool(pages & INVT_PAGES), "sale": bool(pages & SALE_PAGES)}


def tools_for(me: dict) -> list[dict]:
    """사용자가 권한을 가진 메뉴의 데이터 도구만 모델에 제공."""
    sc = data_scopes(me)
    return (TOOLS if sc["price"] else []) + (sale.TOOLS if sc["sale"] else []) + (invt.TOOLS if sc["invt"] else [])


def run_tool(name: str, inp: Any, me: dict) -> dict:
    """도구 실행. 모델에 제공하지 않은 도구라도 여기서 한 번 더 권한을 확인한다."""
    if not isinstance(inp, dict):
        raise ToolInputError("입력은 JSON 객체여야 합니다.")
    sc = data_scopes(me)
    if name in _PRICE_TOOL_NAMES:
        if not sc["price"]:
            raise ToolInputError("이 사용자는 온라인 가격 메뉴 권한이 없어 조회할 수 없습니다.")
        return _run_price_tool(name, inp)
    if name in _INVT_TOOL_NAMES:
        if not sc["invt"]:
            raise ToolInputError("이 사용자는 매장 재고 실사계획 메뉴 권한이 없어 조회할 수 없습니다.")
        try:
            return invt.run(name, inp)
        except invt.InvtToolError as ex:
            raise ToolInputError(str(ex))
    if name in _SALE_TOOL_NAMES:
        if not sc["sale"]:
            raise ToolInputError("이 사용자는 월별 매장별 판매 집계 메뉴 권한이 없어 조회할 수 없습니다.")
        try:
            return sale.run(name, inp)
        except sale.SaleToolError as ex:
            raise ToolInputError(str(ex))
    raise ToolInputError(f"알 수 없는 도구: {name}")
