-- ============================================================================
-- 온라인 가격 수집: 예전 형식 '네이버(사이트)매장명' → 새 형식 (MALL_NM '네이버(사이트)', RMK '매장명')
-- (SS10 스키마에서 실행, 업무 시간 외 권장)
--
-- 2026-10-01 부터 수집은 MALL_NM = '네이버(사이트)', RMK = '동아수성점 리스트' 처럼 들어온다.
-- 그 전(2026-09-02 ~ 09-29) 수집은 MALL_NM = '네이버(사이트)동아수성점 리스트' 처럼 사이트명 뒤에 매장명이 붙어 있어
-- 판매처 매장 연결 화면에서 같은 매장이 두 줄로 나온다. 예전 행을 새 형식으로 맞춘다.
--
-- 2026-10-03 확인: 대상 66개 사이트명, 24,697행. 이 행들의 기존 RMK 는 비어 있거나(14,915행) '크롤링 실패',
-- 또는 상품별 '모델번호 : … / 판매자 : …' 값이라 매장명으로 덮어쓴다 (아래 2) 에서 원래 값을 백업).
-- MALL_NM 만으로 찾으므로 테이블 전체를 읽는다 (약 350MB, 수십 초 예상).
-- ============================================================================

-- 1) 대상 확인 (사이트명별 행 수, 바뀔 RMK)
SELECT MALL_NM, TRIM(SUBSTR(MALL_NM, LENGTH('네이버(사이트)') + 1)) AS NEW_RMK, COUNT(*) AS CNT, MIN(DT), MAX(DT)
  FROM T_SELECT_ONLINE_MNG_R
 WHERE MALL_NM LIKE '네이버(사이트)_%'
 GROUP BY MALL_NM
 ORDER BY CNT DESC;

-- 2) 백업: 바꾸기 전 사이트명·RMK (기본키 ONLINE_ID, DT, TIME, SEQ)
CREATE TABLE T_SELECT_ONLINE_MNG_R_BK1003 AS
SELECT ONLINE_ID, DT, TIME, SEQ, MALL_NM, RMK
  FROM T_SELECT_ONLINE_MNG_R
 WHERE MALL_NM LIKE '네이버(사이트)_%';

SELECT COUNT(*) FROM T_SELECT_ONLINE_MNG_R_BK1003;   -- 1) 의 합계(약 24,697)와 같아야 함

-- 3) 변경: 사이트명 뒤 매장명을 RMK 로 옮기고 사이트명은 '네이버(사이트)' 만 남긴다
UPDATE T_SELECT_ONLINE_MNG_R
   SET RMK     = TRIM(SUBSTR(MALL_NM, LENGTH('네이버(사이트)') + 1)),
       MALL_NM = '네이버(사이트)'
 WHERE MALL_NM LIKE '네이버(사이트)_%';
-- 처리 행 수가 백업 행 수와 같은지 확인한 뒤
COMMIT;

-- 4) 확인: 남은 예전 형식 0건, 새 형식 매장명별 행 수
SELECT COUNT(*) FROM T_SELECT_ONLINE_MNG_R WHERE MALL_NM LIKE '네이버(사이트)_%';
SELECT RMK, COUNT(*) FROM T_SELECT_ONLINE_MNG_R WHERE MALL_NM = '네이버(사이트)' GROUP BY RMK ORDER BY 2 DESC;

-- ----------------------------------------------------------------------------
-- (되돌리기) 문제가 있으면 백업으로 원래 사이트명·RMK 복원
-- ----------------------------------------------------------------------------
-- MERGE INTO T_SELECT_ONLINE_MNG_R R
-- USING T_SELECT_ONLINE_MNG_R_BK1003 B
--    ON (R.ONLINE_ID = B.ONLINE_ID AND R.DT = B.DT AND R.TIME = B.TIME AND R.SEQ = B.SEQ)
--  WHEN MATCHED THEN UPDATE SET R.MALL_NM = B.MALL_NM, R.RMK = B.RMK;
-- COMMIT;
-- 확인이 끝나면 백업 삭제: DROP TABLE T_SELECT_ONLINE_MNG_R_BK1003 PURGE;

-- ----------------------------------------------------------------------------
-- (참고) SSG·지마켓도 예전 형식이 있다 (2026-10-03 확인: 'SSG(사이트)…' 14개 110,553행, '지마켓(사이트)…' 23개 2,054행).
-- 앞으로 같은 새 형식으로 들어온다면 위 1)~4) 에서 '네이버(사이트)' 를 'SSG(사이트)' / '지마켓(사이트)' 로 바꿔 같은 방법으로 맞춘다.
-- 단, SSG(사이트)인동FN 처럼 매장이 아닌 판매업체 이름도 있으니 1) 결과를 먼저 확인할 것.
-- ----------------------------------------------------------------------------
