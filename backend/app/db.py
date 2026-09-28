"""Oracle 11g 접속 (Thick 모드 + 커넥션 풀)."""
import threading

import oracledb

from . import config

_pool: oracledb.ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> oracledb.ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            # Oracle 11g 는 Thin 모드 미지원 → Instant Client 로 Thick 모드 활성화
            oracledb.init_oracle_client(lib_dir=config.ORACLE_CLIENT_PATH or None)
            dsn = oracledb.makedsn(config.DB_HOST, config.DB_PORT, sid=config.DB_SID)
            _pool = oracledb.create_pool(
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                dsn=dsn,
                min=1,
                max=10,
                increment=1,
            )
        return _pool


def query(sql: str, params: dict | None = None, arraysize: int = 5000) -> tuple[list[str], list[tuple]]:
    """SELECT 실행 후 (컬럼명 목록, 로우 목록) 반환."""
    with get_pool().acquire() as conn:
        with conn.cursor() as cur:
            cur.arraysize = arraysize
            cur.execute(sql, params or {})
            cols = [d[0] for d in cur.description]
            return cols, cur.fetchall()


def execute(sql: str, params: dict | None = None) -> int:
    """INSERT/UPDATE 실행 후 커밋. 영향받은 행 수 반환."""
    with get_pool().acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            n = cur.rowcount
        conn.commit()
        return n


def query_dicts(sql: str, params: dict | None = None) -> list[dict]:
    cols, rows = query(sql, params)
    return [dict(zip(cols, r)) for r in rows]
