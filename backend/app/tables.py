"""운영 기능 테이블 확인: Oracle 테이블이 있어야만 기록·조회한다 (서버 로컬 저장 없음).

테이블이 없으면 화면은 '관리자에게 DDL 실행 요청' 안내를 보여주고, 기록(다운로드 이력·작업 실행)은 건너뛴다.
DDL: db/create_erp_web_admin_ops.sql (SS10 스키마에서 실행)
"""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException

from . import db

DDL_FILE = "db/create_erp_web_admin_ops.sql"


class Tables:
    def __init__(self, *tables: str):
        self.tables = tables
        self._state: tuple[float, list[str]] | None = None
        self._lock = threading.Lock()

    def missing(self) -> list[str]:
        """앱 계정이 쓸 수 없는 테이블 이름 (1분 캐시).

        앱이 쓰는 이름 그대로 조회해 본다 (SS10 에 테이블이 있어도 SS10DEV 동의어 · 권한이 없으면 쓸 수 없으므로).
        확인용 조회라 실패해도 SQL 오류 로그를 남기지 않는다."""
        now = time.time()
        with self._lock:
            if self._state and self._state[0] > now:
                return self._state[1]
        miss: list[str] = []
        try:
            with db.get_pool().acquire() as conn, conn.cursor() as cur:
                for t in self.tables:
                    try:
                        cur.execute(f"SELECT 1 FROM {t} WHERE 1 = 0")
                        cur.fetchall()
                    except Exception:  # noqa: BLE001 - ORA-00942 (테이블 · 동의어 · 권한 없음)
                        miss.append(t)
        except Exception:  # noqa: BLE001 - DB 연결 실패 등: 없는 것으로 보고 1분 뒤 다시 확인
            miss = list(self.tables)
        with self._lock:
            self._state = (now + 60, miss)
        return miss

    def ready(self) -> bool:
        return not self.missing()

    def message(self) -> str:
        miss = self.missing()
        return (f"테이블을 쓸 수 없습니다 ({', '.join(miss)}). {DDL_FILE} 를 SS10 스키마에서 실행하세요 "
                f"(테이블이 이미 있으면 SS10DEV 동의어 · 권한만: "
                + " ".join(f"CREATE SYNONYM SS10DEV.{t} FOR SS10.{t};" for t in miss) + ")")

    def require(self) -> None:
        if not self.ready():
            raise HTTPException(status_code=503, detail={"message": self.message(), "code": "TABLE_MISSING"})

    def status(self) -> dict:
        miss = self.missing()
        return {"ready": not miss, "missing": miss, "ddl": DDL_FILE}

    def reset(self) -> None:
        with self._lock:
            self._state = None
