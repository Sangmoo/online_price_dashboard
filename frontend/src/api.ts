export type Column = { key: string; label: string }
export type Row = Record<string, string | number | null>

export type DateInfo = { dt: string; count: number }

export type PageKey = 'dashboard' | 'detail' | 'mall_shop' | 'sale_dashboard' | 'sale_monthly' | 'invt_plan' | 'admin'

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
  brands?: string[] | null // 판매 데이터 브랜드 권한 (null = 모든 브랜드)
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
    SHOP_ROW_CNT: number
    SHOP_CNT: number
  }
  daily: { DT: string; ROW_CNT: number; PRDT_CNT: number; MALL_CNT: number; AVG_DC_RATE: number }[]
  malls: { MALL_NM: string; ROW_CNT: number; PRDT_CNT: number; AVG_DC_RATE: number }[]
  mallDiscount: { MALL_NM: string; ROW_CNT: number; AVG_DC_RATE: number }[]
  histogram: { BUCKET: number; ROW_CNT: number }[]
  shops: { SHOP_ID: string; SHOP_NM: string | null; ROW_CNT: number; PRDT_CNT: number; MALL_CNT: number; AVG_DC_RATE: number | null; MAX_DC_RATE: number | null; LAST_DT: string }[]
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
  shops: { shopId: string; shopNm: string | null; rows: number }[]
  summary: { products: number; malls: number; shops: number; shopRows: number; avgDcRate: number | null }
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
  shops?: string
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

// 문의·오류 신고에 자동으로 붙일 최근 오류 (요청 실패 · 화면 오류, 최근 8건)
export type ClientError = { at: string; kind: 'api' | 'js'; status?: number; url?: string; message: string }
export const recentErrors: ClientError[] = []
export function recordClientError(e: Omit<ClientError, 'at'>) {
  recentErrors.push({ at: new Date().toLocaleTimeString('ko-KR', { hour12: false }), ...e, message: String(e.message).slice(0, 300) })
  if (recentErrors.length > 8) recentErrors.shift()
}

export const SESSION_EXPIRED_EVENT = 'opd:session-expired'
export const SESSION_EXTENDED_EVENT = 'opd:session-extended'
// 점검 모드(503 MAINTENANCE): 관리자 외 사용자는 점검 안내 화면으로
export const MAINTENANCE_EVENT = 'opd:maintenance'

// 사람 조작 없이 화면이 스스로 보내는 요청(주기 확인 등): 서버가 세션을 연장하지 않는다
export const BACKGROUND_HEADERS = { 'X-Background': '1' }

export async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, { credentials: 'same-origin', ...init })
  const exp = res.headers.get('X-Session-Expires')
  const background = new Headers(init?.headers).get('X-Background') === '1'
  if (exp && !background) window.dispatchEvent(new CustomEvent(SESSION_EXTENDED_EVENT, { detail: Number(exp) }))
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const d = body.detail
    const message = typeof d === 'string' ? d : d?.message || `요청 실패 (${res.status})`
    const code = typeof d === 'object' && d?.code ? d.code : 'ERROR'
    if (res.status !== 401) recordClientError({ kind: 'api', status: res.status, url: url.split('?')[0], message })
    if (res.status === 401 && !url.startsWith('/api/auth/login')) {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: message }))
    }
    if (res.status === 503 && code === 'MAINTENANCE' && !url.startsWith('/api/auth/login')) {
      window.dispatchEvent(new CustomEvent(MAINTENANCE_EVENT, { detail: message }))
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
  // 메뉴를 열 때 알림 (관리자 > 메뉴 이용 통계)
  menuOpen: (page: string) => sendJson<{ ok: boolean }>('POST', '/api/usage/menu', { page }),

  // 개인 설정
  getPref: <T>(key: string) => getJson<{ value: T | null }>(`/api/prefs/${key}`),
  setPref: (key: string, value: unknown) => sendJson('PUT', `/api/prefs/${key}`, { value }),

  // 데이터
  dates: () => getJson<{ dates: DateInfo[] }>('/api/dates'),
  dashboard: (start: string, end: string, signal?: AbortSignal) =>
    getJson<Dashboard>(`/api/dashboard?${qs({ start, end })}`, signal),
  rows: (p: RowsQuery, signal?: AbortSignal) => getJson<RowsResponse>(`/api/rows?${qs(p)}`, signal),
  rowsExportUrl: (p: Omit<RowsQuery, 'page' | 'size'> & { cols?: string }) => `/api/rows/export?${qs(p)}`,
  /** 최근 7일(당일 포함) 수집 행 매장코드를 판매처 매장 연결로 채움 */
  fillShopIds: () => sendJson<{ from: string; to: string; updated: number; elapsedSec: number }>('POST', '/api/rows/fill-shop'),

  // AI 대화
  usage: () => getJson<Usage>('/api/chat/usage'),
  conversations: () => getJson<{ conversations: ConversationSummary[] }>('/api/chat/conversations'),
  conversation: (id: string) => getJson<StoredConversation>(`/api/chat/conversations/${id}`),
  renameConversation: (id: string, title: string) => sendJson('PATCH', `/api/chat/conversations/${id}`, { title }),
  deleteConversation: (id: string) => sendJson('DELETE', `/api/chat/conversations/${id}`),
  favorites: () => getJson<{ favorites: Favorite[] }>('/api/chat/favorites'),
  addFavorite: (text: string) => sendJson<{ favorites: Favorite[] }>('POST', '/api/chat/favorites', { text }),
  deleteFavorite: (id: number) => sendJson<{ favorites: Favorite[] }>('DELETE', `/api/chat/favorites/${id}`),

  // 온라인 가격 > 판매처 매장 연결
  mallShops: {
    list: (days: number) => getJson<MallShopList>(`/api/mall-shops?${qs({ days })}`),
    shops: () => getJson<{ shops: { shopId: string; shopNm: string | null; brands: string[]; teamNm: string | null }[] }>('/api/mall-shops/shops'),
    save: (items: MallShopSaveItem[]) =>
      sendJson<{ saved: number; deleted: number; changed: number }>('PUT', '/api/mall-shops', { items }),
  },

  // 문의·오류 신고
  sendFeedback: (body: { type: FeedbackType; content: string; page: string; context: Record<string, unknown>; images?: { name: string; data: string }[] }) =>
    sendJson<Feedback>('POST', '/api/feedback', body),
  myFeedback: () => getJson<{ rows: Feedback[]; limits?: FeedbackLimits }>('/api/feedback/mine'),
  // 주기 확인 → 세션 연장 안 함
  feedbackBadge: async () =>
    (await apiFetch('/api/feedback/badge', { headers: BACKGROUND_HEADERS })).json() as Promise<{ newAnswers: number; open: number | null }>,

  // 관리자
  admin: {
    users: (q?: string) => getJson<AdminUsersResponse>(`/api/admin/users?${qs({ q })}`),
    directory: (q: string) => getJson<{ users: { id: string; name: string; registered: boolean }[] }>(`/api/admin/directory?${qs({ q })}`),
    createUser: (body: AdminUserUpdate & { id: string }) => sendJson<{ user: AdminUser }>('POST', '/api/admin/users', body),
    saveUser: (id: string, body: Partial<AdminUserUpdate>) => sendJson<{ user: AdminUser }>('PUT', `/api/admin/users/${encodeURIComponent(id)}`, body),
    savePermissions: (changes: { id: string; pages: PageKey[] }[]) => sendJson<{ users: AdminUser[] }>('PUT', '/api/admin/permissions', { changes }),
    aiTools: () => getJson<AiToolsOverview>('/api/admin/ai-tools'),
    dataStatus: () => getJson<DataStatus>('/api/admin/data-status'),
    // 10분마다 자동 확인 → 세션 연장 안 함 (화면을 열어만 둬도 1시간 뒤 로그아웃되도록)
    dataFreshness: async () => (await apiFetch('/api/admin/data-freshness', { headers: BACKGROUND_HEADERS })).json() as Promise<DataFreshness>,
    restorePreview: (data: unknown) => sendJson<RestorePreview>('POST', '/api/admin/restore/preview', { data }),
    restoreApply: (data: unknown, sections: string[]) =>
      sendJson<{ applied: string[]; failed: { item: string; reason: string }[] }>('POST', '/api/admin/restore/apply', { data, sections }),
    menuUsage: (days: number) => getJson<MenuUsage>(`/api/admin/menu-usage?${qs({ days })}`),
    aiToolStats: (days: number) => getJson<AiToolStats>(`/api/admin/ai-tool-stats?${qs({ days })}`),
    feedback: (status?: string) => getJson<{ rows: Feedback[]; counts: Record<FeedbackStatus, number>; storage: string; images?: { count: number; bytes: number }; leadStats?: FeedbackLeadStats }>(`/api/admin/feedback?${qs({ status })}`),
    answerFeedback: (id: string, body: { status?: FeedbackStatus; answer?: string }) =>
      sendJson<Feedback>('PUT', `/api/admin/feedback/${encodeURIComponent(id)}`, body),
    serverStatus: (days: number) => getJson<ServerStatus>(`/api/admin/server-status?${qs({ days })}`),
    cleanupLogs: () => sendJson<{ deleted: string[]; freedBytes: number; keepDays: number }>('POST', '/api/admin/logs/cleanup'),
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
  brands: string[] | null
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
  brands: string[] | null
}
export type PageMeta = { key: PageKey; label: string; group: string }
export type AdminUsersResponse = { users: AdminUser[]; pages: PageMeta[]; superAdminId: string; brandOptions: string[]; brandReady: boolean }
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
  productMv?: { exists: boolean; staleness: string | null; mvMaxMonth: string | null }
  prewarm?: { last: string | null; elapsedSec: number | null; scopes: number; error: string | null; reason?: string; running: boolean }
}
export type AiToolStats = {
  days: number
  since: string
  keepDays: number
  questions: number
  models: Record<string, number>
  routes: Record<string, number>
  modelSwitches: number
  tools: {
    name: string; label: string; calls: number; ok: number; inputErrors: number; failures: number; errorRate: number | null
    avgSec: number | null; p95Sec: number | null; maxSec: number | null; users: number; last: string | null
    topErrors: { message: string; count: number }[]
  }[]
  unusedTools: { name: string; label: string }[]
}
export type MallShopRow = {
  mallNm: string; sellNo: string; brdCd: string; brand: string; rows: number; products: number; lastDt: string | null
  shopFilled: number; rmk: string | null; rmkShare?: number | null; seen: boolean; shopId: string | null; shopNm: string | null; useYn: 'Y' | 'N' | null
  mapRmk: string | null; updatedBy: string | null; updatedAt: string | null; starShopId: string | null; starShopNm: string | null
  effectiveShopId: string | null; suggestions: { shopId: string; shopNm: string | null; brand: string }[]
}
export type MallShopSaveItem = { mallNm: string; sellNo: string; brdCd: string; shopId: string; useYn: 'Y' | 'N'; rmk: string }
export type MallShopList = {
  ready: boolean
  days: number
  rows: MallShopRow[]
  summary: { combos: number; sellers: number; mapped: number; unmapped: number; malls: number; rowsTotal: number; rowsMapped: number
             rowsMappedPct: number | null; shopFilled: number }
}
export type FeedbackType = 'BUG' | 'REQ' | 'ASK'
export type FeedbackStatus = 'NEW' | 'DOING' | 'DONE'
export type Feedback = {
  id: string
  userId: string
  userName: string | null
  type: FeedbackType
  typeLabel: string
  content: string
  page: string | null
  context: Record<string, unknown>
  status: FeedbackStatus
  statusLabel: string
  answer: string | null
  answerBy: string | null
  answeredAt: string | null
  createdAt: string
  updatedAt: string | null
  files: { no: number; name: string; type: string; size: number }[]
  history?: { at: string; by: string; from: FeedbackStatus | null; to: FeedbackStatus | null; fromLabel: string | null; toLabel: string | null; answered: boolean }[]
  doneAt?: string | null
  leadHours?: number | null
  ageHours?: number | null
}
export type FeedbackLeadStats = { doneCount: number; avgHours: number | null; medianHours: number | null; oldestOpenHours: number | null }
export type FeedbackLimits = { maxText: number; maxFiles: number; maxFileBytes: number; types: string[] }
export type DataFreshness = {
  behind: boolean; mvMaxMonth: string | null; baseMaxMonth: string | null; lastRefresh: string | null; refreshing: boolean
  maintenance?: { on: boolean; message: string; until: string | null }
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
  logKeepDays: number
  feedbackImageKeepMonths?: number
  autoModel: boolean
  simpleModel: string
}
export type RestorePreview = {
  file: { createdAt: string | null; createdBy: string | null }
  users: {
    added: { id: string; name: string | null }[]
    changed: { id: string; name: string | null; diff: Record<string, { before: unknown; after: unknown }> }[]
    same: number
    notInFile: { id: string; name: string | null }[]
    skipped: { id: string; name: string | null; reason: string }[]
  }
  settings: { changed: { key: string; before: unknown; after: unknown }[] }
  aiTools: {
    builtinChanged: { name: string }[]
    customAdded: { name: string; label: string }[]
    customChanged: { name: string; label: string; keys: string[] }[]
  }
}
export type MenuUsageCell = { granted: boolean; opens: number; days: number; last: string | null }
export type MenuUsage = {
  days: number
  since: string
  storage: 'oracle' | 'sqlite'
  pages: { page: string; label: string; opens: number; users: number; grantedUsers: number; activeDays: number; last: string | null }[]
  users: { id: string; name: string; active: boolean; lastLoginAt: string | null; opens: number; cells: Record<string, MenuUsageCell>; unusedPages: string[] }[]
  daily: { day: string; opens: number }[]
  unusedGrants: number
}
export type ServerStatus = {
  days: number
  since: string
  server: { startedAt: string; uptimeSec: number; pid: number }
  pool: { opened: number; busy: number; max: number } | null
  requests: { count: number; errors5xx: number; slow: number; avgMs: number | null; p95Ms: number | null; slowSec: number; slowPaths: { path: string; count: number; maxMs: number }[] }
  slowSql: { count: number; thresholdSec: number; top: { sql: string; count: number; avgSec: number; maxSec: number; last: string }[] }
  sqlErrors: { count: number; recent: { ts: string; error: string; sql: string }[] }
  errors: { count: number; recent: { ts: string; category: string; message: string }[] }
  daily: { day: string; requests: number; errors: number; slowSql: number }[]
  supervisor: { running: boolean; crashRestarts: number; deployRestarts: number; events: { ts: string; kind: 'crash' | 'deploy' | 'service'; message: string }[] }
  disk: { logsBytes: number; exportsBytes: number; freeBytes: number; totalBytes: number; logFiles: number; oldestLog: string | null }
  keepDays: number | null
}
export type UsageRow = { questions: number; calls: number; input_tokens: number; output_tokens: number; cost: number }
export type AdminUsage = {
  since: string
  days: number
  total: { questions: number; cost: number; input_tokens: number; output_tokens: number; users: number }
  daily: (UsageRow & { day: string; users: number })[]
  byUser: (UsageRow & { usr_id: string; usr_nm: string | null; last_used: string })[]
  byModel?: { model: string | null; calls: number; cost: number; input_tokens: number; output_tokens: number }[]
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

/** AI 답변 표가 잘렸을 때: 같은 도구·조건으로 전체 결과(최대 10만 행)를 서버에서 다시 조회해 엑셀로 */
export function exportFullTable(title: string, source: { tool: string; input: Record<string, unknown> }) {
  return downloadFile(
    '/api/chat/export-full',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, ...source }) },
    `${title}.xlsx`,
  )
}

export type ChatEvent =
  | { type: 'conversation'; id: string; title: string }
  | { type: 'text_start' }
  | { type: 'text'; text: string }
  | { type: 'tool'; id: string; name: string; label: string; input: unknown }
  | { type: 'tool_done'; id: string; ok: boolean }
  | { type: 'table'; id: string; title: string; columns: Column[]; rows: Row[]; totalMatched?: number; truncated?: boolean; source?: { tool: string; input: Record<string, unknown> } }
  | { type: 'notice'; message: string }
  | { type: 'action'; id: string; actionKind: 'mall_shop_save'; title: string; items: MallShopSaveItem[]; lines: string[]; warnings: string[] }
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
