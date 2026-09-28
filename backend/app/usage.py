"""AI 사용량 / 비용 계산 / 일일 한도."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime

from . import db, store

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


# ----------------------------------------------------------------------------
# 저장소 선택: Oracle T_ERP_WEB_AI_USAGE 가 있으면 Oracle, 없으면 SQLite(ai_usage)
# 테이블이 생기면 자동 전환하고, 그동안 SQLite 에 쌓인 사용량을 1회 복사한다.
# ----------------------------------------------------------------------------
ORA_TABLE = "T_ERP_WEB_AI_USAGE"
ORA_SEQ = "SQ_ERP_WEB_AI_USAGE"
_ora_state = {"ok": False, "checked": 0.0}
_ora_lock = threading.Lock()


def _use_oracle() -> bool:
    if _ora_state["ok"]:
        return True
    now = time.time()
    if now - _ora_state["checked"] < 60:
        return False
    with _ora_lock:
        if _ora_state["ok"] or now - _ora_state["checked"] < 60:
            return _ora_state["ok"]
        _ora_state["checked"] = now
        try:
            db.query(f"SELECT 1 FROM {ORA_TABLE} WHERE ROWNUM = 1")
            db.query(f"SELECT {ORA_SEQ}.NEXTVAL FROM DUAL")
        except Exception:
            return False
        _migrate_sqlite_usage()
        _ora_state["ok"] = True
        return True


def backend_name() -> str:
    return "oracle" if _use_oracle() else "sqlite"


def _ymd(iso: str) -> str:
    return iso.replace("-", "")


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if ymd and len(ymd) == 8 else ymd


def _migrate_sqlite_usage() -> None:
    if store.row("SELECT 1 FROM settings WHERE key='_migr_usage_oracle'"):
        return
    rows = store.rows("SELECT * FROM ai_usage ORDER BY id")
    if rows:
        with db.get_pool().acquire() as conn:
            cur = conn.cursor()
            try:
                for r in rows:
                    ts = (r["ts"] or "").replace("-", "").replace(":", "").replace(" ", "")[:14] or _ymd(r["day"]) + "000000"
                    cur.execute(
                        f"""INSERT INTO {ORA_TABLE} (USAGE_ID, USR_ID, USE_DT, USE_DAY, USE_TYPE, CONV_ID, MODEL_NM,
                               INPUT_TOKENS, OUTPUT_TOKENS, CACHE_READ, CACHE_WRITE, COST_USD)
                            VALUES ({ORA_SEQ}.NEXTVAL, :u, :dt, :ts, :t, :c, :m, :i, :o, :cr, :cw, :cost)""",
                        {"u": r["usr_id"], "dt": _ymd(r["day"]), "ts": ts, "t": "Q" if r["kind"] == "question" else "C",
                         "c": r["conversation_id"], "m": r["model"], "i": r["input_tokens"] or 0,
                         "o": r["output_tokens"] or 0, "cr": r["cache_read"] or 0, "cw": r["cache_write"] or 0,
                         "cost": r["cost_usd"] or 0},
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    store.execute("INSERT INTO settings(key, value) VALUES('_migr_usage_oracle', 'true')")


# ----------------------------------------------------------------------------
# 조회
# ----------------------------------------------------------------------------
def today_usage(usr_id: str) -> dict:
    if _use_oracle():
        r = db.query_dicts(
            f"""SELECT NVL(SUM(DECODE(USE_TYPE, 'Q', 1, 0)), 0) AS QUESTIONS, NVL(SUM(COST_USD), 0) AS COST,
                       NVL(SUM(INPUT_TOKENS + CACHE_READ + CACHE_WRITE), 0) AS INPUT_TOKENS,
                       NVL(SUM(OUTPUT_TOKENS), 0) AS OUTPUT_TOKENS
                  FROM {ORA_TABLE} WHERE USR_ID = :u AND USE_DT = :d""",
            {"u": usr_id, "d": _ymd(today())},
        )[0]
        r = {k.lower(): v for k, v in r.items()}
    else:
        r = store.row(
            """SELECT COALESCE(SUM(kind='question'),0) AS questions, COALESCE(SUM(cost_usd),0) AS cost,
                      COALESCE(SUM(input_tokens + cache_read + cache_write),0) AS input_tokens,
                      COALESCE(SUM(output_tokens),0) AS output_tokens
                 FROM ai_usage WHERE usr_id=? AND day=?""",
            (usr_id, today()),
        )
    return {"questions": int(r["questions"]), "costUsd": round(float(r["cost"]), 4),
            "inputTokens": int(r["input_tokens"]), "outputTokens": int(r["output_tokens"])}


def today_by_user() -> dict[str, tuple[int, float]]:
    """관리자 사용자 목록용: 사용자별 오늘 (질문 수, 비용)."""
    if _use_oracle():
        rows = db.query(
            f"""SELECT USR_ID, SUM(DECODE(USE_TYPE, 'Q', 1, 0)), SUM(COST_USD)
                  FROM {ORA_TABLE} WHERE USE_DT = :d GROUP BY USR_ID""",
            {"d": _ymd(today())},
        )[1]
    else:
        rows = [tuple(r.values()) for r in store.rows(
            "SELECT usr_id, SUM(kind='question'), SUM(cost_usd) FROM ai_usage WHERE day=? GROUP BY usr_id", (today(),))]
    return {u: (int(q or 0), round(float(c or 0), 4)) for u, q, c in rows}


def report(since_iso: str) -> dict:
    """관리자 사용 현황: 일자별 / 사용자별 / 합계. day 는 YYYY-MM-DD."""
    if _use_oracle():
        p = {"s": _ymd(since_iso)}
        daily = db.query_dicts(
            f"""SELECT USE_DT AS DAY, SUM(DECODE(USE_TYPE, 'Q', 1, 0)) AS QUESTIONS, SUM(DECODE(USE_TYPE, 'C', 1, 0)) AS CALLS,
                       SUM(INPUT_TOKENS + CACHE_READ + CACHE_WRITE) AS INPUT_TOKENS, SUM(OUTPUT_TOKENS) AS OUTPUT_TOKENS,
                       ROUND(SUM(COST_USD), 4) AS COST, COUNT(DISTINCT USR_ID) AS USERS
                  FROM {ORA_TABLE} WHERE USE_DT >= :s GROUP BY USE_DT ORDER BY USE_DT""", p)
        by_user = db.query_dicts(
            f"""SELECT USR_ID, SUM(DECODE(USE_TYPE, 'Q', 1, 0)) AS QUESTIONS, SUM(DECODE(USE_TYPE, 'C', 1, 0)) AS CALLS,
                       SUM(INPUT_TOKENS + CACHE_READ + CACHE_WRITE) AS INPUT_TOKENS, SUM(OUTPUT_TOKENS) AS OUTPUT_TOKENS,
                       ROUND(SUM(COST_USD), 4) AS COST, MAX(USE_DAY) AS LAST_USED
                  FROM {ORA_TABLE} WHERE USE_DT >= :s GROUP BY USR_ID ORDER BY SUM(COST_USD) DESC""", p)
        total = db.query_dicts(
            f"""SELECT NVL(SUM(DECODE(USE_TYPE, 'Q', 1, 0)), 0) AS QUESTIONS, NVL(ROUND(SUM(COST_USD), 4), 0) AS COST,
                       NVL(SUM(INPUT_TOKENS + CACHE_READ + CACHE_WRITE), 0) AS INPUT_TOKENS,
                       NVL(SUM(OUTPUT_TOKENS), 0) AS OUTPUT_TOKENS, COUNT(DISTINCT USR_ID) AS USERS
                  FROM {ORA_TABLE} WHERE USE_DT >= :s""", p)[0]
        low = lambda r: {k.lower(): (float(v) if k == "COST" and v is not None else int(v) if isinstance(v, (int, float)) else v)
                         for k, v in r.items()}
        daily = [{**low(r), "day": _iso(r["DAY"])} for r in daily]
        by_user = [{**low(r), "last_used": _fmt14(r["LAST_USED"])} for r in by_user]
        return {"daily": daily, "byUser": by_user, "total": low(total)}
    daily = store.rows(
        """SELECT day, SUM(kind='question') AS questions, SUM(kind='api_call') AS calls,
                  SUM(input_tokens + cache_read + cache_write) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  ROUND(SUM(cost_usd), 4) AS cost, COUNT(DISTINCT usr_id) AS users
             FROM ai_usage WHERE day >= ? GROUP BY day ORDER BY day""", (since_iso,))
    by_user = store.rows(
        """SELECT usr_id, SUM(kind='question') AS questions, SUM(kind='api_call') AS calls,
                  SUM(input_tokens + cache_read + cache_write) AS input_tokens, SUM(output_tokens) AS output_tokens,
                  ROUND(SUM(cost_usd), 4) AS cost, MAX(ts) AS last_used
             FROM ai_usage WHERE day >= ? GROUP BY usr_id ORDER BY cost DESC""", (since_iso,))
    total = store.row(
        """SELECT COALESCE(SUM(kind='question'),0) AS questions, COALESCE(ROUND(SUM(cost_usd),4),0) AS cost,
                  COALESCE(SUM(input_tokens + cache_read + cache_write),0) AS input_tokens,
                  COALESCE(SUM(output_tokens),0) AS output_tokens, COUNT(DISTINCT usr_id) AS users
             FROM ai_usage WHERE day >= ?""", (since_iso,))
    return {"daily": daily, "byUser": by_user, "total": total}


def _fmt14(v: str | None) -> str | None:
    return f"{v[:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}" if v and len(v) >= 14 else v


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


# ----------------------------------------------------------------------------
# 기록
# ----------------------------------------------------------------------------
def _ora_insert(usr_id: str, conv_id: str, kind: str, model=None, i=0, o=0, cr=0, cw=0, cost=0.0) -> int:
    new_id = int(db.query(f"SELECT {ORA_SEQ}.NEXTVAL FROM DUAL")[1][0][0])
    db.execute(
        f"""INSERT INTO {ORA_TABLE} (USAGE_ID, USR_ID, USE_DT, USE_DAY, USE_TYPE, CONV_ID, MODEL_NM,
               INPUT_TOKENS, OUTPUT_TOKENS, CACHE_READ, CACHE_WRITE, COST_USD)
            VALUES (:id, :u, :dt, :ts, :t, :c, :m, :i, :o, :cr, :cw, :cost)""",
        {"id": new_id, "u": usr_id, "dt": _ymd(today()), "ts": datetime.now().strftime("%Y%m%d%H%M%S"),
         "t": kind, "c": conv_id, "m": model, "i": i, "o": o, "cr": cr, "cw": cw, "cost": cost},
    )
    return new_id


def record_question(usr_id: str, conversation_id: str) -> tuple[str, int]:
    if _use_oracle():
        return "oracle", _ora_insert(usr_id, conversation_id, "Q")
    cur = store.execute("INSERT INTO ai_usage(usr_id, day, conversation_id, kind) VALUES(?,?,?,'question')",
                        (usr_id, today(), conversation_id))
    return "sqlite", cur.lastrowid


def cancel_question(question: tuple[str, int]) -> None:
    where, qid = question
    if where == "oracle":
        db.execute(f"DELETE FROM {ORA_TABLE} WHERE USAGE_ID = :id AND USE_TYPE = 'Q'", {"id": qid})
    else:
        store.execute("DELETE FROM ai_usage WHERE id=? AND kind='question'", (qid,))


def record_call(usr_id: str, conversation_id: str, model: str | None, usage) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost = cost_of(model, inp, out, cr, cw)
    if _use_oracle():
        _ora_insert(usr_id, conversation_id, "C", model, inp, out, cr, cw, round(cost, 6))
    else:
        store.execute(
            """INSERT INTO ai_usage(usr_id, day, conversation_id, kind, model, input_tokens, output_tokens, cache_read, cache_write, cost_usd)
               VALUES(?,?,?,'api_call',?,?,?,?,?,?)""",
            (usr_id, today(), conversation_id, model, inp, out, cr, cw, cost),
        )
    return cost
