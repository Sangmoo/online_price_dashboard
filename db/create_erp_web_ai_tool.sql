-- ============================================================================
-- ERP 영업 관리 웹 서비스: AI 도구 관리 (관리자 › AI 도구) (SS10 스키마에서 실행)
-- 테이블이 없으면 앱은 서버 로컬(SQLite)에 저장하고, 이 테이블을 만들면 1분 안에 자동으로 옮겨 쓴다(재시작 불필요).
-- ============================================================================

CREATE TABLE T_ERP_WEB_AI_TOOL (
    TOOL_NM      VARCHAR2(50)    NOT NULL,
    TOOL_TYPE    CHAR(1)         NOT NULL,
    LABEL        VARCHAR2(200),
    DESCRIPTION  VARCHAR2(4000),
    EXTRA_DESC   VARCHAR2(4000),
    PAGE_CD      VARCHAR2(30),
    SQL_TEXT     CLOB,
    PARAMS_JSON  CLOB,
    MAX_ROWS     NUMBER(5),
    USE_YN       CHAR(1)         DEFAULT 'Y' NOT NULL,
    INS_DAY      VARCHAR2(14),
    INS_USERID   VARCHAR2(20),
    UPT_DAY      VARCHAR2(14),
    UPT_USERID   VARCHAR2(20),
    CONSTRAINT PK_ERP_WEB_AI_TOOL PRIMARY KEY (TOOL_NM),
    CONSTRAINT CK_ERP_WEB_AI_TOOL_01 CHECK (TOOL_TYPE IN ('B', 'C')),
    CONSTRAINT CK_ERP_WEB_AI_TOOL_02 CHECK (USE_YN IN ('Y', 'N'))
);

COMMENT ON TABLE  T_ERP_WEB_AI_TOOL             IS 'ERP 영업 관리 웹 - AI 도구 설정(기본 도구 사용여부/추가안내, 관리자 정의 조회 도구)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.TOOL_NM     IS '도구 이름(AI 가 호출하는 이름, 영문 소문자·숫자·_)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.TOOL_TYPE   IS 'B=기본 도구 설정, C=관리자 정의 도구';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.LABEL       IS '화면 표시 이름(C)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.DESCRIPTION IS 'AI 에게 주는 도구 설명(C)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.EXTRA_DESC  IS '기본 도구에 덧붙이는 관리자 안내(B)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.PAGE_CD     IS '연결 메뉴(이 메뉴 권한이 있는 사용자에게만 제공, C)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.SQL_TEXT    IS '조회 SQL(SELECT/WITH 한 문장, :파라미터 바인드, C)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.PARAMS_JSON IS '파라미터 정의 JSON(이름/형식/필수/설명/선택값/기본값, C)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.MAX_ROWS    IS '최대 반환 행 수(C)';
COMMENT ON COLUMN T_ERP_WEB_AI_TOOL.USE_YN      IS '사용 여부';

GRANT SELECT, INSERT, UPDATE, DELETE ON T_ERP_WEB_AI_TOOL TO SS10DEV;
CREATE SYNONYM SS10DEV.T_ERP_WEB_AI_TOOL FOR SS10.T_ERP_WEB_AI_TOOL;
