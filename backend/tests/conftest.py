"""테스트 공통 설정.

- 단위 테스트: DB 없이 실행 (Oracle 호출은 monkeypatch 로 대체, SQLite 는 임시 파일)
- 통합 테스트(@pytest.mark.db): 실제 Oracle 에 접속. 접속이 안 되면 자동으로 건너뛴다. 조회만 하며 업무 데이터를 바꾸지 않는다.

실행: backend 폴더에서  .venv\\Scripts\\python -m pytest            (전체)
                     .venv\\Scripts\\python -m pytest -m "not db"  (DB 없이 단위 테스트만)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# .env 가 있으면 실제 값(통합 테스트용), 없으면 더미 값으로 config import 가 실패하지 않게 한다.
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND.parent / ".env")
except ImportError:
    pass
for k, v in {"DB_HOST": "localhost", "DB_SID": "XE", "DB_USER": "test", "DB_PASSWORD": "test"}.items():
    os.environ.setdefault(k, v)


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    """store(SQLite)를 임시 파일로 바꿔 세션·로그인 잠금 테스트가 실제 app.db 를 건드리지 않게 한다."""
    from app import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    if hasattr(store._local, "conn"):
        monkeypatch.delattr(store._local, "conn")
    store.init()
    yield store
    c = getattr(store._local, "conn", None)
    if c is not None:
        c.close()
        del store._local.conn


_oracle_ok: bool | None = None


@pytest.fixture(scope="session")
def oracle():
    """Oracle 접속 가능 여부 확인. 안 되면 통합 테스트 skip."""
    global _oracle_ok
    if _oracle_ok is None:
        try:
            from app import db

            db.query("SELECT 1 FROM DUAL")
            _oracle_ok = True
        except Exception as ex:  # noqa: BLE001
            _oracle_ok = False
            pytest.skip(f"Oracle 접속 불가로 통합 테스트를 건너뜁니다: {ex}")
    if not _oracle_ok:
        pytest.skip("Oracle 접속 불가로 통합 테스트를 건너뜁니다.")
    from app import db

    return db
