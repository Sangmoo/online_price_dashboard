// 2차: 마이페이지(강조 색 · 다크 모드) · 필독 공지 · 점검 예고 · 공지 대상/고정/필독 등록 · 읽음 현황 · 권한 묶음 · 계정 정리 · 화면 미리보기 · 대량 다운로드 알림
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png`, fullPage: true }) : Promise.resolve())
const TABLE_OK = { ready: true, missing: [], ddl: 'db/alter_erp_web_admin_ops_2.sql' }
const TYPES = { all: '전체', pages: '메뉴 권한자', brands: '브랜드 담당자', users: '특정 사용자' }
const notice = (id: string, extra: Record<string, unknown> = {}) => ({
  id, title: `공지 ${id}`, body: '본문', level: 'important', levelLabel: '중요', start: '2026-10-06', end: '2026-10-10', use: true, status: 'active',
  createdBy: '900001', createdAt: '2026-10-06 09:00', updatedBy: '900001', updatedAt: '2026-10-06 09:00', images: [], files: [], commentCount: 0,
  target: { type: 'all', values: [], label: '전체' }, pin: false, mustAck: false, ...extra,
})
const adminUser = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, name, role: 'USER', superAdmin: false, active: true, pages: ['sale_dashboard'], brands: null,
  ai: { enabled: true, globalEnabled: true, userEnabled: true, dailyQuestions: 10, dailyCostUsd: 2, dailyBriefings: 3, customLimits: false },
  rawAiEnabled: true, rawDailyQuestions: null, rawDailyCostUsd: null, lastLoginAt: '2026-10-01 09:00', createdAt: '2026-09-01 10:00:00',
  updatedAt: null, updatedBy: null, todayQuestions: 0, todayCostUsd: 0, rawDailyBriefings: null, todayBriefings: 0, online: false, ...extra,
})
const USERS = { users: [adminUser('170046', '홍길동'), adminUser('170047', '김영업')], pages: [{ key: 'sale_dashboard', label: '판매 현황', group: '판매' },
  { key: 'invt_plan', label: '매장 재고 실사계획', group: '데이터' }], superAdminId: '250016', brandOptions: ['리스트', '쉬즈미스'], brandReady: true }

test('마이페이지: 강조 색을 고르면 바로 바뀌고 서버에 저장되며, 다크 모드에서도 같은 계열 색이 쓰인다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  api.on('GET', '/api/me/overview', () => ({ json: {
    user: api.user, usage: { questions: 2, costUsd: 0.1, questionLimit: 10, costLimitUsd: 2, enabled: true }, lastLoginAt: '2026-10-06 09:00',
    createdAt: '2026-01-01 00:00', pages: [{ key: 'sale_dashboard', label: '판매 현황' }], role: { name: '영업 기본', appliedAt: '2026-10-01 10:00' },
    accents: ['indigo', 'teal'], downloads: { total: 1, rows: [{ id: 'd1', at: '2026-10-06 10:00:00', usrId: '900002', name: '테스트사용자',
      kind: 'table', kindLabel: '화면 표 엑셀', title: '판매집계', params: null, rows: 50, bytes: 1000, ip: null, sensitive: false }] } } }))
  api.on('PUT', '/api/prefs/ui.accent', () => ({ json: { ok: true } }))
  await page.goto('/?view=mypage')
  await expect(page.getByText('권한 묶음')).toBeVisible()
  await page.getByRole('radio', { name: /틸/ }).click()
  await expect(page.locator('html')).toHaveAttribute('data-accent', 'teal')
  await expect.poll(() => api.find('PUT', '/api/prefs/ui.accent').map((c) => c.body)).toEqual([{ value: 'teal' }])
  const primary = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--primary').trim())
  expect(await primary()).toBe('#0f766e')
  await shot(page, 'mypage-light')
  await page.locator('.my-theme').getByRole('button', { name: '다크' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await primary()).toBe('#2dd4bf')
  await expect.poll(() => api.find('PUT', '/api/prefs/ui.theme').map((c) => c.body)).toEqual([{ value: 'dark' }])   // 다크 모드도 사용자별 저장
  // 진한 버튼 · 선택된 탭은 다크 모드에서도 흰 글자가 보이는 진한 색
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent-a').trim())).toBe('#0d9488')
  await shot(page, 'mypage-dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-accent', 'teal')               // 다시 열어도 유지 (브라우저 기억 + 서버 설정)
})

test('필독 공지: 오늘 하루 보지 않기로 숨겨지지 않고 [확인했습니다] 를 누르면 기록, 예약 점검 예고 배너', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  api.on('GET', '/api/notices', () => ({ json: { notices: [notice('m1', { mustAck: true, title: '필독 공지' }), notice('n2', { level: 'info', levelLabel: '안내' })],
    maintenance: { start: '2026-10-10 13:00', until: '2026-10-10 13:30', message: 'DB 작업' } } }))
  api.on('POST', '/api/notices/m1/ack', () => ({ json: { ok: true } }))
  await page.goto('/?view=sale_dashboard')
  const popup = page.getByRole('dialog', { name: '공지사항' })
  await expect(popup.getByText('필독 공지')).toBeVisible()
  await expect(page.getByText(/13:00 ~ 13:30 시스템 점검 예정입니다/)).toBeVisible()
  await expect.poll(() => api.find('POST', '/api/notices/read').map((c) => c.body)).toEqual([{ ids: ['m1', 'n2'] }])
  await expect(popup.getByText('(필독 제외)')).toBeVisible()
  await shot(page, 'must-ack-popup')
  await popup.getByRole('button', { name: '확인했습니다' }).click()
  await expect(popup.getByText('확인함')).toBeVisible()
  expect(api.find('POST', '/api/notices/m1/ack')).toHaveLength(1)
})

test('관리자 공지: 대상 · 상단 고정 · 필독을 지정해 저장하고, 읽음 현황을 본다 · 점검 예약', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/users', () => ({ json: USERS }))
  api.on('GET', '/api/admin/notices', () => ({ json: {
    notices: [notice('n1', { mustAck: true, pin: true, readCount: 1, ackCount: 1, target: { type: 'pages', values: ['sale_dashboard'], label: '메뉴: 판매 현황' } })],
    levels: { info: '안내', warn: '주의', important: '중요' }, table: TABLE_OK, ext: TABLE_OK, targetTypes: TYPES, titleMax: 100, bodyMax: 1000,
    limits: { attach: 3, attachMb: 10, images: 5, imageMb: 5, attachTypes: ['pdf'] }, maintenance: { on: false, manual: false, message: '점검 중', start: null, until: null } } }))
  api.on('GET', '/api/admin/notices/n1/reads', () => ({ json: { ready: true, mustAck: true, target: { type: 'pages', values: ['sale_dashboard'], label: '메뉴: 판매 현황' },
    counts: { target: 2, read: 1, ack: 1 }, users: [
      { id: '170047', name: '김영업', lastLoginAt: null, target: true, readAt: null, ackAt: null },
      { id: '170046', name: '홍길동', lastLoginAt: null, target: true, readAt: '2026-10-06 10:00', ackAt: '2026-10-06 10:01' }] } }))
  api.on('POST', '/api/admin/notices', () => ({ json: { notice: notice('new') } }))
  api.on('PUT', '/api/admin/maintenance', (req) => ({ json: { on: false, manual: false, scheduled: true, message: '점검 중', ...(req.postDataJSON() as object) } }))
  await page.goto('/?view=admin')
  await page.locator('.admin-tab', { hasText: '공지 · 점검' }).click()
  await page.getByRole('button', { name: /1명 · 확인 1/ }).click()
  const reads = page.locator('.reads-modal')
  await expect(reads).toContainText('읽음 1명 (50%)')
  await reads.getByRole('button', { name: '안 읽은 대상자' }).click()
  await expect(reads.locator('tbody tr')).toHaveCount(1)
  await shot(page, 'notice-reads')
  await reads.getByRole('button').first().click()

  await page.getByRole('button', { name: '새 공지' }).click()
  const ed = page.locator('.notice-editor')
  await ed.getByPlaceholder(/마감 매출 적재 안내/).fill('판매팀 필독')
  await ed.getByRole('button', { name: '메뉴 권한자' }).click()
  await ed.getByRole('button', { name: '판매 현황' }).click()
  await ed.getByLabel(/게시판 상단 고정/).check()
  await ed.getByLabel(/필독/).check()
  await shot(page, 'notice-target')
  await ed.getByRole('button', { name: '저장' }).click()
  await expect.poll(() => api.find('POST', '/api/admin/notices').length).toBe(1)
  const body = api.find('POST', '/api/admin/notices')[0].body as Record<string, unknown>
  expect(body.target).toEqual({ type: 'pages', values: ['sale_dashboard'] })
  expect([body.pin, body.mustAck]).toEqual([true, true])

  page.once('dialog', (d) => d.accept())
  const panel = page.locator('.maint-panel')
  await panel.locator('input[type=datetime-local]').nth(0).fill('2026-10-10T13:00')
  await panel.locator('input[type=datetime-local]').nth(1).fill('2026-10-10T13:30')
  await panel.getByRole('button', { name: '예약 저장' }).click()
  await expect.poll(() => api.find('PUT', '/api/admin/maintenance').map((c) => c.body)).toEqual([
    { on: false, start: '2026-10-10 13:00', until: '2026-10-10 13:30', message: '점검 중' }])
})

test('권한 묶음: 묶음을 만들고 사용자에게 적용한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  const roles: unknown[] = []
  api.on('GET', '/api/admin/roles', () => ({ json: { table: TABLE_OK, roles, pages: USERS.pages, brandOptions: ['리스트', '쉬즈미스'], brandReady: true } }))
  api.on('GET', '/api/admin/users', () => ({ json: USERS }))
  api.on('POST', '/api/admin/roles', (req) => {
    const b = req.postDataJSON() as { name: string; description: string; conf: Record<string, unknown> }
    roles.push({ id: 'r1', name: b.name, description: b.description, conf: b.conf, pageLabels: ['판매 현황'], members: [], updatedBy: '900001', updatedAt: null })
    return { json: { id: 'r1', reapplied: null } }
  })
  api.on('POST', '/api/admin/roles/r1/apply', () => ({ json: { applied: ['170046'], skipped: [], role: '영업 기본' } }))
  await page.goto('/?view=admin')
  await page.locator('.admin-tab', { hasText: '권한 묶음' }).click()
  await page.getByRole('button', { name: '새 묶음' }).click()
  const ed = page.locator('.role-editor')
  await ed.getByPlaceholder('예: 영업팀 기본').fill('영업 기본')
  await ed.getByRole('button', { name: '판매 현황' }).click()
  await ed.getByRole('button', { name: '쉬즈미스' }).click()
  await ed.getByRole('button', { name: '저장' }).click()
  await expect.poll(() => api.find('POST', '/api/admin/roles').length).toBe(1)
  expect((api.find('POST', '/api/admin/roles')[0].body as { conf: unknown }).conf).toEqual(
    { pages: ['sale_dashboard'], brands: ['쉬즈미스'], aiEnabled: true, dailyQuestions: null, dailyCostUsd: null })
  await page.getByRole('button', { name: '사용자에게 적용' }).click()
  await page.locator('.role-user', { hasText: '홍길동' }).locator('input').check()
  page.once('dialog', (d) => d.accept())
  await page.locator('.role-apply').getByRole('button', { name: '적용' }).click()
  await expect.poll(() => api.find('POST', '/api/admin/roles/r1/apply').map((c) => c.body)).toEqual([{ userIds: ['170046'] }])
  await expect(page.locator('.toast')).toContainText('1명에게 적용')
})

test('계정 정리: 오래 안 쓴 계정 · 안 쓰는 메뉴를 골라서만 정리한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/cleanup', () => ({ json: { days: 90, periods: [30, 60, 90, 180],
    idle: [{ id: '170047', name: '김영업', role: 'USER', lastLoginAt: null, createdAt: null, pages: ['판매 현황'], idleDays: null }],
    unused: [{ id: '170046', name: '홍길동', lastLoginAt: '2026-10-01 09:00', pages: [{ key: 'invt_plan', label: '매장 재고 실사계획' }], keep: ['판매 현황'] }] } }))
  api.on('POST', '/api/admin/cleanup/apply', () => ({ json: { deactivated: ['170047'], revoked: [{ id: '170046', pages: ['invt_plan'] }], skipped: [] } }))
  await page.goto('/?view=admin')
  await page.locator('.admin-tab', { hasText: '계정 정리' }).click()
  await expect(page.getByRole('button', { name: /고른 0건 정리/ })).toBeDisabled()
  await page.getByLabel('김영업 사용 중지').check()
  await page.locator('label.chip', { hasText: '매장 재고 실사계획' }).click()
  await shot(page, 'cleanup')
  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: /고른 2건 정리/ }).click()
  await expect.poll(() => api.find('POST', '/api/admin/cleanup/apply').map((c) => c.body)).toEqual([
    { deactivate: ['170047'], revoke: [{ id: '170046', pages: ['invt_plan'] }] }])
})

test('사용자 화면 미리보기: 대상 사용자 권한으로 보이고, 요청에 X-View-As 가 붙으며 끝내면 관리자로 돌아온다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  const target = { ...makeUser('USER', ['sale_dashboard']), id: '170046', name: '홍길동' }
  api.on('GET', '/api/admin/users', () => ({ json: USERS }))
  api.on('GET', '/api/admin/view-as/170046', () => ({ json: { user: { ...target, viewAs: { by: '900001', byName: '테스트관리자' } } } }))
  await page.goto('/?view=admin')
  await page.locator('.admin-tab', { hasText: '사용자 · 권한' }).click()
  await page.getByRole('row', { name: /홍길동/ }).getByRole('button', { name: /화면 보기/ }).click()
  await expect(page.getByText(/홍길동\(170046\).*님 화면을 미리보는 중입니다/)).toBeVisible()
  await expect(page.locator('.side-nav')).not.toContainText('관리자')                    // 대상 사용자 메뉴만
  await expect.poll(() => api.calls.some((c) => c.path === '/api/sale-dashboard' && c.headers['x-view-as'] === '170046')).toBe(true)
  expect(api.find('GET', '/api/admin/view-as/170046').map((c) => c.query.get('resume'))).toEqual([null, 'true'])   // 이력은 처음 한 번만
  await shot(page, 'view-as')
  await page.getByRole('button', { name: '미리보기 끝내기' }).click()
  await expect(page.locator('.side-nav')).toContainText('관리자')
  expect(await page.evaluate(() => sessionStorage.getItem('erp.viewAs'))).toBeNull()
})

test('대량 다운로드 알림: 기준을 넘은 사용자를 보여주고 기준을 저장한다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  const report = { days: 30, table: TABLE_OK, total: 0, kinds: {}, sensitiveKinds: [], byUser: [], byKind: [], daily: [], rows: [], truncated: false,
    alerts: [{ usrId: '170046', name: '홍길동', kind: 'count', at: '2026-10-06 10:00:00', count: 12, message: '최근 1시간 엑셀 12건' }],
    alertSettings: { count: 10, phone: 20, rows: 100000 } }
  api.on('GET', '/api/admin/downloads', () => ({ json: report }))
  api.on('PUT', '/api/admin/downloads/alert-settings', (req) => ({ json: req.postDataJSON() }))
  await page.goto('/?view=admin')
  await page.locator('.admin-tab', { hasText: '다운로드 이력' }).click()
  await expect(page.locator('.dl-alert-panel')).toContainText('최근 1시간 엑셀 12건')
  await page.locator('.dl-alert-cfg input').first().fill('5')
  await page.getByRole('button', { name: '기준 저장' }).click()
  await expect.poll(() => api.find('PUT', '/api/admin/downloads/alert-settings').map((c) => c.body)).toEqual([{ count: 5, phone: 20, rows: 100000 }])
})
