// 관리자 '사용 쿼리': 메뉴별 기능 SQL 보기 · 복사, 다크 모드 사용자별 저장
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png` }) : Promise.resolve())

const SQL = 'SELECT DT, COUNT(*) AS CNT FROM T_SELECT_ONLINE_MNG_R WHERE DT >= :since GROUP BY DT ORDER BY DT DESC'
const FILLED = "SELECT DT, COUNT(*) AS CNT FROM T_SELECT_ONLINE_MNG_R WHERE DT >= '20260609' GROUP BY DT ORDER BY DT DESC"
const QUERIES = {
  page: 'detail', label: '일자별 상세', since: '2026-10-07 09:00:00',
  features: [
    { title: '수집 일자 목록', desc: '날짜 선택', items: [{
      fn: 'data_service.available_dates', title: null, file: 'backend/app/data_service.py', line: 124, sqls: [SQL], mine: true,
      runs: [{ sql: SQL, filled: FILLED, binds: { since: '20260609' }, at: '2026-10-07 09:10:00', ms: 42, count: 1, usr: '250016' }],
      older: [{ sql: SQL, filled: FILLED.replace('20260609', '20260601'), binds: { since: '20260601' }, at: '2026-10-07 09:00:00', ms: 40, count: 1, usr: '250016' }],
    }] },
    { title: '일자별 원본 조회', desc: '', items: [{
      fn: 'data_service.load_day', title: null, file: 'backend/app/data_service.py', line: 136,
      sqls: ['SELECT ONLINE_ID FROM T_SELECT_ONLINE_MNG_R WHERE DT = :dt'], runs: [], older: [], mine: false,
    }] },
    { title: '매장코드 채우기', desc: '프로시저', items: [
      { fn: null, title: '프로시저 직접 실행', file: null, line: null, sqls: ['VARIABLE n NUMBER\nEXEC P_FILL_ONLINE_SHOP_ID(:a, :b, :n)\nPRINT n'], runs: [], older: [] },
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

test('관리자: [사용 쿼리] 로 현재 메뉴의 기능별 SQL 을 보고 복사한다 (조회한 기능은 값이 채워진 실제 쿼리)', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/rows', () => ({ json: { rows: [], total: 0, page: 1, size: 100, malls: [], shops: [] } }))
  api.on('GET', '/api/admin/queries', () => ({ json: JSON.parse(JSON.stringify(QUERIES).replaceAll('250016', api.user!.id)) }))   // 내가 실행한 기록
  await trapClipboard(page)
  await page.goto('/?view=detail')
  const btn = page.getByRole('button', { name: '사용 쿼리' })
  await expect(btn).toBeVisible()
  // 도움말 바로 왼쪽
  const [qb, hb] = await Promise.all([btn.boundingBox(), page.getByRole('button', { name: '도움말' }).boundingBox()])
  expect(qb!.x).toBeLessThan(hb!.x)
  expect(hb!.x - (qb!.x + qb!.width)).toBeLessThanOrEqual(6)   // 도움말에 붙어 있음
  await btn.click()

  const dlg = page.getByRole('dialog', { name: '사용 쿼리' })
  await expect(dlg.getByRole('heading', { name: '사용 쿼리 · 일자별 상세' })).toBeVisible()
  expect(api.find('GET', '/api/admin/queries')[0].query.get('page')).toBe('detail')
  await shot(page, 'query-modal')

  // 조회한 기능: 바인드 변수가 아닌 실제 값이 들어간 쿼리를 보여주고 그대로 복사
  const ran = dlg.locator('.q-item').first()
  await expect(ran.getByText('실제 실행 · 내 최근 조회')).toBeVisible()
  await expect(ran.locator('pre.sql-code')).toHaveText(FILLED)
  // 복사 버튼은 SQL 위 막대에 있어 SQL 을 가리지 않는다
  const [btnBox, preBox] = await Promise.all([ran.getByRole('button', { name: '복사', exact: true }).boundingBox(), ran.locator('pre.sql-code').boundingBox()])
  expect(btnBox!.y + btnBox!.height).toBeLessThanOrEqual(preBox!.y)
  await ran.getByRole('button', { name: '복사', exact: true }).click()
  await expect(ran.getByRole('button', { name: '복사됨' })).toBeVisible()
  expect((await copied(page))[0]).toBe(`${FILLED};`)
  await ran.getByRole('button', { name: /이전 실행 1개/ }).click()
  await expect(ran.locator('pre.sql-code').nth(1)).toContainText("'20260601'")
  await ran.getByRole('button', { name: /코드 기준 SQL 1개/ }).click()
  await expect(ran.locator('pre.sql-code').nth(2)).toContainText(':since')

  // 아직 조회하지 않은 기능은 코드 기준
  const notRan = dlg.locator('.q-item').nth(1)
  await expect(notRan.getByText('조회 전 · 코드 기준')).toBeVisible()
  await expect(notRan.locator('pre.sql-code')).toContainText('DT = :dt')

  // 기능 전체 복사: 실제 실행 쿼리 우선, 주석(기능 · 함수 위치 · 실행 시각)과 함께
  await dlg.locator('.q-feature').first().getByRole('button', { name: '기능 전체 복사' }).click()
  const all = (await copied(page))[1]
  expect(all).toContain('-- 수집 일자 목록')
  expect(all).toContain(`${FILLED};`)
  expect(all).not.toContain(':since')

  // 검색
  await dlg.getByPlaceholder(/기능 · 함수 · 테이블 · 값 검색/).fill('P_FILL')
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
