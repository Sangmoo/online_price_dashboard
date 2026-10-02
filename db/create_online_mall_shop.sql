-- ============================================================================
-- 온라인 가격 > 판매처 매장 연결: 사이트(MALL_NM) · 판매자번호(NAVER_PAY_SELL_NO) · 브랜드별 매장코드(SHOP_ID) 매핑
-- (SS10 스키마에서 실행)
--
-- 사용자가 화면(온라인 가격 > 판매처 매장 연결)에서 매장코드를 정해 두면, 가격 수집 프로그램이 수집할 때
-- 이 표를 보고 T_SELECT_ONLINE_MNG_R.SHOP_ID 를 채운다.
--
-- 브랜드(BRD_CD)를 키에 넣은 이유: 롯데온·SSG.COM·하프클럽 같은 온라인몰은 한 사이트·판매자번호에 쉬즈미스·리스트·시스티나 상품이
-- 함께 있고(최근 31일 수집 행의 97%), 매장코드는 브랜드마다 따로다 (예: 하프클럽 S51005 / T51005 / A51005).
--   BRD_CD = 품번 첫 글자 (S 쉬즈미스, T 리스트, A 시스티나). '*' = 모든 브랜드 공통 (브랜드별 행이 없을 때 쓴다).
-- 판매자번호가 없는 사이트(최근 31일 255개 조합 중 50개)는 기본키에 NULL 을 쓸 수 없어 '-' 로 저장한다.
--
-- 수집 프로그램 조회 (브랜드 행 우선, 없으면 '*'):
--   SELECT SHOP_ID FROM (
--       SELECT SHOP_ID FROM T_SELECT_ONLINE_MALL_SHOP
--        WHERE MALL_NM = :mall_nm AND NAVER_PAY_SELL_NO = NVL(:naver_pay_sell_no, '-')
--          AND BRD_CD IN (SUBSTR(:prdt_cd, 1, 1), '*') AND USE_YN = 'Y'
--        ORDER BY DECODE(BRD_CD, '*', 2, 1))
--    WHERE ROWNUM = 1
-- ============================================================================

-- 1) 수집 테이블에 매장코드 열 추가
--    ※ 2026-10-03 확인 결과 SS10.T_SELECT_ONLINE_MNG_R 에 SHOP_ID VARCHAR2(6) 열이 이미 있습니다. 이미 있으면 건너뛰세요 (ORA-01430).
ALTER TABLE T_SELECT_ONLINE_MNG_R ADD (SHOP_ID VARCHAR2(6));
COMMENT ON COLUMN T_SELECT_ONLINE_MNG_R.SHOP_ID IS '매장코드 (T_SELECT_ONLINE_MALL_SHOP 매핑으로 수집 시 입력)';

-- 2) 사이트 · 판매자번호 · 브랜드 → 매장코드 매핑
CREATE TABLE T_SELECT_ONLINE_MALL_SHOP (
    MALL_NM            VARCHAR2(300)   NOT NULL,
    NAVER_PAY_SELL_NO  VARCHAR2(50)    DEFAULT '-' NOT NULL,
    BRD_CD             VARCHAR2(1)     DEFAULT '*' NOT NULL,
    SHOP_ID            VARCHAR2(6)     NOT NULL,
    USE_YN             CHAR(1)         DEFAULT 'Y' NOT NULL,
    RMK                VARCHAR2(500),
    INS_USERID         VARCHAR2(20)    NOT NULL,
    INS_DAY            VARCHAR2(14)    NOT NULL,
    UPT_USERID         VARCHAR2(20)    NOT NULL,
    UPT_DAY            VARCHAR2(14)    NOT NULL,
    CONSTRAINT PK_SELECT_ONLINE_MALL_SHOP PRIMARY KEY (MALL_NM, NAVER_PAY_SELL_NO, BRD_CD),
    CONSTRAINT CK_SELECT_ONLINE_MALL_SHOP_01 CHECK (USE_YN IN ('Y', 'N'))
);

CREATE INDEX IX_SELECT_ONLINE_MALL_SHOP_01 ON T_SELECT_ONLINE_MALL_SHOP (SHOP_ID);

COMMENT ON TABLE  T_SELECT_ONLINE_MALL_SHOP                   IS '온라인 가격 수집 - 사이트·판매자번호·브랜드별 매장코드 매핑';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.MALL_NM           IS '사이트명 (T_SELECT_ONLINE_MNG_R.MALL_NM 과 같은 값)';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.NAVER_PAY_SELL_NO IS '판매자번호 (T_SELECT_ONLINE_MNG_R.NAVER_PAY_SELL_NO, 없으면 ''-'')';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.BRD_CD            IS '브랜드 (품번 첫 글자 S/T/A, ''*'' = 모든 브랜드 공통)';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.SHOP_ID           IS '매장코드 (T_SHOP.SHOP_ID)';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.USE_YN            IS '사용 여부 (N 이면 수집 시 매장코드를 넣지 않음)';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.RMK               IS '비고';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.INS_USERID        IS '등록자 사번';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.INS_DAY           IS '등록 일시(YYYYMMDDHH24MISS)';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.UPT_USERID        IS '수정자 사번';
COMMENT ON COLUMN T_SELECT_ONLINE_MALL_SHOP.UPT_DAY           IS '수정 일시(YYYYMMDDHH24MISS)';

-- 앱 계정 권한 (화면에서 매핑 등록·수정·삭제)
GRANT SELECT, INSERT, UPDATE, DELETE ON T_SELECT_ONLINE_MALL_SHOP TO SS10DEV;
CREATE SYNONYM SS10DEV.T_SELECT_ONLINE_MALL_SHOP FOR SS10.T_SELECT_ONLINE_MALL_SHOP;

-- ----------------------------------------------------------------------------
-- (선택) 이미 수집된 행에 매장코드 채우기 — 매핑을 등록한 뒤 필요한 기간만, 업무 시간 외에 실행
--   기간 조건(DT)으로 인덱스 범위를 찾는다. 하루 약 4만 행. 브랜드 행이 있으면 브랜드 행, 없으면 '*' 행.
-- ----------------------------------------------------------------------------
-- MERGE INTO T_SELECT_ONLINE_MNG_R R
-- USING (
--     SELECT R2.ROWID AS RID,
--            NVL(MAX(CASE WHEN M.BRD_CD <> '*' THEN M.SHOP_ID END), MAX(CASE WHEN M.BRD_CD = '*' THEN M.SHOP_ID END)) AS SHOP_ID
--       FROM T_SELECT_ONLINE_MNG_R R2
--       JOIN T_SELECT_ONLINE_MALL_SHOP M
--         ON M.MALL_NM = R2.MALL_NM AND M.NAVER_PAY_SELL_NO = NVL(R2.NAVER_PAY_SELL_NO, '-')
--        AND M.BRD_CD IN (SUBSTR(R2.PRDT_CD, 1, 1), '*') AND M.USE_YN = 'Y'
--      WHERE R2.DT BETWEEN '20260901' AND '20261003'
--      GROUP BY R2.ROWID
-- ) S
--    ON (R.ROWID = S.RID)
--  WHEN MATCHED THEN UPDATE SET R.SHOP_ID = S.SHOP_ID WHERE R.SHOP_ID IS NULL OR R.SHOP_ID <> S.SHOP_ID;
-- COMMIT;
