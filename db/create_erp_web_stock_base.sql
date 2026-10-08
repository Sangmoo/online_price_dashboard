-- ============================================================================
-- ERP 영업 관리 웹 서비스: 매장 재고 기준 집계 (매장 × 스타일, 재고 있는 것만) — SS10 스키마에서 실행
--
-- 왜: 장기 미판매 · 재고 회전 · 주간 브리핑 · 매장 평가 카드가 쓰는 "매장 재고 기준"을 T_SHOP_STOCK 에서 바로 읽으면
--     이번 달 쉬즈미스만 1,748만 행(재고 있는 행은 49만 · 2.8%)을 하나씩 읽어 브랜드당 70초 안팎 걸립니다.
--     새벽에 한 번 이 테이블로 모아 두면 웹은 1초 안에 읽습니다. ERP 테이블 · 인덱스는 건드리지 않습니다.
--
-- 내용
--   1) T_ERP_WEB_STOCK_BASE      : 브랜드 × 매장 × 스타일 재고 수량 · 금액 · 최종판매일 · 최종/최초 출고일 (브랜드마다 최신 1벌)
--   2) T_ERP_WEB_STOCK_BASE_LOG  : 브랜드별 마지막 갱신 결과 (웹이 "오늘 갱신됐는지" 판단 · 실패하면 지금 방식으로 계산)
--   3) P_LOAD_ERP_WEB_STOCK_BASE : 갱신 프로시저 (브랜드별로 지우고 다시 넣고 커밋 → 갱신 중에도 웹은 이전 데이터를 읽음)
--   4) JOB_ERP_WEB_STOCK_BASE    : 매일 06:30 실행 (웹의 07:00 아침 계산보다 먼저)
--   5) SS10DEV 권한 · 시노님, 첫 적재
--
-- 소요: 브랜드 S 약 70초 · T 약 65초 · A 약 10초 (합계 약 2~3분, 읽기 위주, ERP 테이블 잠금 없음)
-- 사전 권한: SS10 에 CREATE JOB 이 있어야 합니다 (확인됨).
-- ============================================================================

-- 1) 집계 테이블
CREATE TABLE T_ERP_WEB_STOCK_BASE (
    BRAND       VARCHAR2(1)   NOT NULL,   -- 브랜드 (품번 첫 글자: S 쉬즈미스 · T 리스트 · A 시스티나)
    SHOP_ID     VARCHAR2(6)   NOT NULL,   -- 매장
    PRDT_CD     VARCHAR2(20)  NOT NULL,   -- 스타일(품번)
    MAKE_YYMM   VARCHAR2(6)   NOT NULL,   -- 재고 기준 월 (T_SHOP_STOCK.MAKE_YYMM)
    STOCK_QTY   NUMBER        NOT NULL,   -- 재고 수량 (색상 · 사이즈 합, 재고 > 0 인 SKU 만)
    STOCK_AMT   NUMBER        NOT NULL,   -- 재고 금액
    L_SALE_DT   VARCHAR2(8),              -- 최종 판매일 (T_SHOP_PRDT_BASE, SKU 중 가장 늦은 날)
    L_RNDS_DT   VARCHAR2(8),              -- 최종 출고(입고)일
    F_RNDS_DT   VARCHAR2(8),              -- 최초 출고(입고)일 (SKU 중 가장 이른 날)
    SKU_CNT     NUMBER        NOT NULL,   -- 묶인 SKU 수
    BASE_DT     DATE          NOT NULL,   -- 집계 시각
    CONSTRAINT PK_T_ERP_WEB_STOCK_BASE PRIMARY KEY (BRAND, SHOP_ID, PRDT_CD)
);
CREATE INDEX IX_T_ERP_WEB_STOCK_BASE_01 ON T_ERP_WEB_STOCK_BASE (SHOP_ID);   -- 매장 평가 카드(한 매장)

COMMENT ON TABLE T_ERP_WEB_STOCK_BASE IS 'ERP 영업 관리 웹: 매장 × 스타일 재고 기준 (매일 06:30 JOB_ERP_WEB_STOCK_BASE 갱신)';

-- 2) 브랜드별 갱신 결과
CREATE TABLE T_ERP_WEB_STOCK_BASE_LOG (
    BRAND       VARCHAR2(1)    NOT NULL,
    MAKE_YYMM   VARCHAR2(6),               -- 마지막으로 성공한 재고 기준 월
    BASE_DT     DATE,                      -- 마지막으로 성공한 집계 시각 (웹은 이 날짜가 오늘인지 본다)
    ROW_CNT     NUMBER,                    -- 넣은 행 수
    SEC         NUMBER,                    -- 걸린 시간(초)
    STATUS      VARCHAR2(10)   NOT NULL,   -- OK / ERROR / RUNNING
    MSG         VARCHAR2(1000),            -- 실패 메시지
    UPD_DT      DATE           NOT NULL,   -- 마지막 시도 시각
    CONSTRAINT PK_T_ERP_WEB_STOCK_BASE_LOG PRIMARY KEY (BRAND)
);

COMMENT ON TABLE T_ERP_WEB_STOCK_BASE_LOG IS 'ERP 영업 관리 웹: 매장 재고 기준 브랜드별 갱신 결과';

-- 3) 갱신 프로시저
--    수동 실행: EXEC P_LOAD_ERP_WEB_STOCK_BASE;        (모든 브랜드)
--               EXEC P_LOAD_ERP_WEB_STOCK_BASE('S');   (한 브랜드)
CREATE OR REPLACE PROCEDURE P_LOAD_ERP_WEB_STOCK_BASE (
    p_brand IN VARCHAR2 DEFAULT NULL   -- S / T / A, 생략하면 모두
) AS
    TYPE t_list IS TABLE OF VARCHAR2(1);
    v_list   t_list := t_list('S', 'T', 'A');
    v_ym     VARCHAR2(6) := TO_CHAR(SYSDATE, 'YYYYMM');
    v_now    DATE;
    v_t0     NUMBER;
    v_cnt    NUMBER;
    v_msg    VARCHAR2(1000);
    v_failed VARCHAR2(100);
    v_b      VARCHAR2(1);

    -- 매개변수 이름은 p_ 로 시작: SQL 안에서는 같은 이름의 컬럼(SEC · MSG 등)이 PL/SQL 변수보다 먼저 잡히기 때문 (ORA-38101)
    PROCEDURE set_log (p_b VARCHAR2, p_st VARCHAR2, p_cnt NUMBER, p_sec NUMBER, p_msg VARCHAR2) IS
    BEGIN
        MERGE INTO T_ERP_WEB_STOCK_BASE_LOG L
        USING (SELECT p_b AS BRAND FROM DUAL) X ON (L.BRAND = X.BRAND)
        WHEN MATCHED THEN UPDATE SET
             L.STATUS = p_st, L.MSG = p_msg, L.UPD_DT = SYSDATE,
             L.MAKE_YYMM = CASE WHEN p_st = 'OK' THEN v_ym  ELSE L.MAKE_YYMM END,
             L.BASE_DT   = CASE WHEN p_st = 'OK' THEN v_now ELSE L.BASE_DT END,
             L.ROW_CNT   = CASE WHEN p_st = 'OK' THEN p_cnt ELSE L.ROW_CNT END,
             L.SEC       = CASE WHEN p_st = 'OK' THEN p_sec ELSE L.SEC END
        WHEN NOT MATCHED THEN INSERT (L.BRAND, L.MAKE_YYMM, L.BASE_DT, L.ROW_CNT, L.SEC, L.STATUS, L.MSG, L.UPD_DT)
             VALUES (p_b,
                     CASE WHEN p_st = 'OK' THEN v_ym  END,
                     CASE WHEN p_st = 'OK' THEN v_now END,
                     CASE WHEN p_st = 'OK' THEN p_cnt END,
                     CASE WHEN p_st = 'OK' THEN p_sec END,
                     p_st, p_msg, SYSDATE);
    END;
BEGIN
    IF p_brand IS NOT NULL THEN
        v_list := t_list(UPPER(p_brand));
    END IF;

    FOR i IN 1 .. v_list.COUNT LOOP
        BEGIN
            v_b   := v_list(i);
            v_t0  := DBMS_UTILITY.GET_TIME;
            v_now := SYSDATE;
            set_log(v_b, 'RUNNING', NULL, NULL, NULL);
            COMMIT;

            -- 지우기 + 넣기를 한 트랜잭션으로: 커밋 전까지 웹은 이전 데이터를 그대로 읽는다
            DELETE FROM T_ERP_WEB_STOCK_BASE WHERE BRAND = v_b;

            INSERT INTO T_ERP_WEB_STOCK_BASE (BRAND, SHOP_ID, PRDT_CD, MAKE_YYMM, STOCK_QTY, STOCK_AMT,
                                              L_SALE_DT, L_RNDS_DT, F_RNDS_DT, SKU_CNT, BASE_DT)
            SELECT /*+ LEADING(S) INDEX(S T_SHOP_STOCK2_IDX03) USE_NL(B) INDEX(B PK_T_SHOP_PRDT_BASE) */
                   v_b, S.SHOP_ID, S.PRDT_CD, v_ym,
                   SUM(S.STOCK_QTY), SUM(NVL(S.STOCK_AMT, 0)),
                   MAX(B.L_SALE_DT), MAX(B.L_RNDS_DT), MIN(B.F_RNDS_DT), COUNT(*), v_now
              FROM T_SHOP_STOCK S, T_SHOP_PRDT_BASE B
             WHERE S.MAKE_YYMM = v_ym
               AND S.STOCK_QTY > 0
               AND S.PRDT_CD LIKE v_b || '%'
               AND B.COMPY_CD(+)      = 'A01C01'
               AND B.PARENT_BRD_CD(+) = v_b
               AND B.SHOP_ID(+)       = S.SHOP_ID
               AND B.PRDT_CD(+)       = S.PRDT_CD
               AND B.COLOR_CD(+)      = S.COLOR_CD
               AND B.SIZE_CD(+)       = S.SIZE_CD
             GROUP BY S.SHOP_ID, S.PRDT_CD;
            v_cnt := SQL%ROWCOUNT;

            set_log(v_b, 'OK', v_cnt, ROUND((DBMS_UTILITY.GET_TIME - v_t0) / 100, 1), NULL);
            COMMIT;
        EXCEPTION
            WHEN OTHERS THEN
                v_msg := SUBSTR(SQLERRM, 1, 1000);
                ROLLBACK;                                 -- 이전 데이터는 그대로 남는다
                set_log(v_b, 'ERROR', NULL, NULL, v_msg);
                COMMIT;
                v_failed := v_failed || v_b || ' ';
        END;
    END LOOP;

    IF v_failed IS NOT NULL THEN                          -- 한 브랜드가 실패해도 나머지는 갱신하고, 스케줄러 이력에는 실패로 남긴다
        RAISE_APPLICATION_ERROR(-20001, '매장 재고 기준 갱신 실패 브랜드: ' || v_failed);
    END IF;
END P_LOAD_ERP_WEB_STOCK_BASE;
/

-- 4) 매일 06:30 실행
-- 다시 만들 때만: EXEC DBMS_SCHEDULER.DROP_JOB('JOB_ERP_WEB_STOCK_BASE');
BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'JOB_ERP_WEB_STOCK_BASE',
        job_type        => 'STORED_PROCEDURE',
        job_action      => 'P_LOAD_ERP_WEB_STOCK_BASE',
        start_date      => TO_TIMESTAMP_TZ('2026-10-09 06:30:00 Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS TZR'),
        repeat_interval => 'FREQ=DAILY; BYHOUR=6; BYMINUTE=30; BYSECOND=0',
        enabled         => TRUE,
        comments        => '매일 06:30 웹 매장 재고 기준(T_ERP_WEB_STOCK_BASE) 갱신');
END;
/

-- 5) 웹 계정(SS10DEV) 권한 · 시노님
--    SELECT: 화면 조회 / EXECUTE: 관리자가 웹에서 [지금 갱신] 할 때 (예: 오전에 재고가 크게 바뀐 날)
GRANT SELECT ON T_ERP_WEB_STOCK_BASE TO SS10DEV;
GRANT SELECT ON T_ERP_WEB_STOCK_BASE_LOG TO SS10DEV;
GRANT EXECUTE ON P_LOAD_ERP_WEB_STOCK_BASE TO SS10DEV;
CREATE SYNONYM SS10DEV.T_ERP_WEB_STOCK_BASE FOR SS10.T_ERP_WEB_STOCK_BASE;
CREATE SYNONYM SS10DEV.T_ERP_WEB_STOCK_BASE_LOG FOR SS10.T_ERP_WEB_STOCK_BASE_LOG;
CREATE SYNONYM SS10DEV.P_LOAD_ERP_WEB_STOCK_BASE FOR SS10.P_LOAD_ERP_WEB_STOCK_BASE;

-- 6) 첫 적재 (2~3분) — 내일 06:30 을 기다리지 않고 바로 채우기
EXEC P_LOAD_ERP_WEB_STOCK_BASE;

-- 확인
SELECT BRAND, MAKE_YYMM, TO_CHAR(BASE_DT, 'YYYY-MM-DD HH24:MI:SS') BASE_DT, ROW_CNT, SEC, STATUS, MSG
  FROM T_ERP_WEB_STOCK_BASE_LOG ORDER BY BRAND;
-- 기대: S 약 92,000행 · T 약 74,600행 · A 약 19,300행, STATUS = OK

-- SELECT JOB_NAME, ENABLED, STATE, NEXT_RUN_DATE FROM USER_SCHEDULER_JOBS WHERE JOB_NAME = 'JOB_ERP_WEB_STOCK_BASE';
-- SELECT LOG_DATE, STATUS, RUN_DURATION, ADDITIONAL_INFO FROM USER_SCHEDULER_JOB_RUN_DETAILS
--  WHERE JOB_NAME = 'JOB_ERP_WEB_STOCK_BASE' ORDER BY LOG_DATE DESC;

-- 되돌리기 (필요할 때만)
-- EXEC DBMS_SCHEDULER.DROP_JOB('JOB_ERP_WEB_STOCK_BASE');
-- DROP SYNONYM SS10DEV.P_LOAD_ERP_WEB_STOCK_BASE;
-- DROP SYNONYM SS10DEV.T_ERP_WEB_STOCK_BASE_LOG;
-- DROP SYNONYM SS10DEV.T_ERP_WEB_STOCK_BASE;
-- DROP PROCEDURE P_LOAD_ERP_WEB_STOCK_BASE;
-- DROP TABLE T_ERP_WEB_STOCK_BASE_LOG PURGE;
-- DROP TABLE T_ERP_WEB_STOCK_BASE PURGE;
