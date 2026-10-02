"""AI 모델 자동 선택: 꺼져 있으면 기본 모델, 단순 조회는 저렴한 모델(low), 분석·애매하면 기본 모델. 설정 검증."""
import pytest
from fastapi import HTTPException

from app import admin, model_router as mr

ON = {"auto_model": True, "simple_model": "claude-haiku-4-5"}


@pytest.mark.parametrize("q,kind", [
    ("지난달 쉬즈미스 실판금액 얼마야?", "simple"),
    ("김재필 담당 매장 목록 보여줘", "simple"),
    ("타임스퀘어 담당자 누구야", "simple"),
    ("브랜드별 하락 원인을 분석하고 대응 방안 정리해줘", "complex"),
    ("왜 세일 비중이 늘었어?", "complex"),
    ("지난달 실적", "complex"),  # 애매하면 기본 모델
    ("지난달 매출 상위 매장 10곳과 각 매장의 전년 대비 증감, 원가율, 할인율, 담당자를 한 표로 보여줘 그리고 특이점도", "complex"),
])
def test_classify(q, kind):
    assert mr.classify(q) == kind


def test_choose():
    assert mr.choose("얼마야?", {"auto_model": False}, "claude-opus-5", "medium") == ("claude-opus-5", "medium", "off")
    assert mr.choose("실판금액 얼마야?", ON, "claude-opus-5", "medium") == ("claude-haiku-4-5", "low", "simple")
    assert mr.choose("원인 분석해줘", ON, "claude-opus-5", "medium") == ("claude-opus-5", "medium", "complex")
    assert mr.choose("몇 개야?", {"auto_model": True, "simple_model": None}, "claude-opus-5", "high")[0] == mr.DEFAULT_SIMPLE_MODEL


def test_settings_validation(monkeypatch, audit_capture):
    saved = {}
    base = {"ai_enabled": True, "default_daily_questions": 10, "default_daily_cost_usd": 2.0, "model": None, "effort": None,
            "log_keep_days": 7, "auto_model": False, "simple_model": None}
    monkeypatch.setattr(admin.userdb, "get_settings", lambda: {**base, **saved})
    monkeypatch.setattr(admin.userdb, "save_settings", lambda values, by: saved.update(values))
    out = admin.save_settings({"autoModel": True, "simpleModel": "claude-haiku-4-5"}, {"id": "250016"})
    assert out["autoModel"] is True and out["simpleModel"] == "claude-haiku-4-5"
    with pytest.raises(HTTPException):
        admin.save_settings({"simpleModel": "gpt-4"}, {"id": "250016"})
