-- ============================================================================
-- P_LOAD_ERP_WEB_STOCK_BASE 컴파일 오류 수정 (ORA-06575 부적당한 상태 / 원인 ORA-38101) — SS10 스키마에서 실행
--
-- 원인: 처음 프로시저의 내부 프로시저 매개변수 이름(sec · msg)이 로그 테이블 컬럼(SEC · MSG)과 같아,
--       MERGE 안에서 Oracle 이 매개변수가 아닌 컬럼으로 해석했습니다 → 컴파일 실패(INVALID).
-- 조치: 매개변수 이름을 p_ 로 바꾼 프로시저로 교체합니다. 테이블 · 스케줄 · 권한 · 동의어는 그대로 둡니다.
-- ============================================================================

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

-- 1) 컴파일 확인: 아무 행도 안 나와야 정상 · STATUS = VALID
SELECT LINE, POSITION, TEXT FROM USER_ERRORS WHERE NAME = 'P_LOAD_ERP_WEB_STOCK_BASE' ORDER BY SEQUENCE;
SELECT OBJECT_NAME, STATUS FROM USER_OBJECTS WHERE OBJECT_NAME = 'P_LOAD_ERP_WEB_STOCK_BASE';

-- 2) 첫 적재 (2~3분). SQL 창에 따라 둘 중 하나:
EXEC P_LOAD_ERP_WEB_STOCK_BASE;
-- 또는  CALL P_LOAD_ERP_WEB_STOCK_BASE();
-- 또는  BEGIN P_LOAD_ERP_WEB_STOCK_BASE; END;

-- 3) 결과: S 약 92,000 · T 약 74,600 · A 약 19,300행, STATUS = OK
SELECT BRAND, MAKE_YYMM, TO_CHAR(BASE_DT, 'YYYY-MM-DD HH24:MI:SS') BASE_DT, ROW_CNT, SEC, STATUS, MSG
  FROM T_ERP_WEB_STOCK_BASE_LOG ORDER BY BRAND;
