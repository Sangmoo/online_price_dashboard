import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowDownRight, ArrowUpRight, ChartLine, Loader2, RefreshCw } from 'lucide-react'
import { apiFetch } from '../api'
import { fmtNum } from '../format'
import ShopTrendModal, { fmtGrowth, growthClass } from './ShopTrendModal'

type Kpi = {
  amt: number
  prevYearAmt: number
  prevMonthAmt: number
  yoy: number | null
  mom: number | null
  qty: number
  prevYearQty: number
  qtyYoy: number | null
  dsct: number
  dsctYoy: number | null
  cost: number
  costRate: number | null
  prevYearCostRate: number | null
  costRateDiff?: number
  shops: number
  prevYearShops: number
  ytdAmt: number
  prevYtdAmt: number
  ytdYoy: number | null
  avgPerShop: number | null
}
type Trend = { ym: string; amt: number; prevAmt: number; yoy: number | null; costRate: number | null; shops: number }
type Group = { amt: number; prevAmt: number; yoy: number | null; costRate: number | null; shops: number }
type Brand = Group & { brand: string; share: number | null; teams: number }
type Shop = { shopId: string; shopNm: string | null; amt: number; prevYearAmt: number; prevMonthAmt: number; yoy: number | null; mom: number | null; costRate: number | null }
type Dash = {
  ym: string
  prevMonth: string
  prevYear: string
  months: string[]
  kpi: Kpi
  trend: Trend[]
  brands: Brand[]
  topShops: Shop[]
  risers: Shop[]
  fallers: Shop[]
  shopCounts: { selling: number; new: number; comparable: number; closedExcluded: number }
  minPrevForGrowth: number
}

const ymLabel = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
const eok = (v: number) => `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억`
const mil = (v: number) => Math.round(v / 1_000_000)
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v.toFixed(1)}%`)
const pp = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`)

export default function SaleDashboardView({ onContextChange }: { onContextChange?: (ctx: Record<string, string>) => void }) {
  const [ym, setYm] = useState<string | null>(null)
  const [data, setData] = useState<Dash | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [trendShop, setTrendShop] = useState<{ id: string; name: string } | null>(null)

  const load = (target: string | null) => {
    setLoading(true)
    setError(null)
    apiFetch(`/api/sale-dashboard${target ? `?ym=${target}` : ''}`)
      .then((r) => r.json())
      .then((d: Dash) => {
        setData(d)
        setYm(d.ym)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => load(null), [])
  useEffect(() => {
    if (data) onContextChange?.({ ym: data.ym })
  }, [data, onContextChange])

  const tick = { fill: '#8b93a7', fontSize: 12 }
  const trendChart = useMemo(
    () => (data?.trend ?? []).map((t) => ({ name: ymLabel(t.ym).slice(2), 당해: mil(t.amt), 전년: mil(t.prevAmt), 원가율: t.costRate })),
    [data],
  )
  const brandChart = useMemo(() => (data?.brands ?? []).map((b) => ({ name: b.brand, 당해: mil(b.amt), 전년: mil(b.prevAmt) })), [data])

  if (!data) {
    return (
      <div className="stack">
        {error ? <div className="alert error">{error}</div> : <div className="card panel"><div className="trend-loading"><Loader2 size={20} className="spin" /> 판매 현황을 불러오는 중…</div></div>}
      </div>
    )
  }
  const k = data.kpi
  const shopName = (s: Shop) => s.shopNm ?? s.shopId

  return (
    <div className="stack">
      <section className="card toolbar">
        <div className="toolbar-title"><ChartLine size={18} /> 판매 현황</div>
        <select className="input select" value={ym ?? ''} onChange={(e) => load(e.target.value)} disabled={loading} aria-label="기준 월">
          {data.months.map((m) => <option key={m} value={m}>{ymLabel(m)}</option>)}
        </select>
        <span className="muted small">전년 동월 {ymLabel(data.prevYear)} · 전월 {ymLabel(data.prevMonth)} 비교 · 마감 매출(실판금액) 기준</span>
        <div className="toolbar-actions">
          <button className="icon-btn bordered" title="새로고침" onClick={() => load(ym)}><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
      </section>
      {error && <div className="alert error">{error}</div>}

      <section className="kpi-grid sd-kpis">
        <SdKpi label={`${ymLabel(data.ym)} 실판금액`} value={eok(k.amt)} sub={`${fmtNum(k.amt)}원`} delta={k.yoy} deltaLabel="전년 동월" extra={{ label: '전월', v: k.mom }} />
        <SdKpi label={`${data.ym.slice(0, 4)}년 누계`} value={eok(k.ytdAmt)} sub={`전년 누계 ${eok(k.prevYtdAmt)}`} delta={k.ytdYoy} deltaLabel="전년 누계" />
        <SdKpi label="판매 수량" value={fmtNum(k.qty)} sub={`전년 동월 ${fmtNum(k.prevYearQty)}`} delta={k.qtyYoy} deltaLabel="전년 동월" />
        <SdKpi
          label="원가율"
          value={pct(k.costRate)}
          sub={`원가 ${eok(k.cost)} · 전년 ${pct(k.prevYearCostRate)}`}
          deltaText={pp(k.costRateDiff)}
          deltaClass={growthClass(k.costRateDiff ?? null)}
          deltaLabel="전년 동월"
          title="원가율 = 원가 금액(제조원가×수량) ÷ 실판금액"
        />
        <SdKpi label="할인금액" value={eok(k.dsct)} sub={`${fmtNum(k.dsct)}원`} delta={k.dsctYoy} deltaLabel="전년 동월" />
        <SdKpi
          label="판매 매장"
          value={`${fmtNum(k.shops)}개`}
          sub={`매출 발생 ${fmtNum(data.shopCounts.selling)}개 · 신규 ${fmtNum(data.shopCounts.new)}개 · 매장당 ${k.avgPerShop ? eok(k.avgPerShop) : '-'}`}
          title="판매 기록(반품 포함)이 있는 매장 수 · 전년 동월과 같은 기준으로 비교"
          deltaText={`${k.shops - k.prevYearShops >= 0 ? '+' : ''}${fmtNum(k.shops - k.prevYearShops)}개`}
          deltaClass={growthClass(k.shops - k.prevYearShops)}
          deltaLabel="전년 동월"
        />
      </section>

      <section className="sd-grid">
        <div className="card panel sd-wide">
          <div className="panel-head">
            <h3>최근 13개월 실판금액</h3>
            <span className="panel-hint">막대: 당해 · 선: 전년 같은 달 · 점선: 원가율(오른쪽) · 단위 백만원</span>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={trendChart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={60} tickFormatter={(v) => fmtNum(v)} />
              <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}%`} domain={['auto', 'auto']} />
              <Tooltip formatter={(v, n) => (n === '원가율' ? `${v}%` : `${fmtNum(Number(v))}백만원`)} />
              <Legend />
              <Bar yAxisId="l" dataKey="당해" fill="#6366f1" radius={[5, 5, 0, 0]} maxBarSize={30} />
              <Line yAxisId="l" dataKey="전년" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3 }} />
              <Line yAxisId="r" dataKey="원가율" stroke="#10b981" strokeWidth={2} strokeDasharray="4 3" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="card panel">
          <div className="panel-head"><h3>브랜드별</h3><span className="panel-hint">{ymLabel(data.ym)} · 단위 백만원</span></div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={brandChart} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis tick={tick} tickLine={false} axisLine={false} width={56} tickFormatter={(v) => fmtNum(v)} />
              <Tooltip formatter={(v) => `${fmtNum(Number(v))}백만원`} />
              <Legend />
              <Bar dataKey="당해" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={26} />
              <Bar dataKey="전년" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={26} />
            </BarChart>
          </ResponsiveContainer>
          <table className="table sd-table">
            <thead><tr><th>브랜드</th><th className="num">실판금액</th><th className="num">비중</th><th className="num">전년 대비</th><th className="num">원가율</th></tr></thead>
            <tbody>
              {data.brands.map((b) => (
                <tr key={b.brand}>
                  <td className="strong">{b.brand} <span className="muted small">{b.teams}개 팀</span></td>
                  <td className="num">{eok(b.amt)}</td>
                  <td className="num muted">{pct(b.share)}</td>
                  <td className={`num ${growthClass(b.yoy)}`}>{fmtGrowth(b.yoy)}</td>
                  <td className="num">{pct(b.costRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sd-grid three">
        <ShopList title="실판금액 상위 10" hint={ymLabel(data.ym)} rows={data.topShops} mode="top" onShop={(s) => setTrendShop({ id: s.shopId, name: shopName(s) })} />
        <ShopList title="전년 대비 성장 상위 10" hint={`전년 동월 ${eok(data.minPrevForGrowth)} 이상 매장 · 폐점 제외`} rows={data.risers} mode="growth"
          onShop={(s) => setTrendShop({ id: s.shopId, name: shopName(s) })} />
        <ShopList title="전년 대비 하락 상위 10" hint={`폐점·종료 표시 매장 ${fmtNum(data.shopCounts.closedExcluded)}개 제외`} rows={data.fallers} mode="growth"
          onShop={(s) => setTrendShop({ id: s.shopId, name: shopName(s) })} />
      </section>


      {trendShop && (
        <ShopTrendModal url={`/api/sale-dashboard/shops/${encodeURIComponent(trendShop.id)}/trend`} title={trendShop.name} onClose={() => setTrendShop(null)} />
      )}
    </div>
  )
}

function SdKpi({ label, value, sub, delta, deltaText, deltaClass, deltaLabel, extra, title }: {
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
        <div className="kpi-label">{label}</div>
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

function ShopList({ title, hint, rows, mode, onShop }: { title: string; hint: string; rows: Shop[]; mode: 'top' | 'growth'; onShop: (s: Shop) => void }) {
  return (
    <div className="card panel">
      <div className="panel-head"><h3>{title}</h3><span className="panel-hint">{hint}</span></div>
      <table className="table sd-table">
        <thead>
          <tr><th>#</th><th>매장</th><th className="num">실판금액</th><th className="num">{mode === 'top' ? '전년 대비' : '전년 동월'}</th>{mode === 'growth' && <th className="num">증감</th>}</tr>
        </thead>
        <tbody>
          {rows.map((s, i) => (
            <tr key={s.shopId}>
              <td className="muted">{i + 1}</td>
              <td>
                <button className="btn-link" title="최근 12개월 판매 추이" onClick={() => onShop(s)}>{s.shopNm ?? s.shopId}</button>
                <span className="muted mono small"> {s.shopId}</span>
              </td>
              <td className="num">{eok(s.amt)}</td>
              {mode === 'top' ? (
                <td className={`num ${growthClass(s.yoy)}`}>{fmtGrowth(s.yoy)}</td>
              ) : (
                <>
                  <td className="num muted">{eok(s.prevYearAmt)}</td>
                  <td className={`num ${growthClass(s.yoy)}`}>{fmtGrowth(s.yoy)}</td>
                </>
              )}
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="empty">해당 매장이 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
