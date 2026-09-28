"""Claude 조회 도구: 판매 분석 > 월별 매장별 판매 집계 (T_CLOSE_SALE_BASE, 마감 매출 기초 데이터).

chat_tools 와 같은 원칙: 모델은 SQL 을 쓰지 않고, 화이트리스트된 컬럼·조건·집계만 파라미터로 지정한다.
판매년월(ym_from~ym_to)은 필수이며 화면과 같은 최대 기간(sale_monthly.MAX_MONTHS)을 적용한다.
"""
from __future__ import annotations

import re
from typing import Any

from . import db
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
    "SESS_NM": "SESS_NM",
    "PRDT_GRP_NM": "PRDT_GRP_NM",
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
_EXACT = {"prdt_grp_nm": "PRDT_GRP_NM", "charge_clsby_nm": "CHARGE_CLSBY_NM", "dsct_clsby_nm": "DSCT_CLSBY_NM",
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
            "긴 기간에는 꼭 필요한 지표만 요청하세요."
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

TOOL_LABELS = {
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


def _where(inp: dict) -> tuple[str, dict]:
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
        _in("SESS_NM", "sess", seasons)
    for key, col in (("shop_nm", "SHOP_NM"), ("team_cd", "TEAM_CD"), ("item_nm", "ITEM_NM")):
        if (v := _text(inp, key)) is not None:
            conds.append(f"INSTR({col}, :{key}) > 0")
            p[key] = v
    for key, col in _EXACT.items():
        if (v := _text(inp, key)) is not None:
            allowed = _FILTER_PROPS[key].get("enum")
            if allowed and v not in allowed:
                raise SaleToolError(f"{key} 는 {allowed} 중 하나입니다.")
            conds.append(f"{col} = :{key}")
            p[key] = v
    if (v := _text(inp, "prdt_cd")) is not None:
        conds.append("PRDT_CD LIKE :prdt_cd")
        p["prdt_cd"] = v.upper().replace("%", "").replace("_", "") + "%"
    return " AND ".join(conds), p


def _limit(inp: dict, default: int) -> int:
    v = inp.get("limit", default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SaleToolError("limit 는 정수여야 합니다.")
    return max(1, min(int(v), MAX_LIMIT))


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


def _shop_names(ids: list[str]) -> dict[str, str]:
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    binds = {f"s{i}": v for i, v in enumerate(ids)}
    return dict(db.query(f"SELECT SHOP_ID, SHOP_NM FROM T_SHOP WHERE SHOP_ID IN ({', '.join(':' + k for k in binds)})",
                         binds)[1])


def run(name: str, inp: dict) -> dict:
    if name == "aggregate_sales":
        where, p = _where(inp)
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
        select = [f"{GROUP_COLS[g]} AS {g}" for g in group_by] + [f"{METRICS[a]} AS {a}" for a in metrics]
        sql = f"SELECT {', '.join(select)} FROM {TABLE} WHERE {where}"
        if group_by:
            sql += " GROUP BY " + ", ".join(GROUP_COLS[g] for g in group_by)
        if order_by:
            sql += f" ORDER BY {order_by} {_dir(inp, 'desc')} NULLS LAST"
        rows = _clean(db.query_dicts(f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit + 1}", p))
        truncated = len(rows) > limit
        rows = rows[:limit]
        if "SHOP_ID" in group_by and rows:  # 매장명은 반환 행만 T_SHOP 에서 붙인다 (집계는 인덱스만 읽도록)
            names = _shop_names([r["SHOP_ID"] for r in rows])
            rows = [{**{k: v for k, v in r.items() if k in group_by},
                     "SHOP_NM": names.get(r["SHOP_ID"]),
                     **{k: v for k, v in r.items() if k not in group_by}} for r in rows]
        cols = group_by + (["SHOP_NM"] if "SHOP_ID" in group_by else []) + metrics
        return {
            "result": {"row_count": len(rows), "truncated": truncated, "rows": rows,
                       "period": f"{p['ym_from']}~{p['ym_to']}"},
            "table": {"columns": [{"key": c, "label": LABELS[c]} for c in cols], "rows": rows},
        }

    if name == "search_sales":
        where, p = _where(inp)
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
