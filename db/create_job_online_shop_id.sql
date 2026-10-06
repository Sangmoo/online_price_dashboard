-- ============================================================================
-- 온라인 가격 수집(T_SELECT_ONLINE_MNG_R) 매장코드(SHOP_ID) 채우기 — 프로시저 + 매일 02:00 스케줄
-- SS10 스키마에서 실행.
--
-- 판매처 매장 연결(T_SELECT_ONLINE_MALL_SHOP: 사이트·판매자번호·브랜드 → 매장코드)로 수집 행의 SHOP_ID 를 채운다.
--   브랜드 행(품번 첫 글자 S/T/A)이 있으면 그 매장코드, 없으면 '*'(모든 브랜드 공통) 행. USE_YN = 'Y' 만.
--   이미 같은 값이면 건드리지 않는다. 매핑이 없거나 지운 조합의 기존 SHOP_ID 는 그대로 둔다.
-- - 스케줄: 매일 02:00(한국 시간) 전일자. 예) 2026-10-08 02:00 실행 → DT '20261007'
-- - 화면: 온라인 가격 > 일자별 상세 [매장코드 채우기] 버튼 → 최근 7일(당일 포함)
-- - 수동: DECLARE n NUMBER; BEGIN P_FILL_ONLINE_SHOP_ID('20261001', '20261007', n); DBMS_OUTPUT.PUT_LINE(n); END;
--
-- 사전 권한 (DBA 가 실행): GRANT CREATE JOB TO SS10;   (이미 있으면 생략 — JOB_LOAD_CLOSE_SALE_BASE 와 같음)
-- ============================================================================

CREATE OR REPLACE PROCEDURE P_FILL_ONLINE_SHOP_ID (
    p_from IN  VARCHAR2 DEFAULT NULL,   -- 시작 수집일 YYYYMMDD, 생략하면 전일
    p_to   IN  VARCHAR2 DEFAULT NULL,   -- 종료 수집일 YYYYMMDD, 생략하면 p_from 과 같은 날
    p_cnt  OUT NUMBER                   -- 바뀐 행 수
) AS
    v_from VARCHAR2(8);
    v_to   VARCHAR2(8);
BEGIN
    v_from := NVL(p_from, TO_CHAR(TRUNC(SYSDATE) - 1, 'YYYYMMDD'));
    v_to   := NVL(p_to, v_from);
    IF TO_DATE(v_to, 'YYYYMMDD') - TO_DATE(v_from, 'YYYYMMDD') NOT BETWEEN 0 AND 30 THEN
        RAISE_APPLICATION_ERROR(-20001, '기간은 시작일부터 31일 이내여야 합니다: ' || v_from || ' ~ ' || v_to);
    END IF;

    MERGE INTO T_SELECT_ONLINE_MNG_R R
    USING (
        SELECT R2.ROWID AS RID,
               NVL(MAX(CASE WHEN M.BRD_CD <> '*' THEN M.SHOP_ID END), MAX(CASE WHEN M.BRD_CD = '*' THEN M.SHOP_ID END)) AS SHOP_ID
          FROM T_SELECT_ONLINE_MNG_R R2
          JOIN T_SELECT_ONLINE_MALL_SHOP M
            ON M.MALL_NM = R2.MALL_NM AND M.NAVER_PAY_SELL_NO = NVL(R2.NAVER_PAY_SELL_NO, '-')
           AND M.BRD_CD IN (SUBSTR(R2.PRDT_CD, 1, 1), '*') AND M.USE_YN = 'Y'
         WHERE R2.DT BETWEEN v_from AND v_to
         GROUP BY R2.ROWID
    ) S
       ON (R.ROWID = S.RID)
     WHEN MATCHED THEN UPDATE SET R.SHOP_ID = S.SHOP_ID WHERE R.SHOP_ID IS NULL OR R.SHOP_ID <> S.SHOP_ID;

    p_cnt := SQL%ROWCOUNT;
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;   -- 스케줄러 실행 이력(USER_SCHEDULER_JOB_RUN_DETAILS)에 실패로 남긴다
END P_FILL_ONLINE_SHOP_ID;
/

-- 앱 계정 권한 (화면 [매장코드 채우기] 버튼). 프로시저 소유자(SS10) 권한으로 실행되므로 수집 테이블 UPDATE 권한은 주지 않는다.
GRANT EXECUTE ON P_FILL_ONLINE_SHOP_ID TO SS10DEV;
CREATE SYNONYM SS10DEV.P_FILL_ONLINE_SHOP_ID FOR SS10.P_FILL_ONLINE_SHOP_ID;

-- 다시 만들 때만: EXEC DBMS_SCHEDULER.DROP_JOB('JOB_FILL_ONLINE_SHOP_ID');
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'JOB_FILL_ONLINE_SHOP_ID',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'DECLARE n NUMBER; BEGIN P_FILL_ONLINE_SHOP_ID(NULL, NULL, n); END;',   -- 전일자
        start_date      => TO_TIMESTAMP_TZ('2026-10-08 02:00:00 Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS TZR'),
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => '매일 02:00 전일자 온라인 가격 수집(T_SELECT_ONLINE_MNG_R) 매장코드(SHOP_ID) 채우기');
END;
/

-- 확인
-- SELECT JOB_NAME, ENABLED, STATE, NEXT_RUN_DATE FROM USER_SCHEDULER_JOBS WHERE JOB_NAME = 'JOB_FILL_ONLINE_SHOP_ID';
-- SELECT LOG_DATE, STATUS, RUN_DURATION, ADDITIONAL_INFO FROM USER_SCHEDULER_JOB_RUN_DETAILS
--  WHERE JOB_NAME = 'JOB_FILL_ONLINE_SHOP_ID' ORDER BY LOG_DATE DESC;
-- SELECT DT, COUNT(*), COUNT(SHOP_ID) FROM T_SELECT_ONLINE_MNG_R WHERE DT >= TO_CHAR(SYSDATE - 7, 'YYYYMMDD') GROUP BY DT ORDER BY DT;
-- 즉시 한 번 실행(테스트): EXEC DBMS_SCHEDULER.RUN_JOB('JOB_FILL_ONLINE_SHOP_ID', use_current_session => TRUE);
