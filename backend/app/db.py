"""Oracle 11g 접속 (Thick 모드 + 커넥션 풀)."""
import threading
import time
from contextlib import contextmanager

import oracledb

from . import config, logs

_pool: oracledb.ConnectionPool | None = None
_lock = threading.Lock()
_log = logs.get("sql")


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


@contextmanager
def timed(sql: str, params: dict | None = None, what: str = "query"):
    """느린 쿼리(SLOW_SQL_SEC 이상)와 SQL 오류를 로그로 남긴다. 바인드 값은 기록하지 않는다(비밀번호 등 보호)."""
    start = time.perf_counter()
    try:
        yield
    except oracledb.Error as ex:
        _log.error("%s 실패 %.2fs %s | binds=%s | %s", what, time.perf_counter() - start, str(ex).splitlines()[0],
                   sorted((params or {}).keys()), logs.sql_text(sql))
        raise
    sec = time.perf_counter() - start
    if sec >= logs.SLOW_SQL_SEC:
        _log.warning("느린 %s %.2fs | binds=%s | %s", what, sec, sorted((params or {}).keys()), logs.sql_text(sql))


def query(sql: str, params: dict | None = None, arraysize: int = 5000) -> tuple[list[str], list[tuple]]:
    """SELECT 실행 후 (컬럼명 목록, 로우 목록) 반환."""
    with timed(sql, params), get_pool().acquire() as conn:
        with conn.cursor() as cur:
            cur.arraysize = arraysize
            cur.execute(sql, params or {})
            cols = [d[0] for d in cur.description]
            return cols, cur.fetchall()


def execute(sql: str, params: dict | None = None) -> int:
    """INSERT/UPDATE 실행 후 커밋. 영향받은 행 수 반환."""
    with timed(sql, params, "execute"), get_pool().acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            n = cur.rowcount
        conn.commit()
        return n


def query_dicts(sql: str, params: dict | None = None) -> list[dict]:
    cols, rows = query(sql, params)
    return [dict(zip(cols, r)) for r in rows]
