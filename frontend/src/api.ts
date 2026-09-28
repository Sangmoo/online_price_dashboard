export type Column = { key: string; label: string }
export type Row = Record<string, string | number | null>

export type DateInfo = { dt: string; count: number }

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
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `요청 실패 (${res.status})`)
  }
  return res.json()
}

function qs(params: Record<string, string | number | undefined>) {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v))
  return s.toString()
}

export const api = {
  dates: () => getJson<{ dates: DateInfo[] }>('/api/dates'),
  dashboard: (start: string, end: string, signal?: AbortSignal) =>
    getJson<Dashboard>(`/api/dashboard?${qs({ start, end })}`, signal),
  rows: (p: RowsQuery, signal?: AbortSignal) => getJson<RowsResponse>(`/api/rows?${qs(p)}`, signal),
  rowsExportUrl: (p: Omit<RowsQuery, 'page' | 'size'>) => `/api/rows/export?${qs(p)}`,
}

export async function downloadFile(url: string, init?: RequestInit, fallbackName = 'download.xlsx') {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`다운로드 실패 (${res.status})`)
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
  | { type: 'session'; sessionId: string }
  | { type: 'text_start' }
  | { type: 'text'; text: string }
  | { type: 'tool'; id: string; name: string; label: string; input: unknown }
  | { type: 'tool_done'; id: string; ok: boolean }
  | { type: 'table'; id: string; title: string; columns: Column[]; rows: Row[]; totalMatched?: number }
  | { type: 'notice'; message: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export async function streamChat(
  body: { message: string; sessionId?: string | null; context?: Record<string, string> },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`대화 요청 실패 (${res.status})`)
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

export function resetChat(sessionId: string) {
  return fetch(`/api/chat/${sessionId}`, { method: 'DELETE' })
}
