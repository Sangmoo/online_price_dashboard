// 실사계획 달력 보기 · 판매 현황 한 장 보고서
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png` }) : Promise.resolve())

const OPTIONS = { areas: ['서울특별시'], regions: ['수도권'], areaRegion: {}, invtTypes: ['정기'], stlmTeams: ['1팀', '2팀'], rmkMaxBytes: 200, encoding: 'utf-8' }
const now = new Date()
const ymd = (day: number) => `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(day).padStart(2, '0')}`
const lastInvt = ymd(1)
const plan = (id: number, shopNm: string, dt: string | null, team: string | null) => ({
  planId: id, shopId: `S${1000 + id}`, shopNm, brdNm: '쉬즈미스', shopFormNm: '백화점', moBrdCd: 'S', invtPlanDt: dt, stlmTeam: team, baseFee: 100000, expectAmt: 900000,
  lastInvtDt: lastInvt, twiceYearYn: 'N', prevSaleAmt: null, currSaleAmt: null, prevSaleMil: null, currSaleMil: null, saleRate: null, addr: null, areaNm: null,
  regionNm: null, prevInvtType: null, prevInvtResult: null, elapsedDays: 0, stockQty: null, stockBaseDt: null, invtPlanNote: '정기 실사', rmk: null,
  shopRankNm: null, smasrNm: null, smasrHp: null, shopTel: null, insDay: null, insUserId: null, uptDay: null, uptUserId: null,
})

test('실사계획 달력: 예정일 칸에 매장이 보이고, 끌어 놓으면 확인 후 날짜가 바뀌며 보기 방식은 사용자별로 저장된다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['invt_plan']))
  const plans = [plan(1, '현대서울', ymd(10), '1팀'), plan(2, '롯데본점', ymd(10), '2팀'), plan(3, '신세계강남', null, null)]
  api.on('GET', '/api/invt-plans/options', () => ({ json: OPTIONS }))
  api.on('GET', '/api/invt-plans', () => ({ json: { plans } }))
  api.on('PUT', /^\/api\/invt-plans\/\d+$/, (req) => {
    const id = Number(new URL(req.url()).pathname.split('/').pop())
    const body = req.postDataJSON() as { invtPlanDt: string | null }
    return { json: { plan: { ...plans.find((p) => p.planId === id)!, invtPlanDt: body.invtPlanDt } } }
  })
  await page.goto('/?view=invt_plan')
  await page.getByRole('button', { name: '달력' }).click()
  await expect.poll(() => api.find('PUT', '/api/prefs/invt.view').map((c) => c.body)).toEqual([{ value: 'calendar' }])

  const day10 = page.locator(`[data-day="${ymd(10)}"]`)
  await expect(day10.getByRole('button', { name: /현대서울/ })).toBeVisible()
  await expect(day10).toContainText('2곳 · 200만원')
  await expect(page.getByLabel('미정').getByRole('button', { name: /신세계강남/ })).toBeVisible()
  await expect(page.locator('.cal-chip.t1')).toHaveCount(1)              // 정산 1팀 색
  await shot(page, 'invt-calendar')

  // 10일 → 15일로 끌어 놓기
  page.once('dialog', (d) => { expect(d.message()).toContain('현대서울'); d.accept() })
  await day10.getByRole('button', { name: /현대서울/ }).dragTo(page.locator(`[data-day="${ymd(15)}"]`))
  await expect.poll(() => api.find('PUT', '/api/invt-plans/1').map((c) => c.body)).toEqual([{ invtPlanDt: ymd(15) }])
  await expect(page.locator(`[data-day="${ymd(15)}"]`).getByRole('button', { name: /현대서울/ })).toBeVisible()

  // 미정 → 날짜 (확정)
  page.once('dialog', (d) => d.accept())
  await page.getByLabel('미정').getByRole('button', { name: /신세계강남/ }).dragTo(page.locator(`[data-day="${ymd(20)}"]`))
  await expect.poll(() => api.find('PUT', '/api/invt-plans/3').map((c) => c.body)).toEqual([{ invtPlanDt: ymd(20) }])

  // 칩을 누르면 수정 팝업
  await page.locator(`[data-day="${ymd(10)}"]`).getByRole('button', { name: /롯데본점/ }).click()
  await expect(page.getByRole('heading', { name: '실사계획 수정 · 롯데본점' })).toBeVisible()
})

test('실사계획: 저장된 보기 방식(달력)으로 열린다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['invt_plan']))
  api.on('GET', '/api/invt-plans/options', () => ({ json: OPTIONS }))
  api.on('GET', '/api/invt-plans', () => ({ json: { plans: [] } }))
  api.on('GET', '/api/prefs/invt.view', () => ({ json: { value: 'calendar' } }))
  await page.goto('/?view=invt_plan')
  await expect(page.getByRole('grid', { name: '실사 달력' })).toBeVisible()
})

test('판매 현황 한 장 보고서: A4 가로 미리보기 · PDF(인쇄) · PNG 저장', async ({ page, mockApi }) => {
  await mockApi(makeUser('USER', ['sale_dashboard']))
  await page.addInitScript(() => {
    const w = window as unknown as { __printed: string[] }
    w.__printed = []
    // 인쇄 순간: 제목 · 보고서 복사본(#print-host)이 있는지 기록하고, 인쇄 화면 확인용으로 복사본을 남겨 둔다
    window.print = () => {
      const h = document.getElementById('print-host')
      w.__printed.push(`${document.title}|${h?.querySelectorAll('.report-page').length ?? 0}`)
      if (h) { const keep = h.cloneNode(true) as HTMLElement; h.id = 'print-host-old'; document.body.appendChild(keep) }
    }
  })
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: '한 장 보고서' }).click()
  const dlg = page.getByRole('dialog', { name: '한 장 보고서' })
  const sheet = dlg.locator('.report-page')
  await expect(sheet).toContainText('판매 현황 보고')
  await expect(sheet).toContainText('실판금액 194.3억 — 전년 동기 대비 -6.7%')          // 핵심 요약 문장
  await expect(sheet).toContainText('목표 달성률 81.2%')
  expect(await sheet.evaluate((el) => [el.clientWidth, el.clientHeight])).toEqual([1123, 794])   // A4 가로
  expect(await sheet.evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true)          // 한 장 안에 들어감
  await shot(page, 'sale-report')

  await dlg.getByRole('button', { name: /PDF 저장/ }).click()
  expect(await page.evaluate(() => (window as unknown as { __printed: string[] }).__printed)).toEqual(['판매현황_보고_2026-08|1'])

  // 인쇄 화면에는 보고서만 · A4 가로 1장
  await page.emulateMedia({ media: 'print' })
  expect(await page.locator('#root').evaluate((el) => getComputedStyle(el).display)).toBe('none')     // 앱 화면은 통째로 빠짐
  await expect(page.locator('#print-host .report-page')).toBeVisible()
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true })
  expect((pdf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) ?? []).length).toBe(1)
  await page.emulateMedia({ media: 'screen' })
  await page.evaluate(() => document.getElementById('print-host')?.remove())

  const dl = page.waitForEvent('download')
  await dlg.getByRole('button', { name: /이미지/ }).click()
  expect((await dl).suggestedFilename()).toBe('판매현황_보고_2026-08.png')
})
