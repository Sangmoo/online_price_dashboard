"""환경설정 로드 (.env 는 프로젝트 루트에 위치)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

ORACLE_CLIENT_PATH = os.getenv("ORACLE_CLIENT_PATH", "")
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.getenv("DB_PORT", "1521"))
DB_SID = os.environ["DB_SID"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
ANTHROPIC_EFFORT = os.getenv("ANTHROPIC_EFFORT", "medium")

API_PORT = int(os.getenv("API_PORT", "8000"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

# 대시보드 최대 조회 기간(일)
MAX_RANGE_DAYS = 31
