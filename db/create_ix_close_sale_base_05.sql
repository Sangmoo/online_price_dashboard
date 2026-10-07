-- ============================================================================
-- T_CLOSE_SALE_BASE 인덱스 추가 제안 (월별 매장별 판매 집계 · 요약 속도) — 2026-10-07 분석
-- SS10 스키마에서 실행. 테이블 약 3.0GB / 1,619만 행, 기존 인덱스 01~04 합계 약 2.5GB
--
-- [분석 요약] 서버 로그(최근 30일)와 실행 계획(관리자 > 쿼리 성능 · 실행 계획)으로 확인
--  - 최대 124초 · 94초 · 75초 같은 큰 값은 2026-10-06 18:09~18:12 에 몰려 있고, 같은 시각 ALL_MVIEWS 조회(94초) ·
--    설정 1행 조회(124초)도 느렸다 → DB 전체 부하(다른 시스템 배치)로 판단. 인덱스와 무관.
--  - 부하와 관계없이 매번 느린 것: 요약을 '기획년도 · 시즌 · 품군' 기준으로 볼 때 (최대 22초, 기획년도 조건 매장별 7초)
--      SELECT PLAN_YY, COUNT(DISTINCT SHOP_ID), SUM(QTY), SUM(REAL_SALE_AMT), SUM(DSCT_AMT), SUM(PRODUCT_COST2 * QTY)
--        FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM BETWEEN :ym_from AND :ym_to GROUP BY PLAN_YY
--    → 실행 계획: TABLE ACCESS FULL (3GB 전체 읽기). 원가(PRODUCT_COST2) 하나가 IX_04 에 없어서 인덱스만으로 못 끝낸다.
--    (월 · 매장 기준 요약은 사전 집계 뷰 MV_CLOSE_SALE_SHOP_YM 로 자동 재작성되어 이미 빠름)
--
-- [권장] IX_05 = IX_04 + PRODUCT_COST2. 앱 코드는 바꾸지 않는다 (같은 식 SUBSTRB(..., 1, 100) 사용 중).
--  - 효과: 기획년도 · 시즌 · 품군 요약, 기획년도/시즌 조건이 있는 요약 · 할인 합계가 인덱스만 읽음
--          (9개월 조회 기준 테이블 3GB → 인덱스 약 0.25GB 범위만 읽음, 대략 1/10)
--  - 용량: 약 1.2GB (IX_04 1.09GB + 원가 컬럼). 확인 후 IX_04 를 지우면 순증가 약 0.1GB
--  - 영향: 생성 중 테이블 DML 이 막힌다 (ONLINE 은 Enterprise Edition 에서만) → 월 마감 적재
--          (JOB_LOAD_CLOSE_SALE_BASE) · 판매 화면 사용이 적은 시간에 실행. 생성 시간은 수 분 예상.
-- ============================================================================

CREATE INDEX IX_T_CLOSE_SALE_BASE_05
    ON T_CLOSE_SALE_BASE (
        MAKE_YYMM, SHOP_ID, PLAN_YY,
        SUBSTRB(SESS_NM, 1, 100),
        SUBSTRB(PRDT_GRP_NM, 1, 100),
        QTY, REAL_SALE_AMT, DSCT_AMT, PRODUCT_COST2
    )
    TABLESPACE JPRD
    PARALLEL 4 NOLOGGING;

-- 생성 후 병렬도 · 로깅을 원래대로 (쿼리마다 병렬로 돌지 않도록)
ALTER INDEX IX_T_CLOSE_SALE_BASE_05 NOPARALLEL;
ALTER INDEX IX_T_CLOSE_SALE_BASE_05 LOGGING;

-- 함수 기반 인덱스 숨은 컬럼 통계 (IX_04 때와 같음, 수 분)
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

-- ----------------------------------------------------------------------------
-- 확인: 아래 계획에 TABLE ACCESS FULL 대신 IX_T_CLOSE_SALE_BASE_05 가 나오면 성공
--       (웹 관리자 > 쿼리 성능 > 느린 쿼리 순위 [실행 계획] 으로도 확인 가능)
-- ----------------------------------------------------------------------------
-- EXPLAIN PLAN FOR
-- SELECT PLAN_YY AS K, COUNT(DISTINCT SHOP_ID), NVL(SUM(QTY), 0), NVL(SUM(REAL_SALE_AMT), 0), NVL(SUM(DSCT_AMT), 0),
--        NVL(SUM(PRODUCT_COST2 * QTY), 0)
--   FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM BETWEEN '202601' AND '202609' GROUP BY PLAN_YY;
-- SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);

-- 확인되면 IX_04 삭제 (IX_05 가 IX_04 의 모든 컬럼을 같은 순서로 포함 · 앱 코드는 인덱스 이름을 쓰지 않음)
-- DROP INDEX IX_T_CLOSE_SALE_BASE_04;


-- ============================================================================
-- (선택) 아래는 인덱스만으로는 효과가 없고 앱 코드도 함께 바꿔야 하는 항목. 필요하면 요청하세요.
-- ============================================================================
-- [B] 목록 페이지 정렬 (월별 매장별 판매 집계 목록, 평소 p95 약 3초)
--     지금: 한 달 전체(약 30만 행)를 읽어 정렬한 뒤 100행을 자른다 (SORT ORDER BY STOPKEY).
--     정렬 끝에 ROWID 가 있어(같은 매장 · 품번 · 컬러 · 사이즈가 한 달에 15만 행이라 페이지 순서 고정용)
--     인덱스가 있어도 Oracle 이 정렬을 생략하지 않는다 → 정렬 기준을 바꾸는 코드 수정이 함께 필요.
-- CREATE INDEX IX_T_CLOSE_SALE_BASE_06
--     ON T_CLOSE_SALE_BASE (MAKE_YYMM, SHOP_ID, PRDT_CD, COLOR_CD, SIZE_CD) TABLESPACE JPRD PARALLEL 4 NOLOGGING;
-- ALTER INDEX IX_T_CLOSE_SALE_BASE_06 NOPARALLEL;
-- ALTER INDEX IX_T_CLOSE_SALE_BASE_06 LOGGING;

-- [C] 판매 현황 '세일 비중 높은 매장' (평균 5.8초, 14회): TEAM_CD · DSCT_CLSBY_NM 이 VARCHAR2(4000) 이라
--     둘 다 그대로 넣으면 ORA-01450(키 길이 초과) → SUBSTRB 식 인덱스 + 쿼리도 같은 식으로 바꿔야 함.
-- CREATE INDEX IX_T_CLOSE_SALE_BASE_07
--     ON T_CLOSE_SALE_BASE (MAKE_YYMM, SHOP_ID, SUBSTRB(TEAM_CD, 1, 30), SUBSTRB(DSCT_CLSBY_NM, 1, 100), REAL_SALE_AMT)
--     TABLESPACE JPRD PARALLEL 4 NOLOGGING;

-- [참고] IX_01 (MAKE_YYMM, 338MB) · IX_02 (MAKE_YYMM, SHOP_ID, 464MB) 는 IX_03/IX_05 의 앞부분과 같아 역할이 겹친다.
--        다른 프로그램(ERP 화면 · 배치)이 이 인덱스를 힌트로 쓰지 않는지 확인되면 지워서 적재 비용 · 용량을 줄일 수 있다.
