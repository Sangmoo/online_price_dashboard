-- ============================================================================
-- ERP 영업 관리 웹 서비스: 메뉴별 이용 기록 (SS10 스키마에서 실행)
--
-- 사용자가 메뉴를 열 때마다 일자 · 사용자 · 메뉴별 횟수를 더한다 (관리자 > 메뉴 이용 통계).
-- 테이블이 없으면 서버 로컬(SQLite)에 기록하고, 테이블을 만들면 1분 안에 Oracle 을 쓰며 그동안의 기록을 한 번 옮긴다.
-- ============================================================================

CREATE TABLE T_ERP_WEB_MENU_USAGE (
    USE_YMD     VARCHAR2(8)   NOT NULL,
    USR_ID      VARCHAR2(20)  NOT NULL,
    PAGE_CD     VARCHAR2(30)  NOT NULL,
    OPEN_CNT    NUMBER(10)    DEFAULT 0 NOT NULL,
    LAST_DAY    VARCHAR2(14)  NOT NULL,
    CONSTRAINT PK_ERP_WEB_MENU_USAGE PRIMARY KEY (USE_YMD, USR_ID, PAGE_CD)
);

CREATE INDEX IX_ERP_WEB_MENU_USAGE_01 ON T_ERP_WEB_MENU_USAGE (USR_ID, PAGE_CD);

COMMENT ON TABLE  T_ERP_WEB_MENU_USAGE          IS 'ERP 영업 관리 웹 - 메뉴별 이용 기록 (일자·사용자·메뉴별 열람 횟수)';
COMMENT ON COLUMN T_ERP_WEB_MENU_USAGE.USE_YMD  IS '이용일자(YYYYMMDD)';
COMMENT ON COLUMN T_ERP_WEB_MENU_USAGE.USR_ID   IS '사용자ID';
COMMENT ON COLUMN T_ERP_WEB_MENU_USAGE.PAGE_CD  IS '메뉴코드(dashboard/detail/sale_dashboard/sale_monthly/invt_plan/admin/ai)';
COMMENT ON COLUMN T_ERP_WEB_MENU_USAGE.OPEN_CNT IS '그날 메뉴를 연 횟수';
COMMENT ON COLUMN T_ERP_WEB_MENU_USAGE.LAST_DAY IS '그날 마지막 이용 일시';

GRANT SELECT, INSERT, UPDATE, DELETE ON T_ERP_WEB_MENU_USAGE TO SS10DEV;
CREATE SYNONYM SS10DEV.T_ERP_WEB_MENU_USAGE FOR SS10.T_ERP_WEB_MENU_USAGE;
