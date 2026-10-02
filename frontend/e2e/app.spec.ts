// 주요 화면 흐름 자동 테스트: 로그인 · 메뉴 권한 · 판매 현황(조건·엑셀) · 월별 매장별 판매 집계 · 관리자 알림
import { expect, makeUser, test } from './mock'

// 테스트 전용 값 (실제 계정 아님, 가짜 API 로만 전송)
const TEST_ID = '900002'
const TEST_PW = 'e2e-only-password'

test('로그인: 사번·비밀번호를 보내고, 권한 있는 메뉴만 보인다', async ({ page, mockApi }) => {
  const api = await mockApi(null)
  const user = makeUser('USER', ['sale_dashboard'])
  api.on('POST', '/api/auth/login', () => ({ json: { user, sessionTtl: 3600 } }))

  await page.goto('/')
  await page.getByPlaceholder('사번 ID').fill(TEST_ID)
  await page.getByPlaceholder('비밀번호').fill(TEST_PW)
  await page.getByRole('button', { name: /로그인/ }).click()

  await expect(page.getByText('테스트사용자').first()).toBeVisible()
  expect(api.find('POST', '/api/auth/login')[0].body).toEqual({ id: TEST_ID, password: TEST_PW })
  const nav = page.locator('.side-nav')
  await expect(nav.getByText('판매 현황')).toBeVisible()
  await expect(nav.getByText('관리자')).toHaveCount(0)
  await expect(nav.getByText('월별 매장별 판매 집계')).toHaveCount(0)
})

test('로그인 실패 메시지를 보여준다', async ({ page, mockApi }) => {
  const api = await mockApi(null)
  api.on('POST', '/api/auth/login', () => ({ status: 401, json: { detail: { message: '사번 또는 비밀번호가 올바르지 않습니다.', code: 'LOGIN_FAILED' } } }))
  await page.goto('/')
  await page.getByPlaceholder('사번 ID').fill(TEST_ID)
  await page.getByPlaceholder('비밀번호').fill('wrong')
  await page.getByRole('button', { name: /로그인/ }).click()
  await expect(page.getByText('사번 또는 비밀번호가 올바르지 않습니다.')).toBeVisible()
})

test.describe('판매 현황', () => {
  test('핵심 지표·목표·브랜드·매장 순위를 보여주고 팀별 표는 없다', async ({ page, mockApi }) => {
    const api = await mockApi(makeUser('USER'))
      await page.goto('/?view=sale_dashboard')

    await expect(page.getByText('2026-08 실판금액')).toBeVisible()
    await expect(page.getByText('194.3억').first()).toBeVisible()
    await expect(page.locator('.kpi-label', { hasText: '목표 달성률' })).toBeVisible()
    await expect(page.getByText('81.2%')).toBeVisible()
    await expect(page.getByRole('heading', { name: '브랜드별' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '목표 달성률 하위 10' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '전년 동기 대비 성장 상위 10' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '팀별' })).toHaveCount(0)
    expect(api.find('GET', '/api/sale-dashboard')[0].query.toString()).toBe('') // 처음엔 서버 기본값(최근 마감 월)
  })

  test('기간·비교 기준·브랜드를 바꿔 [조회]하면 그 조건으로 요청한다', async ({ page, mockApi }) => {
    const api = await mockApi(makeUser('USER'))
      await page.goto('/?view=sale_dashboard')
    await expect(page.getByText('2026-08 실판금액')).toBeVisible()

    await page.getByLabel('시작 월').selectOption('202601')
    await page.getByLabel('비교 기준').selectOption('custom')
    await page.getByLabel('비교 시작 월').selectOption('202501')
    await page.getByLabel('비교 끝 월').selectOption('202508')
    await page.getByLabel('브랜드').selectOption('쉬즈미스')
    await expect(page.getByText('조건을 바꿨습니다')).toBeVisible()
    await page.getByRole('button', { name: '조회' }).click()

    await expect(page.getByText('2026-01~2026-08 실판금액')).toBeVisible()
    const q = api.find('GET', '/api/sale-dashboard').at(-1)!.query
    expect(Object.fromEntries(q)).toEqual({ ym: '202608', from: '202601', cmp: 'custom', cmpFrom: '202501', cmpTo: '202508', brand: '쉬즈미스' })
    await expect(page.getByRole('heading', { name: '직접 선택 대비 성장 상위 10' })).toBeVisible()
  })

  test('기간이 12개월을 넘으면 조회할 수 없다', async ({ page, mockApi }) => {
    const api = await mockApi(makeUser('USER'))
      await page.goto('/?view=sale_dashboard')
    await page.getByLabel('시작 월').selectOption('202501')
    await expect(page.getByText('기간은 최대 12개월입니다.')).toBeVisible()
    await expect(page.getByRole('button', { name: '조회' })).toBeDisabled()
  })

  test('보고용 엑셀은 조회한 조건으로 내려받는다', async ({ page, mockApi }) => {
    const api = await mockApi(makeUser('USER'))
    api.on('GET', '/api/sale-dashboard/export', () => ({
      body: Buffer.from('xlsx'),
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent('판매현황_202608_prev.xlsx')}`,
      },
    }))
      await page.goto('/?view=sale_dashboard')
    await page.getByLabel('비교 기준').selectOption('prev')
    await page.getByRole('button', { name: '조회' }).click()
    await expect(page.getByRole('heading', { name: '직전 기간 대비 성장 상위 10' })).toBeVisible()

    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /보고용 엑셀/ }).click()
    expect((await download).suggestedFilename()).toBe('판매현황_202608_prev.xlsx')
    expect(Object.fromEntries(api.find('GET', '/api/sale-dashboard/export')[0].query)).toEqual({ ym: '202608', from: '202608', cmp: 'prev' })
  })
})

test('월별 매장별 판매 집계: 처음 들어오면 지난달로 자동 조회하고 건수를 보여준다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_monthly']))
  api.on('GET', '/api/sale-monthly', () => ({
    json: { rows: [{ MAKE_YYMM: '202608', SHOP_ID: 'S41001', QTY: 3 }], summary: { rows: 1234, qty: 5678, realSaleAmt: 90_000_000 } },
  }))
  await page.goto('/?view=sale_monthly')

  await expect(page.getByText('1,234건').first()).toBeVisible()
  await expect(page.getByRole('cell', { name: 'S41001' })).toBeVisible()
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  const last = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  const q = api.find('GET', '/api/sale-monthly')[0].query
  expect([q.get('ymFrom'), q.get('ymTo'), q.get('page')]).toEqual([last, last, '1'])
  await expect(page.getByRole('button', { name: /엑셀 전체 \(1,234건\)/ })).toBeEnabled()
})

test('관리자: 새 마감 월이 들어오면 배너를 보여주고 AI 도구 탭으로 이동한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/data-freshness', () => ({
    json: { behind: true, mvMaxMonth: '202608', baseMaxMonth: '202609', lastRefresh: '2026-09-02 10:00:00', refreshing: false },
  }))
  api.on('GET', '/api/admin/ai-tools', () => ({ json: { storage: 'oracle', builtin: [], custom: [], pages: [], paramTypes: [], maxRowsLimit: 500 } }))
  api.on('GET', '/api/admin/data-status', () => ({
    json: {
      name: 'SS10.MV_CLOSE_SALE_SHOP_YM', usable: false, staleness: 'STALE', lastRefresh: '2026-09-02 10:00:00', mvMaxMonth: '202608',
      baseMaxMonth: '202609', rows: 24000, hasCostColumn: true, behind: true,
      refresh: { status: 'idle', started: null, finished: null, by: null, error: null, elapsedSec: null },
    },
  }))
  await page.goto('/')

  const banner = page.locator('.fresh-warn')
  await expect(banner).toContainText('새 마감 월 2026-09')
  await banner.getByRole('button', { name: '갱신하러 가기' }).click()
  await expect(page.locator('.admin-tab.active')).toHaveText(/AI 도구/)
  await expect(page.getByRole('button', { name: /지금 갱신/ })).toBeVisible()
})

test('일반 사용자에게는 관리자 알림을 요청하지 않는다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER'))
  await page.goto('/?view=sale_dashboard')
  await expect(page.getByText('2026-08 실판금액')).toBeVisible()
  expect(api.find('GET', '/api/admin/data-freshness')).toHaveLength(0)
  await expect(page.locator('.fresh-warn')).toHaveCount(0)
})

test('관리자: 서버 상태 탭에서 요약을 보고 로그 보관 기간을 저장한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '' } }))
  api.on('GET', '/api/admin/server-status', (_, url) => ({
    json: {
      days: Number(url.searchParams.get('days')), since: '2026-09-22 16:00:00',
      server: { startedAt: '2026-09-29 09:00:00', uptimeSec: 3 * 3600 + 120, pid: 1234 },
      pool: { opened: 3, busy: 1, max: 10 },
      requests: { count: 563, errors5xx: 0, slow: 1, avgMs: 245, p95Ms: 1797, slowSec: 5, slowPaths: [{ path: '/api/sale-monthly', count: 1, maxMs: 8986 }] },
      slowSql: { count: 2, thresholdSec: 3, top: [{ sql: 'SELECT 1 FROM T_CLOSE_SALE_BASE', count: 2, avgSec: 4, maxSec: 4.5, last: '2026-09-29 10:00:00' }] },
      sqlErrors: { count: 0, recent: [] }, errors: { count: 0, recent: [] },
      daily: [{ day: '2026-09-28', requests: 100, errors: 0, slowSql: 1 }, { day: '2026-09-29', requests: 463, errors: 0, slowSql: 1 }],
      supervisor: { running: true, crashRestarts: 1, deployRestarts: 2, events: [{ ts: '2026-09-29 14:40:00', kind: 'crash', message: '서버 재시작 예정: 응답 없음(멈춤)' }] },
      disk: { logsBytes: 5 * 1024 ** 2, exportsBytes: 0, freeBytes: 100 * 1024 ** 3, totalBytes: 500 * 1024 ** 3, logFiles: 4, oldestLog: '2026-09-23' },
      keepDays: 7,
    },
  }))
  api.on('PUT', '/api/admin/settings', () => ({ json: { logKeepDays: 14 } }))
  await page.goto('/?view=admin')
  await page.getByRole('button', { name: '서버 상태' }).click()

  await expect(page.getByText('3시간 2분')).toBeVisible()
  await expect(page.locator('.status-card.warn', { hasText: '자동 재시작' })).toContainText('1회')
  await expect(page.getByText('SELECT 1 FROM T_CLOSE_SALE_BASE')).toBeVisible()
  expect(api.find('GET', '/api/admin/server-status')[0].query.get('days')).toBe('7')

  await page.getByRole('button', { name: '30일' }).click()
  await expect.poll(() => api.find('GET', '/api/admin/server-status').at(-1)!.query.get('days')).toBe('30')

  await page.locator('.keep-row input').fill('14')
  await page.getByRole('button', { name: '저장' }).click()
  await expect(page.getByText('로그 보관 기간을 14일로 저장했습니다')).toBeVisible()
  expect(api.find('PUT', '/api/admin/settings')[0].body).toEqual({ logKeepDays: 14 })
})

test('관리자 화면을 열어만 두면 1시간 뒤 로그아웃된다 (자동 확인 요청은 세션을 연장하지 않음)', async ({ page, mockApi }) => {
  await page.clock.install()
  const admin = makeUser('ADMIN')
  admin.sessionExpiresAt = Math.floor(Date.now() / 1000) + 3600
  const api = await mockApi(admin)
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '' } }))
  await page.goto('/?view=admin')
  await expect(page.getByText('테스트관리자').first()).toBeVisible()

  await page.clock.runFor('56:00') // 10분마다 자동 확인이 여러 번 온다
  const polls = api.find('GET', '/api/admin/data-freshness')
  expect(polls.length).toBeGreaterThan(3)
  expect(polls.every((c) => c.headers['x-background'] === '1')).toBe(true)
  await expect(page.getByText('후 자동 로그아웃됩니다')).toBeVisible() // 만료 5분 전 경고

  await page.clock.runFor('05:00')
  await expect(page.getByText('1시간 동안 사용하지 않아 로그아웃되었습니다.')).toBeVisible()
  await expect(page.getByPlaceholder('사번 ID')).toBeVisible()
})

const adminUser = (brands: string[] | null) => ({
  id: '170046', name: '홍길동', role: 'USER', superAdmin: false, active: true, pages: ['sale_dashboard'], brands,
  ai: { enabled: true, globalEnabled: true, userEnabled: true, dailyQuestions: 10, dailyCostUsd: 2, customLimits: false },
  rawAiEnabled: true, rawDailyQuestions: null, rawDailyCostUsd: null, lastLoginAt: null, createdAt: '2026-09-01 10:00:00',
  updatedAt: null, updatedBy: null, todayQuestions: 0, todayCostUsd: 0, online: false,
})

test('관리자: 사용자 브랜드 권한을 바꾸면 선택한 브랜드로 저장한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/users', () => ({
    json: { users: [adminUser(null)], pages: [], superAdminId: '250016', brandOptions: ['리스트', '쉬즈미스', '시스티나'], brandReady: true },
  }))
  api.on('PUT', '/api/admin/users/170046', (req) => ({ json: { user: adminUser((req.postDataJSON() as { brands: string[] | null }).brands) } }))
  await page.goto('/?view=admin')
  const row = page.getByRole('row', { name: /홍길동/ })
  await expect(row).toContainText('모든 브랜드')
  await row.getByRole('button', { name: '설정' }).nth(1).click()
  await page.getByRole('button', { name: '리스트' }).click()
  await page.getByRole('button', { name: '시스티나' }).click()
  await page.getByRole('button', { name: '저장' }).click()
  await expect(row).toContainText('리스트, 시스티나')
  expect(api.find('PUT', '/api/admin/users/170046')[0].body).toEqual({ brands: ['리스트', '시스티나'] })
})

test('메뉴를 열면 이용 기록을 보내고, 관리자는 메뉴 이용 통계를 본다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '', brandOptions: [], brandReady: false } }))
  api.on('GET', '/api/admin/menu-usage', (_, url) => ({
    json: {
      days: Number(url.searchParams.get('days')), since: '2026-09-02', storage: 'oracle', unusedGrants: 1,
      pages: [
        { page: 'sale_dashboard', label: '판매 현황', opens: 42, users: 3, grantedUsers: 4, activeDays: 20, last: '2026-10-01 09:00' },
        { page: 'invt_plan', label: '매장 재고 실사계획', opens: 0, users: 0, grantedUsers: 1, activeDays: 0, last: null },
      ],
      users: [{ id: '170046', name: '홍길동', active: true, lastLoginAt: null, opens: 42, unusedPages: ['invt_plan'],
                cells: { sale_dashboard: { granted: true, opens: 42, days: 20, last: '2026-10-01 09:00' },
                         invt_plan: { granted: true, opens: 0, days: 0, last: null } } }],
      daily: [{ day: '2026-09-30', opens: 20 }, { day: '2026-10-01', opens: 22 }],
    },
  }))
  await page.goto('/?view=sale_dashboard')
  await expect(page.getByText('2026-08 실판금액')).toBeVisible()
  await page.locator('.side-nav').getByText('관리자').click()
  await page.getByRole('button', { name: '메뉴 이용' }).click()
  await expect(page.getByRole('row', { name: /판매 현황 42/ })).toContainText('75%') // 이용자 3 / 권한 4
  await expect(page.getByRole('row', { name: /홍길동/ })).toContainText('미사용')
  expect(api.find('POST', '/api/usage/menu').map((c) => (c.body as { page: string }).page)).toEqual(['sale_dashboard', 'admin'])
  expect(api.find('GET', '/api/admin/menu-usage')[0].query.get('days')).toBe('30')
})

test('판매 현황에서 매장을 누르면 매장 정보·담당 영업직원·목표 대비 판매 추이를 보여준다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER'))
  const months = Array.from({ length: 12 }, (_, i) => {
    const d = new Date(2025, 9 + i, 1)
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  api.on('GET', '/api/sale-dashboard/shops/S41001/trend', () => ({
    json: {
      shopId: 'S41001', shopNm: '테스트매장1', from: months[0], to: months[11],
      months: months.map((m) => ({ ym: m, qty: 100, amt: 200_000_000, prevQty: 90, prevAmt: 180_000_000, growth: 11.1 })),
      total: { qty: 1200, amt: 2_400_000_000, prevQty: 1080, prevAmt: 2_160_000_000, growth: 11.1 },
    },
  }))
  api.on('GET', '/api/shops/S41001/profile', () => ({
    json: {
      shop: { shopId: 'S41001', shopNm: '테스트매장1', status: '정상', teamNm: '쉬즈4팀', repId: '230038', repNm: '양성규', openDt: '2014-09-05',
              closeDt: null, brands: [{ brdCd: 'S', brand: '쉬즈미스' }], addr: '서울 영등포구', tel: '02-123-4567', found: true },
      goals: Object.fromEntries(months.map((m) => [m, 250_000_000])),
    },
  }))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: '테스트매장1' }).click()
  const modal = page.locator('.trend-modal')
  await expect(modal).toContainText('양성규')
  await expect(modal).toContainText('쉬즈미스 · 쉬즈4팀')
  await expect(modal.locator('.shop-status')).toHaveText('정상')
  await expect(modal.getByRole('columnheader', { name: '달성률' })).toBeVisible()
  await expect(modal.locator('.pill', { hasText: '목표 달성률' })).toContainText('80%')
  await expect(modal).not.toContainText('현재 매니저') // 실사계획 권한이 없으면 실사·매니저 정보 없음
})

test('판매 현황에 할인율을 보여준다', async ({ page, mockApi }) => {
  await mockApi(makeUser('USER'))
  await page.goto('/?view=sale_dashboard')
  const card = page.locator('.sd-kpi', { hasText: '할인율' })
  await expect(card).toContainText('3.1%')
  await expect(card).toContainText('-0.7%p')
  await expect(page.locator('.sd-table').first().getByRole('columnheader', { name: '할인율' })).toBeVisible()
})

test('AI 답변의 도구 표시를 누르면 조회 조건(답변 근거)을 펼쳐 보여준다', async ({ page, mockApi }) => {
  const user = makeUser('USER', ['sale_dashboard'])
  user.ai = { ...user.ai, enabled: true, userEnabled: true, dailyQuestions: 10, dailyCostUsd: 2 }
  const api = await mockApi(user)
  const events = [
    { type: 'conversation', id: 'c1', title: '지난달 판매' },
    { type: 'tool', id: 't1', name: 'get_sales_dashboard', label: '판매 현황',
      input: { ym: '202608', compare: 'prev', brand: '쉬즈미스', sections: ['kpi', 'brands'] } },
    { type: 'tool_done', id: 't1', ok: true },
    { type: 'text_start' },
    { type: 'text', text: '2026-08 쉬즈미스 실판금액은 98.3억입니다.' },
    { type: 'done' },
  ]
  api.on('GET', '/api/chat/usage', () => ({ json: { questions: 0, costUsd: 0, inputTokens: 0, outputTokens: 0, questionLimit: 10, costLimitUsd: 2, enabled: true } }))
  api.on('POST', '/api/chat', () => ({
    body: Buffer.from(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')),
    headers: { 'Content-Type': 'text/event-stream' },
  }))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: 'AI 데이터 어시스턴트' }).click()
  await page.getByPlaceholder(/데이터에 대해 질문하세요/).fill('지난달 쉬즈미스 판매 알려줘')
  await page.keyboard.press('Enter')
  await expect(page.getByText('98.3억입니다')).toBeVisible()
  const chip = page.getByRole('button', { name: /판매 현황/ }).filter({ has: page.locator('svg') }).last()
  await chip.click()
  const basis = page.locator('.tool-args')
  await expect(basis).toContainText('get_sales_dashboard')
  await expect(basis).toContainText('기준 월')
  await expect(basis).toContainText('2026-08')
  await expect(basis).toContainText('직전 기간')
  await expect(basis).toContainText('쉬즈미스')
  await expect(basis).toContainText('kpi, brands')
})

test('판매 현황 아래에 판매형태 구성·상품 순위·아이템 비교를 보여주고, 품번을 누르면 온라인 가격과 매장 판매를 비교한다', async ({ page, mockApi }) => {
  const user = makeUser('USER', ['dashboard', 'sale_dashboard'])
  const api = await mockApi(user)
  api.on('GET', '/api/products/TSJTSP62050/insight', () => ({
    json: {
      prdtCd: 'TSJTSP62050',
      online: { title: '리스트 코튼 레터링 반팔 티셔츠', lastDt: '20260930',
                daily: [{ dt: '20260901', avgDcRate: 50.7, maxDcRate: 60, minDcPrice: 13760, price: 40000, malls: 10, rows: 20 },
                        { dt: '20260930', avgDcRate: 56.9, maxDcRate: 64.5, minDcPrice: 14190, price: 40000, malls: 9, rows: 26 }],
                malls: [{ mallNm: '옥션', dcPrice: 14190, price: 40000, dcRate: 64.5 }] },
      sales: { itemNm: '티셔츠', prdtGrpNm: 'JERSEY', source: '사전 집계 뷰',
               months: [{ ym: '202604', amt: 3_411_200, qty: 75, dsctRate: 5.6 }, { ym: '202605', amt: 3_257_300, qty: 74, dsctRate: 6.4 },
                        { ym: '202606', amt: 2_103_610, qty: 52, dsctRate: 5.7 }, { ym: '202607', amt: 1_857_200, qty: 50, dsctRate: 2.8 },
                        { ym: '202608', amt: 880_700, qty: 25, dsctRate: 8.3 }, { ym: '202609', amt: 278_500, qty: 5, dsctRate: 0.5 }] },
    },
  }))
  await page.goto('/?view=sale_dashboard')
  await expect(page.getByRole('heading', { name: '판매형태 구성' })).toBeVisible()
  await expect(page.getByRole('row', { name: /^세일/ }).first()).toContainText('+8.5%p')
  await page.getByRole('button', { name: '수량' }).click()
  await expect(page.getByRole('button', { name: 'SWWSTQ32150' })).toBeVisible()
  await page.getByRole('button', { name: '실판금액' }).click()
  await page.getByRole('button', { name: '품군' }).click()
  await expect(page.getByRole('cell', { name: '우븐', exact: true })).toBeVisible()
  expect(Object.fromEntries(api.find('GET', '/api/sale-dashboard/products')[0].query)).toEqual({ ym: '202608', from: '202608', cmp: 'yoy' })

  await page.getByRole('button', { name: 'TSJTSP62050' }).click()
  const modal = page.locator('.product-modal')
  await expect(modal).toContainText('온라인 평균 할인율 50.7% → 56.9%')
  await expect(modal).toContainText('매장 판매 최근 3개월 80개')
  await expect(modal).toContainText('옥션')
})

test('관리자: 설정 백업 파일을 고르면 바뀌는 내용을 보여주고, 선택한 항목만 복원한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '', brandOptions: [], brandReady: true } }))
  api.on('POST', '/api/admin/restore/preview', () => ({
    json: {
      file: { createdAt: '2026-10-01 10:00:00', createdBy: '250016' },
      users: { added: [{ id: '170047', name: '나신입' }], changed: [{ id: '170046', name: '홍길동', diff: { brands: { before: null, after: ['리스트'] } } }],
               same: 3, notInFile: [], skipped: [{ id: '250016', name: '최고', reason: '최고 관리자는 복원하지 않음' }] },
      settings: { changed: [{ key: 'defaultDailyQuestions', before: 10, after: 20 }] },
      aiTools: { builtinChanged: [], customAdded: [], customChanged: [] },
    },
  }))
  api.on('POST', '/api/admin/restore/apply', () => ({ json: { applied: ['사용자 추가 나신입(170047)', '사용자 변경 홍길동(170046)'], failed: [] } }))
  page.on('dialog', (d) => d.accept())
  await page.goto('/?view=admin')
  await page.getByRole('button', { name: '설정 백업' }).click()
  await page.locator('input[type=file]').setInputFiles({ name: 'backup.json', mimeType: 'application/json', buffer: Buffer.from('{"app":"erp-sales-web","version":1}') })
  await expect(page.locator('.restore-preview')).toContainText('브랜드: 기본/전체 → 리스트')
  await expect(page.locator('.restore-preview')).toContainText('기본 질문 한도: 10 → 20')
  await page.locator('.restore-section', { hasText: '전역 설정' }).locator('input').uncheck()
  await page.getByRole('button', { name: '선택한 항목 복원' }).click()
  await expect(page.getByText('적용 2건 · 실패 0건')).toBeVisible()
  expect(api.find('POST', '/api/admin/restore/apply')[0].body).toEqual({ data: { app: 'erp-sales-web', version: 1 }, sections: ['users'] })
})

test('관리자: AI 사용 설정에서 모델 자동 선택을 켜고 단순 조회용 모델을 저장한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  const settings = {
    aiEnabled: true, defaultDailyQuestions: 10, defaultDailyCostUsd: 2, model: 'claude-opus-5', effort: 'medium',
    models: ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'], efforts: ['low', 'medium', 'high'], envModel: 'claude-opus-5',
    envEffort: 'medium', logKeepDays: 7, autoModel: false, simpleModel: 'claude-haiku-4-5',
  }
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '', brandOptions: [], brandReady: true } }))
  api.on('GET', '/api/admin/settings', () => ({ json: settings }))
  api.on('PUT', '/api/admin/settings', (req) => ({ json: { ...settings, ...(req.postDataJSON() as object) } }))
  await page.goto('/?view=admin')
  await page.getByRole('button', { name: 'AI 사용 설정' }).click()
  const row = page.locator('.setting-row', { hasText: '질문에 따라 모델 자동 선택' })
  await row.getByRole('switch').click()
  await page.locator('.setting-row', { hasText: '단순 조회용 모델' }).locator('select').selectOption('claude-sonnet-5')
  await page.getByRole('button', { name: '저장' }).click()
  await expect(page.getByText('AI 설정을 저장했습니다.')).toBeVisible()
  const body = api.find('PUT', '/api/admin/settings')[0].body as Record<string, unknown>
  expect([body.autoModel, body.simpleModel]).toEqual([true, 'claude-sonnet-5'])
})

test('판매 현황: 시즌 판매 진척과 온라인 할인 주의 상품을 보여주고, 시즌을 바꾸면 그 시즌으로 요청한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['dashboard', 'sale_dashboard']))
  await page.goto('/?view=sale_dashboard')
  const season = page.locator('.season-panel')
  await expect(season).toContainText('시즌 판매 진척')
  await expect(season.locator('.season-kpi', { hasText: '전년 시즌 최종 대비 진척' })).toContainText('90.2%')
  await expect(season.locator('.season-kpi', { hasText: '누적 실판금액' })).toContainText('+5.8%')
  await season.getByRole('combobox', { name: '시즌' }).selectOption('2026 가을')
  await expect.poll(() => api.find('GET', '/api/sale-dashboard/season').map((c) => Object.fromEntries(c.query)).pop())
    .toEqual({ ym: '202608', planYy: '2026', season: '가을' })

  const alerts = page.locator('.online-alert-panel')
  await expect(alerts.locator('.count-badge')).toHaveText('1')
  await expect(alerts.getByRole('row', { name: /SWWJPQ33010/ })).toContainText('+4.5%p')
  await expect(alerts.getByRole('button', { name: 'AWWJKQ31030' })).toHaveCount(0) // 주의만
  await alerts.getByRole('button', { name: /상위 2개 전체/ }).click()
  await expect(alerts.getByRole('button', { name: 'AWWJKQ31030' })).toBeVisible()
})

test('온라인 가격 메뉴 권한이 없으면 온라인 할인 주의 상품을 요청하지 않는다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  await page.goto('/?view=sale_dashboard')
  await expect(page.locator('.season-panel')).toBeVisible()
  await expect(page.locator('.online-alert-panel')).toHaveCount(0)
  expect(api.find('GET', '/api/sale-dashboard/online-alerts')).toHaveLength(0)
})

test('상품 팝업에 많이 팔린 매장·팀, 매장 팝업에 판매형태 구성·주력 아이템을 보여준다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  api.on('GET', '/api/products/TWWJKQ72020/insight', () => ({
    json: {
      prdtCd: 'TWWJKQ72020',
      sales: { itemNm: '자켓', prdtGrpNm: '우븐', source: '사전 집계 뷰', months: [{ ym: '202608', amt: 112_422_100, qty: 581, dsctRate: 2.7 }] },
      shops: { from: '202606', to: '202608', shopCount: 93, qty: 1838, amt: 340_000_000, topShare: 37.9,
               shops: [{ shopId: 'T34606', shopNm: '현대아울렛대전', team: '리스트3팀', qty: 115, amt: 21_746_800, share: 6.4, dsctRate: 2.4 }],
               teams: [{ team: '리스트3팀', brand: '리스트', qty: 902, amt: 168_308_440, shops: 83 }] },
    },
  }))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: 'TWWJKQ72020' }).click()
  const modal = page.locator('.product-modal')
  await expect(modal).toContainText('많이 팔린 매장')
  await expect(modal).toContainText('현대아울렛대전')
  await expect(modal).toContainText('상위 1개 매장이 실판금액의 37.9%')
  await expect(modal.getByRole('row', { name: /리스트3팀 리스트/ })).toContainText('49.1%')
  await modal.getByRole('button').first().click()

  api.on('GET', '/api/sale-dashboard/shops/S41001/trend', () => ({
    json: { shopId: 'S41001', shopNm: '테스트매장1', from: '202510', to: '202609', months: [], total: { qty: 0, amt: 0, prevQty: 0, prevAmt: 0, growth: null } },
  }))
  api.on('GET', '/api/shops/S41001/profile', () => ({
    json: {
      shop: { shopId: 'S41001', shopNm: '테스트매장1', status: '정상', teamNm: '쉬즈4팀', repId: null, repNm: null, openDt: null, closeDt: null,
              brands: [], addr: null, tel: null, found: true },
      mix: { from: '202510', to: '202609', brand: '쉬즈미스', amt: 2_192_109_390, brandAvg: true, itemCount: 12,
             salesTypes: [{ name: '세일', amt: 704_759_900, qty: 5571, share: 32.1, dsctRate: 1.6, brandShare: 23.7, shareDiff: 8.4 }],
             items: [{ name: '자켓', amt: 587_999_900, qty: 3400, share: 26.8, dsctRate: 2.5 }] },
    },
  }))
  await page.getByRole('button', { name: '테스트매장1' }).click()
  const shop = page.locator('.trend-modal').last()
  await expect(shop).toContainText('판매 구성')
  await expect(shop.getByRole('row', { name: /세일/ })).toContainText('+8.4%p')
  await expect(shop).toContainText('주력 아이템 (상위 1/12)')
})

test('문의·신고: 현재 화면과 조회 조건을 붙여 보내고, 관리자는 상태와 답변을 저장한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  const saved = { id: '20261002101500AB12', userId: 'TEST01', userName: '테스트', type: 'BUG', typeLabel: '오류', content: '숫자가 이상합니다',
                  page: 'sale_dashboard', context: { page: '판매 현황', conditions: { ym: '202608' }, errors: [] }, status: 'NEW', statusLabel: '접수',
                  answer: null, answerBy: null, answeredAt: null, createdAt: '2026-10-02 10:15', updatedAt: null, files: [] as unknown[] }
  api.on('POST', '/api/feedback', () => ({ json: saved }))
  await page.goto('/?view=sale_dashboard')
  await expect(page.locator('.sd-kpi').first()).toBeVisible()
  await page.getByRole('button', { name: '문의·신고' }).click()
  const modal = page.locator('.feedback-modal')
  const box = modal.getByRole('textbox', { name: '내용' })
  expect((await box.boundingBox())!.height).toBeGreaterThanOrEqual(280) // 넓은 입력 칸
  await box.fill('숫자가 이상합니다')
  const png = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000', 'hex')
  await modal.locator('input[type=file]').setInputFiles([
    { name: 'a.png', mimeType: 'image/png', buffer: png }, { name: 'b.png', mimeType: 'image/png', buffer: png },
    { name: 'c.png', mimeType: 'image/png', buffer: png }, { name: 'd.png', mimeType: 'image/png', buffer: png },
  ])
  await expect(modal.locator('.fb-thumb')).toHaveCount(3) // 최대 3개
  await expect(modal).toContainText('최대 3개까지라 1개는 빼었습니다')
  await modal.getByRole('button', { name: 'c.png 빼기' }).click()
  await expect(modal.getByRole('button', { name: /이미지 첨부 \(2\/3\)/ })).toBeVisible()
  await modal.getByRole('button', { name: '보내기' }).click()
  await expect(modal).toContainText('접수되었습니다 (번호 20261002101500AB12)')
  const body = api.find('POST', '/api/feedback')[0].body as { type: string; page: string; context: { page: string; conditions: Record<string, string> } }
  expect(body.type).toBe('BUG')
  expect(body.page).toBe('sale_dashboard')
  expect(body.context.page).toBe('판매 현황')
  expect(body.context.conditions.ym).toBe('202608')
  expect((body as unknown as { images: { name: string; data: string }[] }).images.map((i) => i.name)).toEqual(['a.png', 'b.png'])
  expect((body as unknown as { images: { data: string }[] }).images[0].data).toMatch(/^data:image\/png;base64,iVBORw0KGgo/)
  await modal.getByRole('button', { name: '닫기' }).first().click()

  api.on('GET', '/api/admin/feedback', () => ({ json: { rows: [saved], counts: { NEW: 1, DOING: 0, DONE: 0 }, storage: 'oracle', images: { count: 4, bytes: 3_145_728 } } }))
  api.on('GET', '/api/admin/settings', () => ({ json: { feedbackImageKeepMonths: 12 } }))
  api.on('PUT', '/api/admin/settings', () => ({ json: { feedbackImageKeepMonths: 6 } }))
  api.on('PUT', '/api/admin/feedback/20261002101500AB12', () => ({ json: { ...saved, status: 'DONE', answer: '수정했습니다' } }))
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '', brandOptions: [], brandReady: false } }))
  await page.locator('.side-nav').getByText('관리자').click()
  await page.locator('.admin-tabs').getByRole('button', { name: '문의·신고' }).click()
  const row = page.locator('.feedback-admin-row')
  await expect(row).toContainText('숫자가 이상합니다')
  await row.getByRole('combobox', { name: '상태' }).selectOption('DONE')
  await row.getByPlaceholder(/답변/).fill('수정했습니다')
  await row.getByRole('button', { name: '저장' }).click()
  await expect.poll(() => api.find('PUT', '/api/admin/feedback/20261002101500AB12').length).toBe(1)
  await expect(page.locator('.fb-keep')).toContainText('이미지 4개 · 3.0MB')
  await page.getByRole('spinbutton', { name: '이미지 보관 개월' }).fill('6')
  await page.locator('.fb-keep').getByRole('button', { name: '저장' }).click()
  await expect.poll(() => api.find('PUT', '/api/admin/settings').length).toBe(1)
  expect(api.find('PUT', '/api/admin/settings')[0].body).toEqual({ feedbackImageKeepMonths: 6 })
  expect(api.find('PUT', '/api/admin/feedback/20261002101500AB12')[0].body).toEqual({ status: 'DONE', answer: '수정했습니다' })
})

test('문의·신고 배지: 사용자는 새 답변, 관리자는 미처리 건수를 본다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER'))
  api.on('GET', '/api/feedback/badge', () => ({ json: { newAnswers: 2, open: null } }))
  await page.goto('/?view=sale_dashboard')
  await expect(page.getByRole('button', { name: /문의·신고/ })).toContainText('새 답변 2')
  expect(api.find('GET', '/api/feedback/badge')[0].headers['x-background']).toBe('1') // 주기 확인은 세션 연장 안 함
})

test('관리자: 사이드바와 탭에 미처리 문의 건수를 보여준다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/feedback/badge', () => ({ json: { newAnswers: 0, open: 3 } }))
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '', brandOptions: [], brandReady: false } }))
  await page.goto('/?view=sale_dashboard')
  await expect(page.locator('.side-nav .side-item', { hasText: '관리자' }).locator('.count-badge')).toHaveText('3')
  await page.locator('.side-nav').getByText('관리자').click()
  await expect(page.locator('.admin-tabs').getByRole('button', { name: /문의·신고/ }).locator('.count-badge')).toHaveText('3')
})

test('판매 현황: 시즌 진척 아이템별 보기, 세일 비중 높은 매장', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER'))
  api.on('GET', '/api/sale-dashboard/season/items', () => ({
    json: { items: [{ name: '가디건', amt: 1_180_970_200, qty: 12908, prevSameAmt: 717_786_981, prevFinalAmt: 989_656_750, change: 64.5,
                      progress: 119.3, prevProgressSame: 72.5, share: 9.4 }] },
  }))
  await page.goto('/?view=sale_dashboard')
  const season = page.locator('.season-panel')
  await season.getByRole('button', { name: '아이템별 보기' }).click()
  await expect(season.getByRole('row', { name: /가디건/ })).toContainText('119.3%')
  expect(Object.fromEntries(api.find('GET', '/api/sale-dashboard/season/items')[0].query)).toEqual({ ym: '202608', planYy: '2026', season: '여름' })

  const heavy = page.locator('.sale-heavy-panel')
  await expect(heavy.locator('.pill', { hasText: '리스트 평균' })).toContainText('37.9%')
  await expect(heavy.getByRole('row', { name: /신세계의정부/ })).toContainText('+44.5%p')
  await heavy.getByRole('checkbox', { name: /행사·특판 매장 포함/ }).check()
  await expect.poll(() => api.find('GET', '/api/sale-dashboard/sale-heavy-shops').some((c) => c.query.get('includeEvent') === 'true')).toBe(true)
})

test('상품 팝업: 같은 아이템 품번 사이 순위를 보여주고, 다른 품번을 누르면 그 품번으로 바뀐다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER'))
  const insight = (cd: string, rank: number) => ({
    json: {
      prdtCd: cd,
      sales: { itemNm: '자켓', prdtGrpNm: '우븐', source: '사전 집계 뷰', months: [{ ym: '202608', amt: 1, qty: 1, dsctRate: 0 }] },
      siblings: { planYy: '2026', season: '가을기획', itemNm: '자켓', brand: '리스트', count: 19, rank, topPct: 10.5, avgQty: 577,
                  rows: [{ prdtCd: 'TWSJKQ72010', prdtGrpNm: 'SUIT', qty: 1933, amt: 365_273_900, dsctRate: 0.4, from: '202606', to: '202609', rank: 1 },
                         { prdtCd: 'TWWJKQ72020', prdtGrpNm: '우븐', qty: 1838, amt: 340_719_340, dsctRate: 2.0, from: '202607', to: '202609', rank: 2 }] },
    },
  })
  api.on('GET', '/api/products/TWWJKQ72020/insight', () => insight('TWWJKQ72020', 2))
  api.on('GET', '/api/products/TWSJKQ72010/insight', () => insight('TWSJKQ72010', 1))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: 'TWWJKQ72020' }).first().click()
  const modal = page.locator('.product-modal')
  await expect(modal).toContainText('같은 아이템 비교 · 리스트 2026 가을기획 자켓')
  await expect(modal).toContainText('19개 품번 중 수량 2위')
  await modal.getByRole('button', { name: 'TWSJKQ72010' }).click()
  await expect(modal).toContainText('19개 품번 중 수량 1위')
  expect(api.find('GET', '/api/products/TWSJKQ72010/insight')).toHaveLength(1)
})

test('관리자: AI 사용 현황에서 도구별 호출·오류·응답 시간을 본다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/users', () => ({ json: { users: [], pages: [], superAdminId: '', brandOptions: [], brandReady: false } }))
  api.on('GET', '/api/admin/usage', () => ({ json: { since: '2026-09-03', days: 30, total: { questions: 2, cost: 0.24, input_tokens: 1, output_tokens: 1, users: 1 }, daily: [], byUser: [], byModel: [], storage: 'oracle' } }))
  api.on('GET', '/api/admin/ai-tool-stats', () => ({
    json: { days: 30, since: '2026-09-26', keepDays: 7, questions: 2, models: { 'claude-opus-5': 2 }, routes: { off: 2 }, modelSwitches: 0,
            tools: [{ name: 'aggregate_sales', label: '판매 집계', calls: 4, ok: 2, inputErrors: 2, failures: 0, errorRate: 50, avgSec: 19.1, p95Sec: 32,
                      maxSec: 32, users: 1, last: '2026-09-29 13:46:06', topErrors: [{ message: 'ym_from 은 N 형식', count: 2 }] }],
            unusedTools: [{ name: 'get_season_progress', label: '시즌 판매 진척' }] },
  }))
  await page.goto('/?view=sale_dashboard')
  await page.locator('.side-nav').getByText('관리자').click()
  await page.locator('.admin-tabs').getByRole('button', { name: 'AI 사용 현황' }).click()
  const card = page.locator('.ai-tool-stats')
  await expect(card.getByRole('row', { name: /판매 집계/ })).toContainText('50%')
  await expect(card).toContainText('ym_from 은 N 형식 (2)')
  await expect(card).toContainText('로그 보관 기간이 7일이라')
  await expect(card).toContainText('쓰이지 않은 기본 도구: 시즌 판매 진척')
})
