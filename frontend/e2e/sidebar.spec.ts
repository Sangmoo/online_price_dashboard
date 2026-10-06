// 좌측 메뉴: 창이 낮아도 서비스명이 잘리지 않고 메뉴 영역만 스크롤, 로그인 정보는 아래에 고정
import { expect, makeUser, test } from './mock'

test('좌측 메뉴: 낮은 창에서 메뉴 영역만 스크롤되고 서비스명 · 로그인 정보는 온전히 보인다', async ({ page, mockApi }) => {
  await page.setViewportSize({ width: 1280, height: 620 })
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/notices/board', () => ({ json: { notices: [], total: 0, table: { ready: true, missing: [], ddl: '' } } }))
  await page.goto('/?view=notice')
  const scroll = page.locator('.sidebar-scroll')
  const brand = page.locator('.sidebar-brand')
  const user = page.locator('.sidebar > .user-card')
  await expect(user).toBeVisible()
  const sb = (await page.locator('.sidebar').boundingBox())!
  const bb = (await brand.boundingBox())!
  const ub = (await user.boundingBox())!
  expect(bb.height).toBeGreaterThan(50)                                              // 서비스명이 눌려 잘리지 않음
  expect(ub.y + ub.height).toBeLessThanOrEqual(sb.y + sb.height + 1)                 // 로그인 정보는 창 안 아래쪽
  expect(await scroll.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true) // 넘치면 메뉴 영역이 스크롤
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\sidebar-top.png` })
  await scroll.hover()
  await page.mouse.wheel(0, 1000)
  await expect.poll(() => scroll.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  await expect(page.locator('.side-item', { hasText: '메뉴 접기' })).toBeInViewport()
  expect((await user.boundingBox())!.y).toBe(ub.y)                                   // 스크롤해도 로그인 정보 위치 그대로
  expect(await page.evaluate(() => window.scrollY)).toBe(0)                           // 본문은 움직이지 않음
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\sidebar-scrolled.png` })
})
