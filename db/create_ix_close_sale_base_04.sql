-- ============================================================================
-- T_CLOSE_SALE_BASE 집계용 인덱스 (월별 매장별 판매 집계 화면 · 요약 · AI 집계 속도 개선)
-- SS10 스키마에서 실행. 테이블 약 3GB / 1,619만 행 (2026-09 기준)
--
-- 배경: 기존 IX_T_CLOSE_SALE_BASE_03 (MAKE_YYMM, SHOP_ID, REAL_SALE_AMT, QTY) 에는
--       할인금액·기획년도·시즌·품군이 없어, 이 값이 필요한 합계는 테이블 전체를 읽는다.
--       (36개월 할인금액 합계 약 14~40초, 시즌/품군별 요약도 같은 수준)
--
-- 주의: SESS_NM, PRDT_GRP_NM 은 VARCHAR2(4000) 으로 선언돼 있어 컬럼 그대로 넣으면
--       ORA-01450 (키의 최대 길이 6398 초과) 이 난다. 실제 값은 최대 12/19 바이트이므로
--       앞 100바이트만 인덱스에 넣는다(함수 기반 인덱스). 테이블 정의는 바꾸지 않는다.
--       앱은 조건·그룹핑에 이 식과 똑같은 SUBSTRB(..., 1, 100) 을 사용한다 (backend/app/sale_monthly.py 의 SESS_EXPR, PRDT_GRP_EXPR).
--       식을 바꾸면 인덱스를 쓰지 못하므로 두 곳을 함께 바꿔야 한다.
--
-- 영향: 인덱스 용량 약 0.8~1.0GB 예상. 월 마감 데이터 적재(INSERT/DELETE) 시 인덱스 갱신 비용이 조금 늘어난다.
--       생성 중에는 테이블 DML 이 막히므로(ONLINE 옵션은 Enterprise Edition 에서만) 적재가 없는 시간에 실행.
-- ============================================================================

CREATE INDEX IX_T_CLOSE_SALE_BASE_04
    ON T_CLOSE_SALE_BASE (
        MAKE_YYMM, SHOP_ID, PLAN_YY,
        SUBSTRB(SESS_NM, 1, 100),
        SUBSTRB(PRDT_GRP_NM, 1, 100),
        QTY, REAL_SALE_AMT, DSCT_AMT
    )
    PARALLEL 4 NOLOGGING;

-- 생성 후 병렬도/로깅을 원래대로 (쿼리마다 병렬로 돌지 않도록)
ALTER INDEX IX_T_CLOSE_SALE_BASE_04 NOPARALLEL;
ALTER INDEX IX_T_CLOSE_SALE_BASE_04 LOGGING;

-- 함수 기반 인덱스는 숨은 컬럼 통계가 있어야 옵티마이저가 제대로 고른다 (테이블 크기에 따라 수 분)
BEGIN
    DBMS_STATS.GATHER_TABLE_STATS(
        OWNNAME    => 'SS10',
        TABNAME    => 'T_CLOSE_SALE_BASE',
        METHOD_OPT => 'FOR ALL HIDDEN COLUMNS SIZE 1',
        CASCADE    => TRUE,
        DEGREE     => 4
    );
END;
/

-- 확인: 시즌 식 컬럼이 인덱스에 들어갔는지
-- SELECT COLUMN_POSITION, COLUMN_EXPRESSION FROM ALL_IND_EXPRESSIONS
--  WHERE INDEX_OWNER = 'SS10' AND INDEX_NAME = 'IX_T_CLOSE_SALE_BASE_04';

-- (선택) IX_T_CLOSE_SALE_BASE_03 은 04 와 앞 두 컬럼이 같아 역할이 겹친다.
--        04 생성 후 화면/AI 속도를 확인하고, 다른 프로그램이 03 을 쓰지 않는다면 삭제해 용량(576MB)과 적재 비용을 줄일 수 있다.
-- DROP INDEX IX_T_CLOSE_SALE_BASE_03;


-- ----------------------------------------------------------------------------
-- [최소안] 할인금액 합계만 빠르게 하려면 (위 권장안 대신 실행, 4000바이트 컬럼이 없어 오류 없음)
-- ----------------------------------------------------------------------------
-- CREATE INDEX IX_T_CLOSE_SALE_BASE_04
--     ON T_CLOSE_SALE_BASE (MAKE_YYMM, SHOP_ID, REAL_SALE_AMT, QTY, DSCT_AMT)
--     PARALLEL 4 NOLOGGING;
-- ALTER INDEX IX_T_CLOSE_SALE_BASE_04 NOPARALLEL;
-- ALTER INDEX IX_T_CLOSE_SALE_BASE_04 LOGGING;
