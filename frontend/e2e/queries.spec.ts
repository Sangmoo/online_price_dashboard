// 관리자 '사용 쿼리': 메뉴별 기능 SQL 보기 · 복사, 다크 모드 사용자별 저장
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png` }) : Promise.resolve())

const QUERIES = {
  page: 'detail', label: '일자별 상세', since: '2026-10-07 09:00:00',
  features: [
    { title: '수집 일자 목록', desc: '날짜 선택', items: [{
      fn: 'data_service.available_dates', title: null, file: 'backend/app/data_service.py', line: 124,
      sqls: ['SELECT DT, COUNT(*) AS CNT FROM T_SELECT_ONLINE_MNG_R WHERE DT >= :since GROUP BY DT ORDER BY DT DESC'],
      recent: [{ sql: 'SELECT DT, COUNT(*) AS CNT FROM T_SELECT_ONLINE_MNG_R WHERE DT >= :since GROUP BY DT ORDER BY DT DESC',
        filled: "SELECT DT, COUNT(*) AS CNT FROM T_SELECT_ONLINE_MNG_R WHERE DT >= '20260609' GROUP BY DT ORDER BY DT DESC",
        binds: { since: '20260609' }, at: '2026-10-07 09:10:00', ms: 42, count: 3 }],
    }] },
    { title: '매장코드 채우기', desc: '프로시저', items: [
      { fn: null, title: '프로시저 직접 실행', file: null, line: null, sqls: ['VARIABLE n NUMBER\nEXEC P_FILL_ONLINE_SHOP_ID(:a, :b, :n)\nPRINT n'], recent: [] },
    ] },
  ],
}

// 클립보드에 쓴 내용을 확인할 수 있게 가로챈다
const trapClipboard = (page: Page) => page.addInitScript(() => {
  const w = window as unknown as { __copied: string[] }
  w.__copied = []
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (t: string) => { w.__copied.push(t) } } })
})
const copied = (page: Page) => page.evaluate(() => (window as unknown as { __copied: string[] }).__copied)

test('관리자: [사용 쿼리] 로 현재 메뉴의 기능별 SQL 을 보고 복사한다 (최근 실행은 값 채워 복사)', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/rows', () => ({ json: { rows: [], total: 0, page: 1, size: 100, malls: [], shops: [] } }))
  api.on('GET', '/api/admin/queries', () => ({ json: QUERIES }))
  await trapClipboard(page)
  await page.goto('/?view=detail')
  const btn = page.getByRole('button', { name: '사용 쿼리' })
  await expect(btn).toBeVisible()
  // 도움말 바로 왼쪽
  const [qb, hb] = await Promise.all([btn.boundingBox(), page.getByRole('button', { name: '도움말' }).boundingBox()])
  expect(qb!.x).toBeLessThan(hb!.x)
  await btn.click()

  const dlg = page.getByRole('dialog', { name: '사용 쿼리' })
  await expect(dlg.getByRole('heading', { name: '사용 쿼리 · 일자별 상세' })).toBeVisible()
  expect(api.find('GET', '/api/admin/queries')[0].query.get('page')).toBe('detail')
  await expect(dlg.locator('pre.sql-code').first()).toContainText('FROM T_SELECT_ONLINE_MNG_R')
  await shot(page, 'query-modal')

  const item = dlg.locator('.q-item').first()
  await item.getByRole('button', { name: '복사', exact: true }).click()
  await expect(item.getByRole('button', { name: '복사됨' })).toBeVisible()
  expect((await copied(page))[0]).toBe('SELECT DT, COUNT(*) AS CNT FROM T_SELECT_ONLINE_MNG_R WHERE DT >= :since GROUP BY DT ORDER BY DT DESC;')

  await item.getByRole('button', { name: '최근 실행 1' }).click()
  await expect(item.getByText(':since', { exact: true })).toBeVisible()
  await item.getByRole('button', { name: '값 채워 복사' }).click()
  expect((await copied(page))[1]).toContain("DT >= '20260609'")

  // 기능 전체 복사: 주석(기능 · 함수 위치)과 함께
  await dlg.locator('.q-feature').nth(1).getByRole('button', { name: '기능 전체 복사' }).click()
  const all = (await copied(page))[2]
  expect(all).toContain('-- 매장코드 채우기')
  expect(all).toContain('EXEC P_FILL_ONLINE_SHOP_ID')

  // 검색
  await dlg.getByPlaceholder(/기능 · 함수 · 테이블 검색/).fill('P_FILL')
  await expect(dlg.locator('.q-feature')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(dlg).toBeHidden()
})

test('일반 사용자에게는 [사용 쿼리] 버튼이 없다', async ({ page, mockApi }) => {
  await mockApi(makeUser('USER', ['sale_dashboard']))
  await page.goto('/?view=sale_dashboard')
  await expect(page.getByRole('button', { name: '도움말' })).toBeVisible()
  await expect(page.getByRole('button', { name: '사용 쿼리' })).toHaveCount(0)
})

test('다크 모드는 사용자별 서버 설정으로 불러온다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  api.on('GET', '/api/prefs/ui.theme', () => ({ json: { value: 'dark' } }))
  await page.goto('/?view=sale_dashboard')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})
