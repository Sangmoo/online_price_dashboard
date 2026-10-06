// 지표 정의 · 도움말 내용. 화면의 (?) 아이콘이 id 로 이 항목을 열고, 상단 [도움말] 은 전체를 보여준다.
// 계산식을 바꾸면 이 파일도 같이 고친다 (서버 계산 위치를 code 에 적어 둔다).

export type HelpGroup = 'online' | 'sales' | 'invt'

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
]

export const helpById = (id: string) => HELP.find((h) => h.id === id)
