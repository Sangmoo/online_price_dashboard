// 화면 테스트용 가짜 서버 API. 모든 /api 요청을 여기서 응답하고, 정의되지 않은 요청은 404 로 막아
// 실제 서버(포트 8000)로 새어 나가지 않게 한다. 요청 기록(calls)으로 화면이 보낸 조건을 검사한다.
import { expect, test as base, type Page, type Request } from '@playwright/test'

export type Call = { method: string; path: string; query: URLSearchParams; body: unknown; headers: Record<string, string> }
type Reply = { status?: number; json?: unknown; body?: Buffer; headers?: Record<string, string> }
type Handler = (req: Request, url: URL) => Reply | Promise<Reply>

const ALL_PAGES = ['dashboard', 'detail', 'sale_dashboard', 'sale_monthly', 'invt_plan', 'admin']

export function makeUser(role: 'ADMIN' | 'USER', pages: string[] = role === 'ADMIN' ? ALL_PAGES : ['sale_dashboard', 'sale_monthly']) {
  return {
    id: role === 'ADMIN' ? '900001' : '900002',
    name: role === 'ADMIN' ? '테스트관리자' : '테스트사용자',
    role,
    superAdmin: false,
    active: true,
    pages,
    ai: { enabled: false, globalEnabled: true, userEnabled: false, dailyQuestions: 0, dailyCostUsd: 0, customLimits: false },
    sessionExpiresAt: Math.floor(Date.now() / 1000) + 3600,
  }
}

const usage = { questions: 0, costUsd: 0, inputTokens: 0, outputTokens: 0, questionLimit: 0, costLimitUsd: 0, enabled: false }

const shop = (i: number, extra: Record<string, unknown> = {}) => ({
  shopId: `S4100${i}`, shopNm: `테스트매장${i}`, brand: '쉬즈미스', team: '쉬즈1팀', amt: 300_000_000 - i * 10_000_000,
  baseAmt: 250_000_000, change: 12.3 - i, costRate: 30.1, goalAmt: 320_000_000, achieve: 90 - i, closed: false, ...extra,
})

export function dashboardData(q: URLSearchParams) {
  const to = q.get('ym') || '202608'
  const from = q.get('from') || to
  const kind = (q.get('cmp') || 'yoy') as 'yoy' | 'prev' | 'custom'
  const brand = q.get('brand') || null
  const kindLabel = { yoy: '전년 동기', prev: '직전 기간', custom: '직접 선택' }[kind]
  const baseFrom = kind === 'custom' ? q.get('cmpFrom')! : kind === 'prev' ? '202607' : `${Number(from.slice(0, 4)) - 1}${from.slice(4)}`
  const baseTo = kind === 'custom' ? q.get('cmpTo')! : kind === 'prev' ? '202607' : `${Number(to.slice(0, 4)) - 1}${to.slice(4)}`
  const label = (f: string, t: string) => (f === t ? `${f.slice(0, 4)}-${f.slice(4)}` : `${f.slice(0, 4)}-${f.slice(4)}~${t.slice(0, 4)}-${t.slice(4)}`)
  const months = Array.from({ length: 36 }, (_, i) => {
    const d = new Date(2026, 7 - i, 1)
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  return {
    ym: to, from, months,
    period: { from, to, months: [to], label: label(from, to) },
    base: { from: baseFrom, to: baseTo, months: [baseTo], label: label(baseFrom, baseTo), kind, kindLabel },
    extra: { label: kind === 'yoy' ? '전월' : '전년 동기', period: kind === 'yoy' ? '2026-07' : '2025-08' },
    brand, brandOptions: ['리스트', '쉬즈미스', '시스티나'],
    kpi: {
      amt: 19_433_666_108, baseAmt: 20_829_973_950, change: -6.7, extraAmt: 21_083_281_765, extraChange: -7.8,
      qty: 120_000, baseQty: 130_000, qtyChange: -7.7, dsct: 3_000_000_000, baseDsct: 3_100_000_000, dsctChange: -3.2,
      cost: 5_849_533_498, costRate: 30.1, baseCostRate: 33.2, costRateDiff: -3.1, shops: 537, baseShops: 572,
      avgPerShop: 36_189_322, ytdAmt: 199_196_885_900, prevYtdAmt: 218_210_448_485, ytdYoy: -8.7,
      goalAmt: 23_410_000_000, goalSalesAmt: 18_997_274_816, achieve: 81.2, goalGap: -4_412_725_184, goalShops: 483,
      noGoalShops: 46, noGoalAmt: 436_769_692,
    },
    trend: months.slice(0, 13).reverse().map((m, i) => ({ ym: m, amt: 18e9 + i * 1e8, prevAmt: 19e9, yoy: -5 + i * 0.3, costRate: 30 + i * 0.1, shops: 530 })),
    brands: [
      { brand: '쉬즈미스', amt: 9_826_755_278, baseAmt: 10_480_595_076, change: -6.2, costRate: 30.9, shops: 250, share: 50.6, teams: 5, goalAmt: 12_530_000_000, achieve: 77.0 },
      { brand: '리스트', amt: 7_114_638_180, baseAmt: 7_587_483_068, change: -6.2, costRate: 28.8, shops: 201, share: 36.6, teams: 5, goalAmt: 7_490_000_000, achieve: 93.7 },
    ].filter((b) => !brand || b.brand === brand),
    teams: [],
    topShops: [1, 2, 3].map((i) => shop(i)),
    risers: [shop(4, { change: 40.2 })],
    fallers: [shop(5, { change: -35.5 })],
    laggards: [shop(6, { achieve: 10.3, goalAmt: 10_000_000, amt: 1_025_400 })],
    shopCounts: { selling: 529, new: 70, comparable: 405, closedExcluded: 9 },
    minBaseForGrowth: 10_000_000, hasGoals: true, generatedAt: '2026-09-29',
  }
}

export const saleOptions = {
  seasons: ['봄', '여름'], planYears: ['2026', '2025'], pageSize: 100, maxMonths: 36, sheetRows: 1_000_000,
  columns: [{ key: 'MAKE_YYMM', label: '판매년월', type: 'text' }, { key: 'SHOP_ID', label: '매장코드', type: 'text' }, { key: 'QTY', label: '수량', type: 'int' }],
  summaryDims: [{ key: 'month', label: '월별' }],
}

export class MockApi {
  calls: Call[] = []
  unhandled: string[] = []
  private handlers: { method: string; path: string | RegExp; fn: Handler }[] = []

  constructor(public user: ReturnType<typeof makeUser> | null) {
    this.on('GET', '/api/auth/me', () =>
      this.user ? { json: { user: this.user, usage, sessionTtl: 3600 } } : { status: 401, json: { detail: { message: '로그인이 필요합니다.', code: 'UNAUTHORIZED' } } },
    )
    this.on('POST', '/api/auth/logout', () => ({ json: { ok: true } }))
    this.on('POST', '/api/auth/touch', () => ({ json: { sessionExpiresAt: Math.floor(Date.now() / 1000) + 3600 } }))
    this.on('POST', '/api/usage/menu', () => ({ json: { ok: true } }))
    this.on('GET', '/api/dates', () => ({ json: { dates: [] } }))
    this.on('GET', /^\/api\/prefs\//, () => ({ json: { value: null } }))
    this.on('GET', '/api/chat/usage', () => ({ json: usage }))
    this.on('GET', '/api/chat/conversations', () => ({ json: { conversations: [] } }))
    this.on('GET', '/api/chat/favorites', () => ({ json: { favorites: [] } }))
    this.on('GET', '/api/sale-dashboard', (_, url) => ({ json: dashboardData(url.searchParams) }))
    // 판매 집계 화면은 권한이 있으면 숨김 상태로 미리 떠 있어 기본 응답이 필요하다
    this.on('GET', '/api/sale-monthly/options', () => ({ json: saleOptions }))
    this.on('GET', '/api/sale-monthly', () => ({ json: { rows: [], summary: { rows: 0, qty: 0, realSaleAmt: 0 } } }))
    this.on('GET', '/api/sale-monthly/dsct', () => ({ json: { dsctAmt: 0 } }))
    this.on('GET', '/api/sale-monthly/exports/current', () => ({ json: { job: null } }))
    this.on('GET', '/api/admin/data-freshness', () => ({
      json: { behind: false, mvMaxMonth: '202608', baseMaxMonth: '202608', lastRefresh: '2026-09-02 10:00:00', refreshing: false },
    }))
  }

  /** 같은 경로를 다시 등록하면 나중 것이 우선 */
  on(method: string, path: string | RegExp, fn: Handler) {
    this.handlers.unshift({ method, path, fn })
    return this
  }

  find(method: string, path: string) {
    return this.calls.filter((c) => c.method === method && c.path === path)
  }

  async install(page: Page) {
    await page.route('**/api/**', async (route) => {
      const req = route.request()
      const url = new URL(req.url())
      let body: unknown = null
      try {
        body = req.postDataJSON()
      } catch {
        body = req.postData()
      }
      this.calls.push({ method: req.method(), path: url.pathname, query: url.searchParams, body, headers: req.headers() })
      const h = this.handlers.find((x) => x.method === req.method() && (typeof x.path === 'string' ? x.path === url.pathname : x.path.test(url.pathname)))
      if (!h) {
        this.unhandled.push(`${req.method()} ${url.pathname}`)
        return route.fulfill({ status: 404, json: { detail: { message: `테스트에 없는 API: ${url.pathname}`, code: 'NOT_FOUND' } } })
      }
      const r = await h.fn(req, url)
      if (r.body) return route.fulfill({ status: r.status ?? 200, body: r.body, headers: r.headers })
      return route.fulfill({ status: r.status ?? 200, json: r.json ?? {}, headers: r.headers })
    })
  }
}

/** 테스트마다 가짜 API 를 설치하고, 끝나면 정의되지 않은 API 호출이 없었는지 확인한다. */
export const test = base.extend<{ mockApi: (user: ReturnType<typeof makeUser> | null) => Promise<MockApi> }>({
  mockApi: async ({ page }, use) => {
    const made: MockApi[] = []
    await use(async (user) => {
      const m = new MockApi(user)
      await m.install(page)
      made.push(m)
      return m
    })
    for (const m of made) expect(m.unhandled, '테스트에 없는 API 호출').toEqual([])
  },
})
export { expect }
