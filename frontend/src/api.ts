export type Column = { key: string; label: string }
export type Row = Record<string, string | number | null>

export type DateInfo = { dt: string; count: number }

export type PageKey = 'dashboard' | 'detail' | 'sale_dashboard' | 'sale_monthly' | 'invt_plan' | 'admin'

export type AiLimits = {
  enabled: boolean
  globalEnabled: boolean
  userEnabled: boolean
  dailyQuestions: number
  dailyCostUsd: number
  customLimits: boolean
}

export type User = {
  id: string
  name: string
  role: 'ADMIN' | 'USER'
  superAdmin: boolean
  active: boolean
  pages: PageKey[]
  ai: AiLimits
  sessionExpiresAt?: number
}

export type Usage = {
  questions: number
  costUsd: number
  inputTokens: number
  outputTokens: number
  questionLimit: number
  costLimitUsd: number
  enabled: boolean
}

export type Dashboard = {
  start: string
  end: string
  kpi: {
    ROW_CNT: number
    PRDT_CNT: number
    MALL_CNT: number
    SELLER_CNT: number
    DAY_CNT: number
    AVG_DC_RATE: number | null
    MAX_DC_RATE: number | null
    DEEP_DC_CNT: number
  }
  daily: { DT: string; ROW_CNT: number; PRDT_CNT: number; MALL_CNT: number; AVG_DC_RATE: number }[]
  malls: { MALL_NM: string; ROW_CNT: number; PRDT_CNT: number; AVG_DC_RATE: number }[]
  mallDiscount: { MALL_NM: string; ROW_CNT: number; AVG_DC_RATE: number }[]
  histogram: { BUCKET: number; ROW_CNT: number }[]
  topProducts: {
    PRDT_CD: string
    TITLE: string
    PRICE: number
    MIN_DC_PRICE: number
    MAX_DC_RATE: number
    MIN_MALL: string
    MIN_DT: string
    MALL_CNT: number
    ROW_CNT: number
  }[]
  generatedAt: string
}

export type RowsResponse = {
  dt: string
  columns: Column[]
  rows: Row[]
  total: number
  totalAll: number
  page: number
  pages: number
  size: number
  malls: string[]
  summary: { products: number; malls: number; avgDcRate: number | null }
}

export type RowsQuery = {
  dt: string
  page: number
  size: number
  sort?: string
  order: 'asc' | 'desc'
  q?: string
  mall?: string
  minRate?: number
  maxRate?: number
}

// ----------------------------------------------------------------------------
// 공통 fetch: 세션 만료(401) 감지 + 세션 연장 시각 동기화
// ----------------------------------------------------------------------------
export class ApiError extends Error {
  status: number
  code: string
  extra: Record<string, unknown>
  constructor(status: number, message: string, code = 'ERROR', extra: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.extra = extra
  }
}

export const SESSION_EXPIRED_EVENT = 'opd:session-expired'
export const SESSION_EXTENDED_EVENT = 'opd:session-extended'

export async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, { credentials: 'same-origin', ...init })
  const exp = res.headers.get('X-Session-Expires')
  if (exp) window.dispatchEvent(new CustomEvent(SESSION_EXTENDED_EVENT, { detail: Number(exp) }))
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const d = body.detail
    const message = typeof d === 'string' ? d : d?.message || `요청 실패 (${res.status})`
    const code = typeof d === 'object' && d?.code ? d.code : 'ERROR'
    if (res.status === 401 && !url.startsWith('/api/auth/login')) {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: message }))
    }
    throw new ApiError(res.status, message, code, typeof d === 'object' ? d : {})
  }
  return res
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  return (await apiFetch(url, { signal })).json()
}

async function sendJson<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await apiFetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return res.json()
}

export function qs(params: Record<string, string | number | undefined | null>) {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  return s.toString()
}

export const api = {
  // 인증
  login: (id: string, password: string) => sendJson<{ user: User; sessionTtl: number }>('POST', '/api/auth/login', { id, password }),
  logout: () => sendJson<{ ok: boolean }>('POST', '/api/auth/logout'),
  me: () => getJson<{ user: User; usage: Usage; sessionTtl: number }>('/api/auth/me'),
  touch: () => sendJson<{ sessionExpiresAt: number }>('POST', '/api/auth/touch'),

  // 개인 설정
  getPref: <T>(key: string) => getJson<{ value: T | null }>(`/api/prefs/${key}`),
  setPref: (key: string, value: unknown) => sendJson('PUT', `/api/prefs/${key}`, { value }),

  // 데이터
  dates: () => getJson<{ dates: DateInfo[] }>('/api/dates'),
  dashboard: (start: string, end: string, signal?: AbortSignal) =>
    getJson<Dashboard>(`/api/dashboard?${qs({ start, end })}`, signal),
  rows: (p: RowsQuery, signal?: AbortSignal) => getJson<RowsResponse>(`/api/rows?${qs(p)}`, signal),
  rowsExportUrl: (p: Omit<RowsQuery, 'page' | 'size'> & { cols?: string }) => `/api/rows/export?${qs(p)}`,

  // AI 대화
  usage: () => getJson<Usage>('/api/chat/usage'),
  conversations: () => getJson<{ conversations: ConversationSummary[] }>('/api/chat/conversations'),
  conversation: (id: string) => getJson<StoredConversation>(`/api/chat/conversations/${id}`),
  renameConversation: (id: string, title: string) => sendJson('PATCH', `/api/chat/conversations/${id}`, { title }),
  deleteConversation: (id: string) => sendJson('DELETE', `/api/chat/conversations/${id}`),
  favorites: () => getJson<{ favorites: Favorite[] }>('/api/chat/favorites'),
  addFavorite: (text: string) => sendJson<{ favorites: Favorite[] }>('POST', '/api/chat/favorites', { text }),
  deleteFavorite: (id: number) => sendJson<{ favorites: Favorite[] }>('DELETE', `/api/chat/favorites/${id}`),

  // 관리자
  admin: {
    users: (q?: string) => getJson<AdminUsersResponse>(`/api/admin/users?${qs({ q })}`),
    directory: (q: string) => getJson<{ users: { id: string; name: string; registered: boolean }[] }>(`/api/admin/directory?${qs({ q })}`),
    createUser: (body: AdminUserUpdate & { id: string }) => sendJson<{ user: AdminUser }>('POST', '/api/admin/users', body),
    saveUser: (id: string, body: Partial<AdminUserUpdate>) => sendJson<{ user: AdminUser }>('PUT', `/api/admin/users/${encodeURIComponent(id)}`, body),
    savePermissions: (changes: { id: string; pages: PageKey[] }[]) => sendJson<{ users: AdminUser[] }>('PUT', '/api/admin/permissions', { changes }),
    aiTools: () => getJson<AiToolsOverview>('/api/admin/ai-tools'),
    dataStatus: () => getJson<DataStatus>('/api/admin/data-status'),
    refreshState: () => getJson<{ refresh: MvRefresh }>('/api/admin/data-status/refresh'),
    refreshMv: () => sendJson<{ refresh: MvRefresh }>('POST', '/api/admin/data-status/refresh'),
    saveBuiltinTool: (name: string, body: { enabled: boolean; extraDesc: string; description?: string }) =>
      sendJson<AiToolsOverview>('PUT', `/api/admin/ai-tools/builtin/${encodeURIComponent(name)}`, body),
    createTool: (tool: CustomToolDef) => sendJson<AiToolsOverview>('POST', '/api/admin/ai-tools', tool),
    updateTool: (tool: CustomToolDef) => sendJson<AiToolsOverview>('PUT', `/api/admin/ai-tools/${encodeURIComponent(tool.name)}`, tool),
    deleteTool: (name: string) => sendJson<AiToolsOverview>('DELETE', `/api/admin/ai-tools/${encodeURIComponent(name)}`),
    testTool: (tool: CustomToolDef, args: Record<string, string>) => sendJson<AiToolTestResult>('POST', '/api/admin/ai-tools/test', { tool, args }),
    settings: () => getJson<AdminSettings>('/api/admin/settings'),
    saveSettings: (body: Partial<AdminSettings>) => sendJson<AdminSettings>('PUT', '/api/admin/settings', body),
    usage: (days: number) => getJson<AdminUsage>(`/api/admin/usage?${qs({ days })}`),
    logins: (q?: string) => getJson<{ logins: LoginLog[]; locks: LockInfo[] }>(`/api/admin/logins?${qs({ q })}`),
    unlock: (id: string) => sendJson('DELETE', `/api/admin/locks/${encodeURIComponent(id)}`),
    sessions: () => getJson<{ sessions: SessionInfo[] }>('/api/admin/sessions'),
    killSession: (sid: string) => sendJson('DELETE', `/api/admin/sessions/${sid}`),
    logs: (p: { level?: string; q?: string; category?: string }) =>
      getJson<{ logs: ServerLog[]; slowSqlSec: number }>(`/api/admin/logs?${qs(p)}`),
  },
}

export type ConversationSummary = { id: string; title: string; createdAt: string; updatedAt: string }
export type Favorite = { id: number; text: string; createdAt: string }
export type StoredConversation = { id: string; title: string; messages: unknown[]; updatedAt: string }

export type AdminUser = Pick<User, 'id' | 'name' | 'role' | 'superAdmin' | 'active' | 'pages' | 'ai'> & {
  rawAiEnabled: boolean
  rawDailyQuestions: number | null
  rawDailyCostUsd: number | null
  lastLoginAt: string | null
  createdAt: string
  updatedAt: string | null
  updatedBy: string | null
  todayQuestions: number
  todayCostUsd: number
  online: boolean
}
export type ServerLog = { ts: string; level: string; category: string; message: string }
export type AdminUserUpdate = {
  role: 'ADMIN' | 'USER'
  pages: PageKey[]
  aiEnabled: boolean
  dailyQuestions: number | null
  dailyCostUsd: number | null
  active: boolean
}
export type PageMeta = { key: PageKey; label: string; group: string }
export type AdminUsersResponse = { users: AdminUser[]; pages: PageMeta[]; superAdminId: string }
export type ToolParam = { name: string; type: string; required: boolean; description: string; enum?: string[]; default?: string | number | null }
export type CustomToolDef = {
  name: string
  label: string
  description: string
  page: PageKey | ''
  sql: string
  params: ToolParam[]
  maxRows: number
  enabled: boolean
}
export type CustomTool = CustomToolDef & { updatedAt: string | null; updatedBy: string | null }
export type BuiltinTool = {
  name: string
  label: string
  group: string
  pages: { key: PageKey; label: string }[]
  description: string
  defaultDescription: string
  customized: boolean
  params: string[]
  enabled: boolean
  extraDesc: string
  updatedAt: string | null
  updatedBy: string | null
}
export type DataStatus = {
  name: string
  usable: boolean
  staleness: string | null
  lastRefresh: string | null
  mvMaxMonth: string | null
  baseMaxMonth: string | null
  rows: number | null
  hasCostColumn: boolean
  behind: boolean
  refresh: MvRefresh
}
export type MvRefresh = {
  status: 'idle' | 'running' | 'done' | 'error'
  started: string | null
  finished: string | null
  by: string | null
  error: string | null
  elapsedSec: number | null
}
export type AiToolsOverview = {
  storage: 'oracle' | 'sqlite'
  builtin: BuiltinTool[]
  custom: CustomTool[]
  pages: PageMeta[]
  paramTypes: { key: string; label: string }[]
  maxRowsLimit: number
}
export type AiToolTestResult =
  | { ok: true; elapsedMs: number; columns: Column[]; rows: Row[]; truncated: boolean; schema: unknown }
  | { ok: false; stage: 'definition' | 'args' | 'sql'; message: string }
export type AdminSettings = {
  aiEnabled: boolean
  defaultDailyQuestions: number
  defaultDailyCostUsd: number
  model: string
  effort: string
  models: string[]
  efforts: string[]
  envModel: string
  envEffort: string
}
export type UsageRow = { questions: number; calls: number; input_tokens: number; output_tokens: number; cost: number }
export type AdminUsage = {
  since: string
  days: number
  total: { questions: number; cost: number; input_tokens: number; output_tokens: number; users: number }
  daily: (UsageRow & { day: string; users: number })[]
  byUser: (UsageRow & { usr_id: string; usr_nm: string | null; last_used: string })[]
}
export type LoginLog = { id: number; usr_id: string; usr_nm: string | null; ts: string; success: number; reason: string; ip: string | null }
export type LockInfo = { usr_id: string; fail_count: number; locked_until: number; locked: boolean; remainSec: number }
export type SessionInfo = {
  sid: string
  usr_id: string
  usr_nm: string | null
  created_at: number
  last_seen: number
  expires_at: number
  ip: string | null
  user_agent: string | null
}

export async function downloadFile(url: string, init?: RequestInit, fallbackName = 'download.xlsx') {
  const res = await apiFetch(url, init)
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

export function exportTable(title: string, columns: Column[], rows: Row[]) {
  return downloadFile(
    '/api/export/table',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, columns, rows }),
    },
    `${title}.xlsx`,
  )
}

export type ChatEvent =
  | { type: 'conversation'; id: string; title: string }
  | { type: 'text_start' }
  | { type: 'text'; text: string }
  | { type: 'tool'; id: string; name: string; label: string; input: unknown }
  | { type: 'tool_done'; id: string; ok: boolean }
  | { type: 'table'; id: string; title: string; columns: Column[]; rows: Row[]; totalMatched?: number }
  | { type: 'notice'; message: string }
  | { type: 'error'; message: string; code?: string }
  | { type: 'usage' } & Usage
  | { type: 'done' }

export async function streamChat(
  body: { message: string; conversationId?: string | null; context?: Record<string, string> },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
) {
  const res = await apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.body) throw new Error('응답 스트림이 없습니다.')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}
