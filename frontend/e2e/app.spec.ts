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
