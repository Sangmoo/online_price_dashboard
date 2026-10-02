-- ============================================================================
-- 월 × 팀 × 상품 × 판매형태 판매 사전 집계 뷰 (판매 현황 > 상품 순위 · 아이템/품군 전년 비교 · 판매형태 구성 · 시즌 판매 진척,
-- 상품 팝업, AI 상품 분석)
-- SS10 스키마에서 실행. 기존 MV_CLOSE_SALE_SHOP_YM 은 그대로 두고 따로 만든다 (기존 화면 속도에 영향 없음).
--
-- 크기: 한 달 원본 약 31.8만 행 → 약 1.7만 행 (1/18). 전체 45개월 약 77만 행 예상.
--       품번마다 기획년도·시즌은 하나라(2025-01~2026-08 품번 9,836개 중 둘 이상인 품번 0개) 두 열을 더해도 행 수는 같다.
-- 갱신: 관리자 화면 [지금 갱신] 이 MV_CLOSE_SALE_SHOP_YM 과 함께 갱신한다 (이 뷰가 있으면 자동으로 포함).
-- 뷰가 없거나 최신이 아니면 앱은 기간 1개월 조회만 원본에서 계산한다.
--
-- ORA-01450(키의 최대 길이 6398 초과) 관련:
--   GROUP BY 가 있는 집계 뷰를 만들면 Oracle 이 GROUP BY 열 전체로 내부 인덱스(I_SNAP$_…)를 자동으로 만든다.
--   TEAM_CD · DSCT_CLSBY_NM 이 VARCHAR2(4000) 으로 선언돼 있어 그 인덱스 키가 6398바이트를 넘는다.
--   → USING NO INDEX 로 내부 인덱스를 만들지 않는다 (수동 완전 갱신만 쓰므로 필요 없음). 조회용 인덱스는 아래에서 따로 만든다.
--   시즌·품군은 앱 식(SUBSTRB(…, 1, 100))과 같게 둔다. 실제 값은 최대 20바이트 수준이라 결과는 원래 열과 같다.
-- ============================================================================

-- 앞서 실패한 생성이 일부 남아 있으면 먼저 지운다 (없으면 ORA-12003 이 나오며, 무시하면 된다)
-- DROP MATERIALIZED VIEW MV_CLOSE_SALE_PRDT_YM;

CREATE MATERIALIZED VIEW MV_CLOSE_SALE_PRDT_YM
    TABLESPACE JPRI
    NOLOGGING
    BUILD IMMEDIATE
    USING NO INDEX
    REFRESH COMPLETE ON DEMAND
    ENABLE QUERY REWRITE
AS
SELECT  MAKE_YYMM,
        TEAM_CD,
        PRDT_CD,
        PLAN_YY,
        SUBSTRB(SESS_NM, 1, 100)      AS SESS_NM,       -- 앱의 시즌 식과 같게
        ITEM_NM,
        SUBSTRB(PRDT_GRP_NM, 1, 100)  AS PRDT_GRP_NM,   -- 앱의 품군 식과 같게
        DSCT_CLSBY_NM,
        SUM(QTY)                    AS TOTAL_QTY,
        SUM(REAL_SALE_AMT)          AS TOTAL_SALE_AMT,
        SUM(DSCT_AMT)               AS TOTAL_DSCT_AMT,
        SUM(PRODUCT_COST2 * QTY)    AS TOTAL_COST_AMT,
        COUNT(*)                    AS ROW_COUNT
  FROM T_CLOSE_SALE_BASE
 GROUP BY MAKE_YYMM, TEAM_CD, PRDT_CD, PLAN_YY, SUBSTRB(SESS_NM, 1, 100), ITEM_NM, SUBSTRB(PRDT_GRP_NM, 1, 100), DSCT_CLSBY_NM
;

CREATE INDEX IX_MV_CLOSE_SALE_PRDT_YM_01 ON MV_CLOSE_SALE_PRDT_YM (MAKE_YYMM, TEAM_CD) TABLESPACE JPRI;
CREATE INDEX IX_MV_CLOSE_SALE_PRDT_YM_02 ON MV_CLOSE_SALE_PRDT_YM (PRDT_CD, MAKE_YYMM) TABLESPACE JPRI;  -- 상품 팝업 (품번별 월 판매)
CREATE INDEX IX_MV_CLOSE_SALE_PRDT_YM_03 ON MV_CLOSE_SALE_PRDT_YM (PLAN_YY, SESS_NM, MAKE_YYMM) TABLESPACE JPRI;  -- 시즌 판매 진척

COMMENT ON MATERIALIZED VIEW MV_CLOSE_SALE_PRDT_YM IS '월×팀×상품×판매형태 판매 사전 집계 (T_CLOSE_SALE_BASE, 수동 갱신)';

-- 통계 (갱신 후에도 [지금 갱신] 이 자동으로 다시 모으지는 않으므로 처음 한 번)
BEGIN
    DBMS_STATS.GATHER_TABLE_STATS(OWNNAME => USER, TABNAME => 'MV_CLOSE_SALE_PRDT_YM', CASCADE => TRUE);
END;
/

-- 앱 계정 조회 권한
GRANT SELECT ON MV_CLOSE_SALE_PRDT_YM TO SS10DEV;
