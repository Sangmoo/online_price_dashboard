"""브랜드 데이터 권한: 로그인 사용자가 볼 수 있는 브랜드·팀.

사용자별 브랜드(T_ERP_WEB_USER_BRAND)가 없으면 모든 브랜드(None). 최고 관리자는 항상 모든 브랜드.
판매 현황 · 월별 매장별 판매 집계 · AI 판매 도구가 서버에서 이 범위로 거른다 (화면에서 숨기는 것만이 아님).
"""
from __future__ import annotations


def brands_of(me: dict) -> list[str] | None:
    b = me.get("brands")
    return list(b) if b else None


def teams_of(me: dict) -> list[str] | None:
    """허용 브랜드의 팀 목록 (None = 모든 브랜드, [] = 볼 수 있는 팀 없음)"""
    brands = brands_of(me)
    if brands is None:
        return None
    from . import sale_dashboard as sd

    bt = sd.brand_teams()
    return sorted({t for b in brands for t in bt.get(b, [])})


def label(me: dict) -> str:
    b = brands_of(me)
    return "모든 브랜드" if b is None else ", ".join(b)
