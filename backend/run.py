"""백엔드 실행: python backend/run.py  (frontend/dist 가 있으면 같은 포트에서 화면도 제공)"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import uvicorn  # noqa: E402

from app import config  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.API_PORT, reload="--reload" in sys.argv)
