"""AI 도구 관리: 기본 도구 사용 여부·추가 안내, 관리자 정의 조회 도구(SQL 템플릿) 생성·수정·삭제·실행.

저장소: Oracle T_ERP_WEB_AI_TOOL (db/create_erp_web_ai_tool.sql). 테이블이 없으면 서버 로컬 SQLite 에 저장하고,
테이블이 생기면 1분 안에 자동으로 Oracle 을 쓰며 SQLite 내용을 한 번 옮긴다(Oracle 이 비어 있을 때만).

관리자 정의 도구 안전장치
- SQL 은 SELECT/WITH 한 문장만. 쓰기·DDL·PL/SQL·DBMS_/UTL_ 패키지·비밀번호 복호화(CRYPTO_*) 등은 저장 단계에서 거부
- 값은 모두 바인드 변수로만 전달 (파라미터 정의에 없는 바인드는 거부, 형식 검증 후 바인드)
- 실행은 읽기 전용 트랜잭션(SET TRANSACTION READ ONLY) + 30초 제한 + 최대 행 수 제한
- 메뉴 권한과 연결: 도구마다 메뉴(page)를 지정하고, 그 메뉴 권한이 있는 사용자에게만 제공·실행
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from . import db, logs, store

_log = logs.get("aitool")

ORA_TABLE = "T_ERP_WEB_AI_TOOL"
CALL_TIMEOUT_MS = 30_000
MAX_ROWS_LIMIT = 500
PARAM_TYPES = {
    "string": "문자열",
    "integer": "정수",
    "number": "숫자",
    "date": "날짜(YYYYMMDD)",
    "yyyymm": "년월(YYYYMM)",
    "enum": "선택값",
}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,49}$")
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,28}$")
# 문자열 리터럴('…') 또는 바인드(:name). 리터럴 안의 ':' 는 바인드로 보지 않는다.
_TOKEN = re.compile(r"'(?:[^']|'')*'|:([A-Za-z_][A-Za-z0-9_]*)")
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|RENAME|COMMIT|ROLLBACK|SAVEPOINT|LOCK|"
    r"EXECUTE|EXEC|BEGIN|DECLARE|CALL|PURGE|FLASHBACK|AUDIT|DBMS_\w+|UTL_\w+|CRYPTO_\w+|PWD)\b|"
    r"\bFOR\s+UPDATE\b|\bSYS\s*\.|@",
    re.IGNORECASE,
)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_tools (
    tool_nm     TEXT PRIMARY KEY,
    tool_type   TEXT NOT NULL,          -- B=기본 도구 설정, C=관리자 정의 도구
    label       TEXT,
    description TEXT,
    extra_desc  TEXT,
    page_cd     TEXT,
    sql_text    TEXT,
    params_json TEXT,
    max_rows    INTEGER,
    use_yn      TEXT NOT NULL DEFAULT 'Y',
    ins_day     TEXT,
    ins_userid  TEXT,
    upt_day     TEXT,
    upt_userid  TEXT
);
"""
COLS = ["tool_nm", "tool_type", "label", "description", "extra_desc", "page_cd", "sql_text", "params_json",
        "max_rows", "use_yn", "ins_day", "ins_userid", "upt_day", "upt_userid"]


class ToolDefError(ValueError):
    """도구 정의(관리자 입력) 오류."""


class ToolArgError(ValueError):
    """도구 실행 인자(모델 입력) 오류."""


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


# ----------------------------------------------------------------------------
# 저장소 (Oracle 우선, 없으면 SQLite)
# ----------------------------------------------------------------------------
_backend: tuple[float, bool] | None = None
_backend_lock = threading.Lock()
_cache: tuple[float, list[dict]] | None = None
CACHE_TTL = 30


def _sqlite_init() -> None:
    store.conn().executescript(SQLITE_SCHEMA)


def _lob(v):
    return v.read() if hasattr(v, "read") else v


def _use_oracle() -> bool:
    global _backend
    now = time.time()
    with _backend_lock:
        if _backend and _backend[0] > now:
            return _backend[1]
    try:
        # db.query 를 쓰지 않는다: 테이블이 없는 동안 1분마다 SQL 오류 로그가 쌓이지 않도록 조용히 확인
        with db.get_pool().acquire() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {ORA_TABLE} WHERE 1 = 0")
        ok = True
    except Exception:  # noqa: BLE001 - 테이블 없음/권한 없음 → SQLite
        ok = False
    first = ok and not (_backend and _backend[1])
    with _backend_lock:
        _backend = (now + 60, ok)
    if first:
        _migrate_sqlite_to_oracle()
    return ok


def backend_name() -> str:
    return "oracle" if _use_oracle() else "sqlite"


def _load_all() -> list[dict]:
    global _cache
    now = time.time()
    if _cache and _cache[0] > now:
        return _cache[1]
    if _use_oracle():
        cols, rows = db.query(f"SELECT {', '.join(c.upper() for c in COLS)} FROM {ORA_TABLE}")
        out = [{k: _lob(v) for k, v in zip(COLS, r)} for r in rows]
    else:
        _sqlite_init()
        out = store.rows(f"SELECT {', '.join(COLS)} FROM ai_tools")
    _cache = (now + CACHE_TTL, out)
    return out


def invalidate() -> None:
    global _cache
    _cache = None


def _upsert(row: dict) -> None:
    if _use_oracle():
        binds = {f"v_{c}": row.get(c) for c in COLS}
        sets = ", ".join(f"T.{c.upper()} = :v_{c}" for c in COLS if c not in ("tool_nm", "ins_day", "ins_userid"))
        db.execute(
            f"""MERGE INTO {ORA_TABLE} T USING (SELECT :v_tool_nm AS TOOL_NM FROM DUAL) S ON (T.TOOL_NM = S.TOOL_NM)
                WHEN MATCHED THEN UPDATE SET {sets}
                WHEN NOT MATCHED THEN INSERT ({', '.join(c.upper() for c in COLS)})
                                      VALUES ({', '.join(':v_' + c for c in COLS)})""",
            binds,
        )
    else:
        _sqlite_init()
        store.execute(
            f"INSERT INTO ai_tools({', '.join(COLS)}) VALUES({', '.join('?' for _ in COLS)}) "
            f"ON CONFLICT(tool_nm) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in COLS if c not in ('tool_nm', 'ins_day', 'ins_userid'))}",
            tuple(row.get(c) for c in COLS),
        )
    invalidate()


def _delete(name: str) -> None:
    if _use_oracle():
        db.execute(f"DELETE FROM {ORA_TABLE} WHERE TOOL_NM = :n", {"n": name})
    else:
        _sqlite_init()
        store.execute("DELETE FROM ai_tools WHERE tool_nm = ?", (name,))
    invalidate()


def _migrate_sqlite_to_oracle() -> None:
    try:
        _sqlite_init()
        rows = store.rows(f"SELECT {', '.join(COLS)} FROM ai_tools")
        if not rows or db.query(f"SELECT COUNT(*) FROM {ORA_TABLE}")[1][0][0] > 0:
            return
        for r in rows:
            db.execute(f"INSERT INTO {ORA_TABLE} ({', '.join(c.upper() for c in COLS)}) VALUES ({', '.join(':v_' + c for c in COLS)})",
                       {f"v_{c}": r.get(c) for c in COLS})
        _log.info("AI 도구 설정 %d건을 Oracle 로 옮겼습니다.", len(rows))
        invalidate()
    except Exception:  # noqa: BLE001
        _log.exception("AI 도구 설정 Oracle 이전 실패 (SQLite 내용은 그대로 유지)")


# ----------------------------------------------------------------------------
# 설정 조회 (채팅에서 사용)
# ----------------------------------------------------------------------------
def _spec(r: dict) -> dict:
    return {
        "name": r["tool_nm"], "type": r["tool_type"], "label": r.get("label"), "description": r.get("description") or "",
        "extraDesc": r.get("extra_desc") or "", "page": r.get("page_cd"), "sql": r.get("sql_text") or "",
        "params": json.loads(r.get("params_json") or "[]"), "maxRows": int(r.get("max_rows") or 100),
        "enabled": (r.get("use_yn") or "Y") == "Y", "updatedAt": r.get("upt_day") or r.get("ins_day"),
        "updatedBy": r.get("upt_userid") or r.get("ins_userid"),
    }


def snapshot() -> dict:
    """{'builtin': {이름: {enabled, extraDesc}}, 'custom': [spec, ...]} — 오류 시 기본값(모두 사용, 사용자 정의 없음)."""
    try:
        rows = [_spec(r) for r in _load_all()]
    except Exception:  # noqa: BLE001 - 설정 저장소 문제로 AI 전체가 멈추지 않게
        _log.exception("AI 도구 설정 조회 실패 - 기본 설정으로 동작")
        rows = []
    return {"builtin": {r["name"]: r for r in rows if r["type"] == "B"},
            "custom": sorted((r for r in rows if r["type"] == "C"), key=lambda r: r["name"])}


def tool_schema(spec: dict) -> dict:
    props: dict[str, Any] = {}
    for p in spec["params"]:
        typ = p["type"]
        prop: dict[str, Any] = {"type": "integer" if typ == "integer" else "number" if typ == "number" else "string"}
        desc = p.get("description") or ""
        if typ == "date":
            desc = f"{desc} (YYYYMMDD)".strip()
        elif typ == "yyyymm":
            desc = f"{desc} (YYYYMM)".strip()
        if typ == "enum":
            prop["enum"] = p.get("enum") or []
        if desc:
            prop["description"] = desc
        props[p["name"]] = prop
    desc = spec["description"]
    return {
        "name": spec["name"],
        "description": f"{desc}\n(관리자 정의 조회 도구 · 최대 {spec['maxRows']}행)",
        "input_schema": {"type": "object", "properties": props,
                         "required": [p["name"] for p in spec["params"] if p.get("required")],
                         "additionalProperties": False},
        "eager_input_streaming": True,
    }


# ----------------------------------------------------------------------------
# 정의 검증
# ----------------------------------------------------------------------------
def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def binds_in(sql: str) -> list[str]:
    return list(dict.fromkeys(m.group(1).lower() for m in _TOKEN.finditer(sql) if m.group(1)))


def validate_sql(sql: str, param_names: list[str]) -> str:
    s = (sql or "").strip()
    while s.endswith(";"):
        s = s[:-1].rstrip()
    if not s:
        raise ToolDefError("SQL 을 입력하세요.")
    if len(s) > 20000:
        raise ToolDefError("SQL 이 너무 깁니다 (20,000자 이내).")
    body = _strip_literals(s)
    if ";" in body:
        raise ToolDefError("SQL 은 한 문장만 입력하세요 (세미콜론으로 여러 문장을 이을 수 없습니다).")
    if "--" in body or re.search(r"/\*(?!\+)", body):
        raise ToolDefError("SQL 안에 주석은 쓸 수 없습니다 (힌트 /*+ ... */ 는 가능).")
    if not re.match(r"^\s*(SELECT|WITH)\b", body, re.IGNORECASE):
        raise ToolDefError("조회(SELECT 또는 WITH ... SELECT) 문만 등록할 수 있습니다.")
    m = _FORBIDDEN.search(body)
    if m:
        raise ToolDefError(f"사용할 수 없는 구문이 있습니다: {m.group(0).strip()} (조회 전용 도구에는 쓰기·관리·패키지 호출·비밀번호 관련 구문을 쓸 수 없습니다)")
    used = binds_in(s)
    missing = [b for b in used if b not in param_names]
    unused = [p for p in param_names if p not in used]
    if missing:
        raise ToolDefError(f"SQL 의 바인드 변수 {', '.join(':' + b for b in missing)} 가 파라미터에 정의되어 있지 않습니다.")
    if unused:
        raise ToolDefError(f"파라미터 {', '.join(unused)} 가 SQL 에서 쓰이지 않습니다 (:{unused[0]} 형태로 사용).")
    return s


def validate_def(body: dict, builtin_names: set[str], pages: list[str], existing: str | None = None) -> dict:
    name = str(body.get("name") or "").strip().lower()
    if not NAME_RE.match(name):
        raise ToolDefError("도구 이름은 영문 소문자로 시작하는 3~50자 (영문 소문자·숫자·_) 입니다. 예: shop_stock_status")
    if name in builtin_names:
        raise ToolDefError("기본 도구와 같은 이름은 쓸 수 없습니다.")
    if existing is None and any(r["tool_nm"] == name for r in _load_all()):
        raise ToolDefError("같은 이름의 도구가 이미 있습니다.")
    label = str(body.get("label") or "").strip()
    if not 1 <= len(label) <= 50:
        raise ToolDefError("표시 이름을 1~50자로 입력하세요.")
    desc = str(body.get("description") or "").strip()
    if len(desc) < 10:
        raise ToolDefError("AI 가 언제 이 도구를 쓸지 알 수 있게 설명을 10자 이상 입력하세요.")
    if len(desc) > 2000:
        raise ToolDefError("설명은 2,000자 이내로 입력하세요.")
    page = body.get("page")
    if page not in pages:
        raise ToolDefError("연결할 메뉴(권한)를 선택하세요.")
    params = body.get("params") or []
    if not isinstance(params, list) or len(params) > 20:
        raise ToolDefError("파라미터는 20개까지 정의할 수 있습니다.")
    clean_params, seen = [], set()
    for p in params:
        pn = str(p.get("name") or "").strip().lower()
        if not PARAM_RE.match(pn):
            raise ToolDefError(f"파라미터 이름 '{pn}' 이 올바르지 않습니다 (영문 소문자로 시작, 영문 소문자·숫자·_ 최대 29자).")
        if pn in seen:
            raise ToolDefError(f"파라미터 이름 '{pn}' 이 중복됩니다.")
        seen.add(pn)
        typ = p.get("type")
        if typ not in PARAM_TYPES:
            raise ToolDefError(f"파라미터 '{pn}' 의 형식을 선택하세요.")
        enum = [str(x).strip() for x in (p.get("enum") or []) if str(x).strip()]
        if typ == "enum" and not enum:
            raise ToolDefError(f"파라미터 '{pn}' 은 선택값 목록이 필요합니다.")
        default = p.get("default")
        default = None if default in (None, "") else default
        item = {"name": pn, "type": typ, "required": bool(p.get("required")),
                "description": str(p.get("description") or "").strip()[:300]}
        if typ == "enum":
            item["enum"] = enum[:50]
        if default is not None:
            item["default"] = coerce(item, default)  # 기본값도 형식 검사
        clean_params.append(item)
    sql = validate_sql(body.get("sql") or "", [p["name"] for p in clean_params])
    try:
        max_rows = int(body.get("maxRows") or 100)
    except (TypeError, ValueError):
        raise ToolDefError("최대 행 수는 숫자로 입력하세요.")
    if not 1 <= max_rows <= MAX_ROWS_LIMIT:
        raise ToolDefError(f"최대 행 수는 1~{MAX_ROWS_LIMIT} 입니다.")
    return {"name": name, "label": label, "description": desc, "page": page, "sql": sql, "params": clean_params,
            "maxRows": max_rows, "enabled": bool(body.get("enabled", True))}


# ----------------------------------------------------------------------------
# 실행
# ----------------------------------------------------------------------------
def coerce(p: dict, v: Any) -> Any:
    typ, name = p["type"], p["name"]
    try:
        if typ == "integer":
            if isinstance(v, bool):
                raise ValueError
            f = float(v)
            if not f.is_integer():
                raise ValueError
            return int(f)
        if typ == "number":
            if isinstance(v, bool):
                raise ValueError
            return float(v)
        s = str(v).strip()
        if typ == "date":
            s = s.replace("-", "")
            datetime.strptime(s, "%Y%m%d")
            return s
        if typ == "yyyymm":
            s = s.replace("-", "")
            if not re.match(r"^\d{4}(0[1-9]|1[0-2])$", s):
                raise ValueError
            return s
        if typ == "enum":
            if s not in (p.get("enum") or []):
                raise ToolArgError(f"{name} 는 {p.get('enum')} 중 하나입니다.")
            return s
        if len(s) > 200:
            raise ToolArgError(f"{name} 는 200자 이내입니다.")
        return s
    except ToolArgError:
        raise
    except (TypeError, ValueError):
        raise ToolArgError(f"{name} 값 '{v}' 이(가) {PARAM_TYPES[typ]} 형식이 아닙니다.")


def _json_value(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 6)
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, bytes):
        return None
    return _lob(v)


def run_custom(spec: dict, inp: dict, max_rows: int | None = None) -> dict:
    if not isinstance(inp, dict):
        raise ToolArgError("입력은 JSON 객체여야 합니다.")
    known = {p["name"] for p in spec["params"]}
    extra = [k for k in inp if k not in known]
    if extra:
        raise ToolArgError(f"정의되지 않은 입력: {', '.join(extra)}")
    binds: dict[str, Any] = {}
    for p in spec["params"]:
        v = inp.get(p["name"])
        if v is None or v == "":
            v = p.get("default")
        if v is None:
            if p.get("required"):
                raise ToolArgError(f"{p['name']} 는 필수입니다.")
            binds[f"p_{p['name']}"] = None
        else:
            binds[f"p_{p['name']}"] = coerce(p, v)
    # 바인드 이름을 p_ 접두어로 바꿔 Oracle 예약어(:date, :by 등) 충돌을 피한다. 문자열 리터럴은 그대로.
    sql = _TOKEN.sub(lambda m: f":p_{m.group(1).lower()}" if m.group(1) else m.group(0), spec["sql"])
    limit = max(1, min(int(max_rows or spec["maxRows"]), MAX_ROWS_LIMIT))
    wrapped = f"SELECT * FROM (\n{sql}\n) WHERE ROWNUM <= {limit + 1}"
    start = time.perf_counter()
    with db.timed(wrapped, binds, f"AI도구 {spec['name']}"), db.get_pool().acquire() as conn:
        conn.call_timeout = CALL_TIMEOUT_MS
        try:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(wrapped, binds)
            cols = [d[0] for d in cur.description]
            raw = cur.fetchmany(limit + 1)
        finally:
            try:
                conn.rollback()  # 읽기 전용 트랜잭션 종료
            finally:
                conn.call_timeout = 0
    truncated = len(raw) > limit
    rows = [{c: _json_value(v) for c, v in zip(cols, r)} for r in raw[:limit]]
    return {
        "result": {"returned": len(rows), "truncated": truncated, "rows": rows},
        "table": {"columns": [{"key": c, "label": c} for c in cols], "rows": rows},
        "elapsedMs": int((time.perf_counter() - start) * 1000),
    }


# ----------------------------------------------------------------------------
# 관리자 CRUD
# ----------------------------------------------------------------------------
def save_custom(spec: dict, by: str, is_new: bool) -> None:
    now = _now14()
    old = next((r for r in _load_all() if r["tool_nm"] == spec["name"]), None)
    if is_new and old:
        raise ToolDefError("같은 이름의 도구가 이미 있습니다.")
    if not is_new and (not old or old["tool_type"] != "C"):
        raise ToolDefError("수정할 도구를 찾을 수 없습니다.")
    _upsert({
        "tool_nm": spec["name"], "tool_type": "C", "label": spec["label"], "description": spec["description"],
        "extra_desc": None, "page_cd": spec["page"], "sql_text": spec["sql"],
        "params_json": json.dumps(spec["params"], ensure_ascii=False), "max_rows": spec["maxRows"],
        "use_yn": "Y" if spec["enabled"] else "N",
        "ins_day": old["ins_day"] if old else now, "ins_userid": old["ins_userid"] if old else by,
        "upt_day": now if old else None, "upt_userid": by if old else None,
    })
    _log.info("AI 도구 %s: %s (by %s)", "수정" if old else "추가", spec["name"], by)


def delete_custom(name: str, by: str) -> None:
    old = next((r for r in _load_all() if r["tool_nm"] == name), None)
    if not old or old["tool_type"] != "C":
        raise ToolDefError("삭제할 도구를 찾을 수 없습니다 (기본 도구는 삭제할 수 없고 사용 중지만 가능합니다).")
    _delete(name)
    _log.info("AI 도구 삭제: %s (by %s)", name, by)


def save_builtin(name: str, enabled: bool, extra_desc: str, by: str, description: str | None = None) -> None:
    """기본 도구 설정. description 을 주면 AI 에게 주는 설명 자체를 바꾸고, 빈 값/None 이면 프로그램 기본 설명을 쓴다."""
    extra_desc = (extra_desc or "").strip()
    if len(extra_desc) > 1000:
        raise ToolDefError("추가 안내는 1,000자 이내로 입력하세요.")
    description = (description or "").strip() or None
    if description is not None and not 10 <= len(description) <= 4000:
        raise ToolDefError("설명은 10~4,000자로 입력하세요. (비우면 기본 설명)")
    now = _now14()
    old = next((r for r in _load_all() if r["tool_nm"] == name), None)
    _upsert({
        "tool_nm": name, "tool_type": "B", "label": None, "description": description, "extra_desc": extra_desc or None,
        "page_cd": None, "sql_text": None, "params_json": None, "max_rows": None, "use_yn": "Y" if enabled else "N",
        "ins_day": old["ins_day"] if old else now, "ins_userid": old["ins_userid"] if old else by,
        "upt_day": now, "upt_userid": by,
    })
    _log.info("기본 AI 도구 설정: %s 사용=%s 설명변경=%s 추가안내=%d자 (by %s)", name, enabled, description is not None,
              len(extra_desc), by)
