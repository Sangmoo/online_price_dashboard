"""백엔드 실행: python backend/run.py  (frontend/dist 가 있으면 같은 포트에서 화면도 제공)"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

import uvicorn  # noqa: E402

from app import config  # noqa: E402


def _disable_console_quick_edit() -> None:
    """Windows 콘솔의 '빠른 편집(QuickEdit)'을 이 창에서만 끈다.

    켜져 있으면 서버 창을 마우스로 클릭하는 순간 '선택' 상태가 되어 콘솔 출력이 멈추고,
    로그를 출력하려던 서버 전체가 멈춘다(요청 처리 스레드가 출력에서 대기). Esc/Enter 를 눌러야 풀린다.
    Windows 전체 설정은 바꾸지 않으며, 콘솔이 없는 실행(서비스 등)에서는 아무것도 하지 않는다.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
            kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
    except Exception:  # noqa: BLE001 - 콘솔 설정 실패는 서버 실행에 영향 없음
        pass


if __name__ == "__main__":
    _disable_console_quick_edit()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=config.API_PORT,
        reload="--reload" in sys.argv,
        # 요청별 콘솔 출력은 끈다. 요청 기록은 backend/logs/app.log 에 남는다 (app/logs.py).
        access_log=False,
    )
