// AI 주간 브리핑: 판매 현황 · 재고 재배치 추천 위 버튼 → 한 장 보고서 (AI 요약 + 숫자) · 다시 만들기 · AI 한도 시 숫자만
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'
import { writeFileSync } from 'node:fs'

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

test('AI 주간 브리핑 하루 횟수를 넘으면 한도 초과 안내 (숫자 보고서는 그대로)', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  const b = BRIEF(null)
  api.on('GET', '/api/briefing/weekly', () => ({ json: { ...b, ai: { text: null, limit: true, blocked: 'AI 주간 브리핑 일일 사용량 한도 초과\n관리자에게 문의바랍니다.' },
    quota: { used: 3, limit: 3 } } }))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: 'AI 주간 브리핑' }).click()
  const dlg = page.getByRole('dialog', { name: 'AI 주간 브리핑' })
  const alert = dlg.getByRole('alert')
  await expect(alert).toContainText('AI 주간 브리핑 일일 사용량 한도 초과')
  await expect(alert).toContainText('관리자에게 문의바랍니다.')
  await expect(dlg.locator('.brief-nums')).toContainText('25.3억')
  await expect(dlg.getByRole('button', { name: /다시 만들기/ })).toContainText('3/3')
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

const LONG = `### 핵심 요약
- 3개 브랜드 합계 매출 약 67.6억(전주 54.8억 대비 +23.2%), 다만 전년 동기 72.0억 대비 -6.2%로 작년 수준은 아직 못 넘었습니다.
- 쉬즈미스 32.6억(전주 +30.3%, 전년 -1.4%)이 회복을 이끌었고, 시스티나는 10.0억으로 전년 대비 -18.2%로 가장 부진합니다.
- 10/3~10/4 주말 이틀에 매출이 몰렸습니다(쉬즈미스 5.8억·6.1억, 리스트 4.8억·5.0억). 연휴 효과로 보입니다.
- 재고 쪽은 쉬즈미스 RT 수락률 57.5%, 재고일수 175.3일, 리스트 장기 미판매 비중 24.7%가 눈에 띕니다.
### 판매
- 쉬즈미스: 35,633장, 자사몰 3.7억·퀸잇 7,767만·스타필드코엑스 7,204만 순. 스타일은 SWWSLQ42230(5,569만), SWWJKQ32070(5,512만)이 금액 상위.
- 리스트: 24.9억(전주 +20.8%, 전년 -6.7%), 신세계대구 9,911만·롯데아울렛광주월드컵 7,405만. TWWJPQ72040 4,798만으로 주력.
- 시스티나: 전주 +9.1%에 그쳐 세 브랜드 중 회복폭이 가장 작습니다. 스타필드수원 6,897만이 자사몰 다음입니다.
### 재고 · 재배치
- 쉬즈미스 RT 5,694건 중 자동거부 1,534건, 수락률 57.5%로 리스트·시스티나(각 72.0%, 72.1%)보다 낮습니다.
- 미처리 RT는 시스티나 177건(24개 매장)이 가장 많고, 롯데아울렛광주월드컵 31건이 집중돼 있습니다. 쉬즈미스는 56건(29개 매장).
- 창고 부족은 쉬즈미스 377장·무재고 SKU 142개로 가장 큽니다(리스트 54장, 시스티나 0).
- 과다 재고는 쉬즈미스 74,066행·52.8만 장, 리스트 57,060행·35.3만 장. 재고일수 과다 매장은 충주용산점 741일, 롯데아울렛고양터미널 2,828일 등입니다.
- 초도 적중률은 시스티나 37.2%(판매율 24.1%)로 가장 높고, 쉬즈미스 21.9%·저적중 227개 상품으로 가장 낮습니다.
### 이번 주 할 일
1. 시스티나 담당 MD: 롯데아울렛광주월드컵 등 미처리 RT 177건 매장 연락해 처리 마감.
2. 쉬즈미스 담당: 수락률 57.5% 원인 매장 파악, 자동거부 1,534건 중 재요청 대상 선별.
3. 쉬즈미스 창고 부족 377장·무재고 142 SKU는 과다 보유 매장에서 매장 간 RT로 보충 검토.
4. 충주용산·경산·현대아울렛송도 등 재고일수 500일 이상 매장 재고 회수·이동안 작성.
5. 쉬즈미스 저적중 227개 상품 리스트 공유, 다음 초도 배분 기준 재검토.`

test('AI 주간 브리핑 저장: PDF 는 A4 가로 1장 · PNG 는 화면과 같은 글꼴로 겹침 없이', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  const b = BRIEF(LONG)
  const days = b.sales.brands[0].days.map((x, i) => ({ ...x, amt: [950_000_000, 840_000_000, 950_000_000, 720_000_000, 750_000_000, 1_250_000_000, 1_300_000_000][i] }))
  b.brands = ['쉬즈미스', '리스트', '시스티나']
  b.sales.brands = [{ ...b.sales.brands[0], days }, { ...b.sales.brands[0], brand: 'T', brandNm: '리스트', days }, { ...b.sales.brands[0], brand: 'A', brandNm: '시스티나', days }]
  b.stock = [b.stock[0], { ...b.stock[0], brand: 'T', brandNm: '리스트' }, { ...b.stock[0], brand: 'A', brandNm: '시스티나' }]
  api.on('GET', '/api/briefing/weekly', () => ({ json: b }))
  await page.goto('/?view=sale_dashboard')
  await page.getByRole('button', { name: 'AI 주간 브리핑' }).click()
  const dlg = page.getByRole('dialog', { name: 'AI 주간 브리핑' })
  await expect(dlg.locator('.brief-ai')).toContainText('이번 주 할 일')
  // PDF: 인쇄 창 대신 그 순간의 인쇄용 복사본을 남겨 두고 PDF 로 찍어 장수를 센다
  await page.evaluate(() => {
    window.print = () => {
      const h = document.getElementById('print-host')!
      const keep = h.cloneNode(true) as HTMLElement
      h.id = 'print-host-old'
      document.body.appendChild(keep)
    }
  })
  await dlg.getByRole('button', { name: /PDF 저장/ }).click()
  await expect(page.locator('#print-host .report-page')).toHaveCount(1)
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true })
  const pages = (pdf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) ?? []).length
  expect(pages).toBe(1)
  if (SHOT) {
    writeFileSync(`${SHOT}/briefing.pdf`, pdf)
    await page.setViewportSize({ width: 1123, height: 794 })
    await page.emulateMedia({ media: 'print' })
    await page.screenshot({ path: `${SHOT}/briefing-print.png` })
    await page.emulateMedia({ media: 'screen' })
    await page.setViewportSize({ width: 1440, height: 900 })
  }
  await page.evaluate(() => document.getElementById('print-host')?.remove())
  // PNG
  const [dl] = await Promise.all([page.waitForEvent('download'), dlg.getByRole('button', { name: /이미지\(PNG\)/ }).click()])
  expect(dl.suggestedFilename()).toBe('AI주간브리핑_2026-09-28_2026-10-04.png')
  if (SHOT) await dl.saveAs(`${SHOT}/briefing-download.png`)
})
