import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, CalendarRange, Layers, Percent, RefreshCw, ShoppingBag, Store, Tag } from 'lucide-react'
import { api, type Dashboard, type DateInfo } from '../api'
import ProductInsightModal from './ProductInsightModal'
import { addDays, compact, daysBetween, dtLabel, dtShort, dtToIso, fmtNum, fmtPct, fmtWon, isoToDt } from '../format'

const MAX_DAYS = 31
const C = { primary: '#6366f1', teal: '#14b8a6', amber: '#f59e0b', rose: '#f43f5e', grid: 'rgba(148,163,184,.18)', tick: '#8b93a7' }

type Props = {
  dates: DateInfo[]
  range: { start: string; end: string }
  onRangeChange: (r: { start: string; end: string }) => void
  onOpenDetail: (dt: string, q?: string, shops?: string) => void
  canOpenDetail?: boolean
}

export default function DashboardView({ dates, range, onRangeChange, onOpenDetail, canOpenDetail = true }: Props) {
  const [productCd, setProductCd] = useState<string | null>(null)
  const [start, setStart] = useState(range.start)
  const [end, setEnd] = useState(range.end)
  const [data, setData] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  const latest = dates[0]?.dt ?? range.end
  const earliest = dates[dates.length - 1]?.dt
  const span = daysBetween(start, end) + 1
  const invalid = span < 1 ? '시작일이 종료일보다 늦습니다.' : span > MAX_DAYS ? `최대 ${MAX_DAYS}일까지 조회할 수 있습니다.` : null

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    setError(null)
    api
      .dashboard(range.start, range.end, ctl.signal)
      .then(setData)
      .catch((e) => e.name !== 'AbortError' && setError(e.message))
      .finally(() => !ctl.signal.aborted && setLoading(false))
    return () => ctl.abort()
  }, [range.start, range.end, reload])

  const apply = (s = start, e = end) => {
    setStart(s)
    setEnd(e)
    if (s === range.start && e === range.end) setReload((n) => n + 1)
    else onRangeChange({ start: s, end: e })
  }

  const presets = [
    { label: '최근 7일', days: 7 },
    { label: '최근 14일', days: 14 },
    { label: '최근 31일', days: 31 },
  ]

  const daily = useMemo(() => (data?.daily ?? []).map((d) => ({ ...d, label: dtShort(d.DT) })), [data])
  const hist = useMemo(
    () => (data?.histogram ?? []).map((h) => ({ ...h, label: h.BUCKET >= 70 ? '70%+' : `${h.BUCKET}~${h.BUCKET + 5}%` })),
    [data],
  )
  const k = data?.kpi

  return (
    <div className="stack">
      <section className="card toolbar">
        <div className="toolbar-title">
          <CalendarRange size={18} />
          <span>조회 기간</span>
        </div>
        <div className="range-inputs">
          <input
            type="date"
            className="input"
            value={dtToIso(start)}
            min={earliest ? dtToIso(earliest) : undefined}
            max={dtToIso(latest)}
            onChange={(e) => e.target.value && setStart(isoToDt(e.target.value))}
          />
          <span className="muted">~</span>
          <input
            type="date"
            className="input"
            value={dtToIso(end)}
            min={earliest ? dtToIso(earliest) : undefined}
            max={dtToIso(latest)}
            onChange={(e) => e.target.value && setEnd(isoToDt(e.target.value))}
          />
          <span className={`span-badge ${invalid ? 'bad' : ''}`}>{span > 0 ? `${span}일` : '-'}</span>
        </div>
        <div className="chips">
          {presets.map((p) => {
            const s = addDays(latest, -(p.days - 1))
            const active = start === s && end === latest
            return (
              <button key={p.days} className={`chip ${active ? 'active' : ''}`} onClick={() => apply(s, latest)}>
                {p.label}
              </button>
            )
          })}
        </div>
        <button className="btn primary" disabled={!!invalid || loading} onClick={() => apply()}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} /> 조회
        </button>
        {invalid && <div className="field-error">{invalid}</div>}
      </section>

      {error && <div className="alert error">{error}</div>}

      <section className="kpi-grid">
        <Kpi icon={<Layers size={18} />} tone="indigo" label="총 수집 건수" value={k ? fmtNum(k.ROW_CNT) : null} sub={k ? `${k.DAY_CNT}일 · 일평균 ${fmtNum(Math.round(k.ROW_CNT / Math.max(k.DAY_CNT, 1)))}건` : ''} />
        <Kpi icon={<ShoppingBag size={18} />} tone="teal" label="수집 상품 수" value={k ? fmtNum(k.PRDT_CNT) : null} sub="고유 상품코드" />
        <Kpi icon={<Store size={18} />} tone="sky" label="사이트 수" value={k ? fmtNum(k.MALL_CNT) : null} sub={k ? `판매자 ${fmtNum(k.SELLER_CNT)} · 매장 ${fmtNum(k.SHOP_CNT ?? 0)}` : ''} />
        <Kpi icon={<Percent size={18} />} tone="amber" label="평균 할인율" value={k ? fmtPct(k.AVG_DC_RATE, 2) : null} sub="기준가 대비 사이트 할인가" />
        <Kpi icon={<Tag size={18} />} tone="rose" label="최대 할인율" value={k ? fmtPct(k.MAX_DC_RATE, 2) : null} sub="기간 내 최저가 기준" />
        <Kpi icon={<AlertTriangle size={18} />} tone="violet" label="30% 이상 고할인" value={k ? fmtNum(k.DEEP_DC_CNT) : null} sub={k && k.ROW_CNT ? `전체의 ${fmtPct((k.DEEP_DC_CNT / k.ROW_CNT) * 100, 2)}` : ''} />
      </section>

      <section className="grid-2-1">
        <Panel title="일자별 수집 추이" hint={`막대: 수집 건수 · 선: 평균 할인율${canOpenDetail ? ' — 막대를 누르면 해당 일자 상세로 이동' : ''}`} loading={loading && !data}>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} />
              <YAxis yAxisId="l" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={compact} width={48} />
              <YAxis yAxisId="r" orientation="right" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} width={44} domain={['auto', 'auto']} />
              <Tooltip content={<ChartTip />} cursor={{ fill: 'rgba(99,102,241,.08)' }} />
              <Bar yAxisId="l" dataKey="ROW_CNT" name="수집 건수" fill={C.primary} radius={[6, 6, 0, 0]} maxBarSize={34} cursor={canOpenDetail ? 'pointer' : undefined} onClick={(d) => onOpenDetail((d as unknown as { DT: string }).DT)} />
              <Line yAxisId="r" dataKey="AVG_DC_RATE" name="평균 할인율(%)" stroke={C.amber} strokeWidth={2.5} dot={{ r: 3 }} type="monotone" />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>
        <Panel title="할인율 분포" hint="기준가 대비 할인율 구간별 건수" loading={loading && !data}>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={hist} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: C.tick, fontSize: 11 }} tickLine={false} axisLine={false} interval={1} />
              <YAxis tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={compact} width={44} />
              <Tooltip content={<ChartTip />} cursor={{ fill: 'rgba(20,184,166,.08)' }} />
              <Bar dataKey="ROW_CNT" name="건수" radius={[6, 6, 0, 0]}>
                {hist.map((h) => (
                  <Cell key={h.BUCKET} fill={h.BUCKET >= 30 ? C.rose : h.BUCKET >= 15 ? C.amber : C.teal} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </section>

      <section className="grid-2">
        <Panel title="사이트별 수집 건수 Top 15" loading={loading && !data}>
          <ResponsiveContainer width="100%" height={420}>
            <BarChart data={data?.malls ?? []} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} horizontal={false} />
              <XAxis type="number" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={compact} />
              <YAxis type="category" dataKey="MALL_NM" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} width={120} />
              <Tooltip content={<ChartTip />} cursor={{ fill: 'rgba(99,102,241,.08)' }} />
              <Bar dataKey="ROW_CNT" name="수집 건수" fill={C.primary} radius={[0, 6, 6, 0]} barSize={16} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
        <Panel title="평균 할인율 높은 사이트 Top 10" hint="수집 50건 이상 사이트 기준" loading={loading && !data}>
          <ResponsiveContainer width="100%" height={420}>
            <BarChart data={data?.mallDiscount ?? []} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} horizontal={false} />
              <XAxis type="number" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="MALL_NM" tick={{ fill: C.tick, fontSize: 12 }} tickLine={false} axisLine={false} width={120} />
              <Tooltip content={<ChartTip />} cursor={{ fill: 'rgba(244,63,94,.08)' }} />
              <Bar dataKey="AVG_DC_RATE" name="평균 할인율(%)" fill={C.rose} radius={[0, 6, 6, 0]} barSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </section>

      <Panel
        title="매장별 수집 Top 15"
        hint={`매장코드(SHOP_ID)가 있는 수집 ${k ? `${fmtNum(k.SHOP_ROW_CNT ?? 0)}건 · 전체의 ${fmtPct(k.ROW_CNT ? ((k.SHOP_ROW_CNT ?? 0) / k.ROW_CNT) * 100 : 0, 1)}` : ''}${canOpenDetail ? ' — 행을 누르면 그 매장의 마지막 수집일 상세로 이동' : ''}`}
        loading={loading && !data}
      >
        {data && !data.shops?.length ? (
          <div className="empty">이 기간 수집에 매장코드가 들어간 행이 없습니다. 판매처 매장 연결에 등록한 매장코드는 다음 수집부터 들어갑니다.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>매장코드</th>
                  <th>매장명</th>
                  <th className="num">수집 건수</th>
                  <th className="num">상품 수</th>
                  <th className="num">사이트 수</th>
                  <th className="num">평균 할인율</th>
                  <th className="num">최대 할인율</th>
                  <th>마지막 수집일</th>
                </tr>
              </thead>
              <tbody>
                {(data?.shops ?? []).map((s, i) => (
                  <tr key={s.SHOP_ID} className={canOpenDetail ? 'clickable' : ''} onClick={() => onOpenDetail(s.LAST_DT, undefined, s.SHOP_ID)}>
                    <td className="muted">{i + 1}</td>
                    <td className="mono">{s.SHOP_ID}</td>
                    <td>{s.SHOP_NM ?? <span className="muted">-</span>}</td>
                    <td className="num strong">{fmtNum(s.ROW_CNT)}</td>
                    <td className="num">{fmtNum(s.PRDT_CNT)}</td>
                    <td className="num">{s.MALL_CNT}</td>
                    <td className="num"><RateBadge v={s.AVG_DC_RATE} /></td>
                    <td className="num"><RateBadge v={s.MAX_DC_RATE} /></td>
                    <td className="muted">{dtToIso(s.LAST_DT)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="할인율 상위 상품 Top 20" hint={canOpenDetail ? '행을 누르면 최저가 수집일의 상세 내역으로 이동' : undefined} loading={loading && !data}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>상품코드</th>
                <th>상품명 (최저가 기준)</th>
                <th className="num">기준가</th>
                <th className="num">최저 할인가</th>
                <th className="num">최대 할인율</th>
                <th>최저가 사이트</th>
                <th>최저가 일자</th>
                <th className="num">사이트 수</th>
              </tr>
            </thead>
            <tbody>
              {(data?.topProducts ?? []).map((p, i) => (
                <tr key={p.PRDT_CD} className={canOpenDetail ? 'clickable' : ''} onClick={() => onOpenDetail(p.MIN_DT, p.PRDT_CD)}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    <button
                      className="btn-link mono"
                      title="온라인 가격 · 매장 판매 비교"
                      onClick={(e) => {
                        e.stopPropagation()
                        setProductCd(p.PRDT_CD)
                      }}
                    >
                      {p.PRDT_CD}
                    </button>
                  </td>
                  <td className="ellipsis" title={p.TITLE}>{p.TITLE}</td>
                  <td className="num">{fmtWon(p.PRICE)}</td>
                  <td className="num strong">{fmtWon(p.MIN_DC_PRICE)}</td>
                  <td className="num"><RateBadge v={p.MAX_DC_RATE} /></td>
                  <td>{p.MIN_MALL}</td>
                  <td className="muted">{dtToIso(p.MIN_DT)}</td>
                  <td className="num">{p.MALL_CNT}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {data && (
        <div className="footnote">
          {dtLabel(data.start)} ~ {dtLabel(data.end)} · 집계 시각 {data.generatedAt}
        </div>
      )}
      {productCd && <ProductInsightModal prdtCd={productCd} onClose={() => setProductCd(null)} />}
    </div>
  )
}

function Kpi({ icon, label, value, sub, tone }: { icon: ReactNode; label: string; value: string | null; sub: string; tone: string }) {
  return (
    <div className="card kpi">
      <div className={`kpi-icon tone-${tone}`}>{icon}</div>
      <div className="kpi-body">
        <div className="kpi-label">{label}</div>
        {value === null ? <div className="shimmer kpi-shimmer" /> : <div className="kpi-value">{value}</div>}
        <div className="kpi-sub">{sub}</div>
      </div>
    </div>
  )
}

function Panel({ title, hint, loading, children }: { title: string; hint?: string; loading?: boolean; children: ReactNode }) {
  return (
    <div className="card panel">
      <div className="panel-head">
        <h3>{title}</h3>
        {hint && <span className="panel-hint">{hint}</span>}
      </div>
      {loading ? <div className="shimmer panel-shimmer" /> : children}
    </div>
  )
}

export function RateBadge({ v }: { v: unknown }) {
  if (typeof v !== 'number') return <span className="muted">-</span>
  const tone = v >= 30 ? 'hot' : v >= 15 ? 'warm' : 'cool'
  return <span className={`rate ${tone}`}>{v.toFixed(2)}%</span>
}

type TipProps = { active?: boolean; payload?: { name: string; value: number; color?: string; payload: Record<string, unknown> }[]; label?: string }
function ChartTip({ active, payload, label }: TipProps) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const title = (row.MALL_NM as string) || (row.DT ? dtLabel(row.DT as string) : label)
  return (
    <div className="chart-tip">
      <div className="chart-tip-title">{title}</div>
      {payload.map((p) => (
        <div key={p.name} className="chart-tip-row">
          <span className="dot" style={{ background: p.color }} />
          <span>{p.name}</span>
          <b>{p.name.includes('%') ? fmtPct(p.value, 2) : fmtNum(p.value)}</b>
        </div>
      ))}
      {row.PRDT_CNT !== undefined && <div className="chart-tip-row sub">상품 {fmtNum(row.PRDT_CNT)}개{row.MALL_CNT !== undefined && ` · 사이트 ${fmtNum(row.MALL_CNT)}개`}</div>}
    </div>
  )
}
