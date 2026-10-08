"""AI 주간 브리핑: 지난주(월~일) 판매 · RT 성과 · 미처리 RT · 창고 부족 · 재고 회전 · 장기 재고 · 초도 적중률을 모아
한 장 보고서로. 숫자는 서버가 기존 계산(재고 재배치 추천 · 판매)에서 직접 모으고, AI 는 그 숫자로 요약과 이번 주 할 일만 쓴다.

- 브랜드: 사용자의 브랜드 권한 (없으면 모든 브랜드)
- 판매 부분은 판매 메뉴 권한(판매 현황 · 월별 판매), 재고 부분은 재고 재배치 추천 권한이 있을 때만
- AI 는 한 번 호출(대화창과 같은 모델 · 사용량 기록). 한도는 대화 질문 · 비용과 따로 하루 N회(사용자별, 기본 3회) —
  넘으면 숫자 보고서만 돌려준다
- 같은 사용자 · 주 · 브랜드 조합은 1시간 동안 다시 만들지 않는다 ([다시 만들기]는 새로 계산 · AI 다시 호출)
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import anthropic

from . import config, db, logs, usage, userdb
from . import stock_ctl as sc

_log = logs.get("app")
CACHE_TTL = 3600
FALLBACK_BETA = "server-side-fallback-2026-07-01"
SALE_PAGES = {"sale_dashboard", "sale_monthly"}
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()

SYSTEM = """당신은 패션 브랜드 영업 관리팀의 주간 브리핑 작성자입니다. 사용자 메시지의 JSON 숫자만 근거로, 영업 MD · 팀장이 월요일 아침에 1분 안에 읽을 한 장 브리핑을 한국어로 씁니다.

형식 (마크다운, 제목 없이 이 네 부분만):
### 핵심 요약
- 3~4줄. 가장 중요한 변화부터. 숫자는 억 · 만 · % 로 짧게.
### 판매
- 2~4줄. 브랜드별 전주 · 전년 대비, 눈에 띄는 매장 · 스타일. (판매 데이터가 없으면 이 부분은 쓰지 않음)
### 재고 · 재배치
- 3~5줄. RT 수락률 · 미처리(자동거부 임박), 창고 부족, 재고일수 · 품절 위험 · 과다, 장기 미판매, 초도 적중률 중 의미 있는 것만.
### 이번 주 할 일
- 3~5개. 누가 무엇을 하면 되는지 구체적으로 (예: '미처리 RT 많은 ○○매장 확인', '창고 부족 상품 매장 간 RT 로 채우기 검토').

규칙: JSON 에 없는 숫자를 만들지 않습니다. 값이 null 이거나 오류인 항목은 언급하지 않습니다. 원인은 데이터로 보이는 범위에서만 '~로 보입니다'처럼 씁니다. 전체 900자 안팎."""


def week_range(today: date | None = None) -> tuple[date, date]:
    """지난주 월요일 ~ 일요일"""
    t = today or date.today()
    end = t - timedelta(days=t.weekday() + 1)
    return end - timedelta(days=6), end


def _d8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _rate(a: float, b: float) -> float | None:
    return round((a - b) / b * 100, 1) if b else None


def _sales(brands: list[str], start: date, end: date) -> dict:
    """브랜드별 지난주 · 전주 · 전년 같은 요일(364일 전) 실판매금액 · 수량, 일별, 매장 · 스타일 상위"""
    ranges = {"cur": (start, end), "prev": (start - timedelta(days=7), end - timedelta(days=7)),
              "ly": (start - timedelta(days=364), end - timedelta(days=364))}
    out: dict[str, dict] = {b: {"brand": b, "brandNm": sc.BRAND_CODES[b]} for b in brands}
    for key, (f, t) in ranges.items():
        for b, amt, qty in db.query(f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_05) */ SUBSTR(R.PRDT_CD, 1, 1),
                                               SUM(DECODE(R.RET_YN, 'Y', -1, 1) * NVL(R.REAL_SALE_AMT, 0)), SUM(DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY))
                                          FROM T_SHOP_RNDS_BASE R
                                         WHERE R.MAKE_DT BETWEEN :f AND :t AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL
                                           AND R.COMPY_CD = '{sc.COMPY_CD}'
                                         GROUP BY SUBSTR(R.PRDT_CD, 1, 1)""", {"f": _d8(f), "t": _d8(t)})[1]:
            if b in out:
                out[b][f"{key}Amt"], out[b][f"{key}Qty"] = int(amt or 0), int(qty or 0)
    names = {sid: sh["shopNm"] for sid, sh in sc.shops().items()}
    for b, g in out.items():
        g.setdefault("curAmt", 0)
        g.setdefault("curQty", 0)
        g["vsPrev"] = _rate(g["curAmt"], g.get("prevAmt", 0))
        g["vsLy"] = _rate(g["curAmt"], g.get("lyAmt", 0))
        rows = db.query(f"""SELECT /*+ INDEX(R IDX_T_SHOP_RNDS_BASE_05) */ R.SHOP_ID, R.PRDT_CD, R.MAKE_DT,
                                   SUM(DECODE(R.RET_YN, 'Y', -1, 1) * NVL(R.REAL_SALE_AMT, 0)), SUM(DECODE(R.RET_YN, 'Y', -R.QTY, R.QTY))
                              FROM T_SHOP_RNDS_BASE R
                             WHERE R.MAKE_DT BETWEEN :f AND :t AND R.STOCK_STAT = 'C20922' AND R.DEL_DAY IS NULL
                               AND R.COMPY_CD = '{sc.COMPY_CD}' AND R.PRDT_CD LIKE :b || '%'
                             GROUP BY R.SHOP_ID, R.PRDT_CD, R.MAKE_DT""", {"f": _d8(start), "t": _d8(end), "b": b}, arraysize=50000)[1]
        by_shop: dict[str, int] = {}
        by_style: dict[str, list[int]] = {}
        by_day: dict[str, int] = {}
        for sid, p, d8, amt, qty in rows:
            by_shop[sid] = by_shop.get(sid, 0) + int(amt or 0)
            s = by_style.setdefault(p, [0, 0])
            s[0] += int(amt or 0)
            s[1] += int(qty or 0)
            by_day[d8] = by_day.get(d8, 0) + int(amt or 0)
        g["topShops"] = [{"shopId": k, "shopNm": names.get(k), "amt": v} for k, v in sorted(by_shop.items(), key=lambda x: -x[1])[:5]]
        g["topStyles"] = [{"prdtCd": k, "amt": v[0], "qty": v[1]} for k, v in sorted(by_style.items(), key=lambda x: -x[1][1])[:5]]
        g["days"] = [{"day": sc.ymd_label(k), "amt": by_day.get(k, 0)} for k in (_d8(start + timedelta(days=i)) for i in range(7))]
    return {"brands": list(out.values()), "ranges": {k: [sc.ymd_label(_d8(f)), sc.ymd_label(_d8(t))] for k, (f, t) in ranges.items()}}


def _stock(b: str, start: date, end: date, allowed) -> tuple[dict, list[str]]:
    """한 브랜드의 재고 재배치 · 재고 건강 요약 (각 계산이 실패해도 나머지는 채운다)"""
    from . import stock_aging, stock_initial, stock_pending, stock_perf, stock_turnover, wh_alloc

    out: dict = {"brand": b, "brandNm": sc.BRAND_CODES[b]}
    errors: list[str] = []

    def take(name, fn):
        try:
            out[name] = fn()
        except Exception as ex:  # noqa: BLE001 - 한 부분 실패가 브리핑 전체를 막지 않게
            msg = getattr(ex, "detail", None)
            msg = msg.get("message") if isinstance(msg, dict) else str(ex).splitlines()[0]
            errors.append(f"{sc.BRAND_CODES[b]} {name}: {msg[:120]}")
            _log.warning("주간 브리핑 %s %s 실패: %s", b, name, msg)

    def rt():
        s = stock_perf.performance(b, _d8(start), _d8(end), "all", allowed)["summary"]
        return {k: s[k] for k in ("total", "accepted", "denied", "autoDenied", "pending", "canceled", "acceptRate", "avgHours", "soldRate")}

    def pending():
        d = stock_pending.board(b, 7, None, False, allowed)
        return {**{k: d["summary"][k] for k in ("rows", "shops", "urgent")},
                "topShops": [{"shopNm": g["name"], "rows": g["rows"], "urgent": g["urgent"]} for g in d["shops"][:3]]}

    def short():
        s = wh_alloc.recommend(brand=b, allowed=allowed)["summary"]
        return {k: s[k] for k in ("allocQty", "demand", "short", "noStockSkus", "shortRows")}

    def turnover():
        d = stock_turnover.report(b, 28, allowed=allowed)
        return {**{k: d["summary"][k] for k in ("cover", "sellThru", "shortRows", "overRows", "overStock")},
                "slowShops": [{"shopNm": g["shopNm"], "cover": g["cover"]} for g in d["shops"] if g["cover"] is not None][:3]}

    def aging():
        s = stock_aging.report(b, 90, allowed=allowed)["summary"]
        return {k: s[k] for k in ("qty", "agedQty", "agedAmt", "agedRate", "agedShops")}

    def initial():
        d = stock_initial.analyze(b, window=28, allowed=allowed)
        return {**{k: d["summary"][k] for k in ("alloc", "sold", "sellThru", "overlap", "lowOverlap", "products")},
                "period": f"{d['from']} ~ {d['to']}"}

    for name, fn in (("rt", rt), ("pending", pending), ("short", short), ("turnover", turnover), ("aging", aging), ("initial", initial)):
        take(name, fn)
    return out, errors


def _ai(me: dict, data: dict) -> dict:
    blocked = usage.check_can_brief(me)              # 질문 · 비용 한도와 따로: 하루 N회 (사용자별, 기본 3회)
    if blocked:
        return {"text": None, "blocked": blocked, "limit": blocked == usage.BRIEF_LIMIT_MSG}
    conv_id = f"briefing-{int(time.time())}"
    qid = usage.record_question(me["id"], conv_id)
    settings = userdb.get_settings()
    model = settings.get("model") or config.ANTHROPIC_MODEL
    try:
        client = anthropic.Anthropic()
        with client.beta.messages.stream(
            model=model, max_tokens=4000, system=SYSTEM, output_config={"effort": "medium"},
            messages=[{"role": "user", "content": json.dumps(data, ensure_ascii=False, default=str)}],
            betas=[FALLBACK_BETA], fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
        cost = usage.record_call(me["id"], conv_id, msg.model, msg.usage)
        if msg.stop_reason == "refusal":
            return {"text": None, "blocked": "AI 가 이 요청에 답하지 않았습니다. 숫자 보고서만 보여 드립니다.", "model": msg.model}
        text = "".join(bl.text for bl in msg.content if bl.type == "text").strip()
        return {"text": text, "model": msg.model, "costUsd": round(cost, 4)}
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as ex:
        usage.cancel_question(qid)
        _log.warning("주간 브리핑 AI 실패 user=%s: %s", me["id"], ex)
        return {"text": None, "blocked": "AI 요약을 만들지 못했습니다 (AI 서비스 연결 오류). 숫자 보고서만 보여 드립니다."}


def _quota(me: dict) -> dict | None:
    """오늘 브리핑 사용 · 한도 (대화 질문 · 비용 한도와 별도) — 화면 [다시 만들기] 옆 표시"""
    try:
        return {"used": usage.today_usage(me["id"])["briefings"], "limit": (me.get("ai") or {}).get("dailyBriefings", 3)}
    except Exception:  # noqa: BLE001 - 표시용
        return None


def weekly(me: dict, brand: str | None = None, refresh: bool = False, today: date | None = None) -> dict:
    allowed = me.get("brands") or None
    pages = set(me.get("pages") or [])
    if not (pages & (SALE_PAGES | {"stock_rt"})):
        sc.bad("판매 또는 재고 재배치 추천 메뉴 권한이 있어야 주간 브리핑을 볼 수 있습니다.", 403)
    brands = [sc.brand_code(brand, allowed)] if brand else [c for c, n in sc.BRAND_CODES.items() if allowed is None or n in allowed]
    if not brands:
        sc.bad("볼 수 있는 브랜드가 없습니다.", 403)
    start, end = week_range(today)
    key = (me["id"], _d8(start), tuple(brands), tuple(sorted(pages & (SALE_PAGES | {"stock_rt"}))))
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] > time.time() and not refresh:
        return {**hit[1], "cached": True, "quota": _quota(me)}
    t0 = time.perf_counter()
    errors: list[str] = []
    data: dict = {"period": {"from": sc.ymd_label(_d8(start)), "to": sc.ymd_label(_d8(end))}, "brands": [sc.BRAND_CODES[b] for b in brands]}
    # 판매 · 브랜드별 재고를 동시에 계산 (서로 독립 · DB 연결 최대 4개)
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="briefing") as pool:
        sales_f = pool.submit(_sales, brands, start, end) if pages & SALE_PAGES else None
        stock_fs = [pool.submit(_stock, b, start, end, allowed) for b in brands] if "stock_rt" in pages else None
        if sales_f is not None:
            try:
                data["sales"] = sales_f.result()
            except Exception as ex:  # noqa: BLE001
                errors.append(f"판매: {str(ex).splitlines()[0][:120]}")
                _log.error("주간 브리핑 판매 실패", exc_info=ex)
        if stock_fs is not None:
            data["stock"] = []
            for f in stock_fs:
                part, errs = f.result()
                data["stock"].append(part)
                errors += errs
    ai = _ai(me, {**data, "note": "rt=지난주 본사지시 RT(행사 · 가상 매장 제외), pending=지금 매장 미처리 RT(최근 7일 요청), "
                                  "short=어제 판매분 창고 배분 시 창고 부족, turnover=최근 28일 재고일수, aging=90일 넘게 안 팔린 매장 재고, "
                                  "initial=판매 28일이 지난 최근 30일 초도 배분 적중률",
                                  "terms": "용어는 화면과 같게: sellThru=판매율, overlap=적중률(배분 비중과 판매 비중이 겹친 정도), cover=재고일수, "
                                           "acceptRate=수락률, soldRate=RT 후 7일 판매 전환율, agedRate=장기 미판매 비중, urgent=자동거부 임박, "
                                           "shortRows=품절 위험(매장 × 스타일), overRows=과다(매장 × 스타일)"})
    result = {**data, "ai": ai, "errors": errors, "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"), "sec": round(time.perf_counter() - t0, 1),
              "cached": False}
    with _lock:
        _cache[key] = (time.time() + CACHE_TTL, result)
    result = {**result, "quota": _quota(me)}
    _log.info("주간 브리핑 user=%s 브랜드=%s %.1f초 AI=%s 오류 %d", me["id"], brands, result["sec"], bool(ai.get("text")), len(errors))
    return result
