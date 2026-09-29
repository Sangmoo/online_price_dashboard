"""AI 조회 도구의 행 수 상한. 평소에는 도구별 MAX_LIMIT(200), 'AI 표 전체 엑셀' 을 만들 때만 잠시 FULL_EXPORT_MAX 까지 허용.

상한은 요청 스레드의 컨텍스트 변수로 바꿔, 같은 시각 다른 사용자의 AI 대화에는 영향이 없다.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

FULL_EXPORT_MAX = 100_000
_cap: ContextVar[int | None] = ContextVar("tool_row_cap", default=None)


def cap(default_max: int) -> int:
    return _cap.get() or default_max


@contextmanager
def full_export():
    token = _cap.set(FULL_EXPORT_MAX)
    try:
        yield FULL_EXPORT_MAX
    finally:
        _cap.reset(token)
