-- ============================================================================
-- 수불제어 함수 F_GET_RNDS_CNTR_ID 속도 개선 제안 — 2026-10-07 분석
-- SS10 스키마에서 실행. (함수는 SS10DEV, 테이블은 SS10)
--
-- [분석 요약] 운영 DB 실측
--  - 한 번 호출 약 30ms, 논리 읽기 1,300~2,800 블록 (매장 S11012 / S25606, 쉬즈미스, 품번 SWWSLQ32080).
--    판매분 자동보충(SP_AUTO_DVID)은 스타일 × 후보 매장마다 2번(완불 · 판매), 자동 RT 저장은 요청마다 부르므로
--    후보 매장 3,000곳이면 함수만 약 3분이 걸린다.
--  - 느린 곳은 함수의 첫 번째 쿼리(매장 지정 제어)다.
--      1) T_RNDS_CNTR_SHOP_IX01 (SHOP_ID, CNTR_ID) 로 매장의 제어 행 500~2,100건을 찾은 뒤
--         S.DEL_DAY IS NULL 확인을 위해 테이블을 한 건씩 다시 읽는다.            → 아래 [1]
--      2) 그 매장에 걸린 유효 제어 62~66건의 제품 행을 '제품 지정이 있는지 / 이 품번이 있는지' 세려고
--         PK_T_RNDS_CNTR_PRDT (CNTR_ID, CNTR_SEQ) 로 약 19,500건을 찾고 PRDT_CD · COLOR_CD 를 보려고
--         테이블을 한 건씩 다시 읽는다.                                          → 아래 [2]
--  - 두 번째 쿼리(제품 지정 제어)는 T_RNDS_CNTR_PRDT_IX02 로 이미 빠르다 (비용 7).
--
-- [권장] 인덱스 2개로 테이블 재방문을 없앤다 (인덱스만 읽고 끝남). 함수 · 프로시저 코드는 바꾸지 않는다.
--  - 예상 효과: 호출당 논리 읽기 약 1/3~1/5 (테이블 블록 재방문이 사라짐). 결과는 그대로.
--  - 용량: SHOP 73만 행 · PRDT 121만 행 기준 각각 약 20~40MB.
--  - 영향: 생성 중 두 테이블 DML 이 잠깐 막힌다 (Standard Edition 은 ONLINE 불가) → 수불제어 등록이 적은 시간에.
--          생성 시간은 각각 수십 초 이내 예상.
-- ============================================================================

-- [1] 매장 지정 제어 찾기: SHOP_ID = :매장 AND DEL_DAY IS NULL 을 인덱스만으로
--     (DEL_DAY 가 NULL 이어도 SHOP_ID 가 있어 인덱스에 들어간다)
CREATE INDEX IX_T_RNDS_CNTR_SHOP_03
    ON T_RNDS_CNTR_SHOP (SHOP_ID, DEL_DAY, CNTR_ID)
    NOLOGGING;
ALTER INDEX IX_T_RNDS_CNTR_SHOP_03 LOGGING;

-- [2] 제어별 제품 행 세기 · 품번 · 칼라 비교를 인덱스만으로 (CNTR_ID 로 묶여 있어 한 범위만 읽음)
CREATE INDEX IX_T_RNDS_CNTR_PRDT_03
    ON T_RNDS_CNTR_PRDT (CNTR_ID, PRDT_CD, COLOR_CD)
    NOLOGGING;
ALTER INDEX IX_T_RNDS_CNTR_PRDT_03 LOGGING;

BEGIN
    DBMS_STATS.GATHER_INDEX_STATS('SS10', 'IX_T_RNDS_CNTR_SHOP_03');
    DBMS_STATS.GATHER_INDEX_STATS('SS10', 'IX_T_RNDS_CNTR_PRDT_03');
END;
/

-- ----------------------------------------------------------------------------
-- 확인 (SS10DEV 로 접속, 같은 세션에서 차례로 실행): 호출 전후 '논리 읽기' 차이가 생성 전보다 크게 줄면 성공
--   생성 전 실측: S11012 → 1,316 / S25606 → 2,830
-- ----------------------------------------------------------------------------
-- SELECT S.VALUE FROM V$MYSTAT S, V$STATNAME N WHERE N.STATISTIC# = S.STATISTIC# AND N.NAME = 'session logical reads';
-- SELECT F_GET_RNDS_CNTR_ID(TO_CHAR(SYSDATE, 'YYYYMMDD'), 'A01C01', 'S', 'S25606', 'SWWSLQ32080', 'BK', '13') FROM DUAL;
-- SELECT S.VALUE FROM V$MYSTAT S, V$STATNAME N WHERE N.STATISTIC# = S.STATISTIC# AND N.NAME = 'session logical reads';
--
-- 실행 계획에 T_RNDS_CNTR_SHOP · T_RNDS_CNTR_PRDT 의 'TABLE ACCESS BY INDEX ROWID' 가 없어지고
-- IX_T_RNDS_CNTR_SHOP_03 · IX_T_RNDS_CNTR_PRDT_03 'INDEX RANGE SCAN' 만 보이면 된다.


-- ============================================================================
-- (선택) 더 크게 줄이려면: 함수 첫 번째 쿼리를 '세기(COUNT)' 대신 '있는지(EXISTS)' 로
-- ----------------------------------------------------------------------------
--  지금은 매장에 걸린 제어마다 제품 행 전부(약 19,500건)를 세어서 '제품 지정 없음(0건)' 또는
--  '이 품번 있음(1건 이상)' 을 판단한다. 첫 건에서 멈추는 EXISTS 로 바꾸면 인덱스 [2] 와 함께
--  호출당 수십 블록 수준으로 줄어든다. 결과(돌려주는 CNTR_ID = 두 쿼리 결과 중 MAX)는 같다.
--  ERP 공용 함수라 영향 범위(배분 · 출고 · RT · 판매 등록)가 넓으니, 아래는 검토용으로만 두고
--  개발 DB 에서 기존 함수와 결과를 대조한 뒤 적용한다. 필요하면 대조 스크립트를 요청하세요.
--
--  SELECT MAX(CNTR_ID) INTO R_RNDS_CNTR_ID
--    FROM (
--          -- 매장 지정 제어: 매장이 들어 있고 (제품 지정이 없거나, 이 품번 · 칼라가 지정되어 있음)
--          SELECT A.CNTR_ID
--            FROM T_RNDS_CNTR A
--           WHERE A.COMPY_CD = I_COMPY_CD AND A.PARENT_BRD_CD = I_PARENT_BRD_CD AND A.DEL_DAY IS NULL
--             AND I_RNDS_DT BETWEEN A.APLY_DT AND NVL(A.CANCL_DT, A.END_DT)
--             AND INSTR(DECODE(I_CNTR_CLSBY, ... 기존 첫 번째 DECODE 그대로 ...), 'Y') > 0
--             AND EXISTS (SELECT 1 FROM T_RNDS_CNTR_SHOP S
--                          WHERE S.CNTR_ID = A.CNTR_ID AND S.SHOP_ID = I_SHOP_ID AND S.DEL_DAY IS NULL)
--             AND (NOT EXISTS (SELECT 1 FROM T_RNDS_CNTR_PRDT P WHERE P.CNTR_ID = A.CNTR_ID)
--                  OR EXISTS (SELECT 1 FROM T_RNDS_CNTR_PRDT P
--                              WHERE P.CNTR_ID = A.CNTR_ID AND P.PRDT_CD = I_PRDT_CD
--                                AND DECODE(P.COLOR_CD, '*', I_COLOR_CD, P.COLOR_CD) = I_COLOR_CD))
--          UNION ALL
--          -- 제품 지정 제어: 이 품번 · 칼라가 지정되어 있고 매장 지정이 없음 (기존 두 번째 쿼리와 같음)
--          SELECT A.CNTR_ID
--            FROM T_RNDS_CNTR A, T_RNDS_CNTR_PRDT P
--           WHERE A.COMPY_CD = I_COMPY_CD AND A.PARENT_BRD_CD = I_PARENT_BRD_CD AND A.DEL_DAY IS NULL
--             AND P.CNTR_ID = A.CNTR_ID AND P.DEL_DAY IS NULL AND P.PRDT_CD = I_PRDT_CD
--             AND DECODE(P.COLOR_CD, '*', I_COLOR_CD, P.COLOR_CD) = I_COLOR_CD
--             AND I_RNDS_DT BETWEEN A.APLY_DT AND NVL(A.CANCL_DT, A.END_DT)
--             AND INSTR(DECODE(I_CNTR_CLSBY, ... 기존 두 번째 DECODE 그대로 ...), 'Y') > 0
--             AND NOT EXISTS (SELECT 1 FROM T_RNDS_CNTR_SHOP S WHERE S.CNTR_ID = A.CNTR_ID)
--         );
--  ※ 두 DECODE 는 원본과 다르게 생겼으므로(34 · 36 은 두 번째 쿼리에서 INDC_RT_CNTR_YN, 35 는 없음) 그대로 옮긴다.
