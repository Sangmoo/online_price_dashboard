"""판매 현황 첫 화면 미리 계산 — 그날 처음 여는 사용자도 기다리지 않게.

계산 대상: 기본 조건(최신 월 · 전년 동기 · 브랜드 전체)의 판매 현황, 상품·판매형태 패널, 시즌 판매 진척을, 판매 현황 메뉴를 쓰는
사용자들의 브랜드 권한 조합마다 한 번씩 (보통 '모든 브랜드' + 브랜드별 몇 가지).

언제:
- [지금 갱신] 이 끝난 직후 (mv_refresh 가 호출)
- 서버 시작 직후, 매일 아침 WARM_HOUR 시
- 30분마다 데이터 상태(뷰 갱신 시각 · 신선도 · 원본 최신 월)를 보고 바뀌었으면 캐시를 비우고 다시 계산
  → 미리 계산한 결과는 WARM_TTL(26시간) 동안 두지만, 데이터가 바뀐 뒤 최대 30분 안에 새로 계산된다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import logs

_log = logs.get("app")
WARM_TTL = 26 * 3600
WARM_HOUR = 7
CHECK_SEC = 30 * 60
_lock = threading.Lock()
_state: dict = {"signature": None, "day": None, "last": None, "elapsedSec": None, "scopes": 0, "error": None}


def scopes() -> list[list[str] | None]:
    """판매 현황 메뉴를 쓰는 활성 사용자들의 브랜드 권한 조합 (None = 모든 브랜드, 항상 포함)"""
    from . import auth, userdb

    out: dict[tuple | None, list[str] | None] = {None: None}
    settings = userdb.get_settings()
    for u in userdb.list_users():
        e = auth.effective(u, settings)
        if not e["active"] or "sale_dashboard" not in e["pages"]:
            continue
        if e["brands"]:
            out.setdefault(tuple(sorted(e["brands"])), sorted(e["brands"]))
    return list(out.values())


def signature() -> tuple:
    """데이터가 바뀌었는지 판단하는 값: 월×매장 뷰 (신선도, 마지막 갱신, 뷰·원본 최신 월) + 상품 뷰 (있음, 신선도, 최신 월)"""
    from . import chat_tools_sale as cts
    from . import sale_products

    cts._mv_state = None  # 60초 캐시를 건너뛰고 지금 상태로
    sale_products.clear_state()
    st, ps = cts.mv_state(), sale_products.mv_state()
    return (st["staleness"], str(st["last_refresh"]), st["mv_max"], st["base_max"], ps["exists"], ps["staleness"], ps["mv_max"])


def warm(reason: str) -> dict:
    """기본 조건 판매 현황 + 상품 패널 계산 (동시에 한 번만). 실패한 조합은 건너뛴다."""
    from . import sale_dashboard, sale_mix, sale_products, sale_season

    if not _lock.acquire(blocking=False):
        return state()
    try:
        t0 = time.time()
        sc = scopes()
        errors = []
        for allowed in sc:
            try:
                sale_dashboard.dashboard(allowed=allowed, ttl=WARM_TTL)
                sale_products.analyze(allowed=allowed, ttl=WARM_TTL)
                sale_season.progress(allowed=allowed, ttl=WARM_TTL)
                sale_mix.heavy_shops(allowed=allowed, ttl=WARM_TTL)
            except Exception as ex:  # noqa: BLE001 - 한 조합 실패가 나머지를 막지 않게
                errors.append(f"{allowed or '전체'}: {str(ex).splitlines()[0][:120]}")
        sec = round(time.time() - t0, 1)
        _state.update({"last": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "elapsedSec": sec, "scopes": len(sc),
                       "error": "; ".join(errors) or None, "reason": reason})
        _log.info("판매 현황 미리 계산 (%s) 브랜드 조합 %d개 %.1f초%s", reason, len(sc), sec,
                  f" 실패: {errors}" if errors else "")
        from . import jobs

        jobs.record("prewarm", t0, time.time(), "error" if errors else "ok",
                    f"{reason} · 브랜드 조합 {len(sc)}개" + (f" · 실패 {'; '.join(errors)}" if errors else ""))
    finally:
        _lock.release()
    return state()


def after_refresh() -> None:
    """[지금 갱신] 직후: mv_refresh 가 캐시를 비운 뒤 호출 (같은 갱신 스레드에서)"""
    try:
        _state["signature"] = signature()
        warm("뷰 갱신")
    except Exception:  # noqa: BLE001 - 미리 계산 실패가 갱신 결과를 바꾸지 않게
        _log.exception("판매 현황 미리 계산 실패 (뷰 갱신 후)")


def tick(now: datetime | None = None) -> str | None:
    """주기 점검 1회: 데이터 상태가 바뀌었거나 그날 아침 계산을 아직 안 했으면 계산. 실행한 이유를 돌려준다."""
    from . import sale_dashboard, sale_mix, sale_products, sale_season

    now = now or datetime.now()
    sig = signature()
    reason = None
    if _state["signature"] is None:
        reason = "서버 시작"
    elif sig != _state["signature"]:
        reason = "데이터 변경"
        sale_dashboard.clear_cache()
        sale_products.clear_cache()
        sale_season.clear_cache()
        sale_mix.clear_cache()
    elif now.hour >= WARM_HOUR and _state["day"] != now.strftime("%Y%m%d"):
        reason = "아침 계산"
    if reason:
        _state["signature"] = sig
        if now.hour >= WARM_HOUR:
            _state["day"] = now.strftime("%Y%m%d")
        warm(reason)
    return reason


def loop() -> None:
    time.sleep(60)
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001
            _log.exception("판매 현황 미리 계산 점검 실패")
        time.sleep(CHECK_SEC)


def state() -> dict:
    return {k: v for k, v in _state.items() if k != "signature"} | {"running": _lock.locked()}
