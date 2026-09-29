import { useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Loader2 } from 'lucide-react'
import { apiFetch, exportTable } from '../api'
import { fmtNum } from '../format'
import ShopTrendModal, { fmtGrowth, growthClass } from './ShopTrendModal'

export type SummaryCond = { ymFrom: string; ymTo: string; shops: string; planYys: string; seasons: string }
type Dim = { key: string; label: string }
type SRow = {
  key: string | null
  label: string
  shopNm: string | null
  shops: number
  qty: number
  amt: number
  dsct: number
  share: number
  prevKey: string | null
  prevQty: number
  prevAmt: number
  growth: number | null
  cost: number
  costRate: number | null
  prevCostRate: number | null
  costRateDiff: number | null
}
type SData = {
  dim: string
  dimLabel: string
  rows: SRow[]
  period: { from: string; to: string; prevFrom: string; prevTo: string; planYys: string[]; prevPlanYys: string[] }
  total: {
    qty: number
    amt: number
    dsct: number
    prevQty: number
    prevAmt: number
    growth: number | null
    cost: number
    costRate: number | null
    prevCostRate: number | null
    costRateDiff: number | null
  }
}
type SortKey = 'label' | 'shops' | 'qty' | 'amt' | 'dsct' | 'share' | 'prevAmt' | 'growth' | 'cost' | 'costRate' | 'costRateDiff'

const ym = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
const mil = (v: number) => Math.round(v / 1_000_000)
const TOP_N = 15
const pct = (v: number | null) => (v === null ? '-' : `${v.toFixed(1)}%`)
// 원가율 증감: 오르면(원가 부담 증가) 빨강, 내리면 파랑 — 앱의 상승/하락 색과 같은 규칙
const pp = (v: number | null) => (v === null ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`)

export default function SaleSummary({ cond, dims }: { cond: SummaryCond; dims: Dim[] }) {
  const [dim, setDim] = useState('month')
  const [data, setData] = useState<SData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean } | null>(null)
  const [trendShop, setTrendShop] = useState<{ id: string; name: string } | null>(null)
  const [started, setStarted] = useState(0)
  const [, setTick] = useState(0)
  const req = useRef(0)

  useEffect(() => {
    const id = ++req.current
    setLoading(true)
    setError(null)
    setSort(null)
    setStarted(Date.now())
    const p = new URLSearchParams({ ...cond, dim })
    apiFetch(`/api/sale-monthly/summary?${p}`)
      .then((r) => r.json())
      .then((d: SData) => id === req.current && setData(d))
      .catch((e) => id === req.current && setError(e.message))
      .finally(() => id === req.current && setLoading(false))
  }, [cond, dim])

  useEffect(() => {
    if (!loading) return
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [loading])

  const rows = useMemo(() => {
    if (!data) return []
    if (!sort) return data.rows
    const v = (r: SRow) => (sort.key === 'label' ? r.label : (r[sort.key] ?? -Infinity))
    return [...data.rows].sort((a, b) => {
      const x = v(a)
      const y = v(b)
      const c = typeof x === 'string' ? x.localeCompare(String(y)) : (x as number) - (y as number)
      return sort.desc ? -c : c
    })
  }, [data, sort])

  const isMonth = data?.dim === 'month'
  const isShop = data?.dim === 'shop'
  const chart = useMemo(() => {
    if (!data) return []
    const src = isMonth ? data.rows : [...data.rows].sort((a, b) => b.amt - a.amt).slice(0, TOP_N)
    return src.map((r) => ({ name: isMonth ? r.label.slice(2) : r.label, 당해: mil(r.amt), 전년: mil(r.prevAmt) }))
  }, [data, isMonth])

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s?.key === key ? (s.desc ? { key, desc: false } : null) : { key, desc: key !== 'label' }))
  const sortIcon = (key: SortKey) =>
    sort?.key === key ? sort.desc ? <ArrowDown size={12} /> : <ArrowUp size={12} /> : <ArrowUpDown size={12} className="sort-idle" />

  const download = () => {
    if (!data) return
    const cols = [
      { key: 'label', label: data.dimLabel },
      ...(isShop ? [{ key: 'key', label: '매장코드' }] : []),
      { key: 'shops', label: '매장 수' },
      { key: 'qty', label: '수량' },
      { key: 'amt', label: '실판금액' },
      { key: 'dsct', label: '할인금액' },
      { key: 'share', label: '비중(%)' },
      { key: 'prevAmt', label: '전년 동기 실판금액' },
      { key: 'growth', label: '증감(%)' },
      { key: 'cost', label: '원가 금액(제조원가×수량)' },
      { key: 'costRate', label: '원가율(%)' },
      { key: 'prevCostRate', label: '전년 동기 원가율(%)' },
      { key: 'costRateDiff', label: '원가율 증감(%p)' },
    ]
    exportTable(`판매요약_${data.dimLabel}_${data.period.from}-${data.period.to}`, cols, rows as unknown as Record<string, string | number | null>[])
  }

  const p = data?.period
  const tick = { fill: '#8b93a7', fontSize: 12 }
  const th = (key: SortKey, label: string, num = true) => (
    <th className={`sortable ${num ? 'num' : ''} ${sort?.key === key ? 'active' : ''}`} onClick={() => toggleSort(key)}>
      <span className="th-inner">{label}{sortIcon(key)}</span>
    </th>
  )

  return (
    <div className="stack">
      <section className="card sale-summary-head">
        <div className="chips wrap">
          {dims.map((d) => (
            <button key={d.key} className={`chip ${dim === d.key ? 'active' : ''}`} onClick={() => setDim(d.key)}>{d.label}별</button>
          ))}
        </div>
        {p && (
          <span className="muted small">
            전년 동기: {ym(p.prevFrom)} ~ {ym(p.prevTo)}
            {p.prevPlanYys.length ? ` · 기획년도 ${p.prevPlanYys.join(', ')}` : ''} (같은 매장·시즌 조건)
          </span>
        )}
        <div className="grow" />
        <button className="btn success sm" onClick={download} disabled={!data || loading}><Download size={13} /> 엑셀</button>
      </section>

      {error && <div className="alert error">{error}</div>}
      {loading && (
        <div className="trend-loading">
          <Loader2 size={20} className="spin" /> 요약 계산 중… {Math.floor((Date.now() - started) / 1000)}초
          <span className="muted small"> (긴 기간·처음 조회는 수십 초 걸릴 수 있습니다. 같은 조건은 10분간 바로 나옵니다)</span>
        </div>
      )}

      {data && !loading && (
        <>
          <section className="summary-pills">
            <div className="pill strong"><span>실판금액</span><b>{fmtNum(data.total.amt)}원</b></div>
            <div className="pill"><span>전년 동기</span><b>{fmtNum(data.total.prevAmt)}원</b></div>
            <div className="pill"><span>증감</span><b className={growthClass(data.total.growth)}>{fmtGrowth(data.total.growth)}</b></div>
            <div className="pill"><span>수량</span><b>{fmtNum(data.total.qty)}</b><span className="muted">(전년 {fmtNum(data.total.prevQty)})</span></div>
            <div className="pill"><span>할인금액</span><b>{fmtNum(data.total.dsct)}원</b></div>
            <div className="pill" title="원가율 = 원가 금액(제조원가×수량) ÷ 실판금액">
              <span>원가율</span><b>{pct(data.total.costRate)}</b>
              <span className="muted">(전년 {pct(data.total.prevCostRate)}, </span>
              <b className={growthClass(data.total.costRateDiff)}>{pp(data.total.costRateDiff)}</b><span className="muted">)</span>
            </div>
          </section>

          <section className="card panel">
            <div className="panel-head">
              <h3>{isMonth ? '월별 실판금액 추이' : `${data.dimLabel}별 실판금액 상위 ${Math.min(TOP_N, data.rows.length)}`}</h3>
              <span className="panel-hint">단위 백만원 · {isMonth ? '막대: 당해, 선: 전년 같은 달' : '당해 / 전년 동기'}</span>
            </div>
            <ResponsiveContainer width="100%" height={isMonth ? 280 : Math.max(220, chart.length * 30 + 40)}>
              {isMonth ? (
                <ComposedChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                  <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
                  <YAxis tick={tick} tickLine={false} axisLine={false} width={60} tickFormatter={(v) => fmtNum(v)} />
                  <Tooltip formatter={(v) => `${fmtNum(Number(v))}백만원`} />
                  <Legend />
                  <Bar dataKey="당해" fill="#6366f1" radius={[5, 5, 0, 0]} maxBarSize={28} />
                  <Line dataKey="전년" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3 }} />
                </ComposedChart>
              ) : (
                <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(148,163,184,.18)" horizontal={false} />
                  <XAxis type="number" tick={tick} tickLine={false} axisLine={false} tickFormatter={(v) => fmtNum(v)} />
                  <YAxis type="category" dataKey="name" tick={tick} tickLine={false} axisLine={false} width={120} />
                  <Tooltip formatter={(v) => `${fmtNum(Number(v))}백만원`} />
                  <Legend />
                  <Bar dataKey="당해" fill="#6366f1" radius={[0, 4, 4, 0]} maxBarSize={12} />
                  <Bar dataKey="전년" fill="#f59e0b" radius={[0, 4, 4, 0]} maxBarSize={12} />
                </BarChart>
              )}
            </ResponsiveContainer>
          </section>

          <section className="card grid-card">
            <div className="table-wrap tall">
              <table className="table">
                <thead>
                  <tr>
                    {th('label', data.dimLabel, false)}
                    {th('shops', '매장 수')}
                    {th('qty', '수량')}
                    {th('amt', '실판금액(원)')}
                    {th('dsct', '할인금액(원)')}
                    {th('share', '비중')}
                    {th('prevAmt', '전년 동기(원)')}
                    {th('growth', '증감')}
                    {th('cost', '원가(원)')}
                    {th('costRate', '원가율')}
                    {th('costRateDiff', '원가율 증감')}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key ?? '(없음)'}>
                      <td>
                        {isShop && r.key ? (
                          <button className="btn-link" title="최근 12개월 판매 추이" onClick={() => setTrendShop({ id: r.key!, name: r.label })}>
                            {r.label} <span className="muted mono">{r.key}</span>
                          </button>
                        ) : (
                          r.label
                        )}
                      </td>
                      <td className="num">{fmtNum(r.shops)}</td>
                      <td className="num">{fmtNum(r.qty)}</td>
                      <td className="num strong">{fmtNum(r.amt)}</td>
                      <td className="num">{fmtNum(r.dsct)}</td>
                      <td className="num muted">{r.share.toFixed(1)}%</td>
                      <td className="num muted">{fmtNum(r.prevAmt)}</td>
                      <td className={`num ${growthClass(r.growth)}`}>{fmtGrowth(r.growth)}</td>
                      <td className="num">{fmtNum(r.cost)}</td>
                      <td className="num" title={r.prevCostRate !== null ? `전년 동기 ${pct(r.prevCostRate)}` : undefined}>{pct(r.costRate)}</td>
                      <td className={`num ${growthClass(r.costRateDiff)}`}>{pp(r.costRateDiff)}</td>
                    </tr>
                  ))}
                  {rows.length === 0 && <tr><td colSpan={11} className="empty">조회된 데이터가 없습니다.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {trendShop && (
        <ShopTrendModal
          url={`/api/sale-monthly/shops/${encodeURIComponent(trendShop.id)}/trend`}
          title={trendShop.name}
          onClose={() => setTrendShop(null)}
        />
      )}
    </div>
  )
}
