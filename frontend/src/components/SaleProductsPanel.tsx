import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Loader2 } from 'lucide-react'
import { apiFetch } from '../api'
import { fmtNum } from '../format'
import { fmtGrowth, growthClass } from './ShopTrendModal'

type Group = { name: string; amt: number; baseAmt: number; change: number | null; share: number | null; baseShare: number | null; shareDiff: number | null; dsctRate: number | null }
type Product = { prdtCd: string; itemNm: string | null; prdtGrpNm: string | null; amt: number; qty: number; dsctRate: number | null; share: number }
type Products = {
  period: string
  base: string
  baseKind: string
  unavailable?: string
  source?: string
  productCount?: number
  rankings?: { amt: Product[]; qty: Product[]; dsctRate: Product[] }
  items?: Group[]
  groups?: Group[]
  salesTypes?: Group[]
  salesTypeTrend?: Record<string, string | number>[]
  minAmtForDsctRank?: number
}
type RankKey = 'amt' | 'qty' | 'dsctRate'

const eok = (v: number) =>
  Math.abs(v) >= 100_000_000 ? `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억` : `${Math.round(v / 10_000).toLocaleString('ko-KR')}만`
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v.toFixed(1)}%`)
const pp = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`)
const TYPE_COLORS = ['#6366f1', '#f59e0b', '#ef4444', '#10b981', '#06b6d4', '#a855f7', '#94a3b8']

/** 판매 현황 아래: 판매형태 구성 · 상품 순위(기간 안) · 아이템/품군 전년 비교. query 는 판매 현황과 같은 조건. */
export default function SaleProductsPanel({ query, onProduct }: { query: string; onProduct: (prdtCd: string) => void }) {
  const [data, setData] = useState<Products | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rank, setRank] = useState<RankKey>('amt')
  const [dim, setDim] = useState<'items' | 'groups'>('items')

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    apiFetch(`/api/sale-dashboard/products${query}`)
      .then((r) => r.json())
      .then((d: Products) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [query])

  const types = data?.salesTypes ?? []
  const trend = useMemo(() => (data?.salesTypeTrend ?? []).map((t) => {
    const total = types.reduce((s, x) => s + Number(t[x.name] ?? 0), 0) || 1
    return { name: `${String(t.ym).slice(2, 4)}-${String(t.ym).slice(4)}`, ...Object.fromEntries(types.map((x) => [x.name, Math.round((Number(t[x.name] ?? 0) * 1000) / total) / 10])) }
  }), [data, types])
  const shareChart = types.map((t) => ({ name: t.name, 당기: t.share, 비교: t.baseShare }))
  const tick = { fill: '#8b93a7', fontSize: 12 }

  if (loading && !data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 상품·판매형태를 계산하는 중… (뷰가 없으면 원본에서 몇 초 걸립니다)</div></section>
  if (error) return <div className="alert error">상품·판매형태: {error}</div>
  if (!data) return null
  if (data.unavailable) return <section className="card panel"><div className="muted">상품·판매형태: {data.unavailable}</div></section>
  const rows = data.rankings?.[rank] ?? []
  const groups = (dim === 'items' ? data.items : data.groups) ?? []

  return (
    <>
      <section className="sd-grid">
        <div className="card panel">
          <div className="panel-head">
            <h3>판매형태 구성</h3>
            <span className="panel-hint">{data.period} · {data.baseKind} {data.base} 비교 · 실판금액 비중{loading ? ' · 갱신 중…' : ''}</span>
          </div>
          {trend.length > 1 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={trend}>
                <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
                <YAxis tick={tick} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}%`} domain={[0, 100]} />
                <Tooltip formatter={(v) => `${v}%`} />
                <Legend />
                {types.map((t, i) => <Bar key={t.name} dataKey={t.name} stackId="s" fill={TYPE_COLORS[i % TYPE_COLORS.length]} maxBarSize={34} />)}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={shareChart}>
                <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
                <YAxis tick={tick} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(v) => `${v}%`} />
                <Legend />
                <Bar dataKey="당기" fill="var(--primary-2)" radius={[4, 4, 0, 0]} maxBarSize={24} />
                <Bar dataKey="비교" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={24} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card panel">
          <div className="panel-head"><h3>판매형태별</h3><span className="panel-hint">{data.source}</span></div>
          <table className="table sd-table">
            <thead><tr><th>판매형태</th><th className="num">실판금액</th><th className="num">비중</th><th className="num">비중 변화</th><th className="num">증감</th><th className="num">할인율</th></tr></thead>
            <tbody>
              {types.map((t) => (
                <tr key={t.name}>
                  <td className="strong">{t.name}</td>
                  <td className="num">{eok(t.amt)}</td>
                  <td className="num">{pct(t.share)}</td>
                  <td className={`num ${growthClass(t.shareDiff)}`}>{pp(t.shareDiff)}</td>
                  <td className={`num ${growthClass(t.change)}`}>{fmtGrowth(t.change)}</td>
                  <td className="num">{pct(t.dsctRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sd-grid two">
        <div className="card panel">
          <div className="panel-head row">
            <h3>상품 순위</h3>
            <span className="panel-hint">{data.period} 안 순위 · 상품 {fmtNum(data.productCount ?? 0)}개 · 품번을 누르면 온라인 가격 비교</span>
            <div className="grow" />
            <div className="seg">
              {(['amt', 'qty', 'dsctRate'] as RankKey[]).map((k) => (
                <button key={k} className={rank === k ? 'on' : ''} onClick={() => setRank(k)}>{{ amt: '실판금액', qty: '수량', dsctRate: '할인율' }[k]}</button>
              ))}
            </div>
          </div>
          {rank === 'dsctRate' && <div className="muted small">기간 실판금액 {eok(data.minAmtForDsctRank ?? 0)} 이상 상품만</div>}
          <div className="table-wrap tall-ish">
            <table className="table sd-table">
              <thead><tr><th>#</th><th>품번</th><th>아이템 · 품군</th><th className="num">실판금액</th><th className="num">수량</th><th className="num">할인율</th></tr></thead>
              <tbody>
                {rows.map((p, i) => (
                  <tr key={p.prdtCd}>
                    <td className="muted">{i + 1}</td>
                    <td><button className="btn-link mono" title="온라인 가격 · 매장 판매 비교" onClick={() => onProduct(p.prdtCd)}>{p.prdtCd}</button></td>
                    <td className="small">{p.itemNm ?? '-'} <span className="muted">· {p.prdtGrpNm ?? '-'}</span></td>
                    <td className="num">{eok(p.amt)}</td>
                    <td className="num">{fmtNum(p.qty)}</td>
                    <td className="num">{pct(p.dsctRate)}</td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={6} className="empty">해당 상품이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card panel">
          <div className="panel-head row">
            <h3>{dim === 'items' ? '아이템별' : '품군별'}</h3>
            <span className="panel-hint">{data.baseKind} {data.base} 대비</span>
            <div className="grow" />
            <div className="seg">
              <button className={dim === 'items' ? 'on' : ''} onClick={() => setDim('items')}>아이템</button>
              <button className={dim === 'groups' ? 'on' : ''} onClick={() => setDim('groups')}>품군</button>
            </div>
          </div>
          <div className="table-wrap tall-ish">
            <table className="table sd-table">
              <thead><tr><th>{dim === 'items' ? '아이템' : '품군'}</th><th className="num">실판금액</th><th className="num">증감</th><th className="num">비중</th><th className="num">비중 변화</th><th className="num">할인율</th></tr></thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.name}>
                    <td className="strong">{g.name}</td>
                    <td className="num">{eok(g.amt)}</td>
                    <td className={`num ${growthClass(g.change)}`}>{fmtGrowth(g.change)}</td>
                    <td className="num">{pct(g.share)}</td>
                    <td className={`num ${growthClass(g.shareDiff)}`}>{pp(g.shareDiff)}</td>
                    <td className="num">{pct(g.dsctRate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </>
  )
}
