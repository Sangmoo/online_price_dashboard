// AI 주간 브리핑: 판매 현황 · 재고 재배치 추천 위 버튼 → 한 장 보고서 (AI 요약 + 숫자) · 다시 만들기 · AI 한도 시 숫자만
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png`, fullPage: true }) : Promise.resolve())
const now = new Date()
const ymd = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`

const BRIEF = (text: string | null) => ({
  period: { from: '2026-09-28', to: '2026-10-04' }, brands: ['쉬즈미스'],
  sales: { ranges: { prev: ['2026-09-21', '2026-09-27'], ly: ['2025-09-29', '2025-10-05'] }, brands: [{
    brand: 'S', brandNm: '쉬즈미스', curAmt: 2_530_000_000, curQty: 30000, vsPrev: 9.1, vsLy: -18.2,
    topShops: [{ shopId: 'S11001', shopNm: '롯데본점', amt: 120_000_000 }], topStyles: [{ prdtCd: 'SWWJKQ31710', amt: 33_000_000, qty: 221 }],
    days: ['09-28', '09-29', '09-30', '10-01', '10-02', '10-03', '10-04'].map((d, i) => ({ day: `2026-${d}`, amt: 300_000_000 + i * 20_000_000 })) }] },
  stock: [{ brand: 'S', brandNm: '쉬즈미스', rt: { total: 1280, accepted: 923, denied: 189, autoDenied: 168, pending: 0, acceptRate: 72.1, avgHours: 10, soldRate: 40.2 },
    pending: { rows: 177, shops: 24, urgent: 3, topShops: [] }, short: { allocQty: 272, demand: 300, short: 28, noStockSkus: 2, shortRows: 5 },
    turnover: { cover: 171.7, sellThru: 14, shortRows: 3279, overRows: 74440, overStock: 529686 },
    aging: { qty: 600000, agedQty: 120000, agedAmt: 9_000_000_000, agedRate: 20, agedShops: 200 },
    initial: { alloc: 133700, sold: 8500, sellThru: 6.4, overlap: 27.7, lowOverlap: 100, products: 537, period: '2026-08-26 ~ 2026-09-24' } }],
  ai: text ? { text, model: 'claude-opus-5-5' } : { text: null, blocked: '오늘 질문 한도(10회)를 모두 사용했습니다.' },
  errors: [], asOf: '2026-10-08 09:10', sec: 21.3, cached: false,
})
const OPTIONS = { canWrite: false, brand: 'S', brands: [{ code: 'S', name: '쉬즈미스' }], teams: [], seasons: [], prdtGrps: [], planYears: ['2026'], warehouses: [],
  bases: [], gradeGroups: [], recentRuns: [], defaultSeasons: [], defaultPlanYy: [], today: ymd, maxDays: 31 }

test('재고 재배치 추천의 [AI 주간 브리핑]: 브랜드 · AI 요약 · 숫자 · 다시 만들기', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['stock_rt']))
  api.on('GET', '/api/stock-rt/options', () => ({ json: OPTIONS }))
  api.on('GET', '/api/briefing/weekly', () => ({ json: BRIEF('### 핵심 요약\n- 주간 매출 25.3억, 전주 대비 +9.1%\n### 이번 주 할 일\n1. 미처리 RT 3건 확인') }))
  await page.goto('/?view=stock_rt')
  await page.getByRole('button', { name: 'AI 주간 브리핑' }).click()
  const dlg = page.getByRole('dialog', { name: 'AI 주간 브리핑' })
  await expect(dlg.locator('.brief-ai')).toContainText('전주 대비 +9.1%')
  await expect(dlg.locator('.brief-nums')).toContainText('72.1%')
  await expect(dlg.locator('.brief-nums')).toContainText('임박 3')
  await expect(dlg.locator('.brief-days .brief-day')).toHaveCount(7)
  expect(api.find('GET', '/api/briefing/weekly')[0].query.get('brand')).toBe('S')
  await shot(page, 'briefing')
  await dlg.getByRole('button', { name: '다시 만들기' }).click()
  await expect.poll(() => api.find('GET', '/api/briefing/weekly').map((r) => r.query.get('refresh'))).toEqual([null, 'true'])
  await page.keyboard.press('Escape')
  await expect(dlg).toBeHidden()
})

test('판매 현황의 [AI 주간 브리핑]: 브랜드 전체 · AI 한도면 숫자만', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  api.on('GET', '/api/briefing/weekly', () => ({ json: BRIEF(null) }))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: 'AI 주간 브리핑' }).click()
  const dlg = page.getByRole('dialog', { name: 'AI 주간 브리핑' })
  await expect(dlg.locator('.brief-blocked')).toContainText('한도')
  await expect(dlg.locator('.brief-nums')).toContainText('25.3억')
  expect(api.find('GET', '/api/briefing/weekly')[0].query.get('brand')).toBeNull()
})
