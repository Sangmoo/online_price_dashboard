"""Claude 조회 도구: 온라인 가격 > 판매처 매장 연결 (사이트 · 판매자번호 · 브랜드 → 매장코드).

- search_mall_shop_mappings: 조합·매핑 조회 (화면 목록과 같은 데이터)
- propose_mall_shop_mappings: 매핑 등록·수정·해제 '변경안'을 검증해 보여준다. **DB 에는 쓰지 않는다.**
  화면(AI 대화창)에 [적용] 버튼이 붙은 카드로 나가고, 사용자가 눌러야 화면과 같은 저장 경로(PUT /api/mall-shops,
  같은 권한·검증·변경 이력)로 저장된다. AI 가 사이트명·매장코드를 잘못 알아들어도 사람 확인 없이 업무 테이블이 바뀌지 않게.
판매처 매장 연결 메뉴 권한이 있는 사용자만 쓸 수 있다.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import mall_shop as ms
from .shop_info import BRAND_CODES

BRAND_ALIASES = {**{v: k for k, v in BRAND_CODES.items()}, **{k: k for k in BRAND_CODES}, "*": "*", "전체": "*", "모든 브랜드": "*",
                 "공통": "*", "쉬즈": "S"}
MAX_ITEMS = 50

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_mall_shop_mappings",
        "description": (
            "온라인 가격 수집의 판매처(사이트 MALL_NM · 판매자번호 NAVER_PAY_SELL_NO · 브랜드)와 연결된 매장코드를 조회합니다 "
            "(메뉴: 온라인 가격 > 판매처 매장 연결). 브랜드 = 품번 첫 글자(S 쉬즈미스, T 리스트, A 시스티나), '*' = 모든 브랜드 공통. "
            "판매자번호가 없는 사이트는 '-'. 결과: 최근 수집 행 수·상품 수·마지막 수집일·매장정보(RMK) 예시·연결 매장·수집 시 실제 적용 매장"
            "(브랜드 행 → 없으면 '*' 행)·같은 브랜드 매장 후보. '하프클럽 어느 매장으로 연결돼 있어?', '미연결 판매처 보여줘' 같은 질문에 씁니다. "
            "매핑을 바꾸려면 먼저 이 도구로 정확한 사이트명·판매자번호를 확인한 뒤 propose_mall_shop_mappings 를 쓰세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mall_nm": {"type": "string", "description": "사이트명 부분 일치 (예: 하프클럽, 네이버)"},
                "sell_no": {"type": "string", "description": "판매자번호 정확히 ('-' = 판매자번호 없음)"},
                "brand": {"type": "string", "description": "브랜드 (쉬즈미스·리스트·시스티나 또는 S/T/A, '*' = 공통 행)"},
                "shop_id": {"type": "string", "description": "연결된 매장코드로 찾기"},
                "status": {"type": "string", "enum": ["all", "mapped", "unmapped"], "description": "연결 상태 (기본 all)"},
                "days": {"type": "integer", "enum": list(ms.DAYS), "description": "최근 수집 기간(일, 기본 7)"},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "propose_mall_shop_mappings",
        "description": (
            "판매처 매장 연결을 등록·수정·해제하는 변경안을 만듭니다. 이 도구는 DB 에 저장하지 않습니다: 검증한 변경안이 대화창에 "
            "[적용] 버튼이 있는 카드로 표시되고, 사용자가 버튼을 눌러야 저장됩니다. 답변에서 '아래 [적용]을 누르면 저장됩니다'라고 안내하고, "
            "저장했다고 말하지 마세요. 사이트명은 부분 일치로 하나만 찾아지면 그 이름을 쓰고, 여러 개면 오류로 후보를 알려줍니다. "
            "판매자번호를 생략하면 그 사이트의 판매자번호가 하나일 때만 그것을 씁니다. shop_id 를 빈 문자열로 주면 그 연결을 해제합니다. "
            "매장의 브랜드가 행의 브랜드와 다르면 경고가 붙습니다(예: 리스트 행에 쉬즈미스 매장)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array", "maxItems": MAX_ITEMS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "mall_nm": {"type": "string", "description": "사이트명 (정확히 또는 부분 일치)"},
                            "sell_no": {"type": "string", "description": "판매자번호 ('-' = 없음, 생략 가능)"},
                            "brand": {"type": "string", "description": "브랜드 (쉬즈미스·리스트·시스티나·S/T/A, '*' 또는 '전체' = 공통)"},
                            "shop_id": {"type": "string", "description": "매장코드 (빈 문자열 = 연결 해제)"},
                            "use_yn": {"type": "string", "enum": ["Y", "N"], "description": "사용 여부 (기본 Y)"},
                            "rmk": {"type": "string", "description": "비고"},
                        },
                        "required": ["mall_nm", "brand", "shop_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["items"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]
TOOL_LABELS = {"search_mall_shop_mappings": "판매처 매장 연결 조회", "propose_mall_shop_mappings": "판매처 매장 연결 변경안"}
TOOL_NAMES = {t["name"] for t in TOOLS}


class MallToolError(ValueError):
    pass


def _brand(v) -> str:
    if v is None or str(v).strip() == "":
        raise MallToolError("brand 는 쉬즈미스·리스트·시스티나(S/T/A) 또는 '*'(공통) 입니다.")
    b = BRAND_ALIASES.get(str(v).strip()) or BRAND_ALIASES.get(str(v).strip().upper())
    if not b:
        raise MallToolError(f"브랜드 '{v}' 를 알 수 없습니다. 쉬즈미스·리스트·시스티나(S/T/A) 또는 '*'(공통) 중 하나입니다.")
    return b


def run(name: str, inp: dict) -> dict:
    try:
        if name == "search_mall_shop_mappings":
            return _search(inp)
        if name == "propose_mall_shop_mappings":
            return _propose(inp)
    except HTTPException as ex:
        d = ex.detail
        raise MallToolError(d.get("message", str(d)) if isinstance(d, dict) else str(d))
    raise MallToolError(f"알 수 없는 도구: {name}")


COLS = [("mallNm", "사이트"), ("sellNo", "판매자번호"), ("brand", "브랜드"), ("rows", "수집 행"), ("lastDt", "마지막 수집"),
        ("shopId", "연결 매장"), ("shopNm", "매장명"), ("effectiveShopId", "수집 시 적용"), ("suggest", "후보"), ("rmk", "매장정보 예시")]


def _search(inp: dict) -> dict:
    days = inp.get("days") or 7
    d = ms.listing(int(days))
    rows = d["rows"]
    if (v := (inp.get("mall_nm") or "").strip()):
        rows = [r for r in rows if v.upper() in r["mallNm"].upper()]
    if (v := (inp.get("sell_no") or "").strip()):
        rows = [r for r in rows if r["sellNo"] == v]
    if inp.get("brand"):
        b = _brand(inp["brand"])
        rows = [r for r in rows if r["brdCd"] == b]
    if (v := (inp.get("shop_id") or "").strip().upper()):
        rows = [r for r in rows if v in (r["shopId"], r["starShopId"], r["effectiveShopId"])]
    status = inp.get("status") or "all"
    if status == "mapped":
        rows = [r for r in rows if r["effectiveShopId"]]
    elif status == "unmapped":
        rows = [r for r in rows if not r["effectiveShopId"]]
    total = len(rows)
    shown = [{**{k: r.get(k) for k, _ in COLS if k != "suggest"},
              "suggest": ", ".join(f"{s['shopId']} {s['shopNm']}" for s in r["suggestions"]) or None} for r in rows[:200]]
    return {"result": {"tableReady": d["ready"], "days": d["days"], "summary": d["summary"], "total_matched": total,
                       "returned": len(shown), "rows": shown,
                       "basis": "brand: 품번 첫 글자 기준. effectiveShopId = 수집 시 실제로 들어갈 매장(브랜드 행 → 없으면 '*' 공통 행)"},
            "table": {"columns": [{"key": k, "label": v} for k, v in COLS], "rows": shown, "totalMatched": total}}


def _resolve(items: list[dict]) -> tuple[list[dict], list[str]]:
    """AI 입력(부분 일치 사이트명, 브랜드 이름) → 정확한 키. 사이트·판매자번호는 최근 90일 수집 또는 기존 매핑에서 찾는다."""
    known = ms.listing(90)["rows"]
    pairs = sorted({(r["mallNm"], r["sellNo"]) for r in known})
    out, notes = [], []
    for i, it in enumerate(items, 1):
        mall_in = str(it.get("mall_nm") or "").strip()
        if not mall_in:
            raise MallToolError(f"{i}번째 항목: mall_nm 이 필요합니다.")
        malls = sorted({m for m, _ in pairs if m == mall_in}) or sorted({m for m, _ in pairs if mall_in.upper() in m.upper()})
        if not malls:
            raise MallToolError(f"'{mall_in}' 사이트를 최근 90일 수집·기존 매핑에서 찾지 못했습니다. search_mall_shop_mappings 로 확인하세요.")
        if len(malls) > 1:
            raise MallToolError(f"'{mall_in}' 에 맞는 사이트가 {len(malls)}개입니다: {', '.join(malls[:15])}. 정확한 사이트명으로 다시 주세요.")
        mall = malls[0]
        sells = sorted({s for m, s in pairs if m == mall})
        sell = str(it.get("sell_no") or "").strip()
        if not sell:
            if len(sells) != 1:
                raise MallToolError(f"'{mall}' 의 판매자번호가 {len(sells)}개입니다({', '.join(sells[:15])}). sell_no 를 지정하세요.")
            sell = sells[0]
        elif sell not in sells:
            notes.append(f"{i}번째: '{mall}' 의 판매자번호 '{sell}' 는 최근 90일 수집에 없습니다 (새 판매자로 등록됨).")
        if mall != mall_in:
            notes.append(f"{i}번째: 사이트 '{mall_in}' → '{mall}'")
        out.append({"mallNm": mall, "sellNo": sell, "brdCd": _brand(it.get("brand")), "shopId": str(it.get("shop_id") or "").strip().upper(),
                    "useYn": "N" if it.get("use_yn") == "N" else "Y", "rmk": str(it.get("rmk") or "").strip()})
    return out, notes


def _propose(inp: dict) -> dict:
    items = inp.get("items")
    if not isinstance(items, list) or not items:
        raise MallToolError("items 에 변경할 항목을 1개 이상 주세요.")
    if len(items) > MAX_ITEMS:
        raise MallToolError(f"한 번에 최대 {MAX_ITEMS}건입니다.")
    if not ms.table_ready():
        raise MallToolError("매핑 테이블(T_SELECT_ONLINE_MALL_SHOP)이 아직 없어 변경할 수 없습니다. 관리자에게 DDL 실행을 요청하세요.")
    resolved, notes = _resolve(items)
    clean, names = ms.validate(resolved)          # 화면 저장과 같은 검증 (매장코드가 T_SHOP 에 있는지 등)
    from . import shop_info

    shop_brands: dict[str, set] = {}
    for r in shop_info.search(include_closed=True):
        shop_brands.setdefault(r["shopId"], set()).add(r["brdCd"])
    before = ms._maps()
    rows, warnings = [], []
    for (mall, sell, brd, shop, use, rmk), it in zip(clean, resolved):
        b = before.get((mall, sell, brd))
        action = ("해제" if b else "변경 없음(연결 없음)") if not shop else ("수정" if b else "등록")
        if b and shop and b["SHOP_ID"] == shop and b["USE_YN"] == use and (b["RMK"] or None) == (rmk or None):
            action = "변경 없음"
        warn = None
        if shop and brd != ms.ALL_BRANDS and shop_brands.get(shop) and brd not in shop_brands[shop]:
            warn = f"매장 {shop} 은 {'/'.join(BRAND_CODES.get(x, x) for x in sorted(shop_brands[shop]))} 매장인데 {BRAND_CODES.get(brd, brd)} 행에 연결"
            warnings.append(f"{mall}/{sell}/{brd}: {warn}")
        rows.append({"mallNm": mall, "sellNo": sell, "brdCd": brd, "brand": "모든 브랜드" if brd == ms.ALL_BRANDS else BRAND_CODES.get(brd, brd),
                     "before": b["SHOP_ID"] if b else None, "shopId": shop or None, "shopNm": names.get(shop) if shop else None,
                     "useYn": use, "rmk": rmk or None, "action": action, "warning": warn})
    applicable = [r for r in rows if not r["action"].startswith("변경 없음")]
    result = {
        "saved": False,
        "instruction": "아직 저장되지 않았습니다. 사용자가 대화창 카드의 [적용] 버튼을 눌러야 저장됩니다. 저장했다고 말하지 마세요.",
        "changes": rows, "applicableCount": len(applicable), "notes": notes, "warnings": warnings,
    }
    cols = [("action", "구분"), ("mallNm", "사이트"), ("sellNo", "판매자번호"), ("brand", "브랜드"), ("before", "현재 매장"),
            ("shopId", "바꿀 매장"), ("shopNm", "매장명"), ("useYn", "사용"), ("warning", "경고")]
    out: dict = {"result": result, "table": {"columns": [{"key": k, "label": v} for k, v in cols], "rows": rows}}
    if applicable:
        out["action"] = {
            "actionKind": "mall_shop_save",
            "title": f"판매처 매장 연결 변경안 {len(applicable)}건",
            "items": [{"mallNm": r["mallNm"], "sellNo": r["sellNo"], "brdCd": r["brdCd"], "shopId": r["shopId"] or "",
                       "useYn": r["useYn"], "rmk": r["rmk"] or ""} for r in applicable],
            "lines": [f"[{r['action']}] {r['mallNm']} / {r['sellNo']} / {r['brand']}: {r['before'] or '-'} → "
                      f"{(r['shopId'] or '-') + (' ' + r['shopNm'] if r['shopNm'] else '')}{' (미사용)' if r['useYn'] == 'N' else ''}"
                      for r in applicable],
            "warnings": warnings,
        }
    return out
