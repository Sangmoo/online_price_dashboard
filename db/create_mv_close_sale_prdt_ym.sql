-- ============================================================================
-- 월 × 팀 × 상품 × 판매형태 판매 사전 집계 뷰 (판매 현황 > 상품 순위 · 아이템/품군 전년 비교 · 판매형태 구성, AI 상품 분석)
-- SS10 스키마에서 실행. 기존 MV_CLOSE_SALE_SHOP_YM 은 그대로 두고 따로 만든다 (기존 화면 속도에 영향 없음).
--
-- 크기: 한 달 원본 약 31.8만 행 → 약 1.7만 행 (1/18). 전체 45개월 약 77만 행 예상.
-- 갱신: 관리자 화면 [지금 갱신] 이 MV_CLOSE_SALE_SHOP_YM 과 함께 갱신한다 (이 뷰가 있으면 자동으로 포함).
-- 뷰가 없거나 최신이 아니면 앱은 기간 1개월 조회만 원본에서 계산한다.
-- ============================================================================

CREATE MATERIALIZED VIEW MV_CLOSE_SALE_PRDT_YM
    TABLESPACE JPRI
    NOLOGGING
    BUILD IMMEDIATE
    REFRESH COMPLETE ON DEMAND
    ENABLE QUERY REWRITE
AS
SELECT  MAKE_YYMM,
        TEAM_CD,
        PRDT_CD,
        ITEM_NM,
        SUBSTRB(PRDT_GRP_NM, 1, 100)  AS PRDT_GRP_NM,   -- 앱의 품군 식(SUBSTRB)과 같게
        DSCT_CLSBY_NM,
        SUM(QTY)                    AS TOTAL_QTY,
        SUM(REAL_SALE_AMT)          AS TOTAL_SALE_AMT,
        SUM(DSCT_AMT)               AS TOTAL_DSCT_AMT,
        SUM(PRODUCT_COST2 * QTY)    AS TOTAL_COST_AMT,
        COUNT(*)                    AS ROW_COUNT
  FROM T_CLOSE_SALE_BASE
 GROUP BY MAKE_YYMM, TEAM_CD, PRDT_CD, ITEM_NM, SUBSTRB(PRDT_GRP_NM, 1, 100), DSCT_CLSBY_NM
;

CREATE INDEX IX_MV_CLOSE_SALE_PRDT_YM_01 ON MV_CLOSE_SALE_PRDT_YM (MAKE_YYMM, TEAM_CD) TABLESPACE JPRI;
CREATE INDEX IX_MV_CLOSE_SALE_PRDT_YM_02 ON MV_CLOSE_SALE_PRDT_YM (PRDT_CD, MAKE_YYMM) TABLESPACE JPRI;  -- 상품 팝업 (품번별 월 판매)

COMMENT ON MATERIALIZED VIEW MV_CLOSE_SALE_PRDT_YM IS '월×팀×상품×판매형태 판매 사전 집계 (T_CLOSE_SALE_BASE, 수동 갱신)';

-- 앱 계정 조회 권한
GRANT SELECT ON MV_CLOSE_SALE_PRDT_YM TO SS10DEV;
