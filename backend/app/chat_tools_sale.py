"""Claude 조회 도구: 판매 분석 > 월별 매장별 판매 집계 (T_CLOSE_SALE_BASE, 마감 매출 기초 데이터).

chat_tools 와 같은 원칙: 모델은 SQL 을 쓰지 않고, 화이트리스트된 컬럼·조건·집계만 파라미터로 지정한다.
판매년월(ym_from~ym_to)은 필수이며 화면과 같은 최대 기간(sale_monthly.MAX_MONTHS)을 적용한다.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from . import config, db
from . import tool_limits
from . import sale_monthly as sm

TABLE = "T_CLOSE_SALE_BASE"
MAX_LIMIT = 200

# 그룹핑 가능 컬럼 (별칭 → SQL)
GROUP_COLS = {
    "MAKE_YYMM": "MAKE_YYMM",
    "MAKE_YY": "SUBSTR(MAKE_YYMM, 1, 4)",
    "TEAM_CD": "TEAM_CD",
    "SHOP_ID": "SHOP_ID",
    "PLAN_YY": "PLAN_YY",
    "SESS_NM": sm.SESS_EXPR,           # 인덱스(IX_04)와 같은 식이어야 인덱스를 쓴다
    "PRDT_GRP_NM": sm.PRDT_GRP_EXPR,
    "ITEM_NM": "ITEM_NM",
    "CHARGE_CLSBY_NM": "CHARGE_CLSBY_NM",
    "DSCT_CLSBY_NM": "DSCT_CLSBY_NM",
    "PRDT_CLSBY_NM": "PRDT_CLSBY_NM",
    "GOODS_CLSBY_NM": "GOODS_CLSBY_NM",
    "ONLINE_SALE": "ONLINE_SALE",
    "ACC_YN": "ACC_YN",
    "PRDT_CD": "PRDT_CD",
}
METRICS = {
    "ROW_CNT": "COUNT(*)",
    "SHOP_CNT": "COUNT(DISTINCT SHOP_ID)",
    "PRDT_CNT": "COUNT(DISTINCT PRDT_CD)",
    "QTY_SUM": "SUM(QTY)",
    "REAL_SALE_AMT_SUM": "SUM(REAL_SALE_AMT)",
    "DSCT_AMT_SUM": "SUM(DSCT_AMT)",
    "FIRST_AMT_SUM": "SUM(FIRST_PRICE * QTY)",
    "COST_AMT_SUM": "SUM(PRODUCT_COST2 * QTY)",
}
LABELS = {
    "MAKE_YYMM": "판매년월", "MAKE_YY": "판매년도", "TEAM_CD": "팀", "SHOP_ID": "매장코드", "SHOP_NM": "매장명",
    "PLAN_YY": "기획년도", "SESS_NM": "시즌", "PRDT_GRP_NM": "품군", "ITEM_NM": "아이템",
    "CHARGE_CLSBY_NM": "수수료구분", "DSCT_CLSBY_NM": "판매형태", "PRDT_CLSBY_NM": "생산형태",
    "GOODS_CLSBY_NM": "상품구분", "ONLINE_SALE": "온라인 판매 구분", "ACC_YN": "악세사리 구분", "PRDT_CD": "상품",
    "ROW_CNT": "행 수", "SHOP_CNT": "매장 수", "PRDT_CNT": "상품 수", "QTY_SUM": "수량 합계",
    "REAL_SALE_AMT_SUM": "실판금액 합계", "DSCT_AMT_SUM": "할인금액 합계", "FIRST_AMT_SUM": "최초가×수량 합계",
    "COST_AMT_SUM": "제조원가(V+)×수량 합계",
}
# 기본 지표: 인덱스 IX_T_CLOSE_SALE_BASE_03 (MAKE_YYMM, SHOP_ID, REAL_SALE_AMT, QTY) 만으로 계산 가능 → 긴 기간도 빠름.
# 나머지 지표는 테이블 전체를 읽어야 해서 36개월 기준 2분 이상 걸릴 수 있다.
DEFAULT_METRICS = ["ROW_CNT", "SHOP_CNT", "QTY_SUM", "REAL_SALE_AMT_SUM"]
ROW_KEYS = [c for c, _, _ in sm.COLUMNS]
ROW_LABELS = {c: label for c, label, _ in sm.COLUMNS}
NUM_ROW_KEYS = [c for c, _, kind in sm.COLUMNS if kind == "int"]

_FILTER_PROPS: dict[str, Any] = {
    "ym_from": {"type": "string", "description": "판매년월 시작 YYYYMM (필수)"},
    "ym_to": {"type": "string", "description": f"판매년월 종료 YYYYMM (필수, 시작부터 최대 {sm.MAX_MONTHS}개월)"},
    "shop_ids": {"type": "array", "items": {"type": "string"}, "description": "매장코드 목록 (정확히 일치, 최대 500개)"},
    "shop_nm": {"type": "string", "description": "매장명 부분 일치"},
    "team_cd": {"type": "string", "description": "팀 부분 일치 (예: 시스티나1팀)"},
    "plan_yys": {"type": "array", "items": {"type": "string"}, "description": "기획년도 목록 (YYYY)"},
    "seasons": {"type": "array", "items": {"type": "string", "enum": sm.SEASONS}, "description": "시즌 목록"},
    "prdt_grp_nm": {"type": "string", "description": "품군 정확히 일치 (예: JERSEY)"},
    "item_nm": {"type": "string", "description": "아이템 부분 일치 (예: 티셔츠)"},
    "charge_clsby_nm": {"type": "string", "description": "수수료구분 정확히 일치"},
    "dsct_clsby_nm": {"type": "string", "description": "판매형태 정확히 일치 (예: 정상, 세일)"},
    "prdt_clsby_nm": {"type": "string", "description": "생산형태 정확히 일치"},
    "goods_clsby_nm": {"type": "string", "description": "상품구분 정확히 일치"},
    "online_sale": {"type": "string", "enum": ["Y", "N"], "description": "온라인 판매 구분"},
    "acc_yn": {"type": "string", "enum": ["Y", "N"], "description": "악세사리 구분"},
    "prdt_cd": {"type": "string", "description": "상품코드 앞부분 일치"},
}
_EXACT = {"prdt_grp_nm": sm.PRDT_GRP_EXPR, "charge_clsby_nm": "CHARGE_CLSBY_NM", "dsct_clsby_nm": "DSCT_CLSBY_NM",
          "prdt_clsby_nm": "PRDT_CLSBY_NM", "goods_clsby_nm": "GOODS_CLSBY_NM", "online_sale": "ONLINE_SALE",
          "acc_yn": "ACC_YN"}
_REQUIRED = ["ym_from", "ym_to"]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "aggregate_sales",
        "description": (
            "월별 매장별 판매 집계(마감 매출 기초 데이터, 상품·색상·사이즈 단위 판매 행)를 필터링한 뒤 그룹별로 집계합니다. "
            "group_by 를 비우면 전체 합계 1행. 금액 단위는 원. SHOP_ID 로 묶으면 매장명(SHOP_NM)도 함께 반환됩니다. "
            f"metrics 를 생략하면 {DEFAULT_METRICS} 만 계산합니다. 이 기본 지표와 그룹(MAKE_YYMM, MAKE_YY, SHOP_ID)만 쓰고 "
            "다른 필터가 없으면 긴 기간도 빠릅니다. 그 밖의 지표·그룹·필터를 쓰면 기간이 길수록 느려지므로(36개월이면 2분 이상), "
            "긴 기간에는 꼭 필요한 지표만 요청하세요. 매장 조건·매장 묶음 없이 기획년도·시즌·품군·아이템·판매형태·상품·팀·판매년월만 "
            "쓰고 지표가 행 수·상품 수·수량·실판금액·할인금액·원가 금액이면 상품 사전 집계 뷰에서 같은 합계를 빠르게 계산합니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPS,
                "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)},
                            "description": "계산할 지표. PRDT_CNT=상품 수, DSCT_AMT_SUM=할인금액, FIRST_AMT_SUM=최초가×수량, "
                                           "COST_AMT_SUM=제조원가(V+)×수량"},
                "group_by": {"type": "array", "items": {"type": "string", "enum": list(GROUP_COLS)},
                             "description": "그룹핑 컬럼 (0~3개). MAKE_YY=판매년도"},
                "order_by": {"type": "string", "enum": list(GROUP_COLS) + list(METRICS)},
                "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 50)"},
            },
            "required": _REQUIRED,
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "search_sales",
        "description": (
            "월별 매장별 판매 집계의 개별 판매 행을 조회합니다. 반환: 판매년월·팀·매장코드·매장명·기획년도·시즌·품군·아이템·"
            "수수료구분·판매형태·상품·색상·사이즈·수량·최초가·판매단가·실판단가·실판금액·할인금액·생산형태·악세사리 구분·"
            "온라인 판매 구분·상품구분·제조원가(V+). 기본 정렬은 판매년월, 매장코드. total_matched 에 전체 일치 건수가 포함됩니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPS,
                "order_by": {"type": "string", "enum": NUM_ROW_KEYS + ["MAKE_YYMM", "SHOP_ID"]},
                "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 30)"},
            },
            "required": _REQUIRED,
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]

# ----------------------------------------------------------------------------
# 월별·매장별 합계 전용: 사전 집계 뷰 MV_CLOSE_SALE_SHOP_YM (판매년월 × 매장 1행, 원본과 합계 동일)
# 원본 1,600만 행 대신 약 2.4만 행만 읽어 36개월 합계도 0.1초 안쪽. 시즌·기획년도 등 다른 조건은 원본 도구 사용.
# ----------------------------------------------------------------------------
MV_NAME = f"{config.DB_OWNER_SCHEMA}.MV_CLOSE_SALE_SHOP_YM"
MV_MAX_MONTHS = 120
MV_GROUP_COLS = {"MAKE_YYMM": "MAKE_YYMM", "MAKE_YY": "SUBSTR(MAKE_YYMM, 1, 4)", "SHOP_ID": "SHOP_ID", "TEAM_CD": "TEAM_CD"}
# 지표: (뷰 식, 원본 식) — 뷰가 오래됐거나 최근 월이 없으면 같은 결과를 원본에서 계산
MV_METRICS = {
    "ROW_CNT": ("SUM(ROW_COUNT)", "COUNT(*)"),
    "SHOP_CNT": ("COUNT(DISTINCT SHOP_ID)", "COUNT(DISTINCT SHOP_ID)"),
    "QTY_SUM": ("SUM(TOTAL_QTY)", "SUM(QTY)"),
    "REAL_SALE_AMT_SUM": ("SUM(TOTAL_SALE_AMT)", "SUM(REAL_SALE_AMT)"),
    "DSCT_AMT_SUM": ("SUM(TOTAL_DSCT_AMT)", "SUM(DSCT_AMT)"),
    # 원가 금액 = 제조원가(V+) × 수량. 뷰에 TOTAL_COST_AMT 컬럼(db/create_mv_close_sale_shop_ym.sql)이 있을 때만 뷰에서 읽는다.
    # 뷰의 TOTAL_PRODUCT_COST2(단가 단순 합)와 TOTAL_QTY 로는 행별 곱의 합을 되살릴 수 없어 쓰지 않는다.
    "COST_AMT_SUM": ("SUM(TOTAL_COST_AMT)", "SUM(PRODUCT_COST2 * QTY)"),
}
MV_OPTIONAL_METRICS = {"COST_AMT_SUM": "TOTAL_COST_AMT"}  # 지표 → 필요한 뷰 컬럼
MV_TOOL = {
    "name": "sum_sales_shop_month",
    "description": (
        "월별·매장별·팀별 판매 합계 전용 빠른 도구 (월×매장 사전 집계 뷰). 판매년월 기간(필수), 매장코드·매장명·팀 조건과 "
        "판매년월/판매년도/매장/팀 묶음만 지원하며, 수량·실판금액·할인금액·원가 금액(제조원가×수량) 합계, 매장 수, 원본 행 수를 반환합니다. "
        "원가율 = 원가 금액 / 실판금액 으로 계산하세요. "
        "예: 월별 실판금액 추이, 매장별 매출 순위, 팀별 합계, 특정 매장의 월별 매출. "
        "이런 단순 합계에는 aggregate_sales 대신 이 도구를 먼저 쓰세요. 시즌·기획년도·품군·아이템·판매형태·수수료구분 등 "
        "다른 조건이나 묶음, 상품 수·최초가 금액이 필요하면 aggregate_sales 를 쓰세요. 최대 120개월."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ym_from": {"type": "string", "description": "판매년월 시작 YYYYMM (필수)"},
            "ym_to": {"type": "string", "description": f"판매년월 종료 YYYYMM (필수, 최대 {MV_MAX_MONTHS}개월)"},
            "shop_ids": {"type": "array", "items": {"type": "string"}, "description": "매장코드 목록 (최대 500개)"},
            "shop_nm": {"type": "string", "description": "매장명 부분 일치"},
            "team_cd": {"type": "string", "description": "팀 부분 일치 (예: 쉬즈1팀, 리스트, 시스티나)"},
            "group_by": {"type": "array", "items": {"type": "string", "enum": list(MV_GROUP_COLS)},
                         "description": "묶음 (0~3개). 비우면 전체 합계 1행. SHOP_ID 로 묶으면 매장명(SHOP_NM)도 반환"},
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(MV_METRICS)},
                        "description": "생략하면 원가를 뺀 전부. ROW_CNT=원본 판매 행 수, COST_AMT_SUM=원가 금액(제조원가×수량)"},
            "order_by": {"type": "string", "enum": list(MV_GROUP_COLS) + list(MV_METRICS)},
            "order_dir": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "description": f"최대 반환 행 수 (1~{MAX_LIMIT}, 기본 50)"},
        },
        "required": ["ym_from", "ym_to"],
        "additionalProperties": False,
    },
    "eager_input_streaming": True,
}
TOOLS.insert(0, MV_TOOL)  # 단순 합계는 이 도구가 먼저 보이도록

_mv_state: tuple[float, dict] | None = None
_mv_lock = threading.Lock()
MV_STATE_TTL = 60


def mv_state() -> dict:
    """뷰 상태: 사용 가능 여부, 신선도(STALENESS), 마지막 갱신, 뷰/원본 최신 판매년월. 60초 캐시."""
    global _mv_state
    now = time.time()
    with _mv_lock:
        if _mv_state and _mv_state[0] > now:
            return _mv_state[1]
    st = {"usable": False, "staleness": None, "last_refresh": None, "mv_max": None, "base_max": None, "columns": set()}
    try:
        info = db.query("SELECT STALENESS, LAST_REFRESH_DATE FROM ALL_MVIEWS WHERE OWNER = :o AND MVIEW_NAME = 'MV_CLOSE_SALE_SHOP_YM'",
                        {"o": config.DB_OWNER_SCHEMA})[1]
        if info:
            st["staleness"], st["last_refresh"] = info[0][0], info[0][1]
        st["columns"] = {r[0] for r in db.query(
            "SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS WHERE OWNER = :o AND TABLE_NAME = 'MV_CLOSE_SALE_SHOP_YM'",
            {"o": config.DB_OWNER_SCHEMA})[1]}
        st["mv_max"] = db.query(f"SELECT MAX(MAKE_YYMM) FROM {MV_NAME}")[1][0][0]
        st["base_max"] = db.query(f"SELECT MAX(MAKE_YYMM) FROM {TABLE}")[1][0][0]  # 인덱스 최대값 조회
        st["usable"] = st["mv_max"] is not None and st["staleness"] in (None, "FRESH")
    except Exception:  # noqa: BLE001 - 뷰가 없거나 권한이 없으면 원본으로 계산
        st["usable"] = False
    with _mv_lock:
        _mv_state = (now + MV_STATE_TTL, st)
    return st


def _run_mv(inp: dict, teams: list[str] | None = None) -> dict:
    f, t = _ym(inp, "ym_from"), _ym(inp, "ym_to")
    if f > t:
        raise SaleToolError("ym_from 이 ym_to 보다 늦습니다.")
    if sm._months(f, t) > MV_MAX_MONTHS:
        raise SaleToolError(f"판매년월은 최대 {MV_MAX_MONTHS}개월까지 조회할 수 있습니다.")
    group_by = inp.get("group_by") or []
    if not isinstance(group_by, list) or any(g not in MV_GROUP_COLS for g in group_by) or len(group_by) > 3:
        raise SaleToolError(f"group_by 는 {list(MV_GROUP_COLS)} 중 최대 3개입니다. 다른 묶음은 aggregate_sales 를 쓰세요.")
    group_by = list(dict.fromkeys(group_by))
    metrics = inp.get("metrics") or [m for m in MV_METRICS if m not in MV_OPTIONAL_METRICS]
    if not isinstance(metrics, list) or any(m not in MV_METRICS for m in metrics):
        raise SaleToolError(f"metrics 는 {list(MV_METRICS)} 중에서 선택합니다.")
    metrics = [m for m in MV_METRICS if m in metrics]
    order_by = inp.get("order_by") or (("REAL_SALE_AMT_SUM" if "REAL_SALE_AMT_SUM" in metrics else metrics[0]) if group_by else None)
    if order_by is not None and order_by not in metrics and order_by not in group_by:
        raise SaleToolError("order_by 는 요청한 지표이거나 group_by 에 포함된 컬럼이어야 합니다.")
    limit = _limit(inp, 50)

    conds, p = ["MAKE_YYMM BETWEEN :ym_from AND :ym_to"], {"ym_from": f, "ym_to": t}
    if teams is not None:  # 브랜드 권한 (뷰에도 팀이 있어 그대로 거른다)
        tb = {f"bt{i}": x for i, x in enumerate(teams or ["-"])}
        conds.append(f"TEAM_CD IN ({', '.join(':' + k for k in tb)})")
        p.update(tb)
    if shops := _list(inp, "shop_ids", 500):
        binds = {f"shop{i}": s.upper() for i, s in enumerate(shops)}
        conds.append(f"SHOP_ID IN ({', '.join(':' + k for k in binds)})")
        p.update(binds)
    for key, col in (("shop_nm", "SHOP_NM"), ("team_cd", "TEAM_CD")):
        if (v := _text(inp, key)) is not None:
            conds.append(f"INSTR({col}, :{key}) > 0")
            p[key] = v

    # 뷰가 최신이고 요청 기간이 뷰에 모두 들어 있으면 뷰, 아니면 원본에서 같은 합계를 계산
    st = mv_state()
    missing_cols = [c for m, c in MV_OPTIONAL_METRICS.items() if m in metrics and c not in st.get("columns", set())]
    use_mv = (st["usable"] and not missing_cols
              and not (st["base_max"] and st["mv_max"] and t > st["mv_max"] and st["base_max"] > st["mv_max"]))
    src, idx = (MV_NAME, 0) if use_mv else (TABLE, 1)
    select = [f"{MV_GROUP_COLS[g]} AS {g}" for g in group_by]
    if "SHOP_ID" in group_by:
        select.append("MAX(SHOP_NM) AS SHOP_NM")
    select += [f"{MV_METRICS[m][idx]} AS {m}" for m in metrics]
    sql = f"SELECT {', '.join(select)} FROM {src} WHERE {' AND '.join(conds)}"
    if group_by:
        sql += " GROUP BY " + ", ".join(MV_GROUP_COLS[g] for g in group_by)
    if order_by:
        sql += f" ORDER BY {order_by} {_dir(inp, 'desc')} NULLS LAST"
    rows = _clean(db.query_dicts(f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit + 1}", p))
    truncated = len(rows) > limit
    rows = rows[:limit]
    cols = group_by + (["SHOP_NM"] if "SHOP_ID" in group_by else []) + metrics
    refreshed = st["last_refresh"].strftime("%Y-%m-%d %H:%M") if st["last_refresh"] else None
    source = (f"사전 집계 뷰(마지막 갱신 {refreshed})" if use_mv else
              "원본 테이블(집계 뷰에 원가 금액 컬럼이 없어 원본에서 정확히 계산)" if missing_cols and st["usable"] else
              "원본 테이블(집계 뷰가 최신이 아니거나 요청 기간의 최근 월이 아직 뷰에 없어 원본에서 계산)")
    return {
        "result": {"row_count": len(rows), "truncated": truncated, "rows": rows, "period": f"{f}~{t}", "source": source},
        "table": {"columns": [{"key": c, "label": LABELS.get(c, c)} for c in cols], "rows": rows},
    }


TOOL_LABELS = {
    "sum_sales_shop_month": "월·매장 판매 합계",
    "aggregate_sales": "판매 집계",
    "search_sales": "판매 행 검색",
}


class SaleToolError(ValueError):
    pass


def _text(inp: dict, name: str) -> str | None:
    v = inp.get(name)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise SaleToolError(f"{name} 는 문자열이어야 합니다.")
    return v.strip()


def _list(inp: dict, name: str, limit: int) -> list[str]:
    v = inp.get(name)
    if v is None:
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise SaleToolError(f"{name} 는 문자열 배열이어야 합니다.")
    v = list(dict.fromkeys(x.strip() for x in v if x.strip()))
    if len(v) > limit:
        raise SaleToolError(f"{name} 는 최대 {limit}개입니다.")
    return v


def _ym(inp: dict, name: str) -> str:
    v = (_text(inp, name) or "").replace("-", "")
    if not re.match(r"^\d{6}$", v) or not 1 <= int(v[4:]) <= 12:
        raise SaleToolError(f"{name} 는 YYYYMM 형식으로 반드시 지정해야 합니다.")
    return v


NARROW_MAX_SHOPS = 500


def _narrow_by_shop_name(conds: list[str], p: dict, f: str, t: str) -> None:
    """매장명 부분 일치(INSTR) 조건을 빠르게: 사전 집계 뷰에서 이름이 맞는 매장코드를 먼저 찾아
    (판매년월 목록, 매장코드) 조건을 덧붙인다 → 원본 인덱스를 매장 단위로 바로 찾는다 (36개월 기준 30초 → 1초 안팎).

    결과는 같다: 뷰가 최신(FRESH)이고 요청 기간이 뷰에 모두 있을 때만 쓰며(뷰 = 원본의 월·매장·매장명 조합),
    INSTR 조건도 그대로 두어 같은 행만 남는다. 뷰가 오래됐거나 매장이 너무 많으면 기존 방식(INSTR 만)으로 조회한다."""
    st = mv_state()
    if not (st["usable"] and st["mv_max"] and t <= st["mv_max"]):
        return
    ids = [r[0] for r in db.query(
        f"SELECT DISTINCT SHOP_ID FROM {MV_NAME} WHERE MAKE_YYMM BETWEEN :f AND :t AND INSTR(SHOP_NM, :v) > 0",
        {"f": f, "t": t, "v": p["shop_nm"]})[1]]
    if len(ids) > NARROW_MAX_SHOPS:
        return
    if not ids:
        conds.append("1 = 0")  # 이름이 맞는 매장이 없음
        return
    months = sm._month_list(f, t)
    mb = {f"nym{i}": m for i, m in enumerate(months)}
    sb = {f"nshop{i}": s for i, s in enumerate(ids)}
    conds.append(f"MAKE_YYMM IN ({', '.join(':' + k for k in mb)})")
    conds.append(f"SHOP_ID IN ({', '.join(':' + k for k in sb)})")
    p.update(mb)
    p.update(sb)


# ----------------------------------------------------------------------------
# aggregate_sales 의 상품 단위 묶음: 상품 사전 집계 뷰 MV_CLOSE_SALE_PRDT_YM (월 × 팀 × 상품 × 판매형태, 기획년도·시즌·아이템·품군 포함)
# 매장 조건·매장 묶음이 없고, 뷰에 있는 열만 쓰는 질문이면 원본 대신 뷰에서 같은 합계를 읽는다 (시즌·품번 묶음 약 6초 → 0.3초).
# ----------------------------------------------------------------------------
PRDT_MV_GROUPS = {"MAKE_YYMM", "MAKE_YY", "TEAM_CD", "PLAN_YY", "SESS_NM", "PRDT_GRP_NM", "ITEM_NM", "DSCT_CLSBY_NM", "PRDT_CD"}
PRDT_MV_FILTERS = {"ym_from", "ym_to", "team_cd", "plan_yys", "seasons", "prdt_grp_nm", "item_nm", "dsct_clsby_nm", "prdt_cd"}
PRDT_MV_METRICS = {"ROW_CNT": "SUM(ROW_COUNT)", "PRDT_CNT": "COUNT(DISTINCT PRDT_CD)", "QTY_SUM": "SUM(TOTAL_QTY)",
                   "REAL_SALE_AMT_SUM": "SUM(TOTAL_SALE_AMT)", "DSCT_AMT_SUM": "SUM(TOTAL_DSCT_AMT)", "COST_AMT_SUM": "SUM(TOTAL_COST_AMT)"}
# 뷰의 시즌·품군 열은 이미 앱 식(SUBSTRB 100바이트)으로 만들어져 있다
PRDT_MV_COLS = {**{g: g for g in PRDT_MV_GROUPS}, "MAKE_YY": "SUBSTR(MAKE_YYMM, 1, 4)"}


def _use_prdt_mv(inp: dict, group_by: list[str], metrics: list[str], t: str) -> bool:
    if any(k not in PRDT_MV_FILTERS for k, v in inp.items()
           if k not in ("group_by", "metrics", "order_by", "order_dir", "limit") and v not in (None, "", [])):
        return False
    if any(g not in PRDT_MV_GROUPS for g in group_by) or any(m not in PRDT_MV_METRICS for m in metrics):
        return False
    from . import sale_products

    st = sale_products.mv_state()
    return bool(st["usable"] and st["mv_max"] and t <= st["mv_max"])


def _where(inp: dict, teams: list[str] | None = None, prdt_mv: bool = False) -> tuple[str, dict]:
    """prdt_mv=True: 상품 사전 집계 뷰용 조건 (시즌·품군은 뷰 열 그대로, 브랜드 권한은 팀 조건)"""
    f, t = _ym(inp, "ym_from"), _ym(inp, "ym_to")
    if f > t:
        raise SaleToolError("ym_from 이 ym_to 보다 늦습니다.")
    if sm._months(f, t) > sm.MAX_MONTHS:
        raise SaleToolError(f"판매년월은 최대 {sm.MAX_MONTHS}개월까지 조회할 수 있습니다. 기간을 나눠 조회하세요.")
    conds, p = ["MAKE_YYMM BETWEEN :ym_from AND :ym_to"], {"ym_from": f, "ym_to": t}

    def _in(col: str, prefix: str, values: list[str]):
        binds = {f"{prefix}{i}": v for i, v in enumerate(values)}
        conds.append(f"{col} IN ({', '.join(':' + k for k in binds)})")
        p.update(binds)

    if shops := _list(inp, "shop_ids", 500):
        _in("SHOP_ID", "shop", [s.upper() for s in shops])
    if yys := _list(inp, "plan_yys", 30):
        if any(not re.match(r"^\d{4}$", y) for y in yys):
            raise SaleToolError("plan_yys 는 YYYY 형식입니다.")
        _in("PLAN_YY", "yy", yys)
    if seasons := _list(inp, "seasons", len(sm.SEASONS)):
        if any(s not in sm.SEASONS for s in seasons):
            raise SaleToolError(f"seasons 는 {sm.SEASONS} 중에서 선택합니다.")
        _in("SESS_NM" if prdt_mv else sm.SESS_EXPR, "sess", seasons)
    for key, col in (("shop_nm", "SHOP_NM"), ("team_cd", "TEAM_CD"), ("item_nm", "ITEM_NM")):
        if (v := _text(inp, key)) is not None:
            conds.append(f"INSTR({col}, :{key}) > 0")
            p[key] = v
    if "shop_nm" in p:
        _narrow_by_shop_name(conds, p, f, t)
    for key, col in _EXACT.items():
        if prdt_mv and key == "prdt_grp_nm":
            col = "PRDT_GRP_NM"
        if (v := _text(inp, key)) is not None:
            allowed = _FILTER_PROPS[key].get("enum")
            if allowed and v not in allowed:
                raise SaleToolError(f"{key} 는 {allowed} 중 하나입니다.")
            conds.append(f"{col} = :{key}")
            p[key] = v
    if (v := _text(inp, "prdt_cd")) is not None:
        conds.append("PRDT_CD LIKE :prdt_cd")
        p["prdt_cd"] = v.upper().replace("%", "").replace("_", "") + "%"
    if prdt_mv:  # 뷰는 팀 열이 있어 팀 조건으로 바로 거른다
        if teams is not None:
            _in("TEAM_CD", "bft", teams or ["-"])
        return " AND ".join(conds), p
    bconds, bbinds = sm.brand_filter(teams, f, t)  # 브랜드 권한 (화면 판매 집계와 같은 방식)
    conds += bconds
    p.update(bbinds)
    return " AND ".join(conds), p


def _limit(inp: dict, default: int) -> int:
    v = inp.get("limit", default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SaleToolError("limit 는 정수여야 합니다.")
    return max(1, min(int(v), tool_limits.cap(MAX_LIMIT)))  # 전체 엑셀일 때만 상한 확대


def _dir(inp: dict, default: str) -> str:
    d = inp.get("order_dir", default)
    if d not in ("asc", "desc"):
        raise SaleToolError("order_dir 는 asc 또는 desc 입니다.")
    return d.upper()


def _clean(rows: list[dict]) -> list[dict]:
    def num(v):
        if isinstance(v, str) or v is None:
            return v
        f = float(v)
        return int(f) if f.is_integer() else round(f, 2)
    return [{k: num(v) for k, v in r.items()} for r in rows]


def run(name: str, inp: dict, teams: list[str] | None = None) -> dict:
    """teams: 브랜드 권한으로 허용된 팀 (None = 모든 브랜드)"""
    if name == "sum_sales_shop_month":
        return _run_mv(inp, teams)

    if name == "aggregate_sales":
        group_by = inp.get("group_by") or []
        if not isinstance(group_by, list) or any(g not in GROUP_COLS for g in group_by) or len(group_by) > 3:
            raise SaleToolError(f"group_by 는 {list(GROUP_COLS)} 중 최대 3개입니다.")
        group_by = list(dict.fromkeys(group_by))
        metrics = inp.get("metrics") or DEFAULT_METRICS
        if not isinstance(metrics, list) or any(m not in METRICS for m in metrics):
            raise SaleToolError(f"metrics 는 {list(METRICS)} 중에서 선택합니다.")
        metrics = [m for m in METRICS if m in metrics]
        order_by = inp.get("order_by") or (("REAL_SALE_AMT_SUM" if "REAL_SALE_AMT_SUM" in metrics else metrics[0])
                                           if group_by else None)
        if order_by is not None and order_by not in metrics and order_by not in group_by:
            raise SaleToolError("order_by 는 요청한 지표이거나 group_by 에 포함된 컬럼이어야 합니다.")
        limit = _limit(inp, 50)
        use_mv = _use_prdt_mv(inp, group_by, metrics, _ym(inp, "ym_to"))
        where, p = _where(inp, teams, prdt_mv=use_mv)
        if use_mv:
            from . import sale_products

            gcols, mexpr, table = PRDT_MV_COLS, PRDT_MV_METRICS, sale_products.MV_NAME
        else:
            gcols, mexpr, table = GROUP_COLS, METRICS, TABLE
        select = [f"{gcols[g]} AS {g}" for g in group_by] + [f"{mexpr[a]} AS {a}" for a in metrics]
        sql = f"SELECT {', '.join(select)} FROM {table} WHERE {where}"
        if group_by:
            sql += " GROUP BY " + ", ".join(gcols[g] for g in group_by)
        if order_by:
            sql += f" ORDER BY {order_by} {_dir(inp, 'desc')} NULLS LAST"
        rows = _clean(db.query_dicts(f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit + 1}", p))
        truncated = len(rows) > limit
        rows = rows[:limit]
        if "SHOP_ID" in group_by and rows:  # 매장명은 반환 행만 T_SHOP 에서 붙인다 (집계는 인덱스만 읽도록)
            names = sm.shop_names([r["SHOP_ID"] for r in rows])
            rows = [{**{k: v for k, v in r.items() if k in group_by},
                     "SHOP_NM": names.get(r["SHOP_ID"]),
                     **{k: v for k, v in r.items() if k not in group_by}} for r in rows]
        cols = group_by + (["SHOP_NM"] if "SHOP_ID" in group_by else []) + metrics
        return {
            "result": {"row_count": len(rows), "truncated": truncated, "rows": rows,
                       "period": f"{p['ym_from']}~{p['ym_to']}",
                       "source": "상품 사전 집계 뷰(원본과 같은 합계)" if use_mv else "원본"},
            "table": {"columns": [{"key": c, "label": LABELS[c]} for c in cols], "rows": rows},
        }

    if name == "search_sales":
        where, p = _where(inp, teams)
        order_by = inp.get("order_by")
        if order_by is not None and order_by not in NUM_ROW_KEYS + ["MAKE_YYMM", "SHOP_ID"]:
            raise SaleToolError("order_by 값이 올바르지 않습니다.")
        order = (f"{order_by} {_dir(inp, 'desc')} NULLS LAST, MAKE_YYMM, SHOP_ID" if order_by
                 else "MAKE_YYMM, SHOP_ID")
        limit = _limit(inp, 30)
        total = db.query(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}", p)[1][0][0]
        rows = _clean(db.query_dicts(
            f"SELECT * FROM (SELECT {sm.COL_SQL} FROM {TABLE} WHERE {where} "
            f"ORDER BY {order}, PRDT_CD, COLOR_CD, SIZE_CD) WHERE ROWNUM <= {limit}", p))
        return {
            "result": {"total_matched": int(total), "returned": len(rows), "rows": rows},
            "table": {"columns": [{"key": c, "label": ROW_LABELS[c]} for c in ROW_KEYS], "rows": rows,
                      "totalMatched": int(total)},
        }

    raise SaleToolError(f"알 수 없는 도구: {name}")
