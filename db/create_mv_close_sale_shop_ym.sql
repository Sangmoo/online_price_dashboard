-- ============================================================================
-- 월 × 매장 판매 사전 집계 뷰 (AI 도구 sum_sales_shop_month, 화면 월별 합계 자동 재작성에 사용)
-- SS10 스키마에서 실행. 기존 뷰에 원가 금액(제조원가 × 수량) 컬럼 TOTAL_COST_AMT 를 추가해 다시 만든다.
--
-- 왜 필요한가: TOTAL_PRODUCT_COST2 = SUM(PRODUCT_COST2) 는 행마다 단가를 더한 값이라 원가 금액이 아니다.
--   수량이 1이 아닌 행(2026-08 기준 16.5%, 반품 음수 포함)이 있어 뷰의 합계 두 개(단가 합, 수량 합)로는
--   원가 금액을 정확히 되살릴 수 없다 (평균단가 × 수량 근사는 매장별 오차 중앙값 1.7%, 최대 560%).
--   그래서 행 단위로 곱한 합계 SUM(PRODUCT_COST2 * QTY) 를 뷰에 함께 저장한다.
--
-- 앱은 이 컬럼이 있으면 자동으로 뷰에서 원가를 읽고, 없으면 원본 테이블에서 정확히 계산한다 (재시작 불필요, 1분 내 반영).
-- ============================================================================

DROP MATERIALIZED VIEW MV_CLOSE_SALE_SHOP_YM;

CREATE MATERIALIZED VIEW MV_CLOSE_SALE_SHOP_YM
    TABLESPACE JPRI
    NOLOGGING
    BUILD IMMEDIATE
    REFRESH COMPLETE ON DEMAND
    ENABLE QUERY REWRITE
AS
SELECT  MAKE_YYMM,
        SHOP_ID,
        SHOP_NM,
        TEAM_CD,
        SUM(QTY)                    AS TOTAL_QTY,
        SUM(REAL_SALE_AMT)          AS TOTAL_SALE_AMT,
        SUM(DSCT_AMT)               AS TOTAL_DSCT_AMT,
        SUM(PRODUCT_COST2)          AS TOTAL_PRODUCT_COST2,   -- (기존 호환용) 단가 단순 합, 원가 금액 아님
        SUM(PRODUCT_COST2 * QTY)    AS TOTAL_COST_AMT,        -- ★ 원가 금액 = 제조원가(V+) × 수량
        COUNT(*)                    AS ROW_COUNT
  FROM T_CLOSE_SALE_BASE
 GROUP BY MAKE_YYMM, SHOP_ID, SHOP_NM, TEAM_CD
;

CREATE INDEX IX_MV_CLOSE_SALE_SHOP_YM_01 ON MV_CLOSE_SALE_SHOP_YM (MAKE_YYMM);
CREATE INDEX IX_MV_CLOSE_SALE_SHOP_YM_02 ON MV_CLOSE_SALE_SHOP_YM (MAKE_YYMM, SHOP_ID);

COMMENT ON MATERIALIZED VIEW MV_CLOSE_SALE_SHOP_YM IS '월×매장 판매 사전 집계 (T_CLOSE_SALE_BASE, 수동 갱신)';
COMMENT ON COLUMN MV_CLOSE_SALE_SHOP_YM.TOTAL_PRODUCT_COST2 IS '제조원가(V+) 단가 단순 합 - 원가 금액 아님';
COMMENT ON COLUMN MV_CLOSE_SALE_SHOP_YM.TOTAL_COST_AMT IS '원가 금액 합계 = SUM(제조원가(V+) × 수량)';

-- 앱 계정 조회 권한 (다시 만들면 개별 권한이 사라지므로 필요 시 재부여)
GRANT SELECT ON MV_CLOSE_SALE_SHOP_YM TO SS10DEV;

-- 월 마감 적재 후 갱신 (갱신 전에는 앱이 원본 테이블로 자동 전환)
-- EXEC DBMS_MVIEW.REFRESH('SS10.MV_CLOSE_SALE_SHOP_YM', 'C');
