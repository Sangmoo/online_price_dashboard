// 지표 정의 · 도움말 창, 팝업이 열려 있을 때 뒤 페이지 스크롤 막기
import { expect, makeUser, test } from './mock'

const dashboard = {
  start: '20261001', end: '20261007', generatedAt: '2026-10-07 09:00:00',
  kpi: { ROW_CNT: 1000, PRDT_CNT: 100, MALL_CNT: 5, SELLER_CNT: 40, DAY_CNT: 7, AVG_DC_RATE: 8.1, MAX_DC_RATE: 40, DEEP_DC_CNT: 3, SHOP_ROW_CNT: 250, SHOP_CNT: 2 },
  daily: [], malls: [], mallDiscount: [], histogram: [], shops: [],
  topProducts: Array.from({ length: 20 }, (_, i) => ({
    PRDT_CD: `TA${i}`, TITLE: '상품', PRICE: 100000, MIN_DC_PRICE: 80000, MAX_DC_RATE: 20, MIN_MALL: 'SSG', MIN_DT: '20261007', MALL_CNT: 2, ROW_CNT: 5,
  })),
}

async function openDashboard(page: import('@playwright/test').Page, mockApi: (u: ReturnType<typeof makeUser>) => Promise<import('./mock').MockApi>) {
  const api = await mockApi(makeUser('USER', ['dashboard']))
  api.on('GET', '/api/dates', () => ({ json: { dates: [{ dt: '20261007', count: 1000 }] } }))
  api.on('GET', '/api/dashboard', () => ({ json: dashboard }))
  await page.goto('/?view=dashboard')
  await expect(page.getByText('할인율 상위 상품 Top 20')).toBeVisible()
  return api
}

test('도움말: 상단 버튼으로 전체를 열고 검색, 지표 옆 (?) 는 그 지표를 강조해서 연다', async ({ page, mockApi }) => {
  await openDashboard(page, mockApi)
  await page.getByRole('button', { name: '도움말', exact: true }).click()
  const modal = page.getByRole('dialog', { name: '지표 정의 · 도움말' })
  await expect(modal.getByRole('heading', { name: '원가율' })).toBeVisible()
  await modal.getByPlaceholder(/지표 · 계산식/).fill('세일')
  await expect(modal.locator('.help-entry')).toHaveCount(1)
  await expect(modal.locator('.help-entry h4')).toHaveText('세일 비중')
  await page.keyboard.press('Escape')
  await expect(modal).toHaveCount(0)

  await page.getByRole('button', { name: '평균 할인율 도움말' }).click()
  const active = modal.locator('.help-entry.active')
  await expect(active).toHaveCount(1)
  await expect(active.locator('h4')).toHaveText('평균 할인율 (온라인)')
  await expect(active).toBeInViewport()
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\help-modal.png` })
})

test('팝업이 열려 있으면 마우스 휠로 팝업만 스크롤되고 뒤 페이지는 움직이지 않는다', async ({ page, mockApi }) => {
  await page.setViewportSize({ width: 1280, height: 700 })
  await openDashboard(page, mockApi)
  await page.mouse.move(700, 400)
  await page.mouse.wheel(0, 400)
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)   // 팝업 전에는 페이지가 스크롤됨
  const before = await page.evaluate(() => window.scrollY)

  await page.getByRole('button', { name: '도움말', exact: true }).click()
  const body = page.locator('.help-body')
  await expect(body).toBeVisible()
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe('hidden')

  const box = (await body.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 30; i++) await page.mouse.wheel(0, 600)                  // 팝업 끝까지 + 더 내림
  await expect.poll(() => body.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  await page.mouse.move(20, 20)                                                // 팝업 바깥(어두운 배경)에서 휠
  await page.mouse.wheel(0, 800)
  await page.waitForTimeout(300)
  expect(await page.evaluate(() => window.scrollY)).toBe(before)

  await page.keyboard.press('Escape')
  await page.mouse.move(700, 400)
  await page.mouse.wheel(0, -300)
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeLessThan(before)   // 닫으면 다시 페이지 스크롤
})
