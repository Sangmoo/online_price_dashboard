// 재고 재배치 추천: 100행 페이징 · 창고 회수 추천 · 미처리 RT 현황 · 장기 미판매 재고
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png`, fullPage: true }) : Promise.resolve())
const now = new Date()
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const ymd = (d: Date) => isoDay(d).replaceAll('-', '')

const OPTIONS = (brand: string, canWrite = false) => ({
  canWrite, brand, brands: [{ code: 'S', name: '쉬즈미스' }, { code: 'T', name: '리스트' }],
  teams: [{ code: 'C62010', name: '쉬즈1팀' }, { code: 'C62020', name: '쉬즈2팀' }],
  seasons: [{ code: 'C0073', name: '가을' }, { code: 'C0074', name: '겨울' }], prdtGrps: [], planYears: ['2026', '2025'],
  warehouses: [{ code: 'IN', name: 'IN - 이천정상창고' }], bases: [{ id: '202609003', aplyDt: '2026-09-01', rmk: '26 겨울' }],
  gradeGroups: [{ id: '2015011', name: '★전체기준등급★', base: true }],
  recentRuns: [{ seq: '5596', at: '2026-10-07 08:49', user: '260001', askSeqn: 18, wh: 'IN', planYy: ['2026'], seasons: ['C0074'], prdtGrps: [], items: [],
    prdt: null, teams: [], grdGrp: '2015011', from: '2026-10-06', to: '2026-10-06', rate: 1, base: '202609003', ignored: [] }],
  defaultSeasons: ['C0073', 'C0074'], defaultPlanYy: ['2026'], today: ymd(now), maxDays: 31,
})

const rtRow = (i: number) => ({ no: i + 1, prdtCd: `SWW${String(i).padStart(5, '0')}`, styleNm: null, colorCd: 'BK', sizeCd: '55', qty: 1, fromShopId: 'S11003', fromShopNm: '롯데잠실',
  fromTeam: '쉬즈1팀', fromStock: 2, fromSendable: 2, fromSales: 0, fromLastSale: null, toShopId: 'S21018', toShopNm: '천호점', toTeam: '쉬즈2팀', toStock: 0,
  toSales: 1, toFailCnt: 0, toIncoming: 0, why: '판매 후 품절' })
const RT = (n: number) => ({
  brand: 'S', brandNm: '쉬즈미스', from: isoDay(now), to: isoDay(now), asOf: 'x', per: 1, limits: false, order: 'slow', orderNm: '안 팔리는 매장 우선', senderMax: 0,
  summary: { receivers: n, needQty: n, filledReceivers: n, recQty: n, recRows: n, senders: 1, receivingShops: 1, failRequests: 0, failFilled: 0, unfilled: 0,
    unfilledBy: {}, skipped: { noGroup: 0, recvCtl: 0, team: 0, incoming: 0, virtual: 12 }, senderExcluded: { virtual: 3 }, checked: 0, styles: 1 },
  reasonNames: {}, ruleNames: { virtual: '행사 · 가상 매장' }, rows: Array.from({ length: n }, (_, i) => rtRow(i)), unfilled: [], rowsTotal: n, unfilledTotal: 0,
  topSenders: [], topReceivers: [], timing: { total: 1 },
})

test('매장 간 RT 추천: 100행씩 넘겨 보고, 걸러진 전체를 한 번에 선택', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S', true) }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: RT(250) }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('button', { name: /추천 계산/ }).click()
  const table = page.getByRole('table', { name: '매장 간 RT 추천 목록' })
  await expect(table.getByRole('row')).toHaveCount(101)
  await expect(page.locator('.stock-pager').first()).toContainText('1–100 / 250건')
  await page.getByRole('button', { name: '다음 페이지' }).first().click()
  await expect(page.locator('.stock-pager').first()).toContainText('101–200 / 250건')
  await expect(table.getByRole('row').nth(1)).toContainText('SWW00100')
  await page.getByRole('button', { name: '마지막 페이지' }).first().click()
  await expect(table.getByRole('row')).toHaveCount(51)
  await page.getByRole('button', { name: '전체 250건 선택' }).click()
  await expect(page.getByRole('button', { name: /본사지시 RT 지시 \(250건 · 250장\)/ })).toBeEnabled()
  await page.getByLabel('결과 검색').fill('SWW0001')                                    // 검색하면 첫 페이지로 · 걸러진 것만
  await expect(page.locator('.stock-pager').first()).toContainText('1–10 / 10건')
  await shot(page, 'stock-paging')
})

test('창고 회수 추천: 배분 탭의 창고 부족에서 같은 조건으로 회수 추천 (추천만)', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  const short = { prdtCd: 'SWWBLQ42010', styleNm: '블라우스', colorCd: 'IV', sizeCd: '77', rank: 4, shopId: 'S21018', shopNm: '천호점', team: '쉬즈1팀', shopType: '백화점',
    grade: '5등급', gradeRank: 4, srate: 40, fq: 0, sq: 2, stock: 0, askFp: 0, askSale: 0, ask: 0, ctl: false, need: 2, short: 2 }
  api.on('GET', '/api/stock-rt/alloc', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', wh: 'IN', from: '2026-10-06', to: '2026-10-06', base: '202609003', grdGrp: '2015011',
    rate: 1, asOf: 'x', summary: { styleSkus: 1, soldSkus: 1, skus: 1, allocSkus: 0, allocQty: 0, allocFp: 0, shops: 0, demand: 2, short: 2, noStockSkus: 1, ctlRows: 0,
      candidates: 1, shortRows: 1, shortZero: 1, asked: 0 }, rows: [], ctlRows: [], shortRows: [short], skus: [], rowsTotal: 0, skusTotal: 0, shortRowsTotal: 1,
    topShops: [], timing: { total: 1 } } }))
  api.on('GET', '/api/stock-rt/return', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', wh: 'IN', from: '2026-10-06', to: '2026-10-06', allocAsOf: 'x', asOf: 'y',
    lookback: 14, salesFrom: '2026-09-24', mode: 'need', modeNm: '창고 부족 수량만큼',
    summary: { shortSkus: 1, shortQty: 2, returnQty: 2, rows: 2, shops: 2, coveredSkus: 1, partialSkus: 0, noSourceSkus: 0, coveredQty: 2, excluded: { sold: 3, needs: 1, virtual: 2, reserved: 0 } },
    rows: [
      { prdtCd: 'SWWBLQ42010', styleNm: '블라우스', colorCd: 'IV', sizeCd: '77', shopId: 'S11032', shopNm: '(폐)롯데강남', team: '쉬즈1팀', closed: true, stock: 1, avail: 1, qty: 1,
        lastSale: null, daysNoSale: null, lastDelv: '2026-03-02', daysSinceDelv: 219, skuShort: 2 },
      { prdtCd: 'SWWBLQ42010', styleNm: '블라우스', colorCd: 'IV', sizeCd: '77', shopId: 'S41004', shopNm: '타임스퀘어', team: '쉬즈4팀', closed: false, stock: 3, avail: 3, qty: 1,
        lastSale: '2026-08-01', daysNoSale: 67, lastDelv: '2026-07-20', daysSinceDelv: 79, skuShort: 2 }],
    skus: [{ prdtCd: 'SWWBLQ42010', styleNm: '블라우스', colorCd: 'IV', sizeCd: '77', whStock: 0, avail: 0, demand: 2, short: 2, candidates: 2, candQty: 4, returnQty: 2, left: 0 }],
    topShops: [{ shopId: 'S11032', shopNm: '(폐)롯데강남', qty: 1 }], timing: { total: 2 } } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('tab', { name: /창고 → 매장 배분/ }).click()
  await page.getByRole('button', { name: /배분 계산/ }).click()
  await page.getByRole('button', { name: /창고 부족 \(1\)/ }).click()
  await page.getByRole('button', { name: /창고로 회수 추천/ }).click()
  await expect(page.getByRole('tab', { name: /창고 회수/ })).toHaveAttribute('aria-selected', 'true')
  const t = page.getByRole('table', { name: '창고 회수 추천' })
  await expect(t.getByRole('row')).toHaveCount(3)
  await expect(t.getByRole('row').nth(1)).toHaveClass(/row-short/)                       // 폐점 매장 먼저
  await expect(t.getByRole('row').nth(1)).toContainText('판매 이력 없음')
  await expect(page.locator('.summary-pills').last()).toContainText('부족 채움 100%')
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/return')[0].query)).toMatchObject({ brand: 'S', base: '202609003', lookback: '14', mode: 'need' })
  await shot(page, 'stock-return')
  await page.getByRole('button', { name: '판매 없는 재고 전부' }).click()
  await page.getByRole('button', { name: /회수 추천 \*/ }).click()
  await expect.poll(() => api.find('GET', '/api/stock-rt/return').length).toBe(2)
  expect(api.find('GET', '/api/stock-rt/return')[1].query.get('mode')).toBe('all')
})

test('미처리 RT 현황: 매장별 · 자동거부 임박 · 매장 누르면 요청 목록', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  const grp = (key: string, name: string, rows: number, urgent: number, oldest: number) => ({ key, name, team: '쉬즈1팀', rows, qty: rows, urgent, oldestHours: oldest,
    d0: 0, d1: rows - urgent, d2: urgent, d3: 0, C6811: rows, C6812: 0, C6813: 0 })
  const row = (shop: string, hours: number, urgent: boolean) => ({ makeDt: '2026-10-05', seq: Math.round(hours), type: 'C6811', typeNm: '본사지시', fromShopId: shop,
    fromShopNm: shop === 'S32517' ? '현대아울렛송도' : '롯데잠실', fromTeam: '쉬즈1팀', toShopId: 'S21018', toShopNm: '천호점', prdtCd: 'SWWJKQ42010', styleNm: null,
    colorCd: 'BK', sizeCd: '55', qty: 1, requestedAt: '10-05 15:30', hours, age: urgent ? 'd2' : 'd1', urgent, requestedBy: '230112', ref: '2026100500001' })
  api.on('GET', '/api/stock-rt/pending', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', from: '2026-09-24', to: isoDay(now), days: 14, types: ['C6811', 'C6812', 'C6813'],
    typeNames: { C6811: '본사지시', C6812: '자동 RT', C6813: '매장간' }, ages: [{ key: 'd0', name: '1일 미만' }, { key: 'd1', name: '1~2일' }, { key: 'd2', name: '2~3일' }, { key: 'd3', name: '3일 이상' }],
    urgentHours: 48, asOf: 'x', includeVirtual: false, virtualRows: 764,
    summary: { rows: 3, qty: 3, shops: 2, urgent: 1, byAge: { d0: 0, d1: 2, d2: 1, d3: 0 }, byType: { C6811: 3, C6812: 0, C6813: 0 } },
    shops: [grp('S32517', '현대아울렛송도', 2, 1, 50.5), grp('S11003', '롯데잠실', 1, 0, 30)], teams: [grp('쉬즈1팀', '쉬즈1팀', 3, 1, 50.5)],
    rows: [row('S32517', 50.5, true), row('S32517', 30, false), row('S11003', 30, false)] } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('tab', { name: /미처리 RT 현황/ }).click()
  const shops = page.getByRole('table', { name: '미처리 RT 매장별' })
  await expect(shops.getByRole('row')).toHaveCount(3)
  await expect(shops.getByRole('row').nth(1)).toHaveClass(/row-short/)
  await expect(page.locator('.summary-pills').last()).toContainText('행사 · 가상 매장 764건 제외')
  await shot(page, 'stock-pending')
  await shops.getByRole('row').nth(1).click()
  const rows = page.getByRole('table', { name: '미처리 RT 요청 목록' })
  await expect(rows.getByRole('row')).toHaveCount(3)
  await expect(rows).toContainText('자동거부 임박')
  await page.getByLabel('자동거부 임박만').check()
  await expect(rows.getByRole('row')).toHaveCount(2)
  await page.getByRole('button', { name: '최근 7일' }).click()
  await expect.poll(() => api.find('GET', '/api/stock-rt/pending').map((r) => r.query.get('days'))).toEqual(['14', '7'])
})

test('장기 미판매 재고: 구간 · 매장별 · 매장 누르면 스타일 · 행 누르면 칼라 사이즈', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  const detail = (shopId: string, shopNm: string, prdtCd: string, days: number, neverSold = false) => ({ shopId, shopNm, team: '쉬즈1팀', prdtCd, styleNm: null, planYy: '2025',
    sesn: 'C0074', sesnNm: '겨울', qty: 10, amt: 1500000, skus: 4, days, neverSold, lastSale: neverSold ? null : '2025-09-01', lastDelv: '2025-08-01', firstDelv: '2025-07-01' })
  api.on('GET', '/api/stock-rt/aging', (_, url) => ({ json: { brand: 'S', brandNm: '쉬즈미스', minDays: Number(url.searchParams.get('minDays')), asOf: '2026-10-08 07:02', baseSec: 70,
    ym: '202610', virtualQty: 5000, cond: { planYy: [], seasons: [], teams: [], prdt: null, includeVirtual: false },
    summary: { qty: 100000, amt: 9e9, rows: 5000, agedQty: 20000, agedAmt: 1.2e9, agedRows: 800, agedRate: 20, shops: 200, agedShops: 2, agedStyles: 2 },
    buckets: [{ key: 'b30', name: '30일 이하', qty: 60000, amt: 6e9, rows: 3000 }, { key: 'b60', name: '31~60일', qty: 10000, amt: 1e9, rows: 500 },
      { key: 'b90', name: '61~90일', qty: 10000, amt: 8e8, rows: 400 }, { key: 'b180', name: '91~180일', qty: 8000, amt: 6e8, rows: 400 },
      { key: 'b365', name: '181~365일', qty: 7000, amt: 4e8, rows: 300 }, { key: 'bOld', name: '1년 넘음', qty: 5000, amt: 2e8, rows: 400 },
      { key: 'none', name: '판매 · 출고 기준 없음', qty: 0, amt: 0, rows: 0 }],
    shops: [{ shopId: 'S41017', shopNm: '스타필드코엑스몰', team: '쉬즈4팀', closed: false, qty: 5000, amt: 5e8, agedQty: 2000, agedAmt: 2e8, agedStyles: 40, agedRate: 40 },
      { shopId: 'S11003', shopNm: '롯데잠실', team: '쉬즈1팀', closed: false, qty: 4000, amt: 4e8, agedQty: 400, agedAmt: 4e7, agedStyles: 8, agedRate: 10 }],
    styles: [{ prdtCd: 'SWWCTP41010', styleNm: null, planYy: '2025', sesn: 'C0074', sesnNm: '겨울', qty: 300, amt: 4.5e7, agedQty: 200, agedAmt: 3e7, agedShops: 20, maxDays: 400 }],
    stylesTotal: 1, detail: [detail('S41017', '스타필드코엑스몰', 'SWWCTP41010', 400), detail('S11003', '롯데잠실', 'SWWCTP41010', 120, true)], detailTotal: 2,
    timing: { total: 0.1 } } }))
  api.on('GET', '/api/stock-rt/aging/skus', () => ({ json: { rows: [{ colorCd: 'BK', sizeCd: '55', qty: 3, amt: 450000, lastSale: '2025-09-01', lastDelv: '2025-08-01', firstDelv: '2025-07-01', days: 400 }] } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('tab', { name: /장기 미판매 재고/ }).click()
  await expect(page.locator('.summary-pills').last()).toContainText('90일 넘게 안 팔림')
  await expect(page.locator('.stock-aging-buckets')).toContainText('1년 넘음')
  const shops = page.getByRole('table', { name: '장기 미판매 매장별' })
  await expect(shops.getByRole('row').nth(1)).toHaveClass(/row-short/)                   // 비중 30% 이상
  await shot(page, 'stock-aging')
  await shops.getByRole('row').nth(1).click()
  const dt = page.getByRole('table', { name: '장기 미판매 매장 × 스타일' })
  await expect(dt.getByRole('row')).toHaveCount(2)                                       // 그 매장만
  await dt.getByRole('row').nth(1).click()
  await expect(page.getByRole('dialog', { name: '칼라 · 사이즈별 재고' })).toContainText('BK · 55')
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/aging/skus')[0].query)).toMatchObject({ shopId: 'S41017', prdtCd: 'SWWCTP41010' })
  await page.getByRole('dialog', { name: '칼라 · 사이즈별 재고' }).getByTitle('닫기').click()
  await page.getByRole('button', { name: '180일 이상' }).click()
  await page.getByRole('button', { name: /조회 \*/ }).click()
  await expect.poll(() => api.find('GET', '/api/stock-rt/aging').map((r) => r.query.get('minDays'))).toEqual(['90', '180'])
})
