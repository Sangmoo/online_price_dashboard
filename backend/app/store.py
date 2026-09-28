"""서비스 자체 저장소 (SQLite): 사용자 권한, 세션, 로그인 잠금, AI 사용량, 대화 기록, 즐겨찾기, 사용자 설정."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    usr_id          TEXT PRIMARY KEY,
    usr_nm          TEXT,
    role            TEXT NOT NULL DEFAULT 'USER',      -- ADMIN | USER
    pages           TEXT NOT NULL DEFAULT '["dashboard","detail"]',
    ai_enabled      INTEGER NOT NULL DEFAULT 1,
    daily_questions INTEGER,                            -- NULL = 기본값 사용
    daily_cost_usd  REAL,                               -- NULL = 기본값 사용
    active          INTEGER NOT NULL DEFAULT 1,
    last_login_at   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT,
    updated_by      TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    sid         TEXT NOT NULL UNIQUE,                   -- 관리 화면 노출용 ID (토큰 비노출)
    usr_id      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    expires_at  REAL NOT NULL,
    ip          TEXT,
    user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_usr ON sessions(usr_id);
CREATE TABLE IF NOT EXISTS login_attempts (
    usr_id       TEXT PRIMARY KEY,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS login_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    usr_id   TEXT NOT NULL,
    ts       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    success  INTEGER NOT NULL,
    reason   TEXT,
    ip       TEXT
);
CREATE TABLE IF NOT EXISTS ai_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usr_id          TEXT NOT NULL,
    day             TEXT NOT NULL,                      -- YYYY-MM-DD (로컬)
    ts              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    conversation_id TEXT,
    kind            TEXT NOT NULL,                      -- question | api_call
    model           TEXT,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cache_read      INTEGER DEFAULT 0,
    cache_write     INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ai_usage_day ON ai_usage(usr_id, day);
CREATE TABLE IF NOT EXISTS conversations (
    id           TEXT PRIMARY KEY,
    usr_id       TEXT NOT NULL,
    title        TEXT,
    api_messages TEXT NOT NULL DEFAULT '[]',
    display      TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_conv_usr ON conversations(usr_id, updated_at);
CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usr_id     TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(usr_id, text)
);
CREATE TABLE IF NOT EXISTS prefs (
    usr_id TEXT NOT NULL,
    key    TEXT NOT NULL,
    value  TEXT NOT NULL,
    PRIMARY KEY (usr_id, key)
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "ai_enabled": True,               # 전체 AI 기능 사용 여부
    "default_daily_questions": 10,    # 사용자별 일일 질문 수 기본 한도
    "default_daily_cost_usd": 2.0,    # 사용자별 일일 비용 기본 한도(USD)
    "model": None,                    # None = .env 의 ANTHROPIC_MODEL
    "effort": None,                   # None = .env 의 ANTHROPIC_EFFORT
}


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def init() -> None:
    conn().executescript(SCHEMA)
    _migrate()


def _migrate() -> None:
    """1회성 데이터 마이그레이션 (settings 테이블의 '_migr_*' 키로 실행 여부 기록)."""
    if not row("SELECT 1 FROM settings WHERE key='_migr_invt_plan'"):
        # 매장 재고 실사계획 메뉴: 기존 사용자 전원에게 권한 부여
        with tx() as c:
            for u in c.execute("SELECT usr_id, pages FROM users").fetchall():
                pages = json.loads(u["pages"] or "[]")
                if "invt_plan" not in pages:
                    c.execute("UPDATE users SET pages=? WHERE usr_id=?", (json.dumps(pages + ["invt_plan"]), u["usr_id"]))
            c.execute("INSERT INTO settings(key, value) VALUES('_migr_invt_plan', 'true')")


def rows(sql: str, params: tuple | dict = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def row(sql: str, params: tuple | dict = ()) -> dict | None:
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def execute(sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
    return conn().execute(sql, params)


# ----------------------------------------------------------------------------
# 전역 설정
# ----------------------------------------------------------------------------
def get_settings() -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for r in rows("SELECT key, value FROM settings WHERE substr(key, 1, 1) <> '_'"):  # '_migr_*' 등 내부 키 제외
        out[r["key"]] = json.loads(r["value"])
    return out


def save_settings(values: dict[str, Any]) -> dict[str, Any]:
    with tx() as c:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, json.dumps(v)),
                )
    return get_settings()


# ----------------------------------------------------------------------------
# 사용자 설정(개인 환경설정)
# ----------------------------------------------------------------------------
def get_pref(usr_id: str, key: str):
    r = row("SELECT value FROM prefs WHERE usr_id=? AND key=?", (usr_id, key))
    return json.loads(r["value"]) if r else None


def set_pref(usr_id: str, key: str, value) -> None:
    execute(
        "INSERT INTO prefs(usr_id, key, value) VALUES(?,?,?) ON CONFLICT(usr_id, key) DO UPDATE SET value=excluded.value",
        (usr_id, key, json.dumps(value, ensure_ascii=False)),
    )
