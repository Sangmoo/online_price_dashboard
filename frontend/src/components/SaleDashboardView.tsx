import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowDownRight, ArrowUpRight, ChartLine, Download, FileText, Loader2, RefreshCw, Search } from 'lucide-react'
import { apiFetch, downloadFile } from '../api'
import { fmtNum } from '../format'
import ShopTrendModal, { fmtGrowth, growthClass } from './ShopTrendModal'
import SaleProductsPanel from './SaleProductsPanel'
import SeasonProgressPanel from './SeasonProgressPanel'
import OnlineAlertPanel from './OnlineAlertPanel'
import SaleHeavyShopsPanel from './SaleHeavyShopsPanel'
import ProductInsightModal from './ProductInsightModal'
import { HelpTip } from '../help/HelpTip'
import SaleReportModal from './SaleReportModal'
import { BriefingButton } from './WeeklyBriefing'

export type Kpi = {
  amt: number
  baseAmt: number
  change: number | null
  extraAmt: number
  extraChange: number | null
  qty: number
  baseQty: number
  qtyChange: number | null
  dsct: number
  baseDsct: number
  dsctChange: number | null
  cost: number
  costRate: number | null
  baseCostRate: number | null
  costRateDiff: number | null
  dsctRate: number | null
  baseDsctRate: number | null
  dsctRateDiff: number | null
  shops: number
  baseShops: number
  avgPerShop: number | null
  ytdAmt: number
  prevYtdAmt: number
  ytdYoy: number | null
  goalAmt: number
  goalSalesAmt: number
  achieve: number | null
  goalGap: number | null
  goalShops: number
  noGoalShops: number
  noGoalAmt: number
}
export type Trend = { ym: string; amt: number; prevAmt: number; yoy: number | null; costRate: number | null; dsctRate: number | null; shops: number }
export type Brand = { brand: string; amt: number; baseAmt: number; change: number | null; costRate: number | null; dsctRate: number | null; shops: number; share: number | null; teams: number; goalAmt: number; achieve: number | null }
export type Shop = { shopId: string; shopNm: string | null; brand: string; amt: number; baseAmt: number; change: number | null; costRate: number | null; goalAmt: number; achieve: number | null }
export type Period = { from: string; to: string; months: string[]; label: string }
export type CmpKind = 'yoy' | 'prev' | 'custom'
export type Dash = {
  ym: string
  from: string
  months: string[]
  period: Period
  base: Period & { kind: CmpKind; kindLabel: string }
  extra: { label: string; period: string }
  brand: string | null
  brandOptions: string[]
  brandLimited?: boolean // 브랜드 권한이 제한된 사용자 (선택지 = 허용 브랜드)
  kpi: Kpi
  trend: Trend[]
  brands: Brand[]
  topShops: Shop[]
  risers: Shop[]
  fallers: Shop[]
  laggards: Shop[]
  shopCounts: { selling: number; new: number; comparable: number; closedExcluded: number }
  minBaseForGrowth: number
  hasGoals: boolean
}
type Cond = { from: string; to: string; cmp: CmpKind; cmpFrom: string; cmpTo: string; brand: string }

const MAX_PERIOD = 12
const ymLabel = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
// 1억 이상은 억(소수 1자리), 미만은 만원 단위
const eok = (v: number) =>
  Math.abs(v) >= 100_000_000
    ? `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억`
    : `${Math.round(v / 10_000).toLocaleString('ko-KR')}만`
const mil = (v: number) => Math.round(v / 1_000_000)
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v.toFixed(1)}%`)
const pp = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`)
const signedEok = (v: number) => `${v >= 0 ? '+' : '-'}${eok(Math.abs(v))}`
const monthsBetween = (f: string, t: string) => (Number(t.slice(0, 4)) - Number(f.slice(0, 4))) * 12 + Number(t.slice(4)) - Number(f.slice(4)) + 1
const achieveClass = (v: number | null) => (v === null ? 'muted' : v >= 100 ? 'up' : 'down')

function condQuery(c: Cond | null) {
  if (!c) return ''
  const p = new URLSearchParams({ ym: c.to, from: c.from, cmp: c.cmp })
  if (c.cmp === 'custom') {
    p.set('cmpFrom', c.cmpFrom)
    p.set('cmpTo', c.cmpTo)
  }
  if (c.brand) p.set('brand', c.brand)
  return `?${p}`
}

function condOf(d: Dash): Cond {
  return { from: d.period.from, to: d.period.to, cmp: d.base.kind, cmpFrom: d.base.from, cmpTo: d.base.to, brand: d.brand ?? '' }
}

export default function SaleDashboardView({ onContextChange, canOnline = false }: { onContextChange?: (ctx: Record<string, string>) => void; canOnline?: boolean }) {
  const [draft, setDraft] = useState<Cond | null>(null)
  const [applied, setApplied] = useState<Cond | null>(null)
  const [data, setData] = useState<Dash | null>(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [trendShop, setTrendShop] = useState<{ id: string; name: string } | null>(null)
  const [productCd, setProductCd] = useState<string | null>(null)
  const [reportOpen, setReportOpen] = useState(false)

  const load = (c: Cond | null) => {
    setLoading(true)
    setError(null)
    apiFetch(`/api/sale-dashboard${condQuery(c)}`)
      .then((r) => r.json())
      .then((d: Dash) => {
        setData(d)
        const next = condOf(d)
        setApplied(next)
        setDraft(next)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => load(null), [])
  useEffect(() => {
    if (data)
      onContextChange?.({
        ym: data.ym,
        period: data.period.label,
        compare: `${data.base.kindLabel} ${data.base.label}`,
        brand: data.brand ?? '',
      })
  }, [data, onContextChange])

  const draftError = useMemo(() => {
    if (!draft) return null
    if (draft.from > draft.to) return '시작 월이 끝 월보다 늦습니다.'
    if (monthsBetween(draft.from, draft.to) > MAX_PERIOD) return `기간은 최대 ${MAX_PERIOD}개월입니다.`
    if (draft.cmp === 'custom') {
      if (draft.cmpFrom > draft.cmpTo) return '비교 시작 월이 비교 끝 월보다 늦습니다.'
      if (monthsBetween(draft.cmpFrom, draft.cmpTo) > MAX_PERIOD) return `비교 기간은 최대 ${MAX_PERIOD}개월입니다.`
    }
    return null
  }, [draft])
  const dirty = !!draft && !!applied && JSON.stringify(draft) !== JSON.stringify(applied)

  const exportXlsx = async () => {
    setExporting(true)
    try {
      await downloadFile(`/api/sale-dashboard/export${condQuery(applied)}`, undefined, '판매현황.xlsx')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setExporting(false)
    }
  }

  const tick = { fill: '#8b93a7', fontSize: 12 }
  const trendChart = useMemo(
    () => (data?.trend ?? []).map((t) => ({ name: ymLabel(t.ym).slice(2), 당해: mil(t.amt), 전년: mil(t.prevAmt), 원가율: t.costRate, 할인율: t.dsctRate })),
    [data],
  )
  const baseName = data ? `비교(${data.base.label})` : '비교'
  const brandChart = useMemo(
    () => (data?.brands ?? []).map((b) => ({ name: b.brand, 당기: mil(b.amt), [baseName]: mil(b.baseAmt), 목표: b.goalAmt ? mil(b.goalAmt) : null })),
    [data, baseName],
  )

  if (!data || !draft) {
    return (
      <div className="stack">
        {error ? <div className="alert error">{error}</div> : <div className="card panel"><div className="trend-loading"><Loader2 size={20} className="spin" /> 판매 현황을 불러오는 중…</div></div>}
      </div>
    )
  }
  const k = data.kpi
  const shopName = (s: Shop) => s.shopNm ?? s.shopId
  const set = (patch: Partial<Cond>) => setDraft((d) => (d ? { ...d, ...patch } : d))
  const months = data.months
  const openTrend = (s: Shop) => setTrendShop({ id: s.shopId, name: shopName(s) })
  const baseLbl = data.base.kindLabel

  return (
    <div className="stack">
      <section className="card sale-filter sd-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><ChartLine size={18} /> 판매 현황</div>
          <span className="filter-label">기간</span>
          <select className="input select small" value={draft.from} onChange={(e) => set({ from: e.target.value })} aria-label="시작 월">
            {months.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
          </select>
          <span className="muted">~</span>
          <select
            className="input select small"
            value={draft.to}
            onChange={(e) => set({ to: e.target.value, from: draft.from === draft.to ? e.target.value : draft.from })}
            aria-label="끝 월"
          >
            {months.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
          </select>
          <span className="filter-label">비교</span>
          <select
            className="input select small"
            value={draft.cmp}
            onChange={(e) => set({ cmp: e.target.value as CmpKind })}
            aria-label="비교 기준"
          >
            <option value="yoy">전년 동기</option>
            <option value="prev">직전 기간{draft.from === draft.to ? ' (전월)' : ''}</option>
            <option value="custom">직접 선택</option>
          </select>
          {draft.cmp === 'custom' && (
            <>
              <select className="input select small" value={draft.cmpFrom} onChange={(e) => set({ cmpFrom: e.target.value })} aria-label="비교 시작 월">
                {months.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
              </select>
              <span className="muted">~</span>
              <select className="input select small" value={draft.cmpTo} onChange={(e) => set({ cmpTo: e.target.value })} aria-label="비교 끝 월">
                {months.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
              </select>
            </>
          )}
          <span className="filter-label">브랜드</span>
          <select className="input select small" value={draft.brand} onChange={(e) => set({ brand: e.target.value })} aria-label="브랜드">
            <option value="">{data.brandLimited ? `내 브랜드 전체 (${data.brandOptions.join(', ')})` : '전체'}</option>
            {data.brandOptions.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => load(draft)} disabled={loading || !!draftError}>
              {loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 조회
            </button>
            <button className="btn success" onClick={exportXlsx} disabled={exporting || loading} title="지금 조회한 조건으로 보고용 엑셀(요약·추이·브랜드·팀·매장 순위·전체 매장)을 내려받습니다.">
              {exporting ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 보고용 엑셀
            </button>
            <button className="btn ghost" onClick={() => setReportOpen(true)} disabled={loading || dirty}
              title={dirty ? '바꾼 조건을 먼저 [조회]하세요' : '지금 조회한 조건으로 핵심 카드 · 추이 · 브랜드 · 매장 순위를 A4 한 장(PDF · 이미지)으로'}>
              <FileText size={15} /> 한 장 보고서
            </button>
            <BriefingButton />
            <button className="icon-btn bordered" title="새로고침" onClick={() => load(applied)} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
          </div>
        </div>
        <div className="muted small">
          {draftError ? <span className="down">{draftError}</span> : dirty ? '조건을 바꿨습니다. [조회]를 누르면 반영됩니다. · ' : ''}
          조회: {data.period.label} · 비교 {baseLbl} {data.base.label} · 브랜드 {data.brand ?? '전체'} · 마감 매출(실판금액) 기준
        </div>
      </section>
      {error && <div className="alert error">{error}</div>}

      <section className="kpi-grid sd-kpis">
        <SdKpi help="sales.amt" label={`${data.period.label} 실판금액`} value={eok(k.amt)} sub={`${fmtNum(k.amt)}원 · ${baseLbl} ${eok(k.baseAmt)}`} delta={k.change} deltaLabel={baseLbl}
          extra={{ label: data.extra.label, v: k.extraChange }} />
        {data.hasGoals && (
          <SdKpi
            label="목표 달성률"
            help="sales.achieve"
            value={pct(k.achieve)}
            sub={`목표 ${eok(k.goalAmt)} · 목표 매장 ${fmtNum(k.goalShops)}개${k.noGoalShops ? ` · 목표 없는 매장 ${fmtNum(k.noGoalShops)}개(${eok(k.noGoalAmt)}) 제외` : ''}`}
            deltaText={k.goalGap === null ? '-' : signedEok(k.goalGap)}
            deltaClass={achieveClass(k.achieve)}
            deltaLabel="목표 대비"
            title="달성률 = 목표가 있는 매장의 실판금액 ÷ 목표금액 (T_SHOP_SELL_MGOAL, 매장별 목표를 매장의 판매 브랜드로 모음)"
          />
        )}
        <SdKpi help="sales.ytd" label={`${data.ym.slice(0, 4)}년 누계`} value={eok(k.ytdAmt)} sub={`전년 누계 ${eok(k.prevYtdAmt)} · ${ymLabel(data.ym)}까지`} delta={k.ytdYoy} deltaLabel="전년 누계" />
        <SdKpi help="sales.amt" label="판매 수량" value={fmtNum(k.qty)} sub={`${baseLbl} ${fmtNum(k.baseQty)}`} delta={k.qtyChange} deltaLabel={baseLbl} />
        <SdKpi
          label="원가율"
          help="sales.costRate"
          value={pct(k.costRate)}
          sub={`원가 ${eok(k.cost)} · ${baseLbl} ${pct(k.baseCostRate)}`}
          deltaText={pp(k.costRateDiff)}
          deltaClass={growthClass(k.costRateDiff)}
          deltaLabel={baseLbl}
          title="원가율 = 원가 금액(제조원가×수량) ÷ 실판금액"
        />
        <SdKpi
          label="할인율"
          help="sales.dsctRate"
          value={pct(k.dsctRate)}
          sub={`할인금액 ${eok(k.dsct)} (${fmtGrowth(k.dsctChange)}) · ${baseLbl} ${pct(k.baseDsctRate)}`}
          deltaText={pp(k.dsctRateDiff)}
          deltaClass={growthClass(k.dsctRateDiff)}
          deltaLabel={baseLbl}
          title="할인율 = 할인금액 ÷ (실판금액 + 할인금액) · 할인 전 금액 대비 깎아 준 비율"
        />
        <SdKpi
          label="판매 매장"
          help="sales.shops"
          value={`${fmtNum(k.shops)}개`}
          sub={`매출 발생 ${fmtNum(data.shopCounts.selling)}개 · 신규 ${fmtNum(data.shopCounts.new)}개 · 매장당 ${k.avgPerShop ? eok(k.avgPerShop) : '-'}`}
          title={`판매 기록(반품 포함)이 있는 매장 수 · ${baseLbl}(${data.base.label})와 같은 기준으로 비교`}
          deltaText={`${k.shops - k.baseShops >= 0 ? '+' : ''}${fmtNum(k.shops - k.baseShops)}개`}
          deltaClass={growthClass(k.shops - k.baseShops)}
          deltaLabel={baseLbl}
        />
      </section>

      <section className="sd-grid">
        <div className="card panel sd-wide">
          <div className="panel-head">
            <h3>최근 13개월 실판금액{data.brand ? ` · ${data.brand}` : ''}</h3>
            <span className="panel-hint">{ymLabel(data.ym)}까지 · 막대: 당해 · 선: 전년 같은 달 · 점선: 원가율·할인율(오른쪽) · 단위 백만원</span>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={trendChart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={60} tickFormatter={(v) => fmtNum(v)} />
              <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}%`} domain={['auto', 'auto']} />
              <Tooltip formatter={(v, n) => (n === '원가율' ? `${v}%` : `${fmtNum(Number(v))}백만원`)} />
              <Legend />
              <Bar yAxisId="l" dataKey="당해" fill="var(--primary-2)" radius={[5, 5, 0, 0]} maxBarSize={30} />
              <Line yAxisId="l" dataKey="전년" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3 }} />
              <Line yAxisId="r" dataKey="원가율" stroke="#10b981" strokeWidth={2} strokeDasharray="4 3" dot={false} />
              <Line yAxisId="r" dataKey="할인율" stroke="#ef4444" strokeWidth={2} strokeDasharray="2 3" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="card panel">
          <div className="panel-head"><h3>브랜드별</h3><span className="panel-hint">{data.period.label} · 단위 백만원</span></div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={brandChart} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis tick={tick} tickLine={false} axisLine={false} width={56} tickFormatter={(v) => fmtNum(v)} />
              <Tooltip formatter={(v) => `${fmtNum(Number(v))}백만원`} />
              <Legend />
              <Bar dataKey="당기" fill="var(--primary-2)" radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar dataKey={baseName} fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={22} />
              {data.hasGoals && <Bar dataKey="목표" fill="#94a3b8" radius={[4, 4, 0, 0]} maxBarSize={22} />}
            </BarChart>
          </ResponsiveContainer>
          <table className="table sd-table">
            <thead>
              <tr>
                <th>브랜드</th><th className="num">실판금액</th><th className="num">비중</th><th className="num" title={`${baseLbl} 대비`}>증감</th><th className="num">원가율</th><th className="num" title="할인금액 ÷ (실판금액 + 할인금액)">할인율</th>
                {data.hasGoals && <th className="num">달성률</th>}
              </tr>
            </thead>
            <tbody>
              {data.brands.map((b) => (
                <tr key={b.brand}>
                  <td className="strong" title={`${b.teams}개 팀 · 판매 매장 ${fmtNum(b.shops)}개`}>{b.brand}</td>
                  <td className="num">{eok(b.amt)}</td>
                  <td className="num muted">{pct(b.share)}</td>
                  <td className={`num ${growthClass(b.change)}`}>{fmtGrowth(b.change)}</td>
                  <td className="num">{pct(b.costRate)}</td>
                  <td className="num">{pct(b.dsctRate)}</td>
                  {data.hasGoals && <td className={`num ${achieveClass(b.achieve)}`} title={b.goalAmt ? `목표 ${eok(b.goalAmt)}` : '목표 없음'}>{pct(b.achieve)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sd-grid two">
        <ShopList title="실판금액 상위 10" hint={data.period.label} rows={data.topShops} mode="top" baseLbl={baseLbl} showGoal={data.hasGoals} onShop={openTrend} />
        {data.hasGoals && (
          <ShopList title="목표 달성률 하위 10" hint="목표·매출이 있는 영업 매장" rows={data.laggards} mode="goal" baseLbl={baseLbl} showGoal onShop={openTrend} />
        )}
        <ShopList title={`${baseLbl} 대비 성장 상위 10`} hint={`비교 기간 ${eok(data.minBaseForGrowth)} 이상 매장 · 폐점 제외`} rows={data.risers} mode="growth"
          baseLbl={baseLbl} showGoal={false} onShop={openTrend} />
        <ShopList title={`${baseLbl} 대비 하락 상위 10`} hint={`폐점·종료 표시 매장 ${fmtNum(data.shopCounts.closedExcluded)}개 제외`} rows={data.fallers} mode="growth"
          baseLbl={baseLbl} showGoal={false} onShop={openTrend} />
      </section>

      {applied && <SeasonProgressPanel key={`${applied.to}|${applied.brand}`} ym={applied.to} brand={applied.brand} />}
      {applied && <SaleProductsPanel query={condQuery(applied)} onProduct={setProductCd} />}
      {applied && canOnline && <OnlineAlertPanel query={condQuery(applied)} onProduct={setProductCd} />}
      {applied && <SaleHeavyShopsPanel query={condQuery(applied)} onShop={(id, name) => setTrendShop({ id, name })} />}

      {reportOpen && <SaleReportModal data={data} onClose={() => setReportOpen(false)} />}
      {productCd && <ProductInsightModal prdtCd={productCd} onClose={() => setProductCd(null)} />}
      {trendShop && (
        <ShopTrendModal url={`/api/sale-dashboard/shops/${encodeURIComponent(trendShop.id)}/trend`} shopId={trendShop.id} title={trendShop.name} onClose={() => setTrendShop(null)} />
      )}
    </div>
  )
}

function SdKpi({ label, value, sub, delta, deltaText, deltaClass, deltaLabel, extra, title, help }: {
  help?: string
  label: string
  value: string
  sub?: string
  delta?: number | null
  deltaText?: string
  deltaClass?: string
  deltaLabel?: string
  extra?: { label: string; v: number | null }
  title?: string
}) {
  const text = deltaText ?? fmtGrowth(delta ?? null)
  const cls = deltaClass ?? growthClass(delta ?? null)
  const up = cls === 'up'
  return (
    <div className="card kpi sd-kpi" title={title}>
      <div className="kpi-body">
        <div className="kpi-label">{label}{help && <HelpTip id={help} label={label} />}</div>
        <div className="kpi-value">{value}</div>
        <div className="sd-delta">
          <span className={cls}>{cls !== 'muted' && (up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />)}{text}</span>
          {deltaLabel && <span className="muted"> {deltaLabel}</span>}
          {extra && <span className="muted"> · {extra.label} <b className={growthClass(extra.v)}>{fmtGrowth(extra.v)}</b></span>}
        </div>
        {sub && <div className="muted small">{sub}</div>}
      </div>
    </div>
  )
}

function ShopList({ title, hint, rows, mode, baseLbl, showGoal, onShop }: {
  title: string
  hint: string
  rows: Shop[]
  mode: 'top' | 'growth' | 'goal'
  baseLbl: string
  showGoal: boolean
  onShop: (s: Shop) => void
}) {
  return (
    <div className="card panel">
      <div className="panel-head"><h3>{title}</h3><span className="panel-hint">{hint}</span></div>
      <table className="table sd-table">
        <thead>
          <tr>
            <th>#</th><th>매장</th><th className="num">실판금액</th>
            {mode === 'top' && <th className="num">{baseLbl} 대비</th>}
            {mode === 'growth' && <><th className="num">{baseLbl}</th><th className="num">증감</th></>}
            {mode === 'goal' && <th className="num">목표</th>}
            {showGoal && <th className="num">달성률</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => (
            <tr key={s.shopId}>
              <td className="muted">{i + 1}</td>
              <td>
                <button className="btn-link" title="매장 정보 · 최근 12개월 판매 추이" onClick={() => onShop(s)}>{s.shopNm ?? s.shopId}</button>
                <span className="muted mono small"> {s.shopId}</span>
              </td>
              <td className="num">{eok(s.amt)}</td>
              {mode === 'top' && <td className={`num ${growthClass(s.change)}`}>{fmtGrowth(s.change)}</td>}
              {mode === 'growth' && (
                <>
                  <td className="num muted">{eok(s.baseAmt)}</td>
                  <td className={`num ${growthClass(s.change)}`}>{fmtGrowth(s.change)}</td>
                </>
              )}
              {mode === 'goal' && <td className="num muted">{eok(s.goalAmt)}</td>}
              {showGoal && <td className={`num ${achieveClass(s.achieve)}`}>{s.goalAmt ? pct(s.achieve) : '-'}</td>}
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="empty">해당 매장이 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
