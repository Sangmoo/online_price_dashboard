"""관리자 › AI 사용 현황 › 도구별 사용: 서버 로그(app.log, 'erp.ai')에서 AI 도구 호출·실패·응답 시간과 모델 선택을 집계한다.

로그 줄 (chat_service):
- '도구 {이름} user={사번} {초}s 입력=…'          → 성공
- '도구 입력 오류 {이름} user={사번}: {메시지}'      → 입력 오류 (AI 가 고쳐 다시 부르는 경우가 많음)
- '도구 실패 {이름} user={사번} 입력=…' (ERROR)    → 조회 실패 (DB 오류 등)
- '질문 user=… model={모델} … route={simple|base|off}' → 질문 수·모델 선택
- '모델 전환 …'                                     → 단순 조회 모델 → 기본 모델 전환
로그 보관 기간(관리자 설정, 기본 7일)보다 긴 기간은 볼 수 없다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

from . import logs
from .server_status import _LINE

_OK = re.compile(r"^도구 (\S+) user=(\S+) ([\d.]+)s 입력=")
_INPUT_ERR = re.compile(r"^도구 입력 오류 (\S+) user=(\S+): (.*)$")
_FAIL = re.compile(r"^도구 실패 (\S+) user=(\S+) ")
_Q = re.compile(r"^질문 user=(\S+) conv=\S+ model=(\S+) effort=\S+(?: route=(\S+))?")
_SWITCH = re.compile(r"^모델 전환 ")


def report(days: int = 7) -> dict:
    from . import chat_tools as ct

    days = max(1, min(int(days), 90))
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    tools: dict[str, dict] = defaultdict(lambda: {"ok": 0, "inputErrors": 0, "failures": 0, "secs": [], "users": set(),
                                                 "errors": defaultdict(int), "last": None})
    questions, models, routes, switches = 0, defaultdict(int), defaultdict(int), 0
    for path in logs.app_log_files(days + 1):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LINE.match(line.rstrip("\n"))
                if not m or m[1] < since or m[3].removeprefix("erp.") != "ai":
                    continue
                ts, msg = m[1], m[4]
                if (r := _OK.match(msg)):
                    t = tools[r[1]]
                    t["ok"] += 1
                    t["secs"].append(float(r[3]))
                elif (r := _INPUT_ERR.match(msg)):
                    t = tools[r[1]]
                    t["inputErrors"] += 1
                    t["errors"][re.sub(r"\d+", "N", r[3])[:120]] += 1   # 숫자만 다른 같은 오류는 하나로
                elif (r := _FAIL.match(msg)):
                    t = tools[r[1]]
                    t["failures"] += 1
                    t["errors"]["조회 실패 (서버 로그 참고)"] += 1
                elif (r := _Q.match(msg)):
                    questions += 1
                    models[r[2]] += 1
                    routes[r[3] or "off"] += 1
                    continue
                elif _SWITCH.match(msg):
                    switches += 1
                    continue
                else:
                    continue
                t["users"].add(r[2])
                t["last"] = max(t["last"] or "", ts)
    rows = []
    for name, t in tools.items():
        secs = sorted(t["secs"])
        calls = t["ok"] + t["inputErrors"] + t["failures"]
        rows.append({
            "name": name, "label": ct.tool_label(name), "calls": calls, "ok": t["ok"], "inputErrors": t["inputErrors"],
            "failures": t["failures"], "errorRate": round((t["inputErrors"] + t["failures"]) * 100 / calls, 1) if calls else None,
            "avgSec": round(sum(secs) / len(secs), 1) if secs else None,
            "p95Sec": secs[min(len(secs) - 1, int(len(secs) * 0.95))] if secs else None, "maxSec": secs[-1] if secs else None,
            "users": len(t["users"]), "last": t["last"],
            "topErrors": [{"message": k, "count": v} for k, v in sorted(t["errors"].items(), key=lambda x: -x[1])[:3]],
        })
    rows.sort(key=lambda x: -x["calls"])
    unused = sorted(n for n in ct.BUILTIN_NAMES if n not in tools)
    return {"days": days, "since": since[:10], "questions": questions, "models": dict(models), "routes": dict(routes),
            "modelSwitches": switches, "tools": rows, "unusedTools": [{"name": n, "label": ct.tool_label(n)} for n in unused]}
