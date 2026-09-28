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

# 최고 관리자 ID (항상 ADMIN, 권한 변경/비활성화 불가)
SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID", "250016")
# HTTPS 로 서비스할 때만 true (쿠키 Secure 속성)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# 원본/업무 테이블 소유 스키마 (SS10DEV 에 시노님이 없는 객체는 이 스키마로 접근)
DB_OWNER_SCHEMA = os.getenv("DB_OWNER_SCHEMA", "SS10")
