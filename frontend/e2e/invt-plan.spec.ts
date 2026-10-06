// 매장 재고 실사계획 등록: 금액·수량 칸은 천 단위 쉼표로 보이고, 저장할 때는 쉼표 없는 숫자로 보낸다
import { expect, makeUser, test } from './mock'

const OPTIONS = { areas: ['서울'], regions: ['수도권', '지방'], areaRegion: { 서울: '수도권' }, invtTypes: ['정기', '교체'], stlmTeams: ['1팀', '2팀'], rmkMaxBytes: 4000, encoding: 'utf-8' }

test('실사계획 신규 등록: 숫자 칸 쉼표 표시 · 입력 중 쉼표 · 저장 값', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['invt_plan']))
  api.on('GET', '/api/invt-plans/options', () => ({ json: OPTIONS }))
  api.on('GET', '/api/invt-plans', () => ({ json: { plans: [] } }))
  api.on('GET', '/api/invt-plans/shops', () => ({ json: { shops: [{ shopId: 'S31019', shopNm: '현대아울렛가산', shopFormNm: '아울렛', shopForm2Nm: null }] } }))
  api.on('GET', '/api/invt-plans/shops/S31019', () => ({
    json: {
      values: { shopId: 'S31019', shopNm: '현대아울렛가산', brdNm: '쉬즈미스', prevSaleAmt: 1234567890, currSaleAmt: 987654321,
                prevInvtResult: -150000, stockQty: 23456, regionNm: '수도권', baseFee: 150000 },
      missing: [], missingLabels: [], errors: {}, existingPlans: 0,
    },
  }))
  api.on('POST', '/api/invt-plans', (req) => ({ json: { plan: { planId: 1, ...(req.postDataJSON() as object) } } }))
  await page.goto('/?view=invt_plan')

  await page.getByRole('button', { name: /신규 등록/ }).click()
  await page.getByRole('button', { name: '매장코드 선택' }).click()
  await page.getByPlaceholder(/매장코드 또는 매장명/).fill('가산')
  await page.getByRole('row', { name: /S31019/ }).click()

  const field = (label: string) => page.locator('label.field').filter({ has: page.locator('.field-label', { hasText: new RegExp(`^${label}`) }) }).locator('input')
  await expect(field('전년 매출')).toHaveValue('1,234,567,890')
  await expect(field('당년 매출')).toHaveValue('987,654,321')
  await expect(field('전실사결과')).toHaveValue('-150,000')
  await expect(field('재고 수량')).toHaveValue('23,456')
  await expect(field('기본료')).toHaveValue('150,000')
  await expect(field('실사예상액')).toHaveValue('1,993,760')        // 23,456 × 85 자동 계산

  await field('재고 수량').fill('')
  await field('재고 수량').pressSequentially('1000000')
  await expect(field('재고 수량')).toHaveValue('1,000,000')
  await expect(field('실사예상액')).toHaveValue('85,000,000')
  await field('기본료').fill('2abc00,000')                          // 숫자 외 문자는 무시
  await expect(field('기본료')).toHaveValue('200,000')
  await page.screenshot({ path: String.raw`C:\Users\User\AppData\Local\Temp\claude\C--Sangmoo-online-price-dashboard\2a2d2e95-469a-4cdd-9b5e-e8790b83fd08\scratchpad\invt-new.png` })

  await page.getByRole('button', { name: '등록', exact: true }).click()
  await expect.poll(() => api.find('POST', '/api/invt-plans').length).toBe(1)
  const body = api.find('POST', '/api/invt-plans')[0].body as Record<string, unknown>
  expect(body.stockQty).toBe('1000000')
  expect(body.baseFee).toBe('200000')
  expect(body.expectAmt).toBe(85000000)
  expect(body.prevSaleAmt).toBe(1234567890)
  expect(body.prevInvtResult).toBe(-150000)
})
