import { apiFetch, downloadFile, qs } from './api'

// 재고 재배치 추천 (매장 간 RT · 창고 → 매장 배분) — 추천 조회 + 관리자 ERP 등록(본사지시 RT 지시 · 배분의뢰) · 삭제

export type Code = { code: string; name: string }
export type RecentRun = {
  seq: string
  at: string | null
  user: string | null
  askSeqn: number | null
  wh: string
  planYy: string[]
  seasons: string[]
  prdtGrps: string[]
  items: string[]
  prdt: string | null
  teams: string[]
  grdGrp: string | null
  from: string | null
  to: string | null
  rate: number
  base: string
  ignored: string[]
}
export type StockOptions = {
  brand: string
  brands: Code[]
  teams: Code[]
  seasons: Code[]
  prdtGrps: Code[]
  planYears: string[]
  warehouses: Code[]
  bases: { id: string; aplyDt: string | null; rmk: string | null }[]
  gradeGroups: { id: string; name: string; base: boolean }[]
  recentRuns: RecentRun[]
  defaultSeasons: string[]
  defaultPlanYy: string[]
  today: string
  maxDays: number
  canWrite: boolean
}

export type RtCond = {
  brand: string
  dateFrom: string
  dateTo: string
  planYy: string[]
  seasons: string[]
  prdt: string
  teams: string[]
  per: number
  order: 'slow' | 'auto'
  senderMax: number
  limits: boolean
}
export type RtRow = {
  no: number
  prdtCd: string
  styleNm: string | null
  colorCd: string
  sizeCd: string
  qty: number
  fromShopId: string
  fromShopNm: string | null
  fromTeam: string | null
  fromStock: number
  fromSendable: number
  fromSales: number
  fromLastSale: string | null
  toShopId: string
  toShopNm: string | null
  toTeam: string | null
  toStock: number
  toSales: number
  toFailCnt: number
  toIncoming: number
  why: string
}
export type RtUnfilled = {
  shopId: string
  shopNm: string | null
  team: string | null
  prdtCd: string
  styleNm: string | null
  colorCd: string
  sizeCd: string
  stock: number
  sales: number
  failCnt: number
  left: number
  reason: string
  reasonNm: string
}
export type ShopQty = { shopId: string; shopNm: string | null; qty: number }
export type RtResult = {
  brand: string
  brandNm: string
  from: string
  to: string
  asOf: string
  per: number
  limits: boolean
  order: string
  orderNm: string
  senderMax: number
  summary: {
    receivers: number
    needQty: number
    filledReceivers: number
    recQty: number
    recRows: number
    senders: number
    receivingShops: number
    failRequests: number
    failFilled: number
    unfilled: number
    unfilledBy: Record<string, number>
    skipped: { noGroup: number; recvCtl: number; team: number; incoming?: number }
    senderExcluded: Record<string, number>
    checked: number
    styles: number
  }
  reasonNames: Record<string, string>
  ruleNames: Record<string, string>
  rows: RtRow[]
  unfilled: RtUnfilled[]
  rowsTotal: number
  unfilledTotal: number
  topSenders: ShopQty[]
  topReceivers: ShopQty[]
  timing: Record<string, number>
}
export type RtStats = {
  brand: string
  brandNm: string
  from: string
  to: string
  total: number
  noShopCancel: number
  noShopRate: number | null
  results: { code: string; name: string; count: number }[]
  days: { day: string; total: number; done: number; fail: number }[]
  failShops: { shopId: string; shopNm: string | null; count: number }[]
  failProducts: { prdtCd: string; styleNm: string | null; count: number }[]
}

export type AllocCond = {
  brand: string
  wh: string
  dateFrom: string
  dateTo: string
  base: string
  grdGrp: string
  planYy: string[]
  seasons: string[]
  prdtGrps: string[]
  items: string[]
  prdt: string
  teams: string[]
  rate: number
}
export type AllocRow = {
  prdtCd: string
  styleNm: string | null
  colorCd: string
  sizeCd: string
  rank: number
  shopId: string
  shopNm: string | null
  team: string | null
  shopType: string | null
  grade: string | null
  gradeRank: number | null
  srate: number
  fq: number
  sq: number
  stock: number
  askFp: number
  askSale: number
  ask: number
  ctl: boolean
  need: number
  short: number
}
export type AllocSku = {
  prdtCd: string
  styleNm: string | null
  colorCd: string
  sizeCd: string
  whStock: number
  reserved: number
  minWh: number
  avail: number
  shops: number
  demand: number
  alloc: number
  short: number
  maxStock: number
  minRate: number
}
export type AllocResult = {
  brand: string
  brandNm: string
  wh: string
  from: string
  to: string
  base: string
  grdGrp: string
  rate: number
  asOf: string
  summary: {
    styleSkus: number
    soldSkus: number
    skus: number
    allocSkus: number
    allocQty: number
    allocFp: number
    shops: number
    demand: number
    short: number
    noStockSkus: number
    ctlRows: number
    candidates: number
    shortRows: number
    shortZero: number
    asked: number
  }
  rows: AllocRow[]
  shortRows: AllocRow[]
  shortRowsTotal: number
  ctlRows: AllocRow[]
  skus: AllocSku[]
  rowsTotal: number
  skusTotal: number
  topShops: ShopQty[]
  timing: Record<string, number>
}

export type Skipped = { key: string[]; reason: string }
export type WritePreview = { brand: string; brandNm: string; asOf: string; count: number; qty: number; skipped: Skipped[] } & Record<string, unknown>
export type RtRegResult = { ok: boolean; indcDt: string; count: number; qty: number; firstId: string; lastId: string; senders: number; receivers: number; skipped: Skipped[] }
export type AllocRegResult = { ok: boolean; askDt: string; askSeqn: number; count: number; qty: number; shops: number; skipped: Skipped[] }
export type DeleteResult = { ok: boolean; deleted: number; requested: number; notDeleted: number }
export type RtRegistered = {
  brand: string; brandNm: string; from: string; to: string; total: number; deletable: number
  byStatus: { code: string; name: string; qty: number }[]
  rows: { id: string; indcDt: string; prdtCd: string; colorCd: string; sizeCd: string; qty: number; fromShopId: string; fromShopNm: string | null
    toShopId: string; toShopNm: string | null; status: string; statusNm: string; insDay: string; insUser: string; deletable: boolean }[]
}
export type AllocRegistered = {
  brand: string; brandNm: string; from: string; to: string; total: number; deletable: number
  runs: { askDt: string; askSeqn: number; rows: number; qty: number; confirmed: number; deletable: number; insUser: string; insDay: string }[]
  rows: { askDt: string; askSeqn: number; seq: number; shopId: string; shopNm: string | null; prdtCd: string; colorCd: string; sizeCd: string; qty: number
    wh: string; delvPreDt: string | null; confirmed: boolean; statusNm: string; rmk: string | null; insDay: string; insUser: string; deletable: boolean }[]
}
export type AskSeqns = { brand: string; askDt: string; next: number; used: { seqn: number; brand: string; brandNm: string; clsby: string; rows: number; confirmed: boolean; web: boolean }[] }

const list = (v: string[]) => v.join(',')
export const rtQuery = (c: RtCond) =>
  qs({ brand: c.brand, dateFrom: c.dateFrom, dateTo: c.dateTo, planYy: list(c.planYy), seasons: list(c.seasons), prdt: c.prdt.trim(),
    teams: list(c.teams), per: c.per, order: c.order, senderMax: c.senderMax || undefined, limits: c.limits ? 'true' : undefined })
export const allocQuery = (c: AllocCond) =>
  qs({ brand: c.brand, wh: c.wh, dateFrom: c.dateFrom, dateTo: c.dateTo, base: c.base, grdGrp: c.grdGrp, planYy: list(c.planYy),
    seasons: list(c.seasons), prdtGrps: list(c.prdtGrps), items: list(c.items), prdt: c.prdt.trim(), teams: list(c.teams), rate: c.rate })

async function json<T>(url: string, signal?: AbortSignal): Promise<T> {
  return (await apiFetch(url, { signal })).json()
}
async function post<T>(url: string, body: unknown): Promise<T> {
  return (await apiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json()
}

export const stockApi = {
  options: (brand?: string) => json<StockOptions>(`/api/stock-rt/options?${qs({ brand })}`),
  rt: (c: RtCond, refresh = false, signal?: AbortSignal) =>
    json<RtResult>(`/api/stock-rt/rt?${rtQuery(c)}${refresh ? '&refresh=true' : ''}`, signal),
  rtStats: (brand: string, dateFrom: string, dateTo: string) => json<RtStats>(`/api/stock-rt/rt/stats?${qs({ brand, dateFrom, dateTo })}`),
  rtExport: (c: RtCond) => downloadFile(`/api/stock-rt/rt/export?${rtQuery(c)}`, undefined, '매장간RT추천.xlsx'),
  alloc: (c: AllocCond, refresh = false, signal?: AbortSignal) =>
    json<AllocResult>(`/api/stock-rt/alloc?${allocQuery(c)}${refresh ? '&refresh=true' : ''}`, signal),
  allocCandidates: (c: AllocCond, sku: Pick<AllocSku, 'prdtCd' | 'colorCd' | 'sizeCd'>) =>
    json<{ rows: AllocRow[]; sku: AllocSku | null }>(`/api/stock-rt/alloc/candidates?${allocQuery(c)}&${qs(sku)}`),
  allocExport: (c: AllocCond) => downloadFile(`/api/stock-rt/alloc/export?${allocQuery(c)}`, undefined, '창고배분추천.xlsx'),

  // ---- ERP 등록 · 삭제 (관리자)
  rtPreview: (c: RtCond, keys: string[][]) => post<WritePreview>(`/api/stock-rt/rt/preview?${rtQuery(c)}`, { keys }),
  rtRegister: (c: RtCond, keys: string[][], indcDt: string) => post<RtRegResult>(`/api/stock-rt/rt/register?${rtQuery(c)}`, { keys, indcDt }),
  rtRegistered: (brand: string, dateFrom: string, dateTo: string) => json<RtRegistered>(`/api/stock-rt/rt/registered?${qs({ brand, dateFrom, dateTo })}`),
  rtDelete: (brand: string, ids: string[]) => post<DeleteResult>('/api/stock-rt/rt/delete', { brand, ids }),
  askSeqns: (brand: string, askDt: string) => json<AskSeqns>(`/api/stock-rt/alloc/seqns?${qs({ brand, askDt })}`),
  allocPreview: (c: AllocCond, keys: string[][]) => post<WritePreview>(`/api/stock-rt/alloc/preview?${allocQuery(c)}`, { keys }),
  allocRegister: (c: AllocCond, keys: string[][], askDt: string, askSeqn: number, delvPreDt: string) =>
    post<AllocRegResult>(`/api/stock-rt/alloc/register?${allocQuery(c)}`, { keys, askDt, askSeqn, delvPreDt }),
  allocRegistered: (brand: string, dateFrom: string, dateTo: string) => json<AllocRegistered>(`/api/stock-rt/alloc/registered?${qs({ brand, dateFrom, dateTo })}`),
  allocDelete: (brand: string, keys: (string | number)[][]) => post<DeleteResult>('/api/stock-rt/alloc/delete', { brand, keys }),
}
