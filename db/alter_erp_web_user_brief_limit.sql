-- ============================================================================
-- ERP 영업 관리 웹 서비스: 사용자별 AI 주간 브리핑 하루 횟수 (SS10 스키마에서 실행)
--
-- AI 주간 브리핑은 AI 대화의 질문 수 · 비용 한도에서 빼고, 하루 N회로 따로 셉니다.
--   - 기본값(3회)은 관리자 > AI 사용 설정에서 바꿉니다 (T_ERP_WEB_SETTING, DDL 불필요).
--   - 사용자별 값은 관리자 > 사용자 · 권한의 "브리핑" 칸에서 바꾸며, 아래 열에 저장됩니다.
--     열이 없으면 모든 사용자가 기본값을 씁니다 (화면에 이 파일 실행 안내가 나옵니다).
-- NULL = 기본값 사용. 기존 행은 그대로 NULL 이라 바로 기본값(3회)이 적용됩니다.
-- SS10DEV 는 동의어(SS10DEV.T_ERP_WEB_USER)로 이미 쓰고 있어 권한 · 동의어 추가는 필요 없습니다.
-- ============================================================================

ALTER TABLE T_ERP_WEB_USER ADD (DAY_BRIEF_LMT NUMBER(4));

COMMENT ON COLUMN T_ERP_WEB_USER.DAY_BRIEF_LMT IS 'AI 주간 브리핑 하루 횟수 (NULL = 기본값, AI 대화 질문 · 비용 한도와 별도)';

-- 확인: DAY_BRIEF_LMT 가 보이면 정상
SELECT COLUMN_NAME, DATA_TYPE, DATA_PRECISION, NULLABLE FROM USER_TAB_COLUMNS WHERE TABLE_NAME = 'T_ERP_WEB_USER' AND COLUMN_NAME = 'DAY_BRIEF_LMT';

-- 되돌리기 (필요할 때만)
-- ALTER TABLE T_ERP_WEB_USER DROP COLUMN DAY_BRIEF_LMT;
