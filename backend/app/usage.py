"""AI 사용량 / 비용 계산 / 일일 한도."""
from __future__ import annotations

from datetime import date

from . import store

# USD per 1M tokens: (input, output, cache_read). cache write(5분) = input × 1.25
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
DEFAULT_PRICE = PRICES["claude-opus-5"]


def price_for(model: str | None) -> tuple[float, float, float]:
    if not model:
        return DEFAULT_PRICE
    for key in sorted(PRICES, key=len, reverse=True):  # 가장 구체적인 ID 우선
        if model.startswith(key):
            return PRICES[key]
    return DEFAULT_PRICE


def cost_of(model: str | None, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    pin, pout, pread = price_for(model)
    return (input_tokens * pin + output_tokens * pout + cache_read * pread + cache_write * pin * 1.25) / 1_000_000


def today() -> str:
    return date.today().isoformat()


def today_usage(usr_id: str) -> dict:
    r = store.row(
        """SELECT COALESCE(SUM(kind='question'),0) AS questions, COALESCE(SUM(cost_usd),0) AS cost,
                  COALESCE(SUM(input_tokens + cache_read + cache_write),0) AS input_tokens,
                  COALESCE(SUM(output_tokens),0) AS output_tokens
             FROM ai_usage WHERE usr_id=? AND day=?""",
        (usr_id, today()),
    )
    return {"questions": int(r["questions"]), "costUsd": round(float(r["cost"]), 4),
            "inputTokens": int(r["input_tokens"]), "outputTokens": int(r["output_tokens"])}


def usage_summary(me: dict) -> dict:
    u = today_usage(me["id"])
    lim = me["ai"]
    return {
        **u,
        "questionLimit": lim["dailyQuestions"],
        "costLimitUsd": lim["dailyCostUsd"],
        "enabled": lim["enabled"],
    }


def check_can_ask(me: dict) -> str | None:
    """질문 가능하면 None, 아니면 사유 메시지."""
    ai = me["ai"]
    if not ai["globalEnabled"]:
        return "관리자가 AI 기능을 일시 중지했습니다."
    if not ai["userEnabled"]:
        return "AI 사용 권한이 없습니다. 관리자에게 문의하세요."
    u = today_usage(me["id"])
    if u["questions"] >= ai["dailyQuestions"]:
        return f"오늘 질문 한도({ai['dailyQuestions']}회)를 모두 사용했습니다. 내일 다시 이용해 주세요."
    if u["costUsd"] >= ai["dailyCostUsd"]:
        return f"오늘 AI 사용 비용 한도(${ai['dailyCostUsd']:.2f})에 도달했습니다. 내일 다시 이용해 주세요."
    return None


def record_question(usr_id: str, conversation_id: str) -> int:
    cur = store.execute("INSERT INTO ai_usage(usr_id, day, conversation_id, kind) VALUES(?,?,?,'question')",
                        (usr_id, today(), conversation_id))
    return cur.lastrowid


def cancel_question(question_id: int) -> None:
    store.execute("DELETE FROM ai_usage WHERE id=? AND kind='question'", (question_id,))


def record_call(usr_id: str, conversation_id: str, model: str | None, usage) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost = cost_of(model, inp, out, cr, cw)
    store.execute(
        """INSERT INTO ai_usage(usr_id, day, conversation_id, kind, model, input_tokens, output_tokens, cache_read, cache_write, cost_usd)
           VALUES(?,?,?,'api_call',?,?,?,?,?,?)""",
        (usr_id, today(), conversation_id, model, inp, out, cr, cw, cost),
    )
    return cost
