import { useEffect, useState } from 'react'
import { CartesianGrid, ComposedChart, Bar, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Loader2 } from 'lucide-react'
import { apiFetch } from '../api'
import { fmtNum } from '../format'
import { fmtGrowth, growthClass } from './ShopTrendModal'
import { HelpTip } from '../help/HelpTip'

type Month = { ym: string; label: string; step: number; prevYm: string; amt: number | null; qty: number | null; cum: number | null; prevAmt: number; prevCum: number }
type Season = {
  to: string
  toLabel: string
  brand: string | null
  source: string
  options: { planYy: string; season: string; amt: number }[]
  planYy: string | null
  season: string | null
  prevPlanYy?: string | null
  startLabel?: string
  step?: number
  months: Month[]
  kpi?: {
    amt: number; qty: number; prevSameAmt: number; prevSameQty: number; change: number | null; qtyChange: number | null
    prevFinalAmt: number; progress: number | null; prevProgressSame: number | null; dsctRate: number | null; prevDsctRate: number | null
    lastAmt: number; prevLastAmt: number
  }
}

type SeasonItem = {
  name: string; amt: number; qty: number; prevSameAmt: number; prevFinalAmt: number; change: number | null
  progress: number | null; prevProgressSame: number | null; share: number | null
}

const eok = (v: number) =>
  Math.abs(v) >= 100_000_000 ? `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억` : `${Math.round(v / 10_000).toLocaleString('ko-KR')}만`
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v.toFixed(1)}%`)
const mil = (v: number | null) => (v === null ? null : Math.round(v / 1_000_000))

/** 판매 현황 아래: 시즌 월 누적 판매 vs 전년 같은 시즌의 같은 시점. 기준 월·브랜드는 판매 현황 조건을 따른다.
 *  기준 월·브랜드가 바뀌면 부모가 key 를 바꿔 시즌 선택을 처음(기본 시즌)으로 되돌린다. */
export default function SeasonProgressPanel({ ym, brand }: { ym: string; brand: string }) {
  const [sel, setSel] = useState('')
  const [data, setData] = useState<Season | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showItems, setShowItems] = useState(false)
  const [items, setItems] = useState<{ key: string; rows: SeasonItem[] } | null>(null)
  const [itemsError, setItemsError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const p = new URLSearchParams({ ym })
    if (brand) p.set('brand', brand)
    if (sel) {
      const [yy, ...ss] = sel.split(' ')
      p.set('planYy', yy)
      p.set('season', ss.join(' '))
    }
    setLoading(true)
    setError(null)
    apiFetch(`/api/sale-dashboard/season?${p}`)
      .then((r) => r.json())
      .then((d: Season) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [ym, brand, sel])

  // 아이템별: 펼칠 때 한 번 불러온다 (시즌·기준 월·브랜드가 같으면 다시 부르지 않음)
  const itemsKey = data?.planYy ? `${data.to}|${data.brand ?? ''}|${data.planYy}|${data.season}` : ''
  useEffect(() => {
    if (!showItems || !itemsKey || items?.key === itemsKey || !data) return
    const p = new URLSearchParams({ ym, planYy: data.planYy!, season: data.season! })
    if (brand) p.set('brand', brand)
    setItemsError(null)
    apiFetch(`/api/sale-dashboard/season/items?${p}`)
      .then((r) => r.json())
      .then((d: { items: SeasonItem[] }) => setItems({ key: itemsKey, rows: d.items }))
      .catch((e) => setItemsError(e.message))
  }, [showItems, itemsKey, items, data, ym, brand])

  if (loading && !data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 시즌 판매 진척을 계산하는 중… (상품 뷰가 없으면 원본에서 10초 안팎)</div></section>
  if (error) return <div className="alert error">시즌 판매 진척: {error}</div>
  if (!data || !data.kpi || !data.planYy) return null
  const k = data.kpi
  const cur = `${data.planYy} ${data.season}`
  const prev = `${data.prevPlanYy} ${data.season}`
  const chart = data.months.map((m) => ({
    name: m.label.slice(2), [`${cur} 누적`]: mil(m.cum), [`${prev} 누적`]: mil(m.prevCum), [`${cur} 월`]: mil(m.amt), [`${prev} 월`]: mil(m.prevAmt),
    prevYm: m.prevYm,
  }))
  const tick = { fill: '#8b93a7', fontSize: 12 }

  return (
    <section className="card panel season-panel">
      <div className="panel-head row">
        <h3>시즌 판매 진척<HelpTip id="sales.seasonProgress" label="시즌 판매 진척" /></h3>
        <span className="panel-hint">
          {data.toLabel}까지 · {data.startLabel} 시작 {data.step}개월째 · 같은 시점 = 전년 같은 달 · {data.brand ?? '브랜드 전체'} · {data.source}{loading ? ' · 갱신 중…' : ''}
        </span>
        <div className="grow" />
        <select className="input select small" value={sel || cur} onChange={(e) => setSel(e.target.value)} aria-label="시즌">
          {data.options.map((o) => <option key={`${o.planYy} ${o.season}`} value={`${o.planYy} ${o.season}`}>{o.planYy} {o.season}</option>)}
        </select>
      </div>
      <div className="season-kpis">
        <div className="season-kpi">
          <span>누적 실판금액</span><b>{eok(k.amt)}</b>
          <small>{prev} 같은 시점 {eok(k.prevSameAmt)} <em className={growthClass(k.change)}>{fmtGrowth(k.change)}</em></small>
        </div>
        <div className="season-kpi">
          <span>누적 수량</span><b>{fmtNum(k.qty)}</b>
          <small>같은 시점 {fmtNum(k.prevSameQty)} <em className={growthClass(k.qtyChange)}>{fmtGrowth(k.qtyChange)}</em></small>
        </div>
        <div className="season-kpi" title={`올해 누적 ÷ ${prev} 시즌 최종 누적(${eok(k.prevFinalAmt)})`}>
          <span>전년 시즌 최종 대비 진척</span><b>{pct(k.progress)}</b>
          <small>전년 같은 시점 {pct(k.prevProgressSame)}</small>
        </div>
        <div className="season-kpi">
          <span>할인율</span><b>{pct(k.dsctRate)}</b>
          <small>전년 같은 시점 {pct(k.prevDsctRate)}</small>
        </div>
        <div className="season-kpi">
          <span>{data.toLabel} 한 달</span><b>{eok(k.lastAmt)}</b>
          <small>전년 같은 달 {eok(k.prevLastAmt)}</small>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chart}>
          <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
          <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
          <YAxis yAxisId="c" tick={tick} tickLine={false} axisLine={false} width={56} tickFormatter={(v) => fmtNum(v)} />
          <YAxis yAxisId="m" orientation="right" tick={tick} tickLine={false} axisLine={false} width={50} tickFormatter={(v) => fmtNum(v)} />
          <Tooltip
            formatter={(v, n) => [v === null || v === undefined ? '-' : `${fmtNum(Number(v))}백만`, n]}
            labelFormatter={(l, p) => (p?.[0]?.payload?.prevYm ? `${l} (전년 ${String(p[0].payload.prevYm).slice(2, 4)}-${String(p[0].payload.prevYm).slice(4)})` : l)}
          />
          <Legend />
          <Bar yAxisId="m" dataKey={`${cur} 월`} fill="rgba(99,102,241,.35)" maxBarSize={18} />
          <Bar yAxisId="m" dataKey={`${prev} 월`} fill="rgba(245,158,11,.3)" maxBarSize={18} />
          <Line yAxisId="c" type="monotone" dataKey={`${cur} 누적`} stroke="#6366f1" strokeWidth={2.6} dot={{ r: 3 }} connectNulls={false} />
          <Line yAxisId="c" type="monotone" dataKey={`${prev} 누적`} stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 4" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="row season-items-head">
        <button className="btn ghost small" onClick={() => setShowItems((v) => !v)} aria-expanded={showItems}>
          {showItems ? '아이템별 닫기' : '아이템별 보기'}
        </button>
        {showItems && <span className="muted small">아이템마다 같은 기준(전년 같은 시점 · 전년 시즌 최종 대비 진척)</span>}
      </div>
      {showItems && itemsError && <div className="alert error">아이템별: {itemsError}</div>}
      {showItems && !itemsError && (!items || items.key !== itemsKey) && (
        <div className="trend-loading"><Loader2 size={16} className="spin" /> 아이템별로 계산하는 중…</div>
      )}
      {showItems && items && items.key === itemsKey && (
        <div className="table-wrap tall-ish">
          <table className="table sd-table season-items">
            <thead>
              <tr>
                <th>아이템</th><th className="num">누적 실판금액</th><th className="num">비중</th><th className="num">전년 같은 시점</th>
                <th className="num">증감</th><th className="num">진척률</th><th className="num">전년 같은 시점 진척</th><th className="num">수량</th>
              </tr>
            </thead>
            <tbody>
              {items.rows.map((i) => (
                <tr key={i.name}>
                  <td className="strong">{i.name}</td>
                  <td className="num">{eok(i.amt)}</td>
                  <td className="num">{pct(i.share)}</td>
                  <td className="num muted">{eok(i.prevSameAmt)}</td>
                  <td className={`num ${growthClass(i.change)}`}>{fmtGrowth(i.change)}</td>
                  <td className={`num strong ${i.progress !== null && i.prevProgressSame !== null ? growthClass(i.progress - i.prevProgressSame) : ''}`}>{pct(i.progress)}</td>
                  <td className="num muted">{pct(i.prevProgressSame)}</td>
                  <td className="num">{fmtNum(i.qty)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="muted small">선: 누적(왼쪽) · 막대: 월 판매(오른쪽) · 단위 백만원 · 전년 선은 시즌이 끝날 때까지 이어져 남은 기간 흐름을 보여줍니다.</div>
    </section>
  )
}
