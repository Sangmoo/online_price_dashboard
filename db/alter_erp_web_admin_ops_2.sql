-- ============================================================================
-- ERP 영업 관리 웹 서비스: 관리자 운영 기능 2차 (SS10 스키마에서 실행, create_erp_web_admin_ops.sql 다음)
--
-- 1) T_ERP_WEB_NOTICE 컬럼 추가 : 공지 대상(TARGET_JSON) · 상단 고정(PIN_YN) · 필독(MUST_ACK_YN)
-- 2) T_ERP_WEB_NOTICE_READ      : 공지 읽음 · 필독 확인 기록 (사용자별 1행)
-- 3) T_ERP_WEB_ROLE             : 권한 묶음(역할 템플릿) — 메뉴 · 브랜드 · AI 설정 묶음
--    T_ERP_WEB_ROLE_USER        : 사용자에게 적용한 권한 묶음 (묶음을 고칠 때 적용 사용자에게 다시 반영)
--
-- 실행 전에는: 공지는 '전체 대상 · 고정/필독 없음 · 읽음 기록 없음' 으로 그대로 동작하고, 관리자 화면에 이 파일 실행 안내가 나온다.
--             권한 묶음 탭은 실행 안내만 보여준다. 실행 후 1분 안에 화면에 반영된다.
-- 점검 예약 · 대량 다운로드 알림 기준은 기존 설정 테이블(T_ERP_WEB_SETTING)을 쓴다 (화면에서 저장 시 자동 추가).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) 공지 대상 · 상단 고정 · 필독
-- ----------------------------------------------------------------------------
ALTER TABLE T_ERP_WEB_NOTICE ADD (
    TARGET_JSON  VARCHAR2(2000),
    PIN_YN       CHAR(1) DEFAULT 'N' NOT NULL,
    MUST_ACK_YN  CHAR(1) DEFAULT 'N' NOT NULL
);

COMMENT ON COLUMN T_ERP_WEB_NOTICE.TARGET_JSON IS '공지 대상 JSON {"type":"all|pages|brands|users","values":[...]} (NULL = 전체)';
COMMENT ON COLUMN T_ERP_WEB_NOTICE.PIN_YN      IS '게시판 상단 고정 여부';
COMMENT ON COLUMN T_ERP_WEB_NOTICE.MUST_ACK_YN IS '필독 여부 ([확인] 을 눌러야 팝업이 더 뜨지 않음)';

-- ----------------------------------------------------------------------------
-- 2) 공지 읽음 · 필독 확인
-- ----------------------------------------------------------------------------
CREATE TABLE T_ERP_WEB_NOTICE_READ (
    NOTICE_ID   VARCHAR2(32)    NOT NULL,
    USR_ID      VARCHAR2(20)    NOT NULL,
    READ_DAY    VARCHAR2(14)    NOT NULL,
    ACK_DAY     VARCHAR2(14),
    CONSTRAINT PK_ERP_WEB_NOTICE_READ PRIMARY KEY (NOTICE_ID, USR_ID)
);

CREATE INDEX IX_ERP_WEB_NOTICE_READ_01 ON T_ERP_WEB_NOTICE_READ (USR_ID);

COMMENT ON TABLE  T_ERP_WEB_NOTICE_READ          IS 'ERP 영업 관리 웹 - 공지 읽음 · 필독 확인 (사용자별 처음 읽은 시각 · 확인 시각)';
COMMENT ON COLUMN T_ERP_WEB_NOTICE_READ.READ_DAY IS '처음 읽은 일시 (팝업이 뜨거나 게시판에서 연 때)';
COMMENT ON COLUMN T_ERP_WEB_NOTICE_READ.ACK_DAY  IS '필독 [확인] 일시';

GRANT SELECT, INSERT, UPDATE, DELETE ON T_ERP_WEB_NOTICE_READ TO SS10DEV;
CREATE SYNONYM SS10DEV.T_ERP_WEB_NOTICE_READ FOR SS10.T_ERP_WEB_NOTICE_READ;

-- ----------------------------------------------------------------------------
-- 3) 권한 묶음 (역할 템플릿)
-- ----------------------------------------------------------------------------
CREATE TABLE T_ERP_WEB_ROLE (
    ROLE_ID     VARCHAR2(32)    NOT NULL,
    ROLE_NM     VARCHAR2(100)   NOT NULL,
    DESCR       VARCHAR2(500),
    CONF_JSON   VARCHAR2(4000)  NOT NULL,
    INS_USERID  VARCHAR2(20),
    INS_DAY     VARCHAR2(14),
    UPT_USERID  VARCHAR2(20),
    UPT_DAY     VARCHAR2(14),
    CONSTRAINT PK_ERP_WEB_ROLE PRIMARY KEY (ROLE_ID),
    CONSTRAINT UK_ERP_WEB_ROLE_01 UNIQUE (ROLE_NM)
);

COMMENT ON TABLE  T_ERP_WEB_ROLE           IS 'ERP 영업 관리 웹 - 권한 묶음 (메뉴 · 브랜드 · AI 설정)';
COMMENT ON COLUMN T_ERP_WEB_ROLE.CONF_JSON IS '설정 JSON {"pages":[...],"brands":[...]|null,"aiEnabled":bool,"dailyQuestions":n|null,"dailyCostUsd":n|null}';

GRANT SELECT, INSERT, UPDATE, DELETE ON T_ERP_WEB_ROLE TO SS10DEV;
CREATE SYNONYM SS10DEV.T_ERP_WEB_ROLE FOR SS10.T_ERP_WEB_ROLE;

CREATE TABLE T_ERP_WEB_ROLE_USER (
    USR_ID      VARCHAR2(20)    NOT NULL,
    ROLE_ID     VARCHAR2(32)    NOT NULL,
    APPLY_DAY   VARCHAR2(14)    NOT NULL,
    APPLY_USERID VARCHAR2(20),
    CONSTRAINT PK_ERP_WEB_ROLE_USER PRIMARY KEY (USR_ID)
);

CREATE INDEX IX_ERP_WEB_ROLE_USER_01 ON T_ERP_WEB_ROLE_USER (ROLE_ID);

COMMENT ON TABLE  T_ERP_WEB_ROLE_USER IS 'ERP 영업 관리 웹 - 사용자에게 마지막으로 적용한 권한 묶음';

GRANT SELECT, INSERT, UPDATE, DELETE ON T_ERP_WEB_ROLE_USER TO SS10DEV;
CREATE SYNONYM SS10DEV.T_ERP_WEB_ROLE_USER FOR SS10.T_ERP_WEB_ROLE_USER;
