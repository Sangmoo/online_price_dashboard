// 관리자 운영: 홈 · 스케줄/배치 · 다운로드 이력 · 공지/점검 모드, 사용자 공지 팝업
import { apiFetch, BACKGROUND_HEADERS, qs } from './api'

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  return (await apiFetch(url, init)).json()
}
const send = <T,>(method: string, url: string, body?: unknown) =>
  json<T>(url, { method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

const UPLOAD_BASE = { invt: '/api/invt-plans', mall: '/api/mall-shops' } as const
export const uploadTemplateUrl = (kind: 'invt' | 'mall') => `${UPLOAD_BASE[kind]}/upload-template`

type CardError = { error?: string }
/** 운영 테이블 상태: 없으면 db/create_erp_web_admin_ops.sql 실행 안내 */
export type TableStatus = { ready: boolean; missing: string[]; ddl: string }

export type AdminHome = {
  generatedAt: string
  feedback: { open: number } & CardError
  users: { online: number; sessions: number; loginsToday: number; loginFailsToday: number; locked: number } & CardError
  server: {
    uptimeSec: number; startedAt: string; requests: number; errors: number; errors5xx: number; slowRequests: number; slowSql: number
    sqlErrors: number; recentErrors: { ts: string; category: string; message: string }[]; crashRestarts: number
    diskFreeGb: number; diskFreePct: number | null
  } & CardError
  data: {
    onlineLatest: string | null; onlineLatestRows: number; onlineToday: boolean; saleBaseMonth: string | null; saleMvMonth: string | null
    mvBehind: boolean; mvLastRefresh: string | null; shopFill: { dt: string; rows: number; filled: number; pct: number | null }
  } & CardError
  ai: { enabled: boolean; questions: number; costUsd: number; users: number } & CardError
  jobs: { total: number; problems: number; problemNames: string[]; dbReady: boolean; appReady: boolean } & CardError
  downloads: { ready: boolean; alerts: number; alertMessages: string[]; today: number; week: number; sensitiveWeek: number; topUser: { id: string; name: string; count: number } | null } & CardError
  notices: { active: number; titles: string[]; endingSoon: number; maintenance: Maintenance; table: TableStatus } & CardError
}

export type JobRun = { start: string | null; end: string | null; status: 'ok' | 'error' | 'running'; detail: string | null; sec: number | null; by?: string | null; rawStatus?: string }
export type JobStatus = 'ok' | 'error' | 'never' | 'overdue' | 'missing' | 'disabled' | 'unknown'
export type JobInfo = {
  key: string; kind: 'db' | 'app'; label: string; schedule: string; status: JobStatus; last: JobRun | null; runs: JobRun[]; failures: number
  // 앱 작업
  lastOk?: JobRun | null; count?: number
  // DB 스케줄
  sql?: string; enabled?: boolean | null; state?: string | null; nextRun?: string | null; lastStart?: string | null
  failureCount?: number | null; runCount?: number | null; repeat?: string | null; result?: { label: string; warn: boolean } | null
}
export type JobsOverview = {
  days: number
  db: { days: number; ready: boolean; error: string | null; jobs: JobInfo[] }
  app: JobInfo[]
  appTable: TableStatus
  summary: { total: number; problems: number; problemNames: string[]; dbReady: boolean; appReady: boolean }
}

export type DownloadRow = {
  id: string; at: string; usrId: string; name: string; kind: string; kindLabel: string; title: string | null
  params: Record<string, unknown> | null; rows: number | null; bytes: number | null; ip: string | null; sensitive: boolean
}
export type DownloadReport = {
  days: number; table: TableStatus; total: number; kinds: Record<string, string>; sensitiveKinds: string[]
  byUser: { id: string; name: string; count: number; sensitive: number; rows: number; last: string | null; kinds: Record<string, number> }[]
  byKind: { kind: string; label: string; count: number }[]
  daily: { day: string; count: number }[]
  rows: DownloadRow[]
  truncated: boolean
  alerts: DownloadAlert[]
  alertSettings: AlertSettings
}
export type DownloadAlert = { usrId: string; name: string; kind: 'count' | 'phone' | 'rows'; at: string | null; count: number; message: string }
export type AlertSettings = { count: number; phone: number; rows: number }

export type NoticeLevel = 'info' | 'warn' | 'important'
export type NoticeFile = { no: number; kind: 'image' | 'file'; name: string; type: string; size: number }
export type Notice = {
  id: string; title: string; body: string; level: NoticeLevel; levelLabel: string; start: string; end: string; use: boolean
  status: 'active' | 'scheduled' | 'ended' | 'off'; createdBy: string | null; createdAt: string | null; updatedBy: string | null; updatedAt: string | null
  images: NoticeFile[]; files: NoticeFile[]; commentCount: number
  /** 대상 · 상단 고정 · 필독 (db/alter_erp_web_admin_ops_2.sql 실행 후) */
  target: NoticeTarget & { label: string }; pin: boolean; mustAck: boolean
  /** 사용자: 읽음 · 필독 확인 여부 / 관리자 목록: 읽은 사람 · 확인한 사람 수 */
  read?: boolean; acked?: boolean; readCount?: number; ackCount?: number
}
export type NoticeTarget = { type: 'all' | 'pages' | 'brands' | 'users'; values: string[] }
export type NoticeReads = {
  ready: boolean; table?: TableStatus; mustAck?: boolean; target?: NoticeTarget & { label: string }
  counts: { target: number; read: number; ack: number } | null
  users: { id: string; name: string; lastLoginAt: string | null; target: boolean; readAt: string | null; ackAt: string | null }[]
}
export type NoticeComment = {
  id: string; parentId: string | null; userId: string | null; userName: string | null; body: string; deleted: boolean
  createdAt: string; edited: boolean; canEdit: boolean; canDelete: boolean; replies?: NoticeComment[]
}
export type NewNoticeFile = { kind: 'image' | 'file'; name: string; data: string }
export type NoticeInput = {
  title: string; body: string; level: NoticeLevel; start: string; end: string; use: boolean
  /** 남길 기존 파일 번호 (수정 시) · 새로 올릴 파일 (base64) */
  keepFiles?: number[]; newFiles?: NewNoticeFile[]
  target?: NoticeTarget; pin?: boolean; mustAck?: boolean
}
export type NoticeLimits = { attach: number; attachMb: number; images: number; imageMb: number; attachTypes: string[] }
export const fileSize = (b: number) => (b < 1024 ? `${b}B` : b < 1024 ** 2 ? `${Math.round(b / 1024)}KB` : `${(b / 1024 ** 2).toFixed(1)}MB`)
export const noticeFileUrl = (id: string, no: number) => `/api/notices/${id}/files/${no}`
/** on: 지금 막는 중 (직접 켬 또는 예약 시간 안) · manual: 직접 켬 · start/until: 예약 */
export type Maintenance = { on: boolean; manual?: boolean; scheduledNow?: boolean; scheduled?: boolean; message: string; start?: string | null; until: string | null }
export type UpcomingMaintenance = { start: string; until: string; message: string }

export type RoleConf = { pages: string[]; brands: string[] | null; aiEnabled: boolean; dailyQuestions: number | null; dailyCostUsd: number | null }
export type Role = {
  id: string; name: string; description: string; conf: RoleConf; pageLabels: string[]
  members: { id: string; name: string; appliedAt: string | null; by: string | null }[]; updatedBy: string | null; updatedAt: string | null
}
export type RolesData = { table: TableStatus; roles: Role[]; pages: { key: string; label: string; group: string }[]; brandOptions: string[]; brandReady: boolean }
export type CleanupData = {
  days: number; periods: number[]
  idle: { id: string; name: string; role: string; lastLoginAt: string | null; createdAt: string | null; pages: string[]; idleDays: number | null }[]
  unused: { id: string; name: string; lastLoginAt: string | null; pages: { key: string; label: string }[]; keep: string[] }[]
}
export type MyOverview = {
  user: import('./api').User; usage: { questions: number; costUsd: number; questionLimit: number; costLimitUsd: number; enabled: boolean }
  lastLoginAt: string | null; createdAt: string | null; pages: { key: string; label: string }[]
  role: { name: string; appliedAt: string | null } | null; accents: string[]
  downloads: { total: number; rows: DownloadRow[] } | null
}

/** 관리자 '사용 쿼리': 메뉴의 기능별 실제 실행 쿼리(값 채움, 내 최근 조회 1회분) + 코드 기준 SQL */
export type QueryRun = { sql: string; raw?: string; filled: string; binds: Record<string, unknown>; at: string; ms: number; count: number; usr: string | null }
export type QueryItem = { fn: string | null; title: string | null; file: string | null; line: number | null; sqls: string[]; error?: string | null
  runs: QueryRun[]; older: QueryRun[]; mine?: boolean }
export type QueryFeature = { title: string; desc: string; items: QueryItem[] }
export type PageQueries = { page: string; label?: string; features: QueryFeature[]; since: string }

/** 관리자 > 쿼리 성능 */
export type PerfWhere = { menu: string; feature: string }
export type PerfFunc = { fn: string; where: PerfWhere[]; count: number; totalMs: number; avgMs: number; maxMs: number; slow: number; sqls: number; lastAt: string | null }
export type PerfSql = { sql: string; raw: string; filled: string; fn: string; where: PerfWhere[]; count: number; avgMs: number; maxMs: number
  maxAt: string | null; maxUsr: string | null; slow: number; lastAt: string | null }
export type PerfRequest = { method: string; path: string; menu: string; count: number; avgMs: number; p95Ms: number; maxMs: number; slow: number; lastAt: string | null }
export type PerfDay = { day: string; requests: number; slow: number; p95Ms: number; avgMs: number }
export type PerfLogSql = { sql: string; count: number; maxMs: number; avgMs: number; binds: string; lastAt: string | null; truncated: boolean }
export type PerfReport = { since: string; serverStarted: string; slowSqlSec: number; slowRequestSec: number; days: number
  funcs: PerfFunc[]; slowSql: PerfSql[]; requests: PerfRequest[]; daily: PerfDay[]; logSlowSql: PerfLogSql[] }
export type PlanActual = { sqlId: string; planHash: number; children: number; executions: number; avgMs: number | null; bufferGets: number | null
  diskReads: number | null; rows: number | null; lastActive: string | null; plan: string; error?: undefined } | { error: string }
export type ExplainResult = { sqlId: string; actual: PlanActual | null; estimate: { plan?: string; error?: string }; at: string }

/** 엑셀 업로드 미리보기 */
export type UploadRow = { row: number; status: 'ok' | 'warn' | 'error'; messages: string[]; values: Record<string, unknown>
  display?: Record<string, unknown>; change?: string | null; auto?: string[] }
export type UploadPreview = { rows: UploadRow[]; summary: { total: number; ok: number; warn: number; error: number; changes?: Record<string, number> } }

export const opsApi = {
  perf: (days: number) => json<PerfReport>(`/api/admin/perf?${qs({ days })}`),
  perfClear: () => send<{ since: string }>('POST', '/api/admin/perf/clear'),
  explain: (sql: string) => send<ExplainResult>('POST', '/api/admin/sql/explain', { sql }),
  uploadPreview: (kind: 'invt' | 'mall', file: string) => send<UploadPreview>('POST', `${UPLOAD_BASE[kind]}/upload/preview`, { file }),
  uploadApply: (kind: 'invt' | 'mall', rows: UploadRow[]) =>
    send<{ saved: number; skipped: number; deleted?: number; changed?: number }>('POST', `${UPLOAD_BASE[kind]}/upload/apply`,
      { rows: rows.map((r) => ({ row: r.row, values: r.values })) }),
  queries: (page: string) => json<PageQueries>(`/api/admin/queries?${qs({ page })}`),
  home: (fresh = false) => json<AdminHome>(`/api/admin/home?${qs({ fresh: fresh ? 'true' : undefined })}`),
  jobs: (days: number, fresh = false) => json<JobsOverview>(`/api/admin/jobs?${qs({ days, fresh: fresh ? 'true' : undefined })}`),
  downloads: (p: { days: number; usr?: string; kind?: string }) => json<DownloadReport>(`/api/admin/downloads?${qs(p)}`),
  notices: () => json<{ notices: Notice[]; levels: Record<NoticeLevel, string>; table: TableStatus; ext: TableStatus; targetTypes: Record<string, string>
    titleMax: number; bodyMax: number; limits: NoticeLimits; maintenance: Maintenance }>('/api/admin/notices'),
  noticeReads: (id: string) => json<NoticeReads>(`/api/admin/notices/${id}/reads`),
  saveAlertSettings: (body: AlertSettings) => send<AlertSettings>('PUT', '/api/admin/downloads/alert-settings', body),
  roles: () => json<RolesData>('/api/admin/roles'),
  saveRole: (body: { name: string; description: string; conf: RoleConf; reapply?: boolean }, id?: string) =>
    send<{ id: string; reapplied: { applied: string[]; skipped: { id: string; reason: string }[] } | null }>(id ? 'PUT' : 'POST', id ? `/api/admin/roles/${id}` : '/api/admin/roles', body),
  deleteRole: (id: string) => send<{ ok: boolean }>('DELETE', `/api/admin/roles/${id}`),
  applyRole: (id: string, userIds: string[]) => send<{ applied: string[]; skipped: { id: string; reason: string }[]; role: string }>('POST', `/api/admin/roles/${id}/apply`, { userIds }),
  cleanup: (days: number) => json<CleanupData>(`/api/admin/cleanup?${qs({ days })}`),
  applyCleanup: (body: { deactivate: string[]; revoke: { id: string; pages: string[] }[] }) =>
    send<{ deactivated: string[]; revoked: { id: string; pages: string[] }[]; skipped: { id: string; reason: string }[] }>('POST', '/api/admin/cleanup/apply', body),
  viewAs: (id: string, resume = false) => json<{ user: import('./api').User }>(`/api/admin/view-as/${encodeURIComponent(id)}${resume ? '?resume=true' : ''}`),
  myOverview: () => json<MyOverview>('/api/me/overview'),
  createNotice: (body: NoticeInput) => send<{ notice: Notice }>('POST', '/api/admin/notices', body),
  updateNotice: (id: string, body: NoticeInput) => send<{ notice: Notice }>('PUT', `/api/admin/notices/${id}`, body),
  deleteNotice: (id: string) => send<{ ok: boolean }>('DELETE', `/api/admin/notices/${id}`),
  setMaintenance: (body: { on: boolean; message?: string; until?: string; start?: string }) => send<Maintenance>('PUT', '/api/admin/maintenance', body),
  // 사용자: 오늘 게시 중인 공지 (주기 확인 → 세션 연장 안 함)
  activeNotices: () => json<{ notices: Notice[]; maintenance: UpcomingMaintenance | null }>('/api/notices', { headers: BACKGROUND_HEADERS }),
  markRead: (ids: string[]) => send<{ marked: number }>('POST', '/api/notices/read', { ids }),
  ackNotice: (id: string) => send<{ ok: boolean }>('POST', `/api/notices/${id}/ack`),
  // 공지사항 게시판 · 상세 · 댓글
  noticeBoard: (q?: string) => json<{ notices: Notice[]; total: number; table: TableStatus }>(`/api/notices/board?${qs({ q })}`),
  noticeDetail: (id: string) => json<{ notice: Notice & { comments: NoticeComment[] }; commentMax: number }>(`/api/notices/${id}`),
  addComment: (id: string, body: string, parentId?: string) => send<{ comments: NoticeComment[] }>('POST', `/api/notices/${id}/comments`, { body, parentId }),
  editComment: (id: string, cid: string, body: string) => send<{ comments: NoticeComment[] }>('PUT', `/api/notices/${id}/comments/${cid}`, { body }),
  deleteComment: (id: string, cid: string) => send<{ comments: NoticeComment[] }>('DELETE', `/api/notices/${id}/comments/${cid}`),
}
