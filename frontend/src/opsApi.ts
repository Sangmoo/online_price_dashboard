// 관리자 운영: 홈 · 스케줄/배치 · 다운로드 이력 · 공지/점검 모드, 사용자 공지 팝업
import { apiFetch, BACKGROUND_HEADERS, qs } from './api'

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  return (await apiFetch(url, init)).json()
}
const send = <T,>(method: string, url: string, body?: unknown) =>
  json<T>(url, { method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

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
  downloads: { ready: boolean; today: number; week: number; sensitiveWeek: number; topUser: { id: string; name: string; count: number } | null } & CardError
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
}

export type NoticeLevel = 'info' | 'warn' | 'important'
export type NoticeFile = { no: number; kind: 'image' | 'file'; name: string; type: string; size: number }
export type Notice = {
  id: string; title: string; body: string; level: NoticeLevel; levelLabel: string; start: string; end: string; use: boolean
  status: 'active' | 'scheduled' | 'ended' | 'off'; createdBy: string | null; createdAt: string | null; updatedBy: string | null; updatedAt: string | null
  images: NoticeFile[]; files: NoticeFile[]; commentCount: number
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
}
export type NoticeLimits = { attach: number; attachMb: number; images: number; imageMb: number; attachTypes: string[] }
export const fileSize = (b: number) => (b < 1024 ? `${b}B` : b < 1024 ** 2 ? `${Math.round(b / 1024)}KB` : `${(b / 1024 ** 2).toFixed(1)}MB`)
export const noticeFileUrl = (id: string, no: number) => `/api/notices/${id}/files/${no}`
export type Maintenance = { on: boolean; message: string; until: string | null }

export const opsApi = {
  home: (fresh = false) => json<AdminHome>(`/api/admin/home?${qs({ fresh: fresh ? 'true' : undefined })}`),
  jobs: (days: number, fresh = false) => json<JobsOverview>(`/api/admin/jobs?${qs({ days, fresh: fresh ? 'true' : undefined })}`),
  downloads: (p: { days: number; usr?: string; kind?: string }) => json<DownloadReport>(`/api/admin/downloads?${qs(p)}`),
  notices: () => json<{ notices: Notice[]; levels: Record<NoticeLevel, string>; table: TableStatus; titleMax: number; bodyMax: number; limits: NoticeLimits; maintenance: Maintenance }>('/api/admin/notices'),
  createNotice: (body: NoticeInput) => send<{ notice: Notice }>('POST', '/api/admin/notices', body),
  updateNotice: (id: string, body: NoticeInput) => send<{ notice: Notice }>('PUT', `/api/admin/notices/${id}`, body),
  deleteNotice: (id: string) => send<{ ok: boolean }>('DELETE', `/api/admin/notices/${id}`),
  setMaintenance: (body: { on: boolean; message?: string; until?: string }) => send<Maintenance>('PUT', '/api/admin/maintenance', body),
  // 사용자: 오늘 게시 중인 공지 (주기 확인 → 세션 연장 안 함)
  activeNotices: () => json<{ notices: Notice[] }>('/api/notices', { headers: BACKGROUND_HEADERS }),
  // 공지사항 게시판 · 상세 · 댓글
  noticeBoard: (q?: string) => json<{ notices: Notice[]; total: number; table: TableStatus }>(`/api/notices/board?${qs({ q })}`),
  noticeDetail: (id: string) => json<{ notice: Notice & { comments: NoticeComment[] }; commentMax: number }>(`/api/notices/${id}`),
  addComment: (id: string, body: string, parentId?: string) => send<{ comments: NoticeComment[] }>('POST', `/api/notices/${id}/comments`, { body, parentId }),
  editComment: (id: string, cid: string, body: string) => send<{ comments: NoticeComment[] }>('PUT', `/api/notices/${id}/comments/${cid}`, { body }),
  deleteComment: (id: string, cid: string) => send<{ comments: NoticeComment[] }>('DELETE', `/api/notices/${id}/comments/${cid}`),
}
