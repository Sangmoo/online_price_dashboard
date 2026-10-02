-- ============================================================================
-- 마감 매출 기초 데이터(T_CLOSE_SALE_BASE) 월 적재 스케줄
-- SS10 스키마에서 실행. 매월 1일 13:00(한국 시간)에 전월 1일 ~ 말일 판매분을 적재한다.
--   예) 2026-11-01 13:00 실행 → MAKE_DT '20261001' ~ '20261031' → MAKE_YYMM '202610'
--
-- - 같은 월을 다시 돌려도 중복되지 않도록 해당 월을 지우고 다시 넣는다 (한 트랜잭션, 실패 시 롤백).
-- - 수동 재적재: EXEC P_LOAD_CLOSE_SALE_BASE('202610');
-- - 사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM)는 자동 갱신하지 않는다. 적재 확인 후 관리자 화면 [지금 갱신] 으로 반영.
--
-- 사전 권한 (DBA 가 실행, 프로시저 안에서 쓰므로 롤이 아닌 직접 권한이어야 한다)
--   GRANT CREATE JOB TO SS10;
--   GRANT EXECUTE ON SS10DEV.FN_GET_START_PRICE TO SS10;
-- ============================================================================

CREATE OR REPLACE PROCEDURE P_LOAD_CLOSE_SALE_BASE (
    p_yymm IN VARCHAR2 DEFAULT NULL   -- 적재할 판매년월 YYYYMM, 생략하면 전월
) AS
    v_yymm VARCHAR2(6);
    v_from VARCHAR2(8);
    v_to   VARCHAR2(8);
BEGIN
    v_yymm := NVL(p_yymm, TO_CHAR(ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -1), 'YYYYMM'));
    v_from := v_yymm || '01';
    v_to   := TO_CHAR(LAST_DAY(TO_DATE(v_yymm, 'YYYYMM')), 'YYYYMMDD');

    DELETE FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM = v_yymm;

    INSERT INTO T_CLOSE_SALE_BASE (
           MAKE_YYMM, TEAM_CD, SHOP_ID, SHOP_NM, PLAN_YY, SESS_NM, PRDT_GRP_NM, ITEM_NM, CHARGE_CLSBY_NM, DSCT_CLSBY_NM,
           PRDT_CD, COLOR_CD, SIZE_CD, QTY, FIRST_PRICE, REAL_SALE_PRICE, REAL_SALE_AMT_PRICE, REAL_SALE_AMT, DSCT_AMT,
           PRDT_CLSBY_NM, ACC_YN, ONLINE_SALE, GOODS_CLSBY_NM, PRODUCT_COST2)
    SELECT SUBSTR(B.MAKE_DT, 1, 6) AS MAKE_YYMM -- 판매년월
            , F_GET_NM_CLSBY(S.TEAM_CD, 'ko') AS TEAM_CD -- 팀
            , B.SHOP_ID AS SHOP_ID -- 매장코드
            , S.SHOP_NM AS SHOP_NM -- 매장명
            , P.PLAN_YY AS PLAN_YY -- 기획년도
            , F_GET_NM_CLSBY(P.SESN_CD, 'ko') AS SESS_NM -- 시즌
            , F_GET_NM_CLSBY(P.PRDT_GRP_CD, 'ko') AS PRDT_GRP_NM -- 품군
            , (SELECT T.CD_NM AS ITEM_NM
                     FROM T_PRDT_KIND T
                    WHERE 1 = 1
                      AND T.PARENT_PRDT_KIND_CD = 'IND'
                      AND T.PRDT_KIND_CD = P.ITEM_CD) AS ITEM_NM -- 아이템
            , F_GET_NM_CLSBY(P.CHARGE_CLSBY, 'ko') AS CHARGE_CLSBY_NM -- 수수료구분
            , F_GET_NM_CLSBY(SL.DSCT_CLSBY, 'ko') AS DSCT_CLSBY_NM -- 판매형태
            , B.PRDT_CD -- 상품
            , B.COLOR_CD -- 색상
            , B.SIZE_CD -- 사이즈
            , SUM(DECODE(B.RET_YN, 'N', B.QTY, 'Y' , B.QTY * -1)) AS QTY -- 수량
            , SS10DEV.FN_GET_START_PRICE(B.PRDT_CD) AS FIRST_PRICE -- 최초가
            , B.REAL_SALE_PRICE -- 판매단가
            , DECODE(B.QTY, 0, 0, ABS(ROUND(B.REAL_SALE_AMT/B.QTY))) AS  REAL_SALE_AMT_PRICE -- 실판단가
            , SUM(DECODE(B.RET_YN, 'Y', -1 * B.REAL_SALE_AMT, B.REAL_SALE_AMT)) AS REAL_SALE_AMT -- 실판금액
            , SUM(DECODE(B.RET_YN,'Y', -1 * SL.DSCT_AMT, SL.DSCT_AMT)) AS DSCT_AMT -- 할인금액
            , F_GET_NM_CLSBY(P.PRDT_CLSBY, 'ko') AS PRDT_CLSBY_NM -- 생산형태
            , DECODE(P.PRDT_GRP_CD, 'C673A', 'Y', 'N') AS ACC_YN -- 악세사리 구분
            , NVL(B.ONLINE_SALE, 'N') AS ONLINE_SALE -- 온라인 판매 구분
            , F_GET_NM_CLSBY(P.GOODS_CLSBY, 'ko') AS GOODS_CLSBY_NM -- 상품구분
            , NVL(P.AFTER_TOTAL_COST, P.PRE_TOTAL_COST) AS PRODUCT_COST2 -- 제조원가(V+)
    FROM    T_SHOP_RNDS_BASE B
            , T_SHOP S
            , T_SALE SL
            , T_STYLE_PLAN P
    WHERE   1 = 1
    AND     B.SHOP_RNDS_ID = SL.SHOP_RNDS_ID
    AND     B.MAKE_DT BETWEEN v_from AND v_to -- 해당 월 1일 ~ 말일
    AND     B.SHOP_ID = S.SHOP_ID
    AND     B.PRDT_CD = P.PRDT_CD
    AND     B.DEL_DAY IS NULL
    GROUP BY B.MAKE_DT, B.SHOP_ID, S.SHOP_NM, P.CHARGE_CLSBY, SL.DSCT_CLSBY, P.PRDT_CLSBY, P.PRDT_GRP_CD
           , B.ONLINE_SALE, P.GOODS_CLSBY
           , S.TEAM_CD, S.SHOP_NM, P.PLAN_YY, P.SESN_CD, P.ITEM_CD, P.AFTER_TOTAL_COST, P.PRE_TOTAL_COST
           , B.COLOR_CD, B.SIZE_CD, B.PRDT_CD, B.REAL_SALE_PRICE, B.REAL_SALE_AMT, B.QTY;

    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;   -- 스케줄러 실행 이력(USER_SCHEDULER_JOB_RUN_DETAILS)에 실패로 남긴다
END P_LOAD_CLOSE_SALE_BASE;
/

-- 다시 만들 때만: EXEC DBMS_SCHEDULER.DROP_JOB('JOB_LOAD_CLOSE_SALE_BASE');
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'JOB_LOAD_CLOSE_SALE_BASE',
        job_type        => 'STORED_PROCEDURE',
        job_action      => 'P_LOAD_CLOSE_SALE_BASE',
        -- 202609 는 이미 적재되어 있으므로 첫 실행은 2026-11-01 (202610 적재)
        start_date      => TO_TIMESTAMP_TZ('2026-11-01 13:00:00 Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS TZR'),
        repeat_interval => 'FREQ=MONTHLY; BYMONTHDAY=1; BYHOUR=13; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => '매월 1일 13:00 전월 마감 매출 기초 데이터(T_CLOSE_SALE_BASE) 적재');
END;
/

-- 확인
-- SELECT JOB_NAME, ENABLED, STATE, NEXT_RUN_DATE FROM USER_SCHEDULER_JOBS WHERE JOB_NAME = 'JOB_LOAD_CLOSE_SALE_BASE';
-- SELECT LOG_DATE, STATUS, RUN_DURATION, ADDITIONAL_INFO FROM USER_SCHEDULER_JOB_RUN_DETAILS
--  WHERE JOB_NAME = 'JOB_LOAD_CLOSE_SALE_BASE' ORDER BY LOG_DATE DESC;
-- 즉시 한 번 실행(테스트): EXEC DBMS_SCHEDULER.RUN_JOB('JOB_LOAD_CLOSE_SALE_BASE', use_current_session => TRUE);
