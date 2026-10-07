-- ============================================================================
-- 재고 재배치 추천 · RT 성과 · 미처리 RT 현황이 읽는 ERP 테이블 통계 다시 모으기 (SS10 소유자 또는 DBA 로 실행)
--
-- 왜: T_INDC_RT(본사지시 RT, 약 730만 행)의 통계가 2026-05-06 이후 갱신되지 않아 옵티마이저가 지시일 인덱스(T_INDC_RT_IDX01)
--     대신 전체를 읽습니다 (같은 조회 2.8초 → 인덱스면 0.1초). 지금은 화면 쿼리에 INDEX 힌트를 넣어 피하고 있지만,
--     ERP 화면 · 프로시저도 같은 계획을 쓰므로 통계를 새로 모으는 것이 근본 해결입니다.
-- 언제: 업무 시간 밖 (테이블마다 수십 초 ~ 수 분, 읽기만 하며 잠금 없음). 결과가 이상하면 아래 [되돌리기]로 직전 통계 복원.
-- ============================================================================

-- 0) 지금 통계 확인 (마지막 수집일 · 행 수)
SELECT TABLE_NAME, NUM_ROWS, LAST_ANALYZED, STALE_STATS
  FROM ALL_TAB_STATISTICS
 WHERE OWNER = 'SS10'
   AND TABLE_NAME IN ('T_INDC_RT', 'T_SHOP_REQ', 'T_DELV_ASK', 'T_AUTO_RT', 'T_AUTO_RT_TARGET', 'T_SHOP_MOVE')
 ORDER BY TABLE_NAME;

-- 1) (선택) 되돌릴 수 있게 지금 통계 백업
BEGIN
  DBMS_STATS.CREATE_STAT_TABLE(ownname => 'SS10', stattab => 'STATS_BAK_20261008');
EXCEPTION WHEN OTHERS THEN NULL;  -- 이미 있으면 그대로 사용
END;
/
BEGIN
  FOR t IN (SELECT 'T_INDC_RT' tn FROM DUAL UNION ALL SELECT 'T_SHOP_REQ' FROM DUAL UNION ALL SELECT 'T_DELV_ASK' FROM DUAL) LOOP
    DBMS_STATS.EXPORT_TABLE_STATS(ownname => 'SS10', tabname => t.tn, stattab => 'STATS_BAK_20261008', cascade => TRUE);
  END LOOP;
END;
/

-- 2) 통계 모으기 (인덱스 포함 · 표본 자동 · 히스토그램 자동)
BEGIN
  DBMS_STATS.GATHER_TABLE_STATS(ownname => 'SS10', tabname => 'T_INDC_RT',
                                estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE, method_opt => 'FOR ALL COLUMNS SIZE AUTO',
                                cascade => TRUE, degree => 4, no_invalidate => FALSE);
END;
/
-- 같은 이유로 오래됐을 수 있는 테이블 (0) 에서 LAST_ANALYZED 가 오래됐거나 STALE_STATS = 'YES' 인 것만 실행)
BEGIN
  DBMS_STATS.GATHER_TABLE_STATS(ownname => 'SS10', tabname => 'T_SHOP_REQ',
                                estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE, method_opt => 'FOR ALL COLUMNS SIZE AUTO',
                                cascade => TRUE, degree => 4, no_invalidate => FALSE);
END;
/
BEGIN
  DBMS_STATS.GATHER_TABLE_STATS(ownname => 'SS10', tabname => 'T_DELV_ASK',
                                estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE, method_opt => 'FOR ALL COLUMNS SIZE AUTO',
                                cascade => TRUE, degree => 4, no_invalidate => FALSE);
END;
/

-- 3) 확인: 힌트 없이도 지시일 인덱스를 쓰는지 (실행 계획에 T_INDC_RT_IDX01 이 보이면 정상)
EXPLAIN PLAN FOR
SELECT COUNT(*) FROM SS10.T_INDC_RT
 WHERE INDC_DT BETWEEN TO_CHAR(SYSDATE - 10, 'YYYYMMDD') AND TO_CHAR(SYSDATE, 'YYYYMMDD') AND BRD_CD = 'S'
   AND NVL(CNFM_YN, 'N') = 'N' AND DEL_DAY IS NULL;
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);

-- [되돌리기] 새 통계로 계획이 나빠졌으면 백업한 통계로 복원
-- BEGIN
--   DBMS_STATS.IMPORT_TABLE_STATS(ownname => 'SS10', tabname => 'T_INDC_RT', stattab => 'STATS_BAK_20261008', cascade => TRUE, no_invalidate => FALSE);
-- END;
-- /

-- 참고: 매일 밤 자동 통계 작업(auto optimizer stats collection)이 켜져 있는지 확인 — 꺼져 있으면 다른 큰 테이블도 같은 문제가 생깁니다.
SELECT CLIENT_NAME, STATUS FROM DBA_AUTOTASK_CLIENT WHERE CLIENT_NAME = 'auto optimizer stats collection';
