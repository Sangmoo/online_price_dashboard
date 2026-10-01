-- ============================================================================
-- ERP 영업 관리 웹 서비스: 사용자별 브랜드 데이터 권한 (SS10 스키마에서 실행)
--
-- 판매 현황 · 월별 매장별 판매 집계 · AI 판매 답변에서 사용자가 볼 수 있는 브랜드.
-- 사용자에게 행이 하나도 없으면 "모든 브랜드" (기존 사용자는 그대로 전체 권한).
-- 브랜드명은 판매 현황에 보이는 이름 (쉬즈미스 / 리스트 / 시스티나 = 팀명 쉬즈N팀 / 리스트N팀 / 시스티나N팀).
-- 테이블을 만들기 전에는 브랜드 제한 없이 모두 전체 브랜드로 동작한다 (재시작 불필요, 1분 내 인식).
-- ============================================================================

CREATE TABLE T_ERP_WEB_USER_BRAND (
    USR_ID      VARCHAR2(20)  NOT NULL,
    BRAND_NM    VARCHAR2(50)  NOT NULL,
    INS_DAY     VARCHAR2(14)  NOT NULL,
    INS_USERID  VARCHAR2(20)  NOT NULL,
    CONSTRAINT PK_ERP_WEB_USER_BRAND PRIMARY KEY (USR_ID, BRAND_NM),
    CONSTRAINT FK_ERP_WEB_USER_BRAND_01 FOREIGN KEY (USR_ID) REFERENCES T_ERP_WEB_USER (USR_ID) ON DELETE CASCADE
);

COMMENT ON TABLE  T_ERP_WEB_USER_BRAND            IS 'ERP 영업 관리 웹 - 사용자별 브랜드 데이터 권한 (행 없음 = 모든 브랜드)';
COMMENT ON COLUMN T_ERP_WEB_USER_BRAND.USR_ID     IS '사용자ID';
COMMENT ON COLUMN T_ERP_WEB_USER_BRAND.BRAND_NM   IS '브랜드명 (쉬즈미스/리스트/시스티나)';
COMMENT ON COLUMN T_ERP_WEB_USER_BRAND.INS_DAY    IS '부여일시';
COMMENT ON COLUMN T_ERP_WEB_USER_BRAND.INS_USERID IS '부여자ID';

-- 앱 계정(SS10DEV)에서 쓰는 경우 (다른 T_ERP_WEB_* 테이블과 같은 방식)
GRANT SELECT, INSERT, UPDATE, DELETE ON T_ERP_WEB_USER_BRAND TO SS10DEV;
CREATE OR REPLACE SYNONYM SS10DEV.T_ERP_WEB_USER_BRAND FOR SS10.T_ERP_WEB_USER_BRAND;
