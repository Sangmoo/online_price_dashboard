// 지표 정의 · 도움말 내용. 화면의 (?) 아이콘이 id 로 이 항목을 열고, 상단 [도움말] 은 전체를 보여준다.
// 계산식을 바꾸면 이 파일도 같이 고친다 (서버 계산 위치를 code 에 적어 둔다).

export type HelpGroup = 'online' | 'sales' | 'invt' | 'stock'

export type HelpEntry = {
  id: string
  group: HelpGroup
  name: string
  /** 계산식 (한 줄씩) */
  formula: string[]
  /** 원천 테이블 · 열 */
  source: string
  /** 기준 · 예외 · 주의 */
  notes?: string[]
  /** 이 지표가 나오는 화면 */
  where: string[]
  /** 서버 계산 위치 (관리자 참고용) */
  code?: string
}

export const HELP_GROUPS: { key: HelpGroup; label: string; desc: string }[] = [
  { key: 'online', label: '온라인 가격', desc: '온라인몰 가격 수집 결과 (T_SELECT_ONLINE_MNG_R)' },
  { key: 'sales', label: '판매 분석', desc: '마감 매출 기초 데이터 (T_CLOSE_SALE_BASE, 매월 1일 13:00 전월 적재)' },
  { key: 'invt', label: '매장 재고 실사계획', desc: '실사계획 (T_SHOP_INVT_PLAN) 의 자동 계산 값' },
  { key: 'stock', label: '재고 재배치 추천', desc: 'ERP 자동 RT · 판매분 자동보충과 같은 규칙으로 계산 (조회 · 추천만, ERP 에 등록하지 않음)' },
]

export const HELP: HelpEntry[] = [
  // ---------------------------------------------------------------- 온라인 가격
  {
    id: 'online.dcRate',
    group: 'online',
    name: '할인율 (온라인)',
    formula: ['할인율(%) = (기준가 − 사이트 할인가) ÷ 기준가 × 100'],
    source: 'T_SELECT_ONLINE_MNG_R.PRICE(기준가) · DC_PRICE(사이트 할인가)',
    notes: [
      '기준가는 사이트에 표시된 정가입니다. 사이트가 기준가를 낮춰 올리면 할인율이 작게 보일 수 있습니다.',
      '기준가가 0 이거나 비어 있으면 할인율을 계산하지 않습니다.',
    ],
    where: ['대시보드', '일자별 상세', '상품 팝업'],
    code: 'data_service.DC_RATE_SQL',
  },
  {
    id: 'online.avgDcRate',
    group: 'online',
    name: '평균 할인율 (온라인)',
    formula: ['평균 할인율 = 조회 범위 수집 행들의 할인율 단순 평균'],
    source: 'T_SELECT_ONLINE_MNG_R',
    notes: ['금액 가중 평균이 아니라 수집 1건을 1개로 센 평균입니다. 같은 상품이 여러 사이트·여러 번 수집되면 그만큼 반영됩니다.'],
    where: ['대시보드 (KPI · 일자별 추이 · 사이트별)', '일자별 상세 (검색 결과 기준)'],
  },
  {
    id: 'online.maxDcRate',
    group: 'online',
    name: '최대 할인율 · 30% 이상 고할인',
    formula: ['최대 할인율 = 기간 중 수집 행 할인율의 최댓값', '30% 이상 고할인 = 할인율 30% 이상인 수집 건수 (비율 = ÷ 총 수집 건수)'],
    source: 'T_SELECT_ONLINE_MNG_R',
    where: ['대시보드'],
  },
  {
    id: 'online.counts',
    group: 'online',
    name: '수집 건수 · 상품 수 · 사이트 수 · 판매자 수',
    formula: [
      '수집 건수 = 수집 행 수',
      '상품 수 = 서로 다른 상품코드(PRDT_CD) 수',
      '사이트 수 = 서로 다른 사이트명(MALL_NM) 수 · 판매자 = 서로 다른 판매자ID(NAVER_PAY_SELL_NO) 수',
    ],
    source: 'T_SELECT_ONLINE_MNG_R',
    notes: ["네이버·SSG 는 사이트명이 '네이버(사이트)' 처럼 하나이고 매장은 판매자ID·매장정보(RMK)로 구분됩니다."],
    where: ['대시보드', '일자별 상세'],
  },
  {
    id: 'online.shopId',
    group: 'online',
    name: '매장코드 (SHOP_ID) · 매장 연결률',
    formula: [
      '매장코드 = 판매처 매장 연결(사이트 · 판매자번호 · 브랜드 → 매장코드)로 채운 값',
      '브랜드 = 품번 첫 글자 (S 쉬즈미스 · T 리스트 · A 시스티나). 브랜드 행이 없으면 모든 브랜드 공통(*) 행',
      '매장 연결률 = 매장코드가 있는 수집 건수 ÷ 총 수집 건수',
    ],
    source: 'T_SELECT_ONLINE_MNG_R.SHOP_ID ← T_SELECT_ONLINE_MALL_SHOP',
    notes: [
      '매일 02:00 스케줄(JOB_FILL_ONLINE_SHOP_ID)이 전일자를 채웁니다. 오늘 수집분은 다음 날 채워집니다.',
      '일자별 상세 [매장코드 채우기] 로 최근 7일(오늘 포함)을 바로 채울 수 있습니다 (판매처 매장 연결 권한 필요).',
      "매장코드 조건에 '-' 를 넣으면 매장코드가 없는(연결 전) 행만 봅니다.",
    ],
    where: ['일자별 상세', '대시보드 (매장별 수집)', '판매처 매장 연결'],
    code: 'db/create_job_online_shop_id.sql · mall_shop.fill_shop_ids',
  },
  // ---------------------------------------------------------------- 판매 분석
  {
    id: 'sales.amt',
    group: 'sales',
    name: '실판금액 · 판매 수량',
    formula: ['실판금액 = Σ 실판금액(REAL_SALE_AMT), 반품은 마이너스', '판매 수량 = Σ 수량(QTY), 반품은 마이너스'],
    source: 'T_CLOSE_SALE_BASE.REAL_SALE_AMT · QTY',
    notes: [
      '마감 매출 기준이라 월 단위입니다. 전월 판매분은 매월 1일 13:00 에 적재됩니다.',
      '판매 현황의 월×매장 합계는 사전 집계 뷰(MV_CLOSE_SALE_SHOP_YM)로 계산합니다. 적재 후 관리자 [지금 갱신] 이 필요합니다.',
    ],
    where: ['판매 현황', '월별 매장별 판매 집계', '상품 팝업'],
  },
  {
    id: 'sales.growth',
    group: 'sales',
    name: '증감률 · 비교 기준',
    formula: ['증감률(%) = (조회 기간 값 ÷ 비교 기간 값 − 1) × 100', '%p 증감 = 조회 기간 비율 − 비교 기간 비율 (원가율 · 할인율)'],
    source: 'T_CLOSE_SALE_BASE',
    notes: [
      '비교 기준: 전년 동기(기본, 12개월 전 같은 기간) · 직전 기간(바로 앞 같은 길이) · 직접 선택',
      '매장 성장 순위는 비교 기간 월평균 실판금액 1천만원 이상 매장만 봅니다 (작은 매장의 큰 % 변동 제외).',
    ],
    where: ['판매 현황', '월별 매장별 판매 집계'],
    code: 'sale_dashboard._rate',
  },
  {
    id: 'sales.ytd',
    group: 'sales',
    name: '연 누계',
    formula: ['연 누계 = 기준 월이 속한 해 1월 ~ 기준 월 실판금액 합계', '전년 누계 = 전년 1월 ~ 전년 같은 월'],
    source: 'T_CLOSE_SALE_BASE',
    where: ['판매 현황'],
  },
  {
    id: 'sales.achieve',
    group: 'sales',
    name: '목표 달성률',
    formula: ['달성률(%) = 목표가 있는 매장의 실판금액 ÷ 목표금액 × 100', '목표 대비 = 목표가 있는 매장의 실판금액 − 목표금액'],
    source: 'T_SHOP_SELL_MGOAL (매장 × 브랜드 × 월 목표금액)',
    notes: [
      '목표는 매장 단위로 합쳐 매장의 판매 브랜드(팀)로 모읍니다.',
      '목표가 없는 매장의 매출은 달성률 계산에서 빼고 따로 표시합니다.',
    ],
    where: ['판매 현황'],
    code: 'sale_dashboard._achieve',
  },
  {
    id: 'sales.costRate',
    group: 'sales',
    name: '원가율',
    formula: ['원가 금액 = 제조원가(V+) × 수량', '원가율(%) = 원가 금액 ÷ 실판금액 × 100'],
    source: 'T_CLOSE_SALE_BASE.PRODUCT_COST2 (적재 시 T_STYLE_PLAN 사후원가, 없으면 사전원가) · QTY · REAL_SALE_AMT',
    where: ['판매 현황', '월별 매장별 판매 집계'],
    code: 'sale_dashboard._cost_rate',
  },
  {
    id: 'sales.dsctRate',
    group: 'sales',
    name: '할인율 (매장 판매)',
    formula: ['할인율(%) = 할인금액 ÷ (실판금액 + 할인금액) × 100'],
    source: 'T_CLOSE_SALE_BASE.DSCT_AMT · REAL_SALE_AMT',
    notes: ['할인 전 금액 대비 깎아 준 비율입니다. 온라인 할인율(기준가 대비)과 계산 기준이 다릅니다.'],
    where: ['판매 현황', '상품 팝업 (매장 판매)'],
    code: 'sale_dashboard._dsct_rate',
  },
  {
    id: 'sales.shops',
    group: 'sales',
    name: '판매 매장 · 매장당 매출',
    formula: ['판매 매장 = 기간 중 판매 기록(반품 포함)이 있는 매장 수', '매장당 = 실판금액 ÷ 판매 매장 수'],
    source: 'T_CLOSE_SALE_BASE.SHOP_ID',
    where: ['판매 현황'],
  },
  {
    id: 'sales.saleShare',
    group: 'sales',
    name: '세일 비중',
    formula: [
      "세일 비중(%) = 판매형태 이름에 '세일'이 들어간 판매의 실판금액 ÷ 매장 실판금액 × 100",
      '차이(%p) = 매장 세일 비중 − 같은 브랜드 전체 세일 비중',
    ],
    source: 'T_CLOSE_SALE_BASE.DSCT_CLSBY_NM(판매형태)',
    notes: [
      '행사는 백화점 행사장 등 정상 영업 형태라 세일에 넣지 않습니다.',
      "행사·특판 전용 매장('(행)', '(특)', 사내행사)은 기본 제외, 월평균 1천만원 미만·폐점 매장 제외.",
      '매장의 브랜드 = 기간 중 가장 많이 판 팀의 브랜드.',
    ],
    where: ['판매 현황 › 세일 비중이 높은 매장'],
    code: 'sale_mix.py',
  },
  {
    id: 'sales.seasonProgress',
    group: 'sales',
    name: '시즌 판매 진척률',
    formula: [
      '올해 누적 = 시즌(기획년도 + 시즌) 시작 월 ~ 기준 월 실판금액 누적',
      '같은 시점 = 전년 같은 시즌의 12개월 전 같은 달까지 누적',
      '진척률(%) = 올해 누적 ÷ 전년 시즌 최종 누적 × 100',
    ],
    source: 'MV_CLOSE_SALE_PRDT_YM (없으면 T_CLOSE_SALE_BASE)',
    notes: ['시작 월은 시즌 합계의 0.3% 미만인 앞쪽 달(선판매 몇 건)을 건너뛴 첫 달입니다. 기본 시즌은 기준 월에 가장 많이 팔린 시즌.'],
    where: ['판매 현황 › 시즌 판매 진척'],
    code: 'sale_season.py',
  },
  {
    id: 'sales.onlineAlert',
    group: 'sales',
    name: '온라인 할인 주의 상품',
    formula: [
      '대상 = 판매 현황 조건의 매장 실판금액 상위 50개 상품',
      '주의 = 온라인 최근 7일 평균 할인율이 그 전 4주(8~35일 전)보다 3%p 이상 높음',
      '또는 그 전 4주 수집이 없는데 최근 할인율이 15% 이상',
    ],
    source: 'T_CLOSE_SALE_BASE + T_SELECT_ONLINE_MNG_R',
    notes: ['온라인 가격 메뉴 권한도 있는 사용자에게만 보입니다.'],
    where: ['판매 현황 › 온라인 할인 주의 상품'],
    code: 'online_alerts.py',
  },
  // ---------------------------------------------------------------- 실사계획
  {
    id: 'invt.sales',
    group: 'invt',
    name: '전년 매출 · 당년 매출 · 증감율',
    formula: [
      '당년 매출 = 올해 1월 ~ 지난달 매장 실판금액 합계',
      '전년 매출 = 작년 1월 ~ 작년 같은 달 합계',
      '증감율(%) = (당년 ÷ 전년 − 1) × 100',
    ],
    source: 'T_CLOSE_SALE_BASE.REAL_SALE_AMT (매장코드 기준)',
    notes: ['1월에는 당년 구간이 비어 있어 매출이 표시되지 않습니다.'],
    where: ['매장 재고 실사계획'],
    code: 'invt_plan._sales_ytd',
  },
  {
    id: 'invt.lastInvt',
    group: 'invt',
    name: '최종실사일 · 전실사결과 · 경과일',
    formula: [
      '최종실사일 = 실사 정산된 가장 최근 실사일',
      '전실사결과(원) = Σ(확정 수량 × 공급가) − Σ(전산 재고 수량 × 공급가) — 마이너스면 재고 부족',
      '경과일 = 오늘 − 최종실사일',
    ],
    source: 'T_SHOP_INVT · T_SHOP_INVT_STLM_TOT · T_SHOP_INVT_PRE_INFO',
    where: ['매장 재고 실사계획'],
    code: 'invt_plan.shop_detail',
  },
  {
    id: 'invt.cost',
    group: 'invt',
    name: '재고 수량 · 기본료 · 실사예상액',
    formula: [
      '재고 수량 = 이번 달 매장 재고 수량 합계 (매장 선택 당일 기준)',
      '기본료 = 권역이 수도권이면 150,000원, 그 외 200,000원',
      '실사예상액 = 재고 수량 × 85원',
    ],
    source: 'T_SHOP_STOCK.STOCK_QTY',
    notes: ['자동 계산 뒤 직접 고칠 수 있습니다. 권역·재고 수량을 바꾸면 다시 계산됩니다.'],
    where: ['매장 재고 실사계획'],
  },
  // ---------------------------------------------------------------- 재고 재배치 추천
  {
    id: 'stock.rt',
    group: 'stock',
    name: '매장 간 RT 추천',
    formula: [
      '받는 매장 = 판매 기간(최대 31일)에 판매가 있는데 지금 재고 ≤ 0 인 매장 × 품번 · 칼라 · 사이즈 + 기간 중 “지시가능매장없음”으로 취소된 자동 RT 요청',
      '필요 수량 = 받는 상품당 수량(1~3) + 마이너스 재고(완불 대기)',
      '보낼 수 있는 수량 = 현재고 − 이동중(30일 미확정) − 자동 RT 요청중(10일) − 매장 미처리 본사지시 · 매장간 RT(10일) − 최소보유재고',
      '이미 지시 · 요청받아 들어올 수량이 있으면 받는 매장의 필요 수량에서 뺍니다',
      '보내는 매장 = 같은 RT 그룹 · 모매장 브랜드 행낭 규칙 · 정상 매장 · 매장등급 있음 · 최초/최종 출고 경과일 · 수불제어 · 자동RT 제외 스타일 통과',
      '순서: 안 팔리는 매장 우선 = 기간 판매 적은 순 → 자동 RT 순서(보낼 수 있는 수량 많은 순 · 판매율 · 최종판매일 · 최초출고일)',
    ],
    source: 'T_SHOP_RNDS_BASE(판매) · T_SHOP_STOCK(재고) · T_SHOP_PRDT_BASE · T_SHOP_RT_GRP_DETL · T_AUTO_RT · T_SHOP_MOVE · T_INDC_RT · T_SHOP_REQ · T_RNDS_CNTR',
    notes: [
      '[자동 RT 설정 점검]: 하루 한도 없이 계산한 추천에서 보낼 수 있는 매장마다 지정가능수(ASIGN_ABLE_QTY) · 기간 실제 지정 수 · 자동RT 취소 요청을 채울 수 있던 수량을 비교합니다. 권장 지정가능수 = 올림((기간 실제 지정 + 취소 채움) ÷ 기간 일수). 설정 변경은 ERP 에서 합니다.',
      '관리자는 추천을 골라 [본사지시 RT 지시]로 ERP 본사지시 RT(T_INDC_RT, 1장에 1행)를 넣고 로그인한 사번으로 확정합니다 — ERP 확정과 같이 매장 이동요청(T_SHOP_REQ, 매장 미처리)이 함께 생기고 매장이 수락 · 거부합니다. 넣기 직전에 지금 재고로 다시 확인해 모자란 행은 뺍니다. [등록 내역]에서 매장이 아직 처리하지 않은 지시만 ERP 본사지시 취소와 같이(본사지시취소 · 삭제일) 취소할 수 있습니다.',
      'AI 대화에서 “자동RT 취소 2회 이상, 판매 3장 이상만 골라줘”처럼 말하면 [화면에서 열고 선택] 카드가 나오고, 누르면 같은 조건으로 계산해 그 행들을 체크합니다. 등록은 관리자가 직접 누릅니다.',
      '[RT 성과]: 지시일 기간의 본사지시 RT 가 매장에서 수락 · 거부(3일 무응답 자동거부 따로) · 미처리 · 취소된 수량, 수락률, 평균 처리 시간, 거부 사유, 받은 매장이 수락 후 7일 안에 그 상품을 판 비율(판매 전환). 이 화면에서 지시한 것 / 본사지시 전체를 고를 수 있습니다.',
      '[자동 RT 하루 한도 적용]을 켜면 지정가능수(ASIGN_ABLE_QTY) 0 매장을 빼고 오늘 남은 지정 · 요청 가능 수까지 지킵니다. 지정가능수 0 매장이 많아 추천이 크게 줄어듭니다.',
      '수불제어는 ERP 함수(F_GET_RNDS_CNTR · F_GET_RNDS_CNTR_AUTO_RT)와 같은 규칙으로 계산합니다 (표본 421건 대조 일치).',
      '받는 매장은 자동 RT 취소 요청 → 마이너스 재고 → 기간 판매 많은 순으로 먼저 채웁니다.',
    ],
    where: ['재고 재배치 추천 > 매장 간 RT'],
    code: 'stock_rt.recommend',
  },
  {
    id: 'stock.alloc',
    group: 'stock',
    name: '창고 → 매장 배분 추천 (판매분 자동보충)',
    formula: [
      '창고 배분 가능 = 창고 재고(이번 달) − 오늘 이후 출고지시 미명세 − 오늘 이후 미확정 배분의뢰 − 창고재고하한',
      '후보 매장 = 정상 매장 · 등급 그룹에 매장등급 있음 · 기간 판매 있음 · 현재고 ≤ 매장재고상한 · 판매율 ≥ 최소판매율',
      '판매율(%) = 일반 판매 ÷ (현재고 + 기간 시작 시점 재고) × 100',
      '순서 = 유통형태(백화점 → 아울렛 → 직영점 → 대리점) · 판매율 높은 순 · 매장등급 · 등급 내 순위(리스트는 반대) · 최초판매일',
      '배분 = 1차 완불 수량, 2차 일반 판매 수량 — 각각 min(판매 × 배수, 매장재고상한 − 현재고 − 1차 배분, 창고 남은 수량)',
    ],
    source: 'T_SALE_SUPLM_BASE · _APLY · _XCLD · T_STYLE_PLAN · T_WH_STOCK_PRDT · T_DELV_INDC · T_DELV_ASK · T_SHOP_STOCK · T_SHOP_GRD_GRP_DETL',
    notes: [
      '[창고 부족] 탭의 [매장 간 RT 로 채우기]: 창고 부족 수량(− 이미 들어올 지시 · 요청)을 같은 RT 그룹 매장 재고로 채우는 매장 간 RT 를 자동 RT 규칙 · 순서로 추천하고, 관리자는 본사지시 RT 지시로 등록할 수 있습니다.',
      '창고 부족 = 필요(min(완불 + 판매, 매장재고상한 − 현재고)) − 배분. 필요보다 적게 받은 매장은 노란 행으로, [창고 부족] 탭에서 전혀 못 받은 매장까지 따로 봅니다.',
      '관리자는 배분을 골라 [배분의뢰 등록]으로 ERP 출고의뢰(T_DELV_ASK, 판매분의뢰(자동) · 미확정)에 넣습니다 — 의뢰일자 · 차수(확정된 차수는 불가) · 출고예정일을 고르고, 확정 · 출고지시는 ERP 에서 합니다. 이 화면에서 의뢰한 매장 × 상품은 다시 배분하지 않습니다.',
      '최근 판매분 자동보충 실행 조건(SS10DEV.T_AUTO_DVID_MASTER_HIST)을 불러와 같은 조건으로 미리 계산합니다. 오늘 아침 실행과 대조해 상품 목록 · 후보 매장 순서가 일치했습니다.',
      '오늘 이미 실행한 자동보충의 미확정 의뢰는 창고 가용에서 빠지므로, 실행 뒤에 보면 “추가로 더 보낼 수 있는 양”입니다.',
      '상품구분 · 제품상태 · 리오더 · 지역 · 매장형태 · 판매유형 · 물류반품기간 · 스타일그룹 조건은 쓰지 않습니다.',
    ],
    where: ['재고 재배치 추천 > 창고 → 매장 배분'],
    code: 'wh_alloc.recommend',
  },
]

export const helpById = (id: string) => HELP.find((h) => h.id === id)
