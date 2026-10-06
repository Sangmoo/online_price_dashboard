// 공지(로그인 팝업 · 오늘 하루 보지 않기 · 게시판 · 첨부 · 이미지 붙여넣기 · 댓글/대댓글) · 점검 모드 · 관리자 홈/스케줄/다운로드 이력
import { expect, makeUser, test } from './mock'
import type { Page } from '@playwright/test'

const SHOT = process.env.E2E_SHOT_DIR
const shot = (page: Page, name: string) => (SHOT ? page.screenshot({ path: `${SHOT}/${name}.png` }) : Promise.resolve())

const notice = (id: string, extra: Record<string, unknown> = {}) => ({
  id, title: `공지 ${id}`, body: '10/10(금) 13시에 마감 매출을 적재합니다.\n적재 후 판매 현황에 반영됩니다.', level: 'important', levelLabel: '중요',
  start: '2026-10-06', end: '2026-10-10', use: true, status: 'active', createdBy: '900001', createdAt: '2026-10-06 09:00',
  updatedBy: '900001', updatedAt: '2026-10-06 09:00', images: [], files: [{ no: 1, kind: 'file', name: '적재일정.pdf', type: 'application/pdf', size: 20480 }],
  commentCount: 1, target: { type: 'all', values: [], label: '전체' }, pin: false, mustAck: false, ...extra,
})
const TABLE_OK = { ready: true, missing: [], ddl: 'db/create_erp_web_admin_ops.sql' }
const TABLE_NO = { ready: false, missing: ['T_ERP_WEB_JOB_RUN'], ddl: 'db/create_erp_web_admin_ops.sql' }

test('공지: 로그인하면 모든 사용자에게 팝업, 오늘 하루 보지 않기 후 다시 열면 안 뜨고 상단 [공지] 로 다시 본다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  api.on('GET', '/api/notices', () => ({ json: { notices: [notice('n1')] } }))
  await page.goto('/?view=sale_dashboard')
  const popup = page.getByRole('dialog', { name: '공지사항' })
  await expect(popup.getByText('공지 n1')).toBeVisible()
  await expect(popup.getByRole('link', { name: /적재일정\.pdf/ })).toHaveAttribute('href', '/api/notices/n1/files/1')
  await shot(page, 'notice-popup')
  await popup.getByLabel('오늘 하루 보지 않기').check()
  await popup.locator('.modal-foot').getByRole('button', { name: '닫기' }).click()
  await expect(popup).toHaveCount(0)

  await page.reload()
  await expect(page.getByRole('button', { name: /공지 1/ })).toBeVisible()
  await expect(page.getByRole('dialog', { name: '공지사항' })).toHaveCount(0)        // 오늘은 숨김
  await page.getByRole('button', { name: /공지 1/ }).click()
  await expect(page.getByRole('dialog', { name: '공지사항' }).getByText('공지 n1')).toBeVisible()
  await expect(page.getByLabel('오늘 하루 보지 않기')).toHaveCount(0)                  // 직접 연 팝업에는 없음
})

test('공지사항 게시판: 메뉴 권한과 관계없이 보이고, 댓글 · 대댓글을 단다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  const comments = [{ id: 'c1', parentId: null, userId: '900009', userName: '김영업', body: '확인했습니다.', deleted: false, createdAt: '2026-10-06 10:00',
    edited: false, canEdit: false, canDelete: false, replies: [] as unknown[] }]
  api.on('GET', '/api/notices/board', () => ({ json: { notices: [notice('n1'), notice('n2', { status: 'ended', level: 'info', levelLabel: '안내', files: [], commentCount: 0 })], total: 2, table: TABLE_OK } }))
  api.on('GET', '/api/notices/n1', () => ({ json: { notice: { ...notice('n1', { images: [{ no: 2, kind: 'image', name: '화면.png', type: 'image/png', size: 100 }] }), comments }, commentMax: 1000 } }))
  api.on('GET', /^\/api\/notices\/n1\/files\//, () => ({ body: Buffer.from('89504e470d0a1a0a', 'hex'), headers: { 'content-type': 'image/png' } }))
  api.on('POST', '/api/notices/n1/comments', (req) => {
    const b = req.postDataJSON() as { body: string; parentId?: string }
    const c = { id: `c${Date.now()}`, parentId: b.parentId ?? null, userId: '900002', userName: '테스트사용자', body: b.body, deleted: false,
      createdAt: '2026-10-06 11:00', edited: false, canEdit: true, canDelete: true }
    if (b.parentId) comments[0].replies.push(c)
    else comments.push({ ...c, replies: [] })
    return { json: { comments } }
  })
  await page.goto('/?view=sale_dashboard')
  await page.locator('.side-nav').getByText('공지사항').click()
  await expect(page.getByRole('heading', { name: '공지 n1' })).toBeVisible()
  await expect(page.locator('.board-item')).toHaveCount(2)
  await expect(page.locator('.notice-images img')).toHaveAttribute('src', '/api/notices/n1/files/2')

  await page.getByPlaceholder('댓글 쓰기 (Ctrl+Enter 로 등록)').fill('저도 확인')
  await page.getByRole('button', { name: '등록' }).click()
  await expect(page.locator('.comment-body', { hasText: '저도 확인' })).toBeVisible()
  await page.locator('.comment', { hasText: '확인했습니다.' }).getByRole('button', { name: '답글' }).click()
  await page.getByPlaceholder('김영업 님에게 답글 쓰기').fill('답글입니다')
  await page.locator('.comment-form', { hasText: '답글' }).getByRole('button', { name: '답글' }).click()
  await expect(page.locator('.comment.reply .comment-body', { hasText: '답글입니다' })).toBeVisible()
  const posts = api.find('POST', '/api/notices/n1/comments')
  expect(posts.map((p) => p.body)).toEqual([{ body: '저도 확인' }, { body: '답글입니다', parentId: 'c1' }])
  await expect(page.getByRole('heading', { name: /댓글 3/ })).toBeVisible()
  await shot(page, 'notice-board')
})

test('관리자 공지 등록: 첨부파일 · 클립보드 이미지 붙여넣기가 함께 저장된다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/home', () => ({ json: { generatedAt: '2026-10-06 09:00:00', feedback: { open: 0 }, users: { error: 'x' }, server: { error: 'x' },
    data: { error: 'x' }, ai: { error: 'x' }, jobs: { error: 'x' }, downloads: { error: 'x' }, notices: { error: 'x' } } }))
  api.on('GET', '/api/admin/notices', () => ({ json: { notices: [], levels: { info: '안내', warn: '주의', important: '중요' }, table: TABLE_OK, ext: TABLE_OK, targetTypes: { all: '전체', pages: '메뉴 권한자', brands: '브랜드 담당자', users: '특정 사용자' }, titleMax: 100, bodyMax: 1000,
    limits: { attach: 3, attachMb: 10, images: 5, imageMb: 5, attachTypes: ['pdf', 'xlsx', 'png'] }, maintenance: { on: false, message: '점검 중', until: null } } }))
  api.on('POST', '/api/admin/notices', () => ({ json: { notice: notice('new') } }))
  await page.goto('/?view=admin')
  await page.locator('.admin-tab', { hasText: '공지 · 점검' }).click()
  await page.getByRole('button', { name: '새 공지' }).click()
  const editor = page.locator('.notice-editor')
  await editor.getByPlaceholder(/마감 매출 적재 안내/).fill('적재 안내')
  await editor.getByPlaceholder(/줄바꿈은 그대로/).fill('본문')
  await editor.locator('input[type=file]').nth(1).setInputFiles({ name: '일정.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 test') })
  await editor.locator('input[type=file]').nth(1).setInputFiles({ name: 'run.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') })
  await expect(page.locator('.alert.error', { hasText: '첨부할 수 없는 형식' })).toBeVisible()
  // Ctrl+V 로 캡처 이미지 붙여넣기
  await editor.getByPlaceholder(/줄바꿈은 그대로/).evaluate((el) => {
    const png = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='), (c) => c.charCodeAt(0))
    const dt = new DataTransfer()
    dt.items.add(new File([png], 'image.png', { type: 'image/png' }))
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
  })
  await expect(editor.locator('.attach-thumb img')).toHaveCount(1)
  await expect(editor.getByText('일정.pdf')).toBeVisible()
  await shot(page, 'notice-editor')
  await editor.getByRole('button', { name: '저장' }).click()
  await expect.poll(() => api.find('POST', '/api/admin/notices').length).toBe(1)
  const body = api.find('POST', '/api/admin/notices')[0].body as { title: string; newFiles: { kind: string; name: string; data: string }[] }
  expect(body.title).toBe('적재 안내')
  expect(body.newFiles.map((f) => [f.kind, f.name])).toEqual([['file', '일정.pdf'], ['image', '붙여넣은 이미지 1.png']])
  expect(body.newFiles[1].data.startsWith('data:image/png;base64,')).toBe(true)
})

test('점검 모드: 일반 사용자는 점검 안내 화면을 보고, 끝나면 [다시 확인] 으로 들어간다', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('USER', ['sale_dashboard']))
  let maint = true
  const me = api.user
  api.on('GET', '/api/auth/me', () => (maint
    ? { status: 503, json: { detail: { message: 'DB 작업 중입니다. (종료 예정 2026-10-10 15:00)', code: 'MAINTENANCE' } } }
    : { json: { user: me, usage: {}, sessionTtl: 3600 } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '시스템 점검 중' })).toBeVisible()
  await expect(page.getByText('DB 작업 중입니다. (종료 예정 2026-10-10 15:00)')).toBeVisible()
  await shot(page, 'maintenance')
  maint = false
  await page.getByRole('button', { name: '다시 확인' }).click()
  await expect(page.locator('.side-nav')).toBeVisible()
})

test('관리자 홈 · 스케줄 · 다운로드 이력: 카드 요약, 테이블이 없으면 DDL 안내', async ({ page, mockApi }) => {
  const api = await mockApi(makeUser('ADMIN'))
  api.on('GET', '/api/admin/home', () => ({ json: {
    generatedAt: '2026-10-06 09:00:00', feedback: { open: 2 },
    users: { online: 3, sessions: 4, loginsToday: 5, loginFailsToday: 0, locked: 0 },
    server: { uptimeSec: 7200, startedAt: '', requests: 900, errors: 1, errors5xx: 0, slowRequests: 2, slowSql: 3, sqlErrors: 0, recentErrors: [], crashRestarts: 0, diskFreeGb: 50, diskFreePct: 40 },
    data: { onlineLatest: '20261006', onlineLatestRows: 13729, onlineToday: true, saleBaseMonth: '202609', saleMvMonth: '202609', mvBehind: false, mvLastRefresh: null, shopFill: { dt: '20261005', rows: 30698, filled: 4818, pct: 15.7 } },
    ai: { enabled: true, questions: 4, costUsd: 0.12, users: 2 },
    jobs: { total: 6, problems: 1, problemNames: ['온라인 수집 매장코드 채우기'], dbReady: true, appReady: false },
    downloads: { ready: true, today: 3, week: 10, sensitiveWeek: 1, topUser: { id: '900002', name: '홍길동', count: 6 } },
    notices: { active: 1, titles: ['적재 안내'], endingSoon: 0, maintenance: { on: false, message: '', until: null }, table: TABLE_OK },
  } }))
  api.on('GET', '/api/admin/jobs', () => ({ json: {
    days: 14, db: { days: 14, ready: true, error: null, jobs: [{ key: 'JOB_FILL_ONLINE_SHOP_ID', kind: 'db', label: '온라인 수집 매장코드 채우기', schedule: '매일 02:00 · 전일자',
      status: 'error', last: { start: '2026-10-06 02:00:00', end: '2026-10-06 02:00:12', status: 'error', detail: 'ORA-00001', sec: 12, rawStatus: 'FAILED' }, runs: [], failures: 1,
      enabled: true, nextRun: '2026-10-07 02:00:00', result: { label: '전일 수집 30,698건 중 매장코드 4,818건', warn: false } }] },
    app: [{ key: 'prewarm', kind: 'app', label: '판매 현황 미리 계산', schedule: '매일 07시', status: 'unknown', last: null, runs: [], failures: 0, count: 0 }],
    appTable: TABLE_NO, summary: { total: 2, problems: 1, problemNames: [], dbReady: true, appReady: false },
  } }))
  api.on('GET', '/api/admin/downloads', () => ({ json: { days: 30, table: TABLE_OK, total: 1, kinds: { manager_phone: '매장 매니저 연락처 조회' }, sensitiveKinds: ['manager_phone'],
    byUser: [{ id: '900002', name: '홍길동', count: 1, sensitive: 1, rows: 1, last: '2026-10-06 10:00:00', kinds: { manager_phone: 1 } }], byKind: [], daily: [],
    rows: [{ id: 'd1', at: '2026-10-06 10:00:00', usrId: '900002', name: '홍길동', kind: 'manager_phone', kindLabel: '매장 매니저 연락처 조회', title: '매장 S31019 매니저 연락처',
      params: { shopId: 'S31019' }, rows: 1, bytes: null, ip: '10.0.0.2', sensitive: true }], truncated: false,
    alerts: [], alertSettings: { count: 10, phone: 20, rows: 100000 } } }))
  await page.goto('/?view=admin')
  await expect(page.locator('.home-card', { hasText: '문의 · 신고' })).toContainText('미처리 2건')
  await expect(page.locator('.home-card', { hasText: '스케줄 · 배치' })).toContainText('DDL 실행 필요')
  await shot(page, 'admin-home')
  await page.locator('.home-card', { hasText: '스케줄 · 배치' }).click()
  await expect(page.getByText('ORA-00001')).toBeVisible()
  await expect(page.getByText(/실행 기록 테이블을 쓸 수 없어/)).toBeVisible()
  await page.getByRole('button', { name: '다운로드 이력' }).click()
  await expect(page.locator('.dl-kind.sensitive')).toContainText('매장 매니저 연락처 조회')
})
