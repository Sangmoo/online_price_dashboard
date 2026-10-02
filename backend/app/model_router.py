"""AI 모델 자동 선택: 질문을 단순 조회 / 분석으로 나눠, 단순 조회는 저렴한 모델(기본 Haiku 4.5, effort low)로 답한다.

- 관리자 > AI 사용 설정의 '질문에 따라 모델 자동 선택'(기본 꺼짐)이 켜져 있을 때만 동작한다.
- 판단이 애매하면 분석(설정한 기본 모델)으로 본다 — 품질 우선.
- 저렴한 모델로 답하다 도구 입력 오류가 2번 나면 그 질문의 남은 과정은 기본 모델로 넘긴다(chat_service).
"""
from __future__ import annotations

import re

DEFAULT_SIMPLE_MODEL = "claude-haiku-4-5"
SIMPLE_EFFORT = "low"
ESCALATE_AFTER_TOOL_ERRORS = 2
SIMPLE_MAX_LEN = 60

# 분석·판단·글쓰기를 요구하는 표현 → 기본 모델
_COMPLEX = re.compile(
    r"분석|원인|이유|왜|비교해|비교 분석|전략|대응|개선|추천|제안|예측|전망|시사점|인사이트|정리해|요약해|보고서|보고용|"
    r"어떻게 해야|해석|평가해|진단|방안|검토|설명해|차이(가|를|는)?\s*(뭐|무엇|왜)")
# 값·목록을 바로 묻는 표현 → 단순 조회 후보
_SIMPLE = re.compile(r"얼마|몇\s*(개|명|곳|건|%|퍼센트)?|누구|어디|언제|목록|리스트|보여\s*줘|알려\s*줘|조회|찾아\s*줘|있어\?|맞아\?|순위|top|TOP|상위|하위")


def classify(text: str) -> str:
    """'simple' 또는 'complex'"""
    t = (text or "").strip()
    if not t or _COMPLEX.search(t):
        return "complex"
    if len(t) <= SIMPLE_MAX_LEN and _SIMPLE.search(t):
        return "simple"
    return "complex"


def choose(text: str, settings: dict, default_model: str, default_effort: str) -> tuple[str, str, str]:
    """(모델, effort, 구분) — 구분: 'simple' | 'complex' | 'off'"""
    if not settings.get("auto_model"):
        return default_model, default_effort, "off"
    kind = classify(text)
    if kind == "simple":
        return settings.get("simple_model") or DEFAULT_SIMPLE_MODEL, SIMPLE_EFFORT, kind
    return default_model, default_effort, kind
