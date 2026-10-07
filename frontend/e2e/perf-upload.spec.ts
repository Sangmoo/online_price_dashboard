// 쿼리 성능(관리자) · 실행 계획 · 엑셀 업로드로 한 번에 등록(실사계획 · 판매처 매장 연결)
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png` }) : Promise.resolve())

const RAW = 'SELECT MAKE_YYMM, SUM(QTY) FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN (:m0, :m1) GROUP BY MAKE_YYMM'
const FILLED = "SELECT MAKE_YYMM, SUM(QTY) FROM T_CLOSE_SALE_BASE WHERE MAKE_YYMM IN ('202608', '202609') GROUP BY MAKE_YYMM"
const PERF = {
  since: '2026-10-07 09:00:00', serverStarted: '2026-10-07 09:00:00', slowSqlSec: 3, slowRequestSec: 5, days: 7,
  funcs: [{ fn: 'sale_monthly._group', where: [{ menu: '월별 매장별 판매 집계', feature: '요약 (월 · 매장 · 시즌 등)' }], count: 12, totalMs: 48000,
    avgMs: 4000, maxMs: 9100, slow: 5, sqls: 2, lastAt: '2026-10-07 09:30:00' }],
  slowSql: [{ sql: RAW, raw: RAW, filled: FILLED, fn: 'sale_monthly._group', where: [{ menu: '월별 매장별 판매 집계', feature: '요약' }],
    count: 12, avgMs: 4000, maxMs: 9100, maxAt: '2026-10-07 09:20:00', maxUsr: '250016', slow: 5, lastAt: '2026-10-07 09:30:00' }],
  requests: [{ method: 'GET', path: '/api/sale-monthly/summary', menu: '월별 매장별 판매 집계', count: 172, avgMs: 292, p95Ms: 948, maxMs: 22024, slow: 3, lastAt: '2026-10-06 22:21:25' }],
  daily: [{ day: '2026-10-06', requests: 1363, slow: 20, p95Ms: 1201, avgMs: 997 }, { day: '2026-10-07', requests: 159, slow: 0, p95Ms: 649, avgMs: 148 }],
  logSlowSql: [{ sql: 'SELECT SET_KEY, SET_VAL FROM T_ERP_WEB_SETTING', count: 1, maxMs: 124800, avgMs: 124800, binds: '[]', lastAt: '2026-10-06 18:09:03', truncated: false },
    { sql: 'SELECT A, B FROM ( SELECT …', count: 2, maxMs: 5000, avgMs: 4500, binds: "['lo']", lastAt: '2026-10-06 12:00:00', truncated: true }],
}
const PLAN = (s: string) => ({
  sqlId: 'abc', at: '2026-10-07 10:00:00',
  actual: s.includes(':m0') ? { sqlId: 'abc', planHash: 1, children: 1, executions: 12, avgMs: 4000, bufferGets: 120000, diskReads: 30, rows: 2,
    lastActive: '2026-10-07 09:30:00', plan: '| 0 | SELECT STATEMENT |\n|* 1 |  TABLE ACCESS FULL | T_CLOSE_SALE_BASE |' } : null,
  estimate: { plan: '| 0 | SELECT STATEMENT |\n|* 1 |  INDEX RANGE SCAN | IDX_MAKE_YYMM |' },
})

test('관리자 쿼리 성능: 요청 · 기능별 · 느린 쿼리 순위를 보고 실행 계획(실제 · 예상)을 연다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/perf', () => ({ json: PERF }))
  api.on('POST', '/api/admin/perf/clear', () => ({ json: { since: '2026-10-07 10:00:00' } }))
  api.on('POST', '/api/admin/sql/explain', (req) => ({ json: PLAN((req.postDataJSON() as { sql: string }).sql) }))
  await page.goto('/?view=admin')
  await page.getByRole('button', { name: '쿼리 성능' }).click()
  await expect(page.getByRole('heading', { name: '화면 요청 응답 시간' })).toBeVisible()
  await expect(page.getByText('/api/sale-monthly/summary')).toBeVisible()
  await expect(page.locator('.perf-table').nth(1)).toContainText('sale_monthly._group')
  await shot(page, 'perf-tab')

  // 느린 쿼리 → 실행 계획: 실제 계획(커서 캐시) + 전체 스캔 줄 강조
  await page.locator('.perf-table').nth(2).getByRole('button', { name: '실행 계획' }).click()
  const dlg = page.getByRole('dialog', { name: '실행 계획' })
  await expect(dlg.getByText('실행 12회')).toBeVisible()
  await expect(dlg.locator('.plan-hot').first()).toContainText('TABLE ACCESS FULL')
  expect((api.find('POST', '/api/admin/sql/explain')[0].body as { sql: string }).sql).toBe(RAW)
  await shot(page, 'plan-modal')
  await dlg.getByRole('button', { name: '값 채운 쿼리' }).click()
  await expect(dlg.getByText(/커서 캐시에 없습니다|앱이 실제로 보낸 문장이 아니라/)).toBeVisible()
  expect((api.find('POST', '/api/admin/sql/explain')[1].body as { sql: string }).sql).toBe(FILLED)
  await page.keyboard.press('Escape')
  await expect(dlg).toBeHidden()

  // 로그에 앞부분만 남은 쿼리는 실행 계획 버튼이 꺼져 있다
  await expect(page.locator('.perf-table').nth(3).getByRole('button', { name: '실행 계획' }).nth(1)).toBeDisabled()

  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: /쿼리 기록 초기화/ }).click()
  await expect.poll(() => api.find('POST', '/api/admin/perf/clear').length).toBe(1)
})

const INVT_OPTIONS = { areas: ['서울특별시'], regions: ['수도권'], areaRegion: {}, invtTypes: ['정기'], stlmTeams: ['1팀', '2팀'], rmkMaxBytes: 200, encoding: 'utf-8' }
const XLSX = { name: 'upload.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('PKfake') }

test('실사계획 엑셀 업로드: 양식 → 미리보기(자동 입력 · 오류 행) → 정상 · 주의 행만 저장', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['invt_plan']))
  api.on('GET', '/api/invt-plans/options', () => ({ json: INVT_OPTIONS }))
  api.on('GET', '/api/invt-plans', () => ({ json: { plans: [] } }))
  api.on('GET', '/api/invt-plans/upload-template', () => ({
    body: Buffer.from('PK'), headers: { 'Content-Type': 'application/octet-stream', 'Content-Disposition': "attachment; filename*=UTF-8''%EC%96%91%EC%8B%9D.xlsx" },
  }))
  const rows = [
    { row: 2, status: 'warn', messages: ['이미 등록된 실사계획 1건이 있습니다 (새 계획으로 추가).'], auto: ['shopNm', 'brdNm'],
      values: { shopId: 'A11001', shopNm: '현대서울', brdNm: '시스티나', invtPlanDt: '20261103' },
      display: { shopId: 'A11001', shopNm: '현대서울', brdNm: '시스티나', invtPlanDt: '20261103' } },
    { row: 3, status: 'ok', messages: [], auto: ['shopNm'], values: { shopId: 'T22002', shopNm: '롯데본점' }, display: { shopId: 'T22002', shopNm: '롯데본점' } },
    { row: 4, status: 'error', messages: ['매장(T_SHOP)에 없는 매장코드: ZZ0001'], values: { shopId: 'ZZ0001' }, display: { shopId: 'ZZ0001' } },
  ]
  api.on('POST', '/api/invt-plans/upload/preview', () => ({ json: { rows, summary: { total: 3, ok: 1, warn: 1, error: 1 } } }))
  api.on('POST', '/api/invt-plans/upload/apply', () => ({ json: { saved: 2, skipped: 0, errors: [] } }))
  await page.goto('/?view=invt_plan')
  await page.getByRole('button', { name: '엑셀 업로드' }).click()
  const dlg = page.getByRole('dialog', { name: '실사계획 엑셀 업로드' })
  await expect(dlg.getByText(/매장코드만 적으면/)).toBeVisible()

  const dl = page.waitForEvent('download')
  await dlg.getByRole('button', { name: /업로드 양식/ }).click()
  expect((await dl).suggestedFilename()).toBe('양식.xlsx')

  await dlg.getByLabel('엑셀 파일').setInputFiles(XLSX)
  await expect(dlg.getByText('현대서울')).toBeVisible()
  expect(String((api.find('POST', '/api/invt-plans/upload/preview')[0].body as { file: string }).file)).toMatch(/^data:/)
  await expect(dlg.getByRole('cell', { name: '현대서울' })).toHaveClass(/auto-cell/)                 // 자동 입력 표시
  await expect(dlg.getByText('2026-11-03')).toBeVisible()
  await shot(page, 'upload-invt')
  await dlg.getByRole('button', { name: '오류 1' }).click()
  await expect(dlg.locator('tbody tr')).toHaveCount(1)

  page.once('dialog', (d) => d.accept())
  await dlg.getByRole('button', { name: '2건 저장' }).click()
  await expect(dlg).toBeHidden()
  const sent = (api.find('POST', '/api/invt-plans/upload/apply')[0].body as { rows: { row: number }[] }).rows
  expect(sent.map((r) => r.row)).toEqual([2, 3])
  await expect(page.getByText('실사계획 2건을 등록했습니다.')).toBeVisible()
  expect(api.find('GET', '/api/invt-plans').length).toBeGreaterThanOrEqual(2)                      // 저장 뒤 목록 새로고침
})

test('판매처 매장 연결 엑셀 업로드: 신규 · 변경 · 같음 표시, 바뀌는 행만 저장', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['dashboard', 'mall_shop']))
  api.on('GET', '/api/mall-shops', () => ({ json: { ready: true, days: 7, rows: [],
    summary: { combos: 0, sellers: 0, mapped: 0, unmapped: 0, malls: 0, rowsTotal: 0, rowsMapped: 0, rowsMappedPct: 0, shopFilled: 0 } } }))
  api.on('GET', '/api/mall-shops/shops', () => ({ json: { shops: [] } }))
  const v = (o: Record<string, unknown>) => ({ sellNo: '-', brdCd: 'S', brand: '쉬즈미스', useYn: 'Y', rmk: null, ...o })
  const rows = [
    { row: 2, status: 'ok', change: '신규', messages: [], values: v({ mallNm: '새몰', shopId: 'S1', shopNm: '매장1' }) },
    { row: 3, status: 'ok', change: '변경', messages: ['매장 S00001 → S00002'], values: v({ mallNm: '롯데온', shopId: 'S00002' }) },
    { row: 4, status: 'ok', change: '같음', messages: [], values: v({ mallNm: '하프클럽', shopId: 'S51005' }) },
  ]
  api.on('POST', '/api/mall-shops/upload/preview', () => ({ json: { rows, summary: { total: 3, ok: 3, warn: 0, error: 0,
    changes: { 신규: 1, 변경: 1, 해제: 0, 같음: 1 } } } }))
  api.on('POST', '/api/mall-shops/upload/apply', () => ({ json: { saved: 2, deleted: 0, changed: 2, skipped: 0 } }))
  await page.goto('/?view=mall_shop')
  await page.getByRole('button', { name: '엑셀 업로드' }).click()
  const dlg = page.getByRole('dialog', { name: '판매처 매장 연결 엑셀 업로드' })
  await dlg.getByLabel('엑셀 파일').setInputFiles(XLSX)
  await expect(dlg.getByText('매장 S00001 → S00002')).toBeVisible()
  await expect(dlg.getByText('신규 1 · 변경 1 · 같음 1')).toBeVisible()
  page.once('dialog', (d) => d.accept())
  await dlg.getByRole('button', { name: '2건 저장' }).click()
  await expect(page.getByText(/판매처 매장 연결을 저장했습니다 · 등록·수정 2건/)).toBeVisible()
  const sent = (api.find('POST', '/api/mall-shops/upload/apply')[0].body as { rows: { row: number }[] }).rows
  expect(sent.map((r) => r.row)).toEqual([2, 3])
})
