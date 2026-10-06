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
        """없는 테이블 이름 (1분 캐시). 데이터 사전으로 확인해 SQL 오류 로그를 남기지 않는다."""
        now = time.time()
        with self._lock:
            if self._state and self._state[0] > now:
                return self._state[1]
        try:
            binds = {f"t{i}": t for i, t in enumerate(self.tables)}
            found = {r[0] for r in db.query(
                f"SELECT DISTINCT TABLE_NAME FROM ALL_TABLES WHERE TABLE_NAME IN ({', '.join(':' + k for k in binds)})", binds)[1]}
            miss = [t for t in self.tables if t not in found]
        except Exception:  # noqa: BLE001 - DB 연결 실패 등: 없는 것으로 보고 짧게 다시 확인
            miss = list(self.tables)
        with self._lock:
            self._state = (now + 60, miss)
        return miss

    def ready(self) -> bool:
        return not self.missing()

    def message(self) -> str:
        return f"테이블이 없습니다 ({', '.join(self.missing())}). {DDL_FILE} 를 SS10 스키마에서 실행하세요."

    def require(self) -> None:
        if not self.ready():
            raise HTTPException(status_code=503, detail={"message": self.message(), "code": "TABLE_MISSING"})

    def status(self) -> dict:
        miss = self.missing()
        return {"ready": not miss, "missing": miss, "ddl": DDL_FILE}

    def reset(self) -> None:
        with self._lock:
            self._state = None
