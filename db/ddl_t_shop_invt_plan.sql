/* ============================================================================
   매장 재고 실사계획 (메뉴: 데이터 관리 > 매장 재고 실사계획)
   - 1행 = 매장 1곳의 실사 계획 1건 (같은 매장도 연2회 등 여러 건 등록 가능)
   - 자동 조회 값(브랜드·유통·매장명·매출·최종실사일·재고·관리등급·매장번호·매니저)은
     등록 시점의 "스냅샷"으로 저장한다. 조회가 안 된 값은 사용자가 수기로 입력하므로
     원본 테이블 조인 대신 이 테이블에 값을 보관해야 한다.
   - 경과일, 증감율은 저장하지 않고 조회 시 계산한다 (날짜가 지나도 항상 정확).
   - Oracle 11g: IDENTITY 미지원 → 시퀀스 사용
   ============================================================================ */

-- ---------------------------------------------------------------------------
-- 0) 생성 전 확인 쿼리 (결과를 보고 길이/스키마를 조정하세요)
-- ---------------------------------------------------------------------------
-- 원본 컬럼 길이 (SHOP_ID, 매장명, 전화번호, 매니저명 길이를 맞추기 위함)
-- SELECT table_name, column_name, data_type, data_length, data_precision
--   FROM all_tab_columns
--  WHERE (table_name, column_name) IN (
--          ('T_SHOP','SHOP_ID'), ('T_SHOP','SHOP_NM'), ('T_SHOP','MO_BRD_CD'),
--          ('T_SHOP','SHOP_FORM'), ('T_SHOP','SHOP_RANK_CLSBY'),
--          ('T_SHOP','SHOP_TEL_NO1'), ('T_SHOP','SHOP_TEL_NO2'), ('T_SHOP','SHOP_TEL_NO3'),
--          ('T_SHOP_SMAS','SMASR_NM'), ('T_SHOP_SMAS','HP_NO1'),
--          ('T_SHOP_STOCK','STOCK_QTY'), ('T_CLOSE_SALE_BASE','REAL_SALE_AMT'))
--  ORDER BY 1, 2;
--
-- 원본 테이블 소유 스키마 (T_SHOP 이 SS10 소유라면 이 테이블도 같은 스키마에 만들고 ss10dev 에 권한 부여)
-- SELECT owner, object_name, object_type FROM all_objects WHERE object_name IN ('T_SHOP', 'T_USR');
--
-- DB 문자셋 (비고 200바이트 제한 계산용: KO16MSWIN949 = 한글 2바이트, AL32UTF8 = 한글 3바이트)
-- SELECT value FROM nls_database_parameters WHERE parameter = 'NLS_CHARACTERSET';
--
-- 이름 중복 확인
-- SELECT owner, object_name FROM all_objects WHERE object_name IN ('T_SHOP_INVT_PLAN', 'SQ_SHOP_INVT_PLAN');


-- ---------------------------------------------------------------------------
-- 1) 시퀀스
-- ---------------------------------------------------------------------------
CREATE SEQUENCE SQ_SHOP_INVT_PLAN
    START WITH 1
    INCREMENT BY 1
    NOCACHE
    NOCYCLE;


-- ---------------------------------------------------------------------------
-- 2) 테이블
-- ---------------------------------------------------------------------------
CREATE TABLE T_SHOP_INVT_PLAN (
    PLAN_ID             NUMBER(12)          NOT NULL,   -- 계획 ID (SQ_SHOP_INVT_PLAN)

    -- 매장 기본 (T_SHOP 스냅샷)
    SHOP_ID             VARCHAR2(20)        NOT NULL,   -- 매장코드
    MO_BRD_CD           VARCHAR2(10),                   -- 브랜드코드 (S/T/A)
    BRD_NM              VARCHAR2(50),                   -- 브랜드명 (쉬즈미스/리스트/시스티나, 수기 가능)
    SHOP_FORM_NM        VARCHAR2(100),                  -- 유통
    SHOP_NM             VARCHAR2(200),                  -- 매장명

    -- 평균매출 (T_CLOSE_SALE_BASE 스냅샷, 단위: 원 / 화면은 백만원, 증감율은 조회 시 계산)
    PREV_SALE_AMT       NUMBER(15),                     -- 전년 매출 (전년 1월~전년 동월-1)
    CURR_SALE_AMT       NUMBER(15),                     -- 당년 매출 (당년 1월~전월)

    -- 위치 (수기)
    ADDR                VARCHAR2(300),                  -- 주소
    AREA_NM             VARCHAR2(30),                   -- 지역 (시·도 택1)
    REGION_NM           VARCHAR2(20),                   -- 권역 (수도권/영남권/호남권/충청권/기타)

    -- 직전 실사
    LAST_INVT_DT        VARCHAR2(8),                    -- 최종실사일 YYYYMMDD (자동, 수기 가능) → 경과일 계산 기준
    PREV_INVT_TYPE      VARCHAR2(10),                   -- 전실사유형 (교체/정기/오픈)
    PREV_INVT_RESULT    NUMBER(15,2),                   -- 전실사결과 (수기 숫자)

    -- 재고
    STOCK_QTY           NUMBER(12),                     -- 재고 수량 (당일 기준)
    STOCK_BASE_DT       VARCHAR2(8),                    -- 재고 수량 기준일 YYYYMMDD

    -- 실사 계획 / 업체 예상 비용
    INVT_PLAN_NOTE      VARCHAR2(1000),                 -- 실사예정 (자유 작성)
    BASE_FEE            NUMBER(12),                     -- 기본료
    EXPECT_AMT          NUMBER(12),                     -- 실사예상액
    INVT_PLAN_DT        VARCHAR2(8),                    -- 실사예정일 YYYYMMDD (NULL = 미정)
    RMK                 VARCHAR2(200 BYTE),             -- 비고 (200바이트 제한)
    TWICE_YEAR_YN       CHAR(1)             DEFAULT 'N' NOT NULL,  -- 연2회 실사 매장 여부
    SHOP_RANK_NM        VARCHAR2(100),                  -- 관리등급 (자동)
    STLM_TEAM           VARCHAR2(10),                   -- 정산 팀구분 (NULL/1팀/2팀)

    -- 매니저 (T_SHOP_SMAS 팝업, 수기 가능) / 매장번호 (T_SHOP)
    SMASR_NM            VARCHAR2(100),                  -- 매니저 성함
    SMASR_HP            VARCHAR2(30),                   -- 매니저 전화번호
    SHOP_TEL            VARCHAR2(30),                   -- 매장번호

    -- 감사 컬럼 (T_USR 등 기존 테이블 관례)
    INS_DAY             VARCHAR2(14)        NOT NULL,   -- 등록일시 YYYYMMDDHH24MISS
    INS_USERID          VARCHAR2(20)        NOT NULL,   -- 등록자
    UPT_DAY             VARCHAR2(14),                   -- 수정일시
    UPT_USERID          VARCHAR2(20),                   -- 수정자
    DEL_DAY             VARCHAR2(14),                   -- 삭제일시 (소프트 삭제, NULL = 사용 중)
    DEL_USERID          VARCHAR2(20),                   -- 삭제자

    CONSTRAINT PK_SHOP_INVT_PLAN PRIMARY KEY (PLAN_ID),
    CONSTRAINT CK_SHOP_INVT_PLAN_01 CHECK (TWICE_YEAR_YN IN ('Y', 'N')),
    CONSTRAINT CK_SHOP_INVT_PLAN_02 CHECK (PREV_INVT_TYPE IS NULL OR PREV_INVT_TYPE IN ('교체', '정기', '오픈')),
    CONSTRAINT CK_SHOP_INVT_PLAN_03 CHECK (REGION_NM IS NULL OR REGION_NM IN ('수도권', '영남권', '호남권', '충청권', '기타')),
    CONSTRAINT CK_SHOP_INVT_PLAN_04 CHECK (STLM_TEAM IS NULL OR STLM_TEAM IN ('1팀', '2팀'))
);

-- 조회용 인덱스: 매장별 이력, 실사예정일 순 목록
CREATE INDEX IX_SHOP_INVT_PLAN_01 ON T_SHOP_INVT_PLAN (SHOP_ID, DEL_DAY);
CREATE INDEX IX_SHOP_INVT_PLAN_02 ON T_SHOP_INVT_PLAN (INVT_PLAN_DT);


-- ---------------------------------------------------------------------------
-- 3) 코멘트 (describe/AI 도구가 한글 설명을 읽을 수 있도록)
-- ---------------------------------------------------------------------------
COMMENT ON TABLE  T_SHOP_INVT_PLAN                   IS '매장 재고 실사계획';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.PLAN_ID           IS '계획ID(SQ_SHOP_INVT_PLAN)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SHOP_ID           IS '매장코드';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.MO_BRD_CD         IS '브랜드코드';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.BRD_NM            IS '브랜드';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SHOP_FORM_NM      IS '유통';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SHOP_NM           IS '매장명';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.PREV_SALE_AMT     IS '평균매출-전년(원)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.CURR_SALE_AMT     IS '평균매출-당년(원)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.ADDR              IS '주소';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.AREA_NM           IS '지역(시도)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.REGION_NM         IS '권역';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.LAST_INVT_DT      IS '최종실사일(YYYYMMDD)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.PREV_INVT_TYPE    IS '전실사유형(교체/정기/오픈)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.PREV_INVT_RESULT  IS '전실사결과';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.STOCK_QTY         IS '재고수량(당일기준)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.STOCK_BASE_DT     IS '재고수량 기준일(YYYYMMDD)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.INVT_PLAN_NOTE    IS '실사예정(자유작성)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.BASE_FEE          IS '업체예상비용-기본료';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.EXPECT_AMT        IS '업체예상비용-실사예상액';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.INVT_PLAN_DT      IS '실사예정일(YYYYMMDD, NULL=미정)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.RMK               IS '비고(200바이트)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.TWICE_YEAR_YN     IS '연2회 실사 매장 여부(Y/N)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SHOP_RANK_NM      IS '관리등급';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.STLM_TEAM         IS '정산 팀구분(1팀/2팀)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SMASR_NM          IS '매니저 성함';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SMASR_HP          IS '매니저 전화번호';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.SHOP_TEL          IS '매장번호';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.INS_DAY           IS '등록일시';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.INS_USERID        IS '등록자ID';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.UPT_DAY           IS '수정일시';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.UPT_USERID        IS '수정자ID';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.DEL_DAY           IS '삭제일시(소프트삭제)';
COMMENT ON COLUMN T_SHOP_INVT_PLAN.DEL_USERID        IS '삭제자ID';


-- ---------------------------------------------------------------------------
-- 4) (소유 스키마가 ss10dev 가 아닐 때만) 앱 계정 권한 / 시노님
-- ---------------------------------------------------------------------------
-- GRANT SELECT, INSERT, UPDATE ON T_SHOP_INVT_PLAN TO SS10DEV;
-- GRANT SELECT ON SQ_SHOP_INVT_PLAN TO SS10DEV;
-- CREATE SYNONYM SS10DEV.T_SHOP_INVT_PLAN FOR <소유스키마>.T_SHOP_INVT_PLAN;
-- CREATE SYNONYM SS10DEV.SQ_SHOP_INVT_PLAN FOR <소유스키마>.SQ_SHOP_INVT_PLAN;


-- ---------------------------------------------------------------------------
-- 5) 화면 조회 예시 (경과일·증감율은 계산)
-- ---------------------------------------------------------------------------
-- SELECT P.*,
--        TRUNC(SYSDATE) - TO_DATE(P.LAST_INVT_DT, 'YYYYMMDD')                  AS ELAPSED_DAYS,
--        ROUND(P.PREV_SALE_AMT / 1000000)                                     AS PREV_SALE_MIL,
--        ROUND(P.CURR_SALE_AMT / 1000000)                                     AS CURR_SALE_MIL,
--        ROUND((P.CURR_SALE_AMT / NULLIF(P.PREV_SALE_AMT, 0) - 1) * 100, 1)   AS SALE_RATE
--   FROM T_SHOP_INVT_PLAN P
--  WHERE P.DEL_DAY IS NULL
--  ORDER BY P.INVT_PLAN_DT NULLS LAST, P.SHOP_ID;
