-- ============================================================================
-- [제안] 온라인 가격 수집 테이블 인덱스 · 공간 정리 (SS10 스키마, DBA 검토 후 업무 시간 외 실행)
-- 이 파일은 앱이 자동으로 실행하지 않는다. 2026-10-01 측정값 기준.
--
-- 현황
--   T_SELECT_ONLINE_MNG    : 374행. 인덱스 추가 불필요 (PK 로 충분)
--   T_SELECT_ONLINE_MNG_S  : 66,809행, PK(ONLINE_ID, PRDT_CD). 이 앱은 조회하지 않음 (수집 프로그램 전용)
--   T_SELECT_ONLINE_MNG_R  : 1,037,060행 (2026-08-31 ~ 2026-10-01, 31일 보관), 하루 약 3~4만 행
--     - 실제 데이터 약 240MB (평균 233바이트/행) 인데 테이블이 23.6GB (300만 블록) → 99% 가 지운 행의 빈 공간
--     - 통계 정보가 2026-05-21 이후 갱신 안 됨 (통계상 43만 행) → 실행 계획이 틀어질 수 있음
--     - 측정: 7일 대시보드 집계 약 2초, 31일 상품코드 검색 3.7초, 하루 행 조회 0.04초
--
-- 기존 인덱스 (_R)
--   PK_T_SELECT_ONLINE_MNG_R        (ONLINE_ID, DT, TIME, SEQ)  925MB
--   PK_T_SELECT_ONLINE_MNG_R_IDX01  (DT)                         541MB
--   IX_T_SELECT_ONLINE_MNG_R_IDX01  (SEQ)
--   IX_T_SELECT_ONLINE_MNG_R_IDX02  (ONLINE_ID, DT)   ← PK 앞 두 컬럼과 같아 중복
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1) [최우선] 공간 정리 + 통계 갱신 — 인덱스를 추가하는 것보다 효과가 크다
--    오래된 행을 DELETE 로 지워 온 것으로 보임. 정리하면 전체 읽기·범위 읽기 블록 수가 크게 준다.
--    (A) 온라인 정리: JPRD 는 ASSM(자동 세그먼트 관리) 확인됨. 진행 중에도 조회 가능, 시간이 걸림
-- ----------------------------------------------------------------------------
ALTER TABLE T_SELECT_ONLINE_MNG_R ENABLE ROW MOVEMENT;
ALTER TABLE T_SELECT_ONLINE_MNG_R SHRINK SPACE CASCADE;
ALTER TABLE T_SELECT_ONLINE_MNG_R DISABLE ROW MOVEMENT;

--    (B) ASSM 이 아니면: MOVE 후 인덱스 재생성 (수집 프로그램을 멈춘 시간에, MOVE 중에는 인덱스가 UNUSABLE)
-- ALTER TABLE T_SELECT_ONLINE_MNG_R MOVE;
-- ALTER INDEX PK_T_SELECT_ONLINE_MNG_R REBUILD;
-- ALTER INDEX PK_T_SELECT_ONLINE_MNG_R_IDX01 REBUILD;
-- ALTER INDEX IX_T_SELECT_ONLINE_MNG_R_IDX01 REBUILD;
-- ALTER INDEX IX_T_SELECT_ONLINE_MNG_R_IDX02 REBUILD;

BEGIN
    DBMS_STATS.GATHER_TABLE_STATS(OWNNAME => 'SS10', TABNAME => 'T_SELECT_ONLINE_MNG_R', CASCADE => TRUE);
END;
/

-- 앞으로 오래된 행을 지우는 작업(31일 보관)이 계속 DELETE 라면, 월 1회 정도 1) 을 반복하거나
-- DT 기준 파티션(일/월)으로 바꿔 DROP PARTITION 으로 지우면 공간이 쌓이지 않는다.


-- ----------------------------------------------------------------------------
-- 2) 대시보드 집계용 커버링 인덱스 (대시보드 · 일자별 추이 · 사이트별 · 할인율 분포 · AI 집계)
--    기간(DT) 조건 + 이 컬럼들만 쓰는 집계를 테이블을 읽지 않고 인덱스만으로 계산한다.
--    예상 크기 약 80~120MB. (상품 순위는 제목(TITLE)이 필요해 테이블을 읽음)
-- ----------------------------------------------------------------------------
CREATE INDEX IX_T_SELECT_ONLINE_MNG_R_03 ON T_SELECT_ONLINE_MNG_R
    (DT, MALL_NM, PRDT_CD, PRICE, DC_PRICE, NAVER_PAY_SELL_NO)
    TABLESPACE JPRD;   -- 기존 _R 인덱스와 같은 테이블스페이스


-- ----------------------------------------------------------------------------
-- 3) 상품코드로 찾기 (AI '특정 상품 가격 추이', 상세 검색)
--    지금은 기간 안의 모든 행을 읽고 상품코드를 거른다 (31일 3.7초) → 상품 행만 바로 찾는다.
-- ----------------------------------------------------------------------------
CREATE INDEX IX_T_SELECT_ONLINE_MNG_R_04 ON T_SELECT_ONLINE_MNG_R (PRDT_CD, DT) TABLESPACE JPRD;


-- ----------------------------------------------------------------------------
-- 4) 중복 인덱스 정리 (확인 후)
--    IX_T_SELECT_ONLINE_MNG_R_IDX02 (ONLINE_ID, DT) 는 PK 의 앞부분과 같아 쓸모가 거의 없고 적재만 느리게 한다.
--    IX_..._IDX01 (SEQ) 은 이 앱은 쓰지 않음 — 수집 프로그램이 쓰는지 사용 여부를 먼저 확인.
--    한 달쯤 사용 여부를 모은 뒤 USED = 'NO' 이면 지운다.
-- ----------------------------------------------------------------------------
ALTER INDEX IX_T_SELECT_ONLINE_MNG_R_IDX02 MONITORING USAGE;
ALTER INDEX IX_T_SELECT_ONLINE_MNG_R_IDX01 MONITORING USAGE;
-- SELECT INDEX_NAME, USED, START_MONITORING FROM V$OBJECT_USAGE WHERE TABLE_NAME = 'T_SELECT_ONLINE_MNG_R';
-- DROP INDEX IX_T_SELECT_ONLINE_MNG_R_IDX02;


-- ----------------------------------------------------------------------------
-- 5) T_SELECT_ONLINE_MNG_S (선택)
--    수집 프로그램이 스타일(PRDT_CD)만으로 기준가를 찾는다면 아래 인덱스가 도움이 된다 (PK 는 ONLINE_ID 가 앞).
--    6.7만 행이라 지금도 전체 읽기 0.1초 수준이므로, 실제 그런 조회가 있을 때만.
-- ----------------------------------------------------------------------------
-- CREATE INDEX IX_T_SELECT_ONLINE_MNG_S_01 ON T_SELECT_ONLINE_MNG_S (PRDT_CD);
