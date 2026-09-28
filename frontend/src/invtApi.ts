import { apiFetch, downloadFile } from './api'

export type InvtPlan = {
  planId: number
  shopId: string
  moBrdCd: string | null
  brdNm: string | null
  shopFormNm: string | null
  shopNm: string | null
  prevSaleAmt: number | null
  currSaleAmt: number | null
  prevSaleMil: number | null
  currSaleMil: number | null
  saleRate: number | null
  addr: string | null
  areaNm: string | null
  regionNm: string | null
  lastInvtDt: string | null
  prevInvtType: string | null
  prevInvtResult: number | null
  elapsedDays: number | null
  stockQty: number | null
  stockBaseDt: string | null
  invtPlanNote: string | null
  baseFee: number | null
  expectAmt: number | null
  invtPlanDt: string | null
  rmk: string | null
  twiceYearYn: 'Y' | 'N'
  shopRankNm: string | null
  stlmTeam: string | null
  smasrNm: string | null
  smasrHp: string | null
  shopTel: string | null
  insDay: string | null
  insUserId: string | null
  uptDay: string | null
  uptUserId: string | null
}

/** 등록/수정 폼에서 다루는 값 (모두 문자열/불리언으로 편집) */
export type PlanForm = Partial<Record<keyof InvtPlan, string | number | boolean | null>>

export type InvtOptions = {
  areas: string[]
  regions: string[]
  areaRegion: Record<string, string>
  invtTypes: string[]
  stlmTeams: string[]
  rmkMaxBytes: number
  encoding: 'utf-8' | 'cp949'
}

export type ShopRow = { shopId: string; shopNm: string; shopFormNm: string | null; shopForm2Nm: string | null }
export type ShopDetail = {
  values: PlanForm
  missing: string[]
  missingLabels: string[]
  notes?: string[]
  errors: Record<string, string>
  existingPlans: number
}
export type Manager = {
  shopId: string
  smasrNm: string | null
  smasrHp: string | null
  openDt: string | null
  closeDt: string | null
  current: boolean
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  return (await apiFetch(url, init)).json()
}
const send = <T,>(method: string, url: string, body: unknown) =>
  json<T>(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const invtApi = {
  options: () => json<InvtOptions>('/api/invt-plans/options'),
  list: () => json<{ plans: InvtPlan[] }>('/api/invt-plans'),
  create: (body: PlanForm) => send<{ plan: InvtPlan }>('POST', '/api/invt-plans', body),
  update: (id: number, body: PlanForm) => send<{ plan: InvtPlan }>('PUT', `/api/invt-plans/${id}`, body),
  remove: (ids: number[]) => send<{ deleted: number }>('POST', '/api/invt-plans/delete', { ids }),
  shops: (q: string) => json<{ shops: ShopRow[] }>(`/api/invt-plans/shops?q=${encodeURIComponent(q)}`),
  shop: (id: string) => json<ShopDetail>(`/api/invt-plans/shops/${encodeURIComponent(id)}`),
  managers: (id: string) => json<{ managers: Manager[] }>(`/api/invt-plans/shops/${encodeURIComponent(id)}/managers`),
  exportXlsx: (ids: number[]) => downloadFile(`/api/invt-plans/export?ids=${ids.join(',')}`, undefined, '매장재고실사계획.xlsx'),
}

/** DB 문자셋 기준 바이트 수 (AL32UTF8: 한글 3바이트, KO16MSWIN949: 2바이트) */
export function byteLength(s: string, encoding: 'utf-8' | 'cp949') {
  if (encoding === 'utf-8') return new TextEncoder().encode(s).length
  let n = 0
  for (const ch of s) n += ch.charCodeAt(0) > 0x7f ? 2 : 1
  return n
}

export const ymdToIso = (v: unknown) => {
  const s = String(v ?? '')
  return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : ''
}
export const isoToYmd = (v: string) => v.replaceAll('-', '')
