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
    skipped: { noGroup: number; recvCtl: number; team: number; incoming?: number; virtual?: number }
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
export type DeleteResult = { ok: boolean; deleted: number; requested: number; notDeleted: number; canceled?: number; removed?: number }
export type RtRegistered = {
  brand: string; brandNm: string; from: string; to: string; total: number; deletable: number
  byStatus: { code: string; name: string; qty: number }[]
  rows: { id: string; indcDt: string; prdtCd: string; colorCd: string; sizeCd: string; qty: number; fromShopId: string; fromShopNm: string | null
    toShopId: string; toShopNm: string | null; status: string; statusNm: string; insDay: string; insUser: string; cnfmUser?: string | null; resn?: string | null; deletable: boolean }[]
}
export type AllocRegistered = {
  brand: string; brandNm: string; from: string; to: string; total: number; deletable: number
  runs: { askDt: string; askSeqn: number; rows: number; qty: number; confirmed: number; deletable: number; insUser: string; insDay: string }[]
  rows: { askDt: string; askSeqn: number; seq: number; shopId: string; shopNm: string | null; prdtCd: string; colorCd: string; sizeCd: string; qty: number
    wh: string; delvPreDt: string | null; confirmed: boolean; statusNm: string; rmk: string | null; insDay: string; insUser: string; deletable: boolean }[]
}
export type SettingCheckRow = {
  shopId: string; shopNm: string | null; team: string | null; rtGrp: string | null; asign: number; reqAble: number | null; minRetain: number | null
  assigned: number; assignedPerDay: number; recRows: number; recQty: number; failQty: number; receivers: number; suggest: number; blocked: boolean; status: string
}
export type SettingCheck = {
  brand: string; brandNm: string; from: string; to: string; days: number; asOf: string
  summary: { senders: number; blockedShops: number; lowShops: number; recQty: number; blockedQty: number; failRequests: number; failFilled: number
    blockedFailQty: number; lowFailQty: number }
  rows: SettingCheckRow[]
}
export type ShortRt = {
  brand: string; brandNm: string; asOf: string; allocAsOf: string; wh: string; from: string; to: string; orderNm: string
  summary: { shortRows: number; shortQty: number; receivers: number; needQty: number; filledReceivers: number; recRows: number; recQty: number
    senders: number; receivingShops: number; unfilled: number; unfilledBy: Record<string, number>
    skipped: { noGroup: number; recvCtl: number; team: number; incoming: number; virtual?: number }; senderExcluded: Record<string, number> }
  reasonNames: Record<string, string>; ruleNames: Record<string, string>
  rows: RtRow[]; unfilled: RtUnfilled[]; timing: Record<string, number>
}
/** RT 지시 등록 대상: 매장 간 RT 추천 또는 창고 부족 채우기 */
export type RtWriteSource = {
  preview: (keys: string[][]) => Promise<WritePreview>
  register: (keys: string[][], indcDt: string) => Promise<RtRegResult>
}
export type PerfShop = { shopId: string; shopNm: string | null; team: string | null; total: number; accepted: number; denied: number; autoDenied: number
  pending: number; canceled: number; acceptRate: number | null; avgHours: number | null; sold: number; soldRate: number | null }
export type RtPerformance = {
  brand: string; brandNm: string; from: string; to: string; scope: 'web' | 'all'; asOf: string; soldDays: number; includeVirtual?: boolean; virtualQty?: number
  summary: { total: number; byStatus: { code: string; name: string; qty: number }[]; accepted: number; denied: number; autoDenied: number; pending: number
    canceled: number; acceptRate: number | null; avgHours: number | null; sold: number; soldRate: number | null; maturedAccepted: number; maturedSold: number }
  senders: PerfShop[]; receivers: PerfShop[]; reasons: { reason: string; qty: number }[]
  days: { day: string; total: number; accepted: number; denied: number; pending: number }[]
}
export type PendingGroup = { key: string; name: string | null; team?: string | null; rows: number; qty: number; urgent: number; oldestHours: number
  d0: number; d1: number; d2: number; d3: number; C6811: number; C6812: number; C6813: number }
export type PendingRow = { makeDt: string; seq: number; type: string; typeNm: string; fromShopId: string; fromShopNm: string | null; fromTeam: string | null
  toShopId: string; toShopNm: string | null; prdtCd: string; styleNm: string | null; colorCd: string; sizeCd: string; qty: number; requestedAt: string | null
  hours: number; age: 'd0' | 'd1' | 'd2' | 'd3'; urgent: boolean; requestedBy: string | null; ref: string | null }
export type PendingBoard = {
  brand: string; brandNm: string; from: string; to: string; days: number; types: string[]; typeNames: Record<string, string>
  ages: { key: string; name: string }[]; urgentHours: number; asOf: string; includeVirtual: boolean; virtualRows: number
  summary: { rows: number; qty: number; shops: number; urgent: number; byAge: Record<string, number>; byType: Record<string, number> }
  shops: PendingGroup[]; teams: PendingGroup[]; rows: PendingRow[]
}
export type ReturnRow = { prdtCd: string; styleNm: string | null; colorCd: string; sizeCd: string; shopId: string; shopNm: string | null; team: string | null
  closed: boolean; stock: number; avail: number; qty: number; lastSale: string | null; daysNoSale: number | null; lastDelv: string | null
  daysSinceDelv: number | null; skuShort: number }
export type ReturnSku = { prdtCd: string; styleNm: string | null; colorCd: string; sizeCd: string; whStock: number; avail: number; demand: number; short: number
  candidates: number; candQty: number; returnQty: number; left: number }
export type ReturnResult = {
  brand: string; brandNm: string; wh: string; from: string; to: string; allocAsOf: string; asOf: string; lookback: number; salesFrom: string
  mode: 'need' | 'all'; modeNm: string
  summary: { shortSkus: number; shortQty: number; returnQty: number; rows: number; shops: number; coveredSkus: number; partialSkus: number
    noSourceSkus: number; coveredQty: number; excluded: Record<string, number> }
  rows: ReturnRow[]; skus: ReturnSku[]; topShops: ShopQty[]; timing: Record<string, number>
}
export type AgingRow = { shopId: string; shopNm: string | null; team: string | null; prdtCd: string; styleNm: string | null; planYy: string | null
  sesn: string | null; sesnNm: string | null; qty: number; amt: number; skus: number; days: number | null; neverSold: boolean; lastSale: string | null
  lastDelv: string | null; firstDelv: string | null }
export type AgingShop = { shopId: string; shopNm: string | null; team: string | null; closed: boolean; qty: number; amt: number; agedQty: number
  agedAmt: number; agedStyles: number; agedRate: number | null }
export type AgingStyle = { prdtCd: string; styleNm: string | null; planYy: string | null; sesn: string | null; sesnNm: string | null; qty: number; amt: number
  agedQty: number; agedAmt: number; agedShops: number; maxDays: number | null }
export type AgingReport = {
  brand: string; brandNm: string; minDays: number; asOf: string; baseSec: number; baseSource?: 'table' | 'live'; ym: string; virtualQty: number
  cond: { planYy: string[]; seasons: string[]; teams: string[]; prdt: string | null; includeVirtual: boolean }
  summary: { qty: number; amt: number; rows: number; agedQty: number; agedAmt: number; agedRows: number; agedRate: number | null; shops: number
    agedShops: number; agedStyles: number }
  buckets: { key: string; name: string; qty: number; amt: number; rows: number }[]
  shops: AgingShop[]; styles: AgingStyle[]; stylesTotal: number; detail: AgingRow[]; detailTotal: number; timing: Record<string, number>
}
export type AgingCond = { brand: string; minDays: number; planYy: string[]; seasons: string[]; teams: string[]; prdt: string; includeVirtual: boolean }
export type AgingSku = { colorCd: string; sizeCd: string; qty: number; amt: number; lastSale: string | null; lastDelv: string | null; firstDelv: string | null; days: number | null }
export type TurnGroup = { stock: number; amt: number; sales: number; daily: number; cover: number | null; sellThru: number | null; short: number; over: number
  overStock: number }
export type TurnShop = TurnGroup & { shopId: string; shopNm: string | null; team: string | null; styles: number }
export type TurnStyle = TurnGroup & { prdtCd: string; styleNm: string | null; planYy: string | null; sesnNm: string | null; shops: number }
export type TurnTeam = TurnGroup & { team: string; shops: number }
export type TurnRow = { shopId: string; shopNm: string | null; team: string | null; prdtCd: string; styleNm: string | null; planYy: string | null
  sesnNm: string | null; stock: number; amt: number; sales: number; daily: number; cover: number | null; sellThru: number | null; cls: string }
export type TurnCond = { brand: string; days: number; planYy: string[]; seasons: string[]; teams: string[]; prdt: string; includeVirtual: boolean }
export type TurnReport = {
  brand: string; brandNm: string; days: number; stockAsOf: string; stockSource?: 'table' | 'live'; asOf: string; virtualRows: number
  summary: { stock: number; amt: number; sales: number; daily: number; cover: number | null; sellThru: number | null; shops: number; styles: number
    shortRows: number; overRows: number; overStock: number }
  classes: { key: string; name: string; rows: number; stock: number; sales: number }[]
  shops: TurnShop[]; teams: TurnTeam[]; styles: TurnStyle[]; stylesTotal: number; detail: TurnRow[]; detailTotal: number
}
export type InitAgg = { alloc: number; sold: number; sellThru: number | null; rows: number; zero: number; soldOut: number }
export type InitProduct = InitAgg & { prdtCd: string; colorCd: string; styleNm: string | null; planYy: string | null; sesnNm: string | null; start: string | null
  shops: number; overlap: number | null }
export type InitShop = InitAgg & { shopId: string; shopNm: string | null; team: string | null; shopType: string | null; products: number }
export type InitCond = { brand: string; dateFrom: string; dateTo: string; window: number; planYy: string[]; seasons: string[]; includeVirtual: boolean; maturedOnly: boolean }
export type InitReport = {
  brand: string; brandNm: string; from: string; to: string; window: number; asOf: string; maturedOnly: boolean; immature: number; virtualRows: number
  includeVirtual: boolean
  summary: InitAgg & { products: number; shops: number; overlap: number | null; lowOverlap: number; judged: number; minSold: number; zeroProducts: number }
  products: InitProduct[]; shops: InitShop[]; types: (InitAgg & { shopType: string })[]
}
export type InitProductShop = { shopId: string; shopNm: string | null; team: string | null; shopType: string | null; alloc: number; sold: number
  sellThru: number | null; allocShare: number; soldShare: number; start: string | null; matured: boolean }
export type AskSeqns = { brand: string; askDt: string; next: number; used: { seqn: number; brand: string; brandNm: string; clsby: string; rows: number; confirmed: boolean; web: boolean }[] }

const list = (v: string[]) => v.join(',')
export const rtQuery = (c: RtCond) =>
  qs({ brand: c.brand, dateFrom: c.dateFrom, dateTo: c.dateTo, planYy: list(c.planYy), seasons: list(c.seasons), prdt: c.prdt.trim(),
    teams: list(c.teams), per: c.per, order: c.order, senderMax: c.senderMax || undefined, limits: c.limits ? 'true' : undefined })
export const allocQuery = (c: AllocCond) =>
  qs({ brand: c.brand, wh: c.wh, dateFrom: c.dateFrom, dateTo: c.dateTo, base: c.base, grdGrp: c.grdGrp, planYy: list(c.planYy),
    seasons: list(c.seasons), prdtGrps: list(c.prdtGrps), items: list(c.items), prdt: c.prdt.trim(), teams: list(c.teams), rate: c.rate })

export const turnQuery = (c: TurnCond) =>
  qs({ brand: c.brand, days: c.days, planYy: list(c.planYy), seasons: list(c.seasons), teams: list(c.teams), prdt: c.prdt.trim() || undefined,
    includeVirtual: c.includeVirtual ? 'true' : undefined })
export const initQuery = (c: InitCond) =>
  qs({ brand: c.brand, dateFrom: c.dateFrom || undefined, dateTo: c.dateTo || undefined, window: c.window, planYy: list(c.planYy), seasons: list(c.seasons),
    includeVirtual: c.includeVirtual ? 'true' : undefined, maturedOnly: c.maturedOnly ? 'true' : 'false' })
export const agingQuery = (c: AgingCond) =>
  qs({ brand: c.brand, minDays: c.minDays, planYy: list(c.planYy), seasons: list(c.seasons), teams: list(c.teams), prdt: c.prdt.trim() || undefined,
    includeVirtual: c.includeVirtual ? 'true' : undefined })

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

  rtPerformance: (brand: string, dateFrom: string, dateTo: string, scope: string, refresh = false, includeVirtual = false) =>
    json<RtPerformance>(`/api/stock-rt/rt/performance?${qs({ brand, dateFrom, dateTo, scope, refresh: refresh ? 'true' : undefined, includeVirtual: includeVirtual ? 'true' : undefined })}`),
  rtPerformanceExport: (brand: string, dateFrom: string, dateTo: string, scope: string, includeVirtual = false) =>
    downloadFile(`/api/stock-rt/rt/performance/export?${qs({ brand, dateFrom, dateTo, scope, includeVirtual: includeVirtual ? 'true' : undefined })}`, undefined, 'RT성과.xlsx'),
  // ---- 미처리 RT 현황 · 창고 회수 · 장기 미판매 재고
  pending: (brand: string, days: number, types: string[], includeVirtual: boolean, refresh = false) =>
    json<PendingBoard>(`/api/stock-rt/pending?${qs({ brand, days, types: list(types), includeVirtual: includeVirtual ? 'true' : undefined, refresh: refresh ? 'true' : undefined })}`),
  pendingExport: (brand: string, days: number, types: string[], includeVirtual: boolean) =>
    downloadFile(`/api/stock-rt/pending/export?${qs({ brand, days, types: list(types), includeVirtual: includeVirtual ? 'true' : undefined })}`, undefined, '미처리RT현황.xlsx'),
  returnRec: (c: AllocCond, lookback: number, mode: string, refresh = false, signal?: AbortSignal) =>
    json<ReturnResult>(`/api/stock-rt/return?${allocQuery(c)}&${qs({ lookback, mode })}${refresh ? '&refresh=true' : ''}`, signal),
  returnExport: (c: AllocCond, lookback: number, mode: string) =>
    downloadFile(`/api/stock-rt/return/export?${allocQuery(c)}&${qs({ lookback, mode })}`, undefined, '창고회수추천.xlsx'),
  aging: (c: AgingCond, refresh = false, signal?: AbortSignal) => json<AgingReport>(`/api/stock-rt/aging?${agingQuery(c)}${refresh ? '&refresh=true' : ''}`, signal),
  agingExport: (c: AgingCond) => downloadFile(`/api/stock-rt/aging/export?${agingQuery(c)}`, undefined, '장기미판매재고.xlsx'),
  agingSkus: (brand: string, shopId: string, prdtCd: string) => json<{ rows: AgingSku[] }>(`/api/stock-rt/aging/skus?${qs({ brand, shopId, prdtCd })}`),

  // ---- 재고 회전 · 초도 배분 적중률
  turnover: (c: TurnCond, refresh = false, signal?: AbortSignal) => json<TurnReport>(`/api/stock-rt/turnover?${turnQuery(c)}${refresh ? '&refresh=true' : ''}`, signal),
  turnoverExport: (c: TurnCond) => downloadFile(`/api/stock-rt/turnover/export?${turnQuery(c)}`, undefined, '재고회전.xlsx'),
  initial: (c: InitCond, refresh = false, signal?: AbortSignal) => json<InitReport>(`/api/stock-rt/initial?${initQuery(c)}${refresh ? '&refresh=true' : ''}`, signal),
  initialShops: (c: InitCond, prdtCd: string, colorCd: string) =>
    json<{ rows: InitProductShop[] }>(`/api/stock-rt/initial/shops?${initQuery(c)}&${qs({ prdtCd, colorCd })}`),
  initialExport: (c: InitCond) => downloadFile(`/api/stock-rt/initial/export?${initQuery(c)}`, undefined, '초도배분적중률.xlsx'),

  // ---- 자동 RT 설정 점검 · 창고 부족 → 매장 간 RT
  settingCheck: (c: RtCond) => json<SettingCheck>(`/api/stock-rt/rt/setting-check?${rtQuery(c)}`),
  settingExport: (c: RtCond) => downloadFile(`/api/stock-rt/rt/setting-check/export?${rtQuery(c)}`, undefined, '자동RT설정점검.xlsx'),
  shortRt: (c: AllocCond, refresh = false) => json<ShortRt>(`/api/stock-rt/alloc/short-rt?${allocQuery(c)}${refresh ? '&refresh=true' : ''}`),
  shortRtSource: (c: AllocCond): RtWriteSource => ({
    preview: (keys) => post<WritePreview>(`/api/stock-rt/alloc/short-rt/preview?${allocQuery(c)}`, { keys }),
    register: (keys, indcDt) => post<RtRegResult>(`/api/stock-rt/alloc/short-rt/register?${allocQuery(c)}`, { keys, indcDt }),
  }),
  rtSource: (c: RtCond): RtWriteSource => ({
    preview: (keys) => post<WritePreview>(`/api/stock-rt/rt/preview?${rtQuery(c)}`, { keys }),
    register: (keys, indcDt) => post<RtRegResult>(`/api/stock-rt/rt/register?${rtQuery(c)}`, { keys, indcDt }),
  }),
}
