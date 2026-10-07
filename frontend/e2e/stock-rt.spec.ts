// 재고 재배치 추천: 매장 간 RT · 창고 → 매장 배분 (조회 · 추천만)
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png`, fullPage: true }) : Promise.resolve())

const now = new Date()
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const ymd = (d: Date) => isoDay(d).replaceAll('-', '')
const daysAgo = (n: number) => new Date(now.getFullYear(), now.getMonth(), now.getDate() - n)

const OPTIONS = (brand: string) => ({
  brand, brands: [{ code: 'S', name: '쉬즈미스' }, { code: 'T', name: '리스트' }],
  teams: [{ code: 'C62010', name: '쉬즈1팀' }, { code: 'C62020', name: '쉬즈2팀' }],
  seasons: [{ code: 'C0073', name: '가을' }, { code: 'C0074', name: '겨울' }, { code: 'C0078', name: '겨울기획' }],
  prdtGrps: [{ code: 'C673K', name: '니트' }], planYears: ['2027', '2026', '2025'],
  warehouses: [{ code: 'IN', name: 'IN - 이천정상창고' }, { code: 'IA', name: 'IA - 이천제2정상창고' }],
  bases: [{ id: '202609003', aplyDt: '2026-09-01', rmk: '26 겨울' }, { id: '202606005', aplyDt: '2026-06-26', rmk: "26'가을" }],
  gradeGroups: [{ id: '2015011', name: '★전체기준등급★', base: true }],
  recentRuns: [{ seq: '5596', at: '2026-10-07 08:49', user: '260001', askSeqn: 18, wh: 'IN', planYy: ['2026'], seasons: ['C0074', 'C0078'],
    prdtGrps: [], items: [], prdt: null, teams: ['C62010'], grdGrp: '2015011', from: '2026-10-06', to: '2026-10-06', rate: 1, base: '202609003',
    ignored: ['물류반품기간'] }],
  defaultSeasons: ['C0073', 'C0074'], defaultPlanYy: ['2026'], today: ymd(now), maxDays: 31,
})

const RT = {
  brand: 'S', brandNm: '쉬즈미스', from: isoDay(daysAgo(6)), to: isoDay(now), asOf: '2026-10-07 16:20', per: 1, limits: false, order: 'slow',
  orderNm: '안 팔리는 매장 우선', senderMax: 0,
  summary: { receivers: 3, needQty: 4, filledReceivers: 2, recQty: 3, recRows: 2, senders: 2, receivingShops: 2, failRequests: 1, failFilled: 1,
    unfilled: 1, unfilledBy: { no_stock: 1, rules: 0, limit: 0, recv_limit: 0 }, skipped: { noGroup: 2, recvCtl: 1, team: 0 },
    senderExcluded: { moving: 3, days: 5, control: 1, grade: 0, abnormal: 0, today: 0, asign0: 0, nobase: 2 }, checked: 20, styles: 300 },
  reasonNames: { no_stock: '같은 RT 그룹에 재고 없음', rules: '재고는 있으나 자동 RT 조건에 막힘', limit: '보낼 매장의 지정가능수 · 최대 수량 소진', recv_limit: '받는 매장 하루 요청가능수 초과' },
  ruleNames: { moving: '이동중 · 요청중 · 최소보유로 남는 재고 없음', days: '최초/최종 출고 경과일 미달', control: '자동 RT 반출 제어 · 제외 스타일', grade: '매장등급 없음',
    abnormal: '정상 매장 아님', today: '오늘 같은 상품 지정받음', asign0: '자동 RT 지정가능수 0', nobase: '매장 상품 기준 없음(2023년 이후 출고 없음)' },
  rows: [
    { no: 1, prdtCd: 'SWWSLQ42230', styleNm: '울 슬랙스', colorCd: 'LG', sizeCd: '44', qty: 1, fromShopId: 'S11003', fromShopNm: '롯데잠실', fromTeam: '쉬즈1팀',
      fromStock: 2, fromSendable: 2, fromSales: 0, fromLastSale: '2026-09-15', toShopId: 'S21018', toShopNm: '천호점', toTeam: '쉬즈2팀', toStock: -1, toSales: 2,
      toFailCnt: 3, why: '자동RT 취소' },
    { no: 2, prdtCd: 'SWWJKQ42010', styleNm: '자켓', colorCd: 'BK', sizeCd: '55', qty: 2, fromShopId: 'S32017', fromShopNm: 'NC수원터미널', fromTeam: '쉬즈3팀',
      fromStock: 3, fromSendable: 3, fromSales: 0, fromLastSale: null, toShopId: 'S11016', toShopNm: '롯데영등포', toTeam: '쉬즈1팀', toStock: 0, toSales: 4,
      toFailCnt: 0, why: '판매 후 품절' },
  ],
  unfilled: [{ shopId: 'S11001', shopNm: '롯데본점', team: '쉬즈1팀', prdtCd: 'SWWOPQ42001', styleNm: '원피스', colorCd: 'NV', sizeCd: '66', stock: 0, sales: 1,
    failCnt: 0, left: 1, reason: 'no_stock', reasonNm: '같은 RT 그룹에 재고 없음' }],
  rowsTotal: 2, unfilledTotal: 1,
  topSenders: [{ shopId: 'S32017', shopNm: 'NC수원터미널', qty: 2 }, { shopId: 'S11003', shopNm: '롯데잠실', qty: 1 }],
  topReceivers: [{ shopId: 'S11016', shopNm: '롯데영등포', qty: 2 }, { shopId: 'S21018', shopNm: '천호점', qty: 1 }],
  timing: { total: 14.2 },
}
const STATS = {
  brand: 'S', brandNm: '쉬즈미스', from: RT.from, to: RT.to, total: 1200, noShopCancel: 640, noShopRate: 53.3,
  results: [{ code: 'C6869', name: '취소', count: 640 }, { code: 'C686Z', name: '완료', count: 420 }],
  days: [{ day: '2026-10-06', total: 300, done: 120, fail: 150 }, { day: '2026-10-07', total: 200, done: 80, fail: 90 }],
  failShops: [{ shopId: 'S21018', shopNm: '천호점', count: 37 }], failProducts: [{ prdtCd: 'SWWSLQ42230', styleNm: '울 슬랙스', count: 12 }],
}
const allocRow = (shopId: string, shopNm: string, rank: number, ask: number, extra: Record<string, unknown> = {}) => ({
  prdtCd: 'SWWBLQ42010', styleNm: '블라우스', colorCd: 'IV', sizeCd: '77', rank, shopId, shopNm, team: '쉬즈1팀', shopType: '백화점', grade: '5등급',
  gradeRank: rank, srate: 50 - rank, fq: ask ? 1 : 0, sq: 1, stock: 0, askFp: ask ? 1 : 0, askSale: ask ? ask - 1 : 0, ask, ctl: false, ...extra,
})
const ALLOC = {
  brand: 'S', brandNm: '쉬즈미스', wh: 'IN', from: '2026-10-06', to: '2026-10-06', base: '202609003', grdGrp: '2015011', rate: 1, asOf: '2026-10-07 16:21',
  summary: { styleSkus: 1810, soldSkus: 708, skus: 2, allocSkus: 1, allocQty: 3, allocFp: 2, shops: 2, demand: 6, short: 3, noStockSkus: 1, ctlRows: 1, candidates: 4 },
  rows: [allocRow('S11001', '롯데본점', 1, 2), allocRow('S11003', '롯데잠실', 2, 1)],
  ctlRows: [allocRow('S12001', '현대본점', 3, 0, { ctl: true })],
  skus: [
    { prdtCd: 'SWWBLQ42010', styleNm: '블라우스', colorCd: 'IV', sizeCd: '77', whStock: 6, reserved: 2, minWh: 1, avail: 3, shops: 3, demand: 4, alloc: 3, short: 1, maxStock: 3, minRate: 0 },
    { prdtCd: 'SSKCDQ42050', styleNm: '가디건', colorCd: 'OT', sizeCd: '55', whStock: 0, reserved: 0, minWh: 0, avail: 0, shops: 2, demand: 2, alloc: 0, short: 2, maxStock: 9999, minRate: 0 },
  ],
  rowsTotal: 2, skusTotal: 2, topShops: [{ shopId: 'S11001', shopNm: '롯데본점', qty: 2 }], timing: { total: 1.7 },
}

test('매장 간 RT 추천: 기본 조건으로 계산하고 결과 · 못 채운 수요 · 매장별 · 자동 RT 현황 · 엑셀', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: RT }))
  api.on('GET', '/api/stock-rt/rt/stats', () => ({ json: STATS }))
  api.on('GET', '/api/stock-rt/rt/export', () => ({ body: Buffer.from('PK'), headers: {
    'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent('매장간RT추천_쉬즈미스_2026-10-07.xlsx')}` } }))
  await page.goto('/?view=stock_rt')
  await expect(page.getByText('조회 · 추천만 합니다')).toBeVisible()
  await page.getByRole('button', { name: /추천 계산/ }).click()

  await expect.poll(() => api.find('GET', '/api/stock-rt/rt').length).toBe(1)
  const q = api.find('GET', '/api/stock-rt/rt')[0].query
  expect(Object.fromEntries(q)).toMatchObject({ brand: 'S', dateFrom: isoDay(daysAgo(6)), dateTo: isoDay(now), planYy: '2026', seasons: 'C0073,C0074', per: '1', order: 'slow' })
  expect(q.get('limits')).toBeNull()

  const table = page.getByRole('table', { name: '매장 간 RT 추천 목록' })
  await expect(table.getByRole('row')).toHaveCount(3)
  await expect(table.getByRole('row').nth(1)).toContainText('롯데잠실')
  await expect(table.getByRole('row').nth(1)).toContainText('자동RT 취소 3회')
  await expect(page.locator('.summary-pills')).toContainText('2건 · 3장')
  await shot(page, 'stock-rt')

  // 결과 검색
  await page.getByLabel('결과 검색').fill('S32017')
  await expect(table.getByRole('row')).toHaveCount(2)
  await page.getByLabel('결과 검색').fill('')

  await page.getByRole('button', { name: /못 채운 수요/ }).click()
  await expect(page.getByRole('table', { name: '못 채운 수요' })).toContainText('같은 RT 그룹에 재고 없음')
  await expect(page.locator('.stock-reasons')).toContainText('최초/최종 출고 경과일 미달 5')

  await page.getByRole('button', { name: '매장별 합계' }).click()
  await expect(page.locator('.stock-two')).toContainText('NC수원터미널')

  await page.getByRole('button', { name: /자동 RT 현황/ }).click()
  await expect(page.locator('.stock-stats')).toContainText("'지시가능매장없음' 취소")
  await expect(page.locator('.stock-stats')).toContainText('640건 (53.3%)')
  await shot(page, 'stock-rt-stats')

  // 조건을 바꾸면 * 표시 · 엑셀은 막힘, 옵션은 요청에 실림
  await page.getByLabel('자동 RT 하루 한도 적용').check()
  await page.getByLabel('보내는 매장당 최대 수량').selectOption('20')
  await expect(page.getByRole('button', { name: /추천 계산 \*/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '엑셀' })).toBeDisabled()
  await page.getByRole('button', { name: /추천 계산/ }).click()
  await expect.poll(() => api.find('GET', '/api/stock-rt/rt').length).toBe(2)
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/rt')[1].query)).toMatchObject({ limits: 'true', senderMax: '20' })

  const dl = page.waitForEvent('download')
  await page.getByRole('button', { name: '엑셀' }).click()
  expect((await dl).suggestedFilename()).toBe('매장간RT추천_쉬즈미스_2026-10-07.xlsx')

  // 기간 31일 넘으면 계산 불가
  await page.getByLabel('판매 기간 시작', { exact: true }).fill(isoDay(daysAgo(40)))
  await expect(page.getByText('기간은 최대 31일입니다.')).toBeVisible()
  await expect(page.getByRole('button', { name: /추천 계산/ })).toBeDisabled()
})

test('창고 → 매장 배분 추천: 최근 자동보충 조건으로 계산하고 상품을 누르면 후보 매장 순서', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  api.on('GET', '/api/stock-rt/alloc', () => ({ json: ALLOC }))
  api.on('GET', '/api/stock-rt/alloc/candidates', () => ({ json: { rows: [...ALLOC.rows, ...ALLOC.ctlRows], sku: ALLOC.skus[0] } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('tab', { name: /창고 → 매장 배분/ }).click()
  await expect(page.getByLabel('최근 판매분 자동보충 실행 조건')).toContainText('5596')
  await expect(page.getByText('이 화면에서 쓰지 않는 조건: 물류반품기간')).toBeVisible()
  await expect(page.getByLabel('판매보충기준')).toHaveValue('202609003')
  await page.getByRole('button', { name: /배분 계산/ }).click()

  await expect.poll(() => api.find('GET', '/api/stock-rt/alloc').length).toBe(1)
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/alloc')[0].query)).toMatchObject({
    brand: 'S', wh: 'IN', base: '202609003', grdGrp: '2015011', planYy: '2026', seasons: 'C0074,C0078', teams: 'C62010', rate: '1',
    dateFrom: isoDay(daysAgo(1)), dateTo: isoDay(daysAgo(1)),
  })
  const rows = page.getByRole('table', { name: '매장별 배분' })
  await expect(rows.getByRole('row')).toHaveCount(3)
  await expect(page.locator('.summary-pills')).toContainText('3장')
  await shot(page, 'stock-alloc')

  await page.getByRole('button', { name: /상품별/ }).click()
  await page.getByLabel('부족한 상품만').check()
  const skus = page.getByRole('table', { name: '상품별 배분' })
  await expect(skus.getByRole('row')).toHaveCount(3)
  await skus.getByRole('row').nth(1).click()
  const modal = page.getByRole('dialog', { name: '후보 매장 순서' })
  await expect(modal).toContainText('현대본점 (수불제어 · 건너뜀)')
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/alloc/candidates')[0].query)).toMatchObject({ prdtCd: 'SWWBLQ42010', colorCd: 'IV', sizeCd: '77' })
  await shot(page, 'stock-alloc-cand')
})
