// 재고 재배치 추천: 매장 간 RT · 창고 → 매장 배분 (추천 조회 · 관리자 ERP 지시 · 의뢰 등록 · 삭제)
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png`, fullPage: true }) : Promise.resolve())

const now = new Date()
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const ymd = (d: Date) => isoDay(d).replaceAll('-', '')
const daysAgo = (n: number) => new Date(now.getFullYear(), now.getMonth(), now.getDate() - n)

const OPTIONS = (brand: string, canWrite = false) => ({
  canWrite,
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
      toFailCnt: 3, toIncoming: 0, why: '자동RT 취소' },
    { no: 2, prdtCd: 'SWWJKQ42010', styleNm: '자켓', colorCd: 'BK', sizeCd: '55', qty: 2, fromShopId: 'S32017', fromShopNm: 'NC수원터미널', fromTeam: '쉬즈3팀',
      fromStock: 3, fromSendable: 3, fromSales: 0, fromLastSale: null, toShopId: 'S11016', toShopNm: '롯데영등포', toTeam: '쉬즈1팀', toStock: 0, toSales: 4,
      toFailCnt: 0, toIncoming: 0, why: '판매 후 품절' },
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
  gradeRank: rank, srate: 50 - rank, fq: ask ? 1 : 0, sq: 1, stock: 0, askFp: ask ? 1 : 0, askSale: ask ? ask - 1 : 0, ask, ctl: false,
  need: 2, short: Math.max(2 - ask, 0), ...extra,
})
const ALLOC = {
  brand: 'S', brandNm: '쉬즈미스', wh: 'IN', from: '2026-10-06', to: '2026-10-06', base: '202609003', grdGrp: '2015011', rate: 1, asOf: '2026-10-07 16:21',
  summary: { styleSkus: 1810, soldSkus: 708, skus: 2, allocSkus: 1, allocQty: 3, allocFp: 2, shops: 2, demand: 6, short: 3, noStockSkus: 1, ctlRows: 1, candidates: 4,
    shortRows: 2, shortZero: 1, asked: 0 },
  rows: [allocRow('S11001', '롯데본점', 1, 2), allocRow('S11003', '롯데잠실', 2, 1)],
  shortRows: [allocRow('S11003', '롯데잠실', 2, 1), allocRow('S21018', '천호점', 4, 0)], shortRowsTotal: 2,
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
  // 창고 부족으로 덜 받은 행은 노란 행 · '부족' 표시, 일반 사용자는 등록 버튼 없음
  await expect(rows.getByRole('row').nth(2)).toHaveClass(/row-short/)
  await expect(rows.getByRole('row').nth(2)).toContainText('부족 1')
  await expect(rows.getByRole('row').nth(1)).not.toHaveClass(/row-short/)
  await expect(page.getByRole('button', { name: /배분의뢰 등록/ })).toHaveCount(0)
  await shot(page, 'stock-alloc')

  await page.getByRole('button', { name: /창고 부족 \(2\)/ }).click()
  await expect(page.locator('.stock-short-note')).toContainText('전혀 못 받음 1건')
  await expect(rows.getByRole('row').nth(2)).toContainText('미배분 부족 2')

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

test('관리자: 매장 간 RT 추천을 골라 본사지시 RT 지시 · 확정(로그인 사번) 등록 · 등록 내역에서 매장 미처리 지시 취소', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S', true) }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: RT }))
  api.on('POST', '/api/stock-rt/rt/preview', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', asOf: RT.asOf, count: 1, qty: 2, senders: 1, receivers: 1,
    skipped: [{ key: ['SWWSLQ42230', 'LG', '44', 'S11003', 'S21018'], reason: '보내는 매장 재고 부족 (지금 보낼 수 있는 수량 0)' }] } }))
  api.on('POST', '/api/stock-rt/rt/register', () => ({ json: { ok: true, indcDt: ymd(now), count: 1, qty: 2, firstId: `${ymd(now)}00042`,
    lastId: `${ymd(now)}00043`, senders: 1, receivers: 1, skipped: [] } }))
  const reg = { brand: 'S', brandNm: '쉬즈미스', from: '', to: '', total: 2, deletable: 1,
    byStatus: [{ code: 'N', name: '미확정 (매장 확정 전)', qty: 1 }, { code: 'C2951', name: '수락', qty: 1 }],
    rows: [
      { id: `${ymd(now)}00042`, indcDt: isoDay(now), prdtCd: 'SWWJKQ42010', colorCd: 'BK', sizeCd: '55', qty: 1, fromShopId: 'S32017', fromShopNm: 'NC수원터미널',
        toShopId: 'S11016', toShopNm: '롯데영등포', status: 'C2954', statusNm: '확정 · 매장 미처리', insDay: '20261007161000', insUser: 'admin', cnfmUser: 'admin', deletable: true },
      { id: `${ymd(now)}00043`, indcDt: isoDay(now), prdtCd: 'SWWJKQ42010', colorCd: 'BK', sizeCd: '55', qty: 1, fromShopId: 'S32017', fromShopNm: 'NC수원터미널',
        toShopId: 'S11016', toShopNm: '롯데영등포', status: 'C2951', statusNm: '수락', insDay: '20261007161000', insUser: 'admin', deletable: false },
    ] }
  api.on('GET', '/api/stock-rt/rt/registered', () => ({ json: reg }))
  api.on('POST', '/api/stock-rt/rt/delete', () => ({ json: { ok: true, deleted: 1, requested: 1, notDeleted: 0 } }))

  await page.goto('/?view=stock_rt')
  await expect(page.getByText('관리자: 고른 추천을 ERP')).toBeVisible()
  await page.getByRole('button', { name: /추천 계산/ }).click()
  const table = page.getByRole('table', { name: '매장 간 RT 추천 목록' })
  await expect(table.getByRole('row')).toHaveCount(3)
  await expect(page.getByRole('button', { name: /본사지시 RT 지시/ })).toBeDisabled()
  await table.getByLabel('추천 모두 선택').check()
  await expect(page.getByRole('button', { name: /본사지시 RT 지시 \(2건 · 3장\)/ })).toBeEnabled()
  await table.getByLabel('SWWSLQ42230 S11003→S21018 선택').uncheck()
  await page.getByRole('button', { name: /본사지시 RT 지시 \(1건 · 2장\)/ }).click()

  const dlg = page.getByRole('dialog', { name: '본사지시 RT 지시 등록' })
  await expect(dlg).toContainText('로그인한 사번으로 확정')
  await expect(dlg).toContainText('제외 1건')
  expect(api.find('POST', '/api/stock-rt/rt/preview')[0].body).toEqual({ keys: [['SWWJKQ42010', 'BK', '55', 'S32017', 'S11016']] })
  await shot(page, 'stock-rt-register')
  await dlg.getByRole('button', { name: '2장 지시' }).click()
  await expect(page.locator('.stock-done')).toContainText(`지시번호 ${ymd(now)}00042 ~ ${ymd(now)}00043`)
  const body = api.find('POST', '/api/stock-rt/rt/register')[0].body as { keys: string[][]; indcDt: string }
  expect(body).toEqual({ keys: [['SWWJKQ42010', 'BK', '55', 'S32017', 'S11016']], indcDt: isoDay(now) })
  expect(Object.fromEntries(api.find('POST', '/api/stock-rt/rt/register')[0].query)).toMatchObject({ brand: 'S', order: 'slow' })
  // 등록 뒤 지금 재고로 다시 계산
  await expect.poll(() => api.find('GET', '/api/stock-rt/rt').filter((r) => r.query.get('refresh') === 'true').length).toBe(1)

  await page.getByRole('button', { name: /등록 내역/ }).click()
  const list = page.getByRole('dialog', { name: /본사지시 RT 지시 등록 내역/ })
  await expect(list.getByRole('row')).toHaveCount(3)
  await expect(list.getByLabel(`${ymd(now)}00043 선택`)).toBeDisabled()          // 매장이 수락한 지시는 삭제 불가
  await list.getByLabel('삭제 가능한 행 모두 선택').check()
  await list.getByRole('button', { name: /선택 취소 \(1\)/ }).click()
  await expect(list).toContainText('본사지시 취소와 같이 취소')
  await shot(page, 'stock-rt-registered')
  await list.getByRole('button', { name: '취소', exact: true }).click()
  await expect(list).toContainText('1건을 취소했습니다')
  expect(api.find('POST', '/api/stock-rt/rt/delete')[0].body).toEqual({ brand: 'S', ids: [`${ymd(now)}00042`] })
})

test('관리자: 창고 배분을 골라 배분의뢰(미확정) 등록 — 차수 제안 · 확정 차수는 막음', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S', true) }))
  api.on('GET', '/api/stock-rt/alloc', () => ({ json: ALLOC }))
  api.on('POST', '/api/stock-rt/alloc/preview', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', asOf: ALLOC.asOf, wh: 'IN', count: 2, qty: 3, shops: 2, skipped: [] } }))
  api.on('GET', '/api/stock-rt/alloc/seqns', () => ({ json: { brand: 'S', askDt: isoDay(now), next: 19,
    used: [{ seqn: 17, brand: 'S', brandNm: '쉬즈미스', clsby: 'C0632', rows: 1295, confirmed: true, web: false },
      { seqn: 18, brand: 'S', brandNm: '쉬즈미스', clsby: 'C0632', rows: 2861, confirmed: true, web: false }] } }))
  api.on('POST', '/api/stock-rt/alloc/register', () => ({ json: { ok: true, askDt: isoDay(now), askSeqn: 19, count: 2, qty: 3, shops: 2, skipped: [] } }))

  await page.goto('/?view=stock_rt')
  await page.getByRole('tab', { name: /창고 → 매장 배분/ }).click()
  await page.getByRole('button', { name: /배분 계산/ }).click()
  const rows = page.getByRole('table', { name: '매장별 배분' })
  await expect(rows.getByRole('row')).toHaveCount(3)
  await rows.getByLabel('배분 모두 선택').check()
  await page.getByRole('button', { name: /배분의뢰 등록 \(2건 · 3장\)/ }).click()
  const dlg = page.getByRole('dialog', { name: '배분의뢰 등록' })
  await expect(dlg.getByLabel('의뢰차수')).toHaveValue('19')
  await expect(dlg).toContainText('17(쉬즈미스·확정)')
  await dlg.getByLabel('의뢰차수').fill('18')
  await expect(dlg).toContainText('이미 확정된 차수')
  await expect(dlg.getByRole('button', { name: '3장 의뢰' })).toBeDisabled()
  await dlg.getByLabel('의뢰차수').fill('19')
  await shot(page, 'stock-alloc-register')
  await dlg.getByRole('button', { name: '3장 의뢰' }).click()
  await expect(page.locator('.stock-done')).toContainText('19차에 3장')
  expect(api.find('POST', '/api/stock-rt/alloc/register')[0].body).toEqual({
    keys: [['S11001', 'SWWBLQ42010', 'IV', '77'], ['S11003', 'SWWBLQ42010', 'IV', '77']], askDt: isoDay(now), askSeqn: 19, delvPreDt: isoDay(now) })
})

test('메뉴를 옮겼다 돌아와도 조회 결과가 그대로 · 사이드바 서비스명은 메뉴 스크롤과 따로 고정', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt', 'invt_plan']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: RT }))
  api.on('GET', '/api/invt-plans/options', () => ({ json: { areas: [], regions: [], areaRegion: {}, invtTypes: ['정기'], stlmTeams: [], rmkMaxBytes: 200, encoding: 'utf-8' } }))
  api.on('GET', '/api/invt-plans', () => ({ json: { plans: [] } }))
  await page.goto('/?view=stock_rt')
  await page.getByLabel('품번', { exact: true }).fill('SWW')
  await page.getByRole('button', { name: /추천 계산/ }).click()
  await expect(page.getByRole('table', { name: '매장 간 RT 추천 목록' }).getByRole('row')).toHaveCount(3)
  await page.locator('.side-item', { hasText: '매장 재고 실사계획' }).click()
  await expect(page.getByRole('table', { name: '매장 간 RT 추천 목록' })).toBeHidden()
  await page.locator('.side-item', { hasText: '재고 재배치 추천' }).click()
  await expect(page.getByRole('table', { name: '매장 간 RT 추천 목록' }).getByRole('row')).toHaveCount(3)
  await expect(page.getByLabel('품번', { exact: true })).toHaveValue('SWW')
  expect(api.find('GET', '/api/stock-rt/rt').length).toBe(1)           // 다시 계산하지 않음
  expect(await page.locator('.sidebar-scroll .sidebar-brand').count()).toBe(0)
  await expect(page.locator('.sidebar > .sidebar-brand')).toBeVisible()
})

test('자동 RT 설정 점검: 지정가능수 0 · 부족 매장과 권장값 · 엑셀', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: RT }))
  const row = (shopId: string, shopNm: string, asign: number, suggest: number, status: string) => ({
    shopId, shopNm, team: '쉬즈4팀', rtGrp: '201501001', asign, reqAble: 30, minRetain: 0, assigned: asign * 7, assignedPerDay: asign, recRows: 90,
    recQty: 100, failQty: 40, receivers: 30, suggest, blocked: asign === 0, status })
  api.on('GET', '/api/stock-rt/rt/setting-check', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', from: RT.from, to: RT.to, days: 7, asOf: RT.asOf,
    summary: { senders: 3, blockedShops: 1, lowShops: 1, recQty: 300, blockedQty: 100, failRequests: 788, failFilled: 784, blockedFailQty: 40, lowFailQty: 40 },
    rows: [row('S41017', '스타필드코엑스몰', 0, 23, '지정가능수 0 — 자동 RT 에서 보내는 매장으로 지정되지 않음'), row('S11003', '롯데잠실', 2, 6, '지정가능수 부족'),
      row('S11016', '롯데영등포', 9, 9, '적정')] } }))
  api.on('GET', '/api/stock-rt/rt/setting-check/export', () => ({ body: Buffer.from('PK'), headers: {
    'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent('자동RT설정점검_쉬즈미스.xlsx')}` } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('button', { name: /추천 계산/ }).click()
  await page.getByRole('button', { name: /자동 RT 설정 점검/ }).click()
  const t = page.getByRole('table', { name: '자동 RT 설정 점검' })
  await expect(t.getByRole('row')).toHaveCount(3)                       // 적정 매장은 기본으로 숨김
  await expect(t.getByRole('row').nth(1)).toHaveClass(/row-short/)
  await expect(t.getByRole('row').nth(1)).toContainText('스타필드코엑스몰')
  await expect(page.locator('.stock-stats')).toContainText('지정가능수 0')
  await shot(page, 'stock-rt-check')
  await page.getByLabel('적정 매장도 보기').check()
  await expect(t.getByRole('row')).toHaveCount(4)
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/rt/setting-check')[0].query)).toMatchObject({ brand: 'S', order: 'slow' })
  const dl = page.waitForEvent('download')
  await page.locator('.stock-stats').getByRole('button', { name: '엑셀' }).click()
  expect((await dl).suggestedFilename()).toBe('자동RT설정점검_쉬즈미스.xlsx')
})

test('창고 부족 → 매장 간 RT 로 채우기: 추천을 보고 관리자는 본사지시 RT 지시', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S', true) }))
  api.on('GET', '/api/stock-rt/alloc', () => ({ json: ALLOC }))
  const fill = { ...RT.rows[1], no: 1, toShopId: 'S21018', toShopNm: '천호점', qty: 2, why: '창고 부족', prdtCd: 'SWWBLQ42010', colorCd: 'IV', sizeCd: '77' }
  api.on('GET', '/api/stock-rt/alloc/short-rt', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', asOf: '2026-10-07 16:30', allocAsOf: ALLOC.asOf, wh: 'IN',
    from: ALLOC.from, to: ALLOC.to, orderNm: '자동 RT 순서', summary: { shortRows: 2, shortQty: 3, receivers: 2, needQty: 3, filledReceivers: 1, recRows: 1, recQty: 2,
      senders: 1, receivingShops: 1, unfilled: 1, unfilledBy: { no_stock: 1, rules: 0, limit: 0, recv_limit: 0 }, skipped: { noGroup: 0, recvCtl: 0, team: 0, incoming: 0 },
      senderExcluded: RT.summary.senderExcluded }, reasonNames: RT.reasonNames, ruleNames: RT.ruleNames, rows: [fill], unfilled: RT.unfilled, timing: { total: 3.1 } } }))
  api.on('POST', '/api/stock-rt/alloc/short-rt/preview', () => ({ json: { brand: 'S', brandNm: '쉬즈미스', asOf: 'x', count: 1, qty: 2, senders: 1, receivers: 1, skipped: [] } }))
  api.on('POST', '/api/stock-rt/alloc/short-rt/register', () => ({ json: { ok: true, indcDt: ymd(now), count: 1, qty: 2, firstId: `${ymd(now)}00050`,
    lastId: `${ymd(now)}00051`, senders: 1, receivers: 1, skipped: [] } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('tab', { name: /창고 → 매장 배분/ }).click()
  await page.getByRole('button', { name: /배분 계산/ }).click()
  await page.getByRole('button', { name: /창고 부족 \(2\)/ }).click()
  await page.getByRole('button', { name: /매장 간 RT 로 채우기/ }).click()
  const dlg = page.getByRole('dialog', { name: '창고 부족을 매장 간 RT 로 채우기' })
  await expect(dlg).toContainText('RT 로 채움')
  const t = dlg.getByRole('table', { name: '매장 간 RT 추천 목록' })
  await expect(t.getByRole('row').nth(1)).toContainText('창고 부족')
  await t.getByLabel('추천 모두 선택').check()
  await shot(page, 'stock-short-rt')
  await dlg.getByRole('button', { name: /본사지시 RT 지시 \(1건 · 2장\)/ }).click()
  await page.getByRole('dialog', { name: '본사지시 RT 지시 등록' }).getByRole('button', { name: '2장 지시' }).click()
  await expect(dlg).toContainText(`지시번호 ${ymd(now)}00050`)
  expect(api.find('POST', '/api/stock-rt/alloc/short-rt/register')[0].body).toEqual({ keys: [['SWWBLQ42010', 'IV', '77', 'S32017', 'S21018']], indcDt: isoDay(now) })
  expect(Object.fromEntries(api.find('POST', '/api/stock-rt/alloc/short-rt/register')[0].query)).toMatchObject({ brand: 'S', wh: 'IN', base: '202609003' })
  await expect.poll(() => api.find('GET', '/api/stock-rt/alloc/short-rt').filter((r) => r.query.get('refresh') === 'true').length).toBe(1)
})

test('AI 대화 [화면에서 열기]: 다른 메뉴에서 눌러도 재고 재배치 화면을 그 조건으로 열고 계산', async ({ page, mockApi }) => {
  const user = makeUser('USER', ['stock_rt', 'invt_plan'])
  user.ai = { ...user.ai, enabled: true, userEnabled: true, dailyQuestions: 10, dailyCostUsd: 2 }
  const api = await mockApi(user)
  api.on('GET', '/api/invt-plans/options', () => ({ json: { areas: [], regions: [], areaRegion: {}, invtTypes: ['정기'], stlmTeams: [], rmkMaxBytes: 200, encoding: 'utf-8' } }))
  api.on('GET', '/api/invt-plans', () => ({ json: { plans: [] } }))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: { ...RT, brand: 'T', brandNm: '리스트' } }))
  const from = isoDay(daysAgo(13))
  const events = [
    { type: 'conversation', id: 'c1', title: '리스트 RT' },
    { type: 'tool', id: 't1', name: 'open_stock_rt_screen', label: '재고 재배치 화면 열기', input: { brand: '리스트', seasons: ['겨울'] } },
    { type: 'action', id: 't1', actionKind: 'open_stock', title: '재고 재배치 추천 화면 · 리스트 매장 간 RT',
      items: [{ tab: 'rt', brand: 'T', view: 'unfilled', run: true, cond: { dateFrom: from, dateTo: isoDay(now), seasons: ['C0074'], prdt: 'TWK' } }],
      lines: ['브랜드: 리스트 · 매장 간 RT', `판매 기간: ${from} ~ ${isoDay(now)}`, '시즌: 겨울'], warnings: [] },
    { type: 'tool_done', id: 't1', ok: true },
    { type: 'text_start' }, { type: 'text', text: '아래 [화면에서 열기]를 누르세요.' }, { type: 'done' },
  ]
  api.on('GET', '/api/chat/usage', () => ({ json: { questions: 0, costUsd: 0, inputTokens: 0, outputTokens: 0, questionLimit: 10, costLimitUsd: 2, enabled: true } }))
  api.on('POST', '/api/chat', () => ({ body: Buffer.from(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')), headers: { 'Content-Type': 'text/event-stream' } }))
  await page.goto('/?view=invt_plan')
  await page.getByRole('button', { name: 'AI 데이터 어시스턴트' }).click()
  await page.getByPlaceholder(/데이터에 대해 질문하세요/).fill('리스트 겨울 2주 RT 화면으로 보여줘')
  await page.keyboard.press('Enter')
  const card = page.locator('.action-card')
  await expect(card).toContainText('시즌: 겨울')
  expect(api.find('GET', '/api/stock-rt/rt')).toHaveLength(0)            // 카드만으로는 열지 않음
  await card.getByRole('button', { name: '화면에서 열기' }).click()
  await expect.poll(() => api.find('GET', '/api/stock-rt/rt').length).toBe(1)
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/rt')[0].query)).toMatchObject({ brand: 'T', dateFrom: from, dateTo: isoDay(now), seasons: 'C0074', prdt: 'TWK' })
  await expect(page.getByRole('table', { name: '못 채운 수요' })).toBeVisible()
  await expect(page.getByRole('button', { name: '리스트', exact: true })).toHaveClass(/active/)
  await expect(page.getByLabel('품번', { exact: true })).toHaveValue('TWK')
})

test('AI 가 고른 RT 추천: [화면에서 열고 선택]을 누르면 같은 조건으로 계산하고 그 행만 체크 (등록은 관리자가 직접)', async ({ page, mockApi }) => {
  const user = makeUser('ADMIN')
  user.ai = { ...user.ai, enabled: true, userEnabled: true, dailyQuestions: 10, dailyCostUsd: 2 }
  const api = await mockApi(user)
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S', true) }))
  api.on('GET', '/api/stock-rt/rt', () => ({ json: RT }))
  const cond = { dateFrom: RT.from, dateTo: RT.to, planYy: [], seasons: [], teams: [], prdt: '', per: 1, order: 'slow', senderMax: 0, limits: false }
  const events = [
    { type: 'conversation', id: 'c1', title: 'RT 고르기' },
    { type: 'tool', id: 't1', name: 'pick_store_rt_rows', label: 'RT 추천 골라 선택', input: { min_fail_cnt: 2 } },
    { type: 'action', id: 't1', actionKind: 'open_stock', title: '매장 간 RT 추천 골라 선택 · 쉬즈미스 1건',
      items: [{ tab: 'rt', brand: 'S', view: 'rows', run: true, cond, select: { keys: [['SWWSLQ42230', 'LG', '44', 'S11003', 'S21018']], label: '자동RT 취소 2회 이상' } }],
      lines: ['고른 기준: 자동RT 취소 2회 이상', '선택: 1건 · 1장 (추천 2건 중)'], warnings: [] },
    { type: 'tool_done', id: 't1', ok: true }, { type: 'text_start' }, { type: 'text', text: '카드를 누르세요.' }, { type: 'done' },
  ]
  api.on('GET', '/api/chat/usage', () => ({ json: { questions: 0, costUsd: 0, inputTokens: 0, outputTokens: 0, questionLimit: 10, costLimitUsd: 2, enabled: true } }))
  api.on('POST', '/api/chat', () => ({ body: Buffer.from(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')), headers: { 'Content-Type': 'text/event-stream' } }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('button', { name: 'AI 데이터 어시스턴트' }).click()
  await page.getByPlaceholder(/데이터에 대해 질문하세요/).fill('자동RT 취소 2회 이상만 골라줘')
  await page.keyboard.press('Enter')
  const card = page.locator('.action-card')
  await card.getByRole('button', { name: '화면에서 열고 선택' }).click()
  await expect.poll(() => api.find('GET', '/api/stock-rt/rt').length).toBe(1)
  expect(Object.fromEntries(api.find('GET', '/api/stock-rt/rt')[0].query)).toMatchObject({ brand: 'S', dateFrom: RT.from, dateTo: RT.to, order: 'slow' })
  await expect(page.locator('.stock-ai-pick')).toContainText('자동RT 취소 2회 이상 · 1건 · 1장')
  const table = page.getByRole('table', { name: '매장 간 RT 추천 목록' })
  await expect(table.getByRole('row')).toHaveCount(2)                                  // 고른 것만 보기
  await expect(table.getByLabel('SWWSLQ42230 S11003→S21018 선택')).toBeChecked()
  await expect(page.getByRole('button', { name: /본사지시 RT 지시 \(1건 · 1장\)/ })).toBeEnabled()
  expect(api.find('POST', '/api/stock-rt/rt/register')).toHaveLength(0)              // 등록은 하지 않음
  await shot(page, 'stock-ai-pick')
  await page.getByLabel('고른 것만 보기').uncheck()
  await expect(table.getByRole('row')).toHaveCount(3)
})

test('RT 성과: 이 화면 지시 · 본사지시 전체, 수락률 · 판매 전환 · 거부 사유 (추천 계산 없이도)', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', (_, url) => ({ json: OPTIONS(url.searchParams.get('brand') || 'S') }))
  const shop = (shopId: string, shopNm: string, accepted: number, denied: number) => ({ shopId, shopNm, team: '쉬즈1팀', total: accepted + denied, accepted,
    denied, autoDenied: 0, pending: 0, canceled: 0, acceptRate: Math.round((accepted / (accepted + denied)) * 1000) / 10, avgHours: 12.5, sold: 3, soldRate: 20 })
  const empty = { total: 0, byStatus: [], accepted: 0, denied: 0, autoDenied: 0, pending: 0, canceled: 0, acceptRate: null, avgHours: null, sold: 0, soldRate: null,
    maturedAccepted: 0, maturedSold: 0 }
  const full = { total: 100, byStatus: [], accepted: 70, denied: 20, autoDenied: 5, pending: 5, canceled: 0, acceptRate: 73.7, avgHours: 12.2, sold: 14, soldRate: 20,
    maturedAccepted: 40, maturedSold: 10 }
  api.on('GET', '/api/stock-rt/rt/performance', (_, url) => {
    const all = url.searchParams.get('scope') === 'all'
    return { json: { brand: 'S', brandNm: '쉬즈미스', from: '', to: '', scope: all ? 'all' : 'web', asOf: 'x', soldDays: 7, summary: all ? full : empty,
      senders: all ? [shop('S11003', '롯데잠실', 2, 8), shop('S11016', '롯데영등포', 60, 10)] : [], receivers: [],
      reasons: [{ reason: '판매', qty: 12 }, { reason: '자동거부 (3일 무응답)', qty: 5 }], days: [] } }
  })
  await page.goto('/?view=stock_rt')
  await page.getByRole('button', { name: 'RT 성과 보기' }).click()
  await expect(page.locator('.stock-perf')).toContainText('이 화면에서 지시한 RT 가 없습니다')
  await page.getByRole('button', { name: '본사지시 전체' }).click()
  await expect(page.locator('.stock-perf .summary-pills')).toContainText('73.7%')
  await expect(page.locator('.stock-perf .summary-pills')).toContainText('7일 지난 건 25%')
  const t = page.getByRole('table', { name: 'RT 성과 보내는 매장' })
  await expect(t.getByRole('row').nth(1)).toHaveClass(/row-short/)                     // 수락률 50% 미만
  await shot(page, 'stock-rt-perf')
  await page.getByRole('button', { name: '거부 사유' }).click()
  await expect(page.locator('.stock-perf')).toContainText('자동거부 (3일 무응답)')
  expect(api.find('GET', '/api/stock-rt/rt/performance').map((r) => r.query.get('scope'))).toEqual(['web', 'all'])
})
