// 온라인 가격 매장코드: 일자별 상세의 매장코드 컬럼·IN 조건(URL 공유), 대시보드 매장별 표 → 상세 이동
import { expect, makeUser, test } from './mock'

const COLUMNS = [
  ['ONLINE_ID', 'ONLINE_ID'], ['DT', '수집일'], ['PRDT_CD', '상품코드'], ['PRICE', '기준가'], ['DC_PRICE', '사이트_할인가'], ['DC_RATE', '할인율(%)'],
  ['MALL_NM', '사이트명'], ['TITLE', 'TITLE'], ['RMK', '매장정보'], ['INS_DAY', '수집시간'], ['NAVER_PAY_SELL_NO', '판매자ID'],
  ['SHOP_ID', '매장코드'], ['SHOP_NM', '매장명'], ['URL', 'URL'],
].map(([key, label]) => ({ key, label }))

const row = (id: number, shop: string | null) => ({
  ONLINE_ID: id, DT: '20261007', PRDT_CD: `TA${id}`, PRICE: 100000, DC_PRICE: 90000, DC_RATE: 10, MALL_NM: 'SSG(사이트)', TITLE: '상품',
  RMK: null, INS_DAY: '20261007010101', NAVER_PAY_SELL_NO: '0623601366', SHOP_ID: shop, SHOP_NM: shop ? '신세계광주' : null, URL: 'https://example.com',
})

const rowsJson = (shops: string | null) => {
  const rows = shops ? [row(1, 'T15602'), row(2, 'A15602')] : [row(1, 'T15602'), row(2, 'A15602'), row(3, null)]
  return {
    dt: '20261007', columns: COLUMNS, rows, total: rows.length, totalAll: 3, page: 1, pages: 1, size: 100, malls: ['SSG(사이트)'],
    shops: [{ shopId: 'T15602', shopNm: '신세계광주', rows: 1 }, { shopId: 'A15602', shopNm: '신세계광주', rows: 1 }],
    summary: { products: rows.length, malls: 1, shops: 2, shopRows: 2, avgDcRate: 10 },
  }
}

test('일자별 상세: 매장코드·매장명 컬럼, 매장코드 IN 조건이 요청·링크에 들어간다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['detail']))
  api.on('GET', '/api/dates', () => ({ json: { dates: [{ dt: '20261007', count: 3 }] } }))
  api.on('GET', '/api/rows', (_, url) => ({ json: rowsJson(url.searchParams.get('shops')) }))
  await page.goto('/?view=detail')

  await expect(page.getByRole('columnheader', { name: '매장코드' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '매장명' })).toBeVisible()
  await expect(page.locator('td.col-SHOP_ID').first()).toHaveText('T15602')

  await page.getByPlaceholder('매장코드 (여러 개: 쉼표)').fill('t15602 a15602')
  await expect.poll(() => api.find('GET', '/api/rows').at(-1)!.query.get('shops')).toBe('T15602,A15602')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page).toHaveURL(/shops=T15602%2CA15602/)
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\detail-shops.png` })

  // 이 날 수집된 매장 목록에서 추가 → 기존 입력 뒤에 붙는다
  await page.getByPlaceholder('매장코드 (여러 개: 쉼표)').fill('T15602')
  await page.locator('.shop-pick').selectOption('-')
  await expect(page.getByPlaceholder('매장코드 (여러 개: 쉼표)')).toHaveValue('T15602, -')
  await expect.poll(() => api.find('GET', '/api/rows').at(-1)!.query.get('shops')).toBe('T15602,-')
})

test('대시보드: 매장별 수집 표의 행을 누르면 그 매장 조건으로 일자별 상세가 열린다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['dashboard', 'detail']))
  api.on('GET', '/api/dates', () => ({ json: { dates: [{ dt: '20261007', count: 3 }, { dt: '20261006', count: 3 }] } }))
  api.on('GET', '/api/rows', (_, url) => ({ json: rowsJson(url.searchParams.get('shops')) }))
  api.on('GET', '/api/dashboard', () => ({
    json: {
      start: '20261001', end: '20261007', generatedAt: '2026-10-07 09:00:00',
      kpi: { ROW_CNT: 1000, PRDT_CNT: 100, MALL_CNT: 5, SELLER_CNT: 40, DAY_CNT: 7, AVG_DC_RATE: 8.1, MAX_DC_RATE: 40, DEEP_DC_CNT: 3, SHOP_ROW_CNT: 250, SHOP_CNT: 2 },
      daily: [], malls: [], mallDiscount: [], histogram: [], topProducts: [],
      shops: [
        { SHOP_ID: 'T15602', SHOP_NM: '신세계광주', ROW_CNT: 200, PRDT_CNT: 50, MALL_CNT: 2, AVG_DC_RATE: 9.5, MAX_DC_RATE: 30, LAST_DT: '20261006' },
        { SHOP_ID: 'A15602', SHOP_NM: '신세계광주', ROW_CNT: 50, PRDT_CNT: 20, MALL_CNT: 1, AVG_DC_RATE: 5, MAX_DC_RATE: 12, LAST_DT: '20261007' },
      ],
    },
  }))
  await page.goto('/?view=dashboard')
  await expect(page.getByText('판매자 40 · 매장 2')).toBeVisible()
  await expect(page.getByText(/매장코드\(SHOP_ID\)가 있는 수집 250건 · 전체의 25\.0%/)).toBeVisible()
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\dashboard-shops.png`, fullPage: true })

  await page.getByRole('row', { name: /T15602/ }).click()
  await expect.poll(() => api.find('GET', '/api/rows').at(-1)?.query.get('shops')).toBe('T15602')
  expect(api.find('GET', '/api/rows').at(-1)!.query.get('dt')).toBe('20261006')
  await expect(page.getByPlaceholder('매장코드 (여러 개: 쉼표)')).toHaveValue('T15602')
})

test('일자별 상세: 판매처 매장 연결 권한이 있으면 [매장코드 채우기] 로 최근 7일을 채우고 다시 조회한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['detail', 'mall_shop']))
  api.on('GET', '/api/dates', () => ({ json: { dates: [{ dt: '20261007', count: 3 }] } }))
  api.on('GET', '/api/rows', (_, url) => ({ json: rowsJson(url.searchParams.get('shops')) }))
  api.on('POST', '/api/rows/fill-shop', () => ({ json: { from: '20261001', to: '20261007', updated: 12345, elapsedSec: 3.2 } }))
  // 판매처 매장 연결 화면은 권한이 있으면 숨김 상태로 떠 있을 수 있다
  api.on('GET', '/api/mall-shops', () => ({ json: { ready: true, days: 7, rows: [], summary: { combos: 0, sellers: 0, mapped: 0, unmapped: 0, malls: 0, rowsTotal: 0, rowsMapped: 0, rowsMappedPct: null, shopFilled: 0 } } }))
  api.on('GET', '/api/mall-shops/shops', () => ({ json: { shops: [] } }))
  await page.goto('/?view=detail')
  await expect(page.locator('tbody tr')).toHaveCount(3)
  const before = api.find('GET', '/api/rows').length

  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: '매장코드 채우기' }).click()
  await expect(page.getByText(/12,345건 매장코드 반영/)).toBeVisible()
  expect(api.find('POST', '/api/rows/fill-shop')).toHaveLength(1)
  await expect.poll(() => api.find('GET', '/api/rows').length).toBeGreaterThan(before)   // 반영 후 다시 조회
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\detail-fill.png` })
})

test('일자별 상세: 판매처 매장 연결 권한이 없으면 [매장코드 채우기] 버튼이 없다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['detail']))
  api.on('GET', '/api/dates', () => ({ json: { dates: [{ dt: '20261007', count: 3 }] } }))
  api.on('GET', '/api/rows', (_, url) => ({ json: rowsJson(url.searchParams.get('shops')) }))
  await page.goto('/?view=detail')
  await expect(page.locator('tbody tr')).toHaveCount(3)
  await expect(page.getByRole('button', { name: '매장코드 채우기' })).toHaveCount(0)
})
