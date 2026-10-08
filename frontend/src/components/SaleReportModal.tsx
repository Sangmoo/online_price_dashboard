import { useEffect, useRef, useState } from 'react'
import { printReport, saveReportPng } from '../reportExport'
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, XAxis, YAxis } from 'recharts'
import { FileImage, FileText, Loader2, Printer, X } from 'lucide-react'
import type { Dash, Shop } from './SaleDashboardView'
import { fmtGrowth } from './ShopTrendModal'
import { fmtNum } from '../format'

// 보고서는 다크 모드 · 강조 색과 관계없이 흰 바탕 인쇄용 색을 쓴다
const C = { bar: '#4f46e5', prev: '#f59e0b', cost: '#10b981', dsct: '#ef4444', goal: '#94a3b8', grid: '#e5e7eb', tick: '#6b7280' }
const ymLabel = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
const eok = (v: number) =>
  Math.abs(v) >= 100_000_000
    ? `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억`
    : `${Math.round(v / 10_000).toLocaleString('ko-KR')}만`
const mil = (v: number) => Math.round(v / 1_000_000)
const pct = (v: number | null | undefined) => (v == null ? '-' : `${v.toFixed(1)}%`)
const pp = (v: number | null | undefined) => (v == null ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`)
const sign = (v: number | null | undefined) => (v == null ? '' : v >= 0 ? 'rp-up' : 'rp-down')
const nameOf = (s: Shop) => s.shopNm ?? s.shopId
const now = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 숫자에서 뽑은 핵심 요약 문장 (보고 첫 줄) */
function highlights(d: Dash): string[] {
  const k = d.kpi
  const b = d.base.kindLabel
  const out = [`${d.period.label} 실판금액 ${eok(k.amt)} — ${b} 대비 ${fmtGrowth(k.change)} (${b} ${eok(k.baseAmt)})`]
  if (d.hasGoals && k.achieve != null) out.push(`목표 달성률 ${pct(k.achieve)} (목표 ${eok(k.goalAmt)}, ${k.goalGap != null && k.goalGap >= 0 ? '초과' : '부족'} ${eok(Math.abs(k.goalGap ?? 0))})`)
  out.push(`원가율 ${pct(k.costRate)} (${pp(k.costRateDiff)}) · 할인율 ${pct(k.dsctRate)} (${pp(k.dsctRateDiff)}) · 판매 매장 ${fmtNum(k.shops)}개`)
  const brands = d.brands.filter((x) => x.change != null)
  if (brands.length > 1) {
    const best = brands.reduce((a, x) => (x.change! > a.change! ? x : a))
    const worst = brands.reduce((a, x) => (x.change! < a.change! ? x : a))
    if (best.change !== worst.change) out.push(`브랜드: ${best.brand} ${fmtGrowth(best.change)}로 가장 좋고, ${worst.brand} ${fmtGrowth(worst.change)}로 가장 낮음`)
  }
  if (d.topShops[0]) out.push(`매출 1위 매장 ${nameOf(d.topShops[0])} ${eok(d.topShops[0].amt)}${d.risers[0] ? ` · 성장 1위 ${nameOf(d.risers[0])} ${fmtGrowth(d.risers[0].change)}` : ''}`)
  return out
}

function ShopTable({ title, rows, mode, n }: { title: string; rows: Shop[]; mode: 'amt' | 'growth' | 'goal'; n: number }) {
  return (
    <div className="rp-box">
      <div className="rp-box-title">{title}</div>
      <table className="rp-table">
        <tbody>
          {rows.slice(0, n).map((s, i) => (
            <tr key={s.shopId}>
              <td className="rp-rank">{i + 1}</td>
              <td className="rp-name">{nameOf(s)} <span className="rp-dim">{s.brand}</span></td>
              <td className="rp-num">{eok(s.amt)}</td>
              <td className={`rp-num ${mode === 'goal' ? '' : sign(s.change)}`}>{mode === 'goal' ? pct(s.achieve) : fmtGrowth(s.change)}</td>
            </tr>
          ))}
          {!rows.length && <tr><td className="rp-dim" colSpan={4}>해당 없음</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

/** 판매 현황 한 장 보고서 (A4 가로): PDF 는 브라우저 인쇄(PDF로 저장), 이미지는 PNG 로 */
export default function SaleReportModal({ data, userName, onClose }: { data: Dash; userName?: string; onClose: () => void }) {
  const pageRef = useRef<HTMLDivElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stamp] = useState(now)
  const d = data
  const k = d.kpi
  const b = d.base.kindLabel
  const fileBase = `판매현황_보고_${d.period.label.replace(/[^\d~-]/g, '')}${d.brand ? `_${d.brand}` : ''}`

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', esc)
    document.documentElement.classList.add('printing-report')   // 인쇄할 때 보고서만 나오게
    return () => {
      document.removeEventListener('keydown', esc)
      document.documentElement.classList.remove('printing-report')
    }
  }, [])

  const printPdf = () => pageRef.current && printReport(pageRef.current, fileBase)   // 'PDF로 저장' 기본 파일 이름
  const savePng = async () => {
    if (!pageRef.current) return
    setBusy(true)
    setError(null)
    try {
      await saveReportPng(pageRef.current, fileBase)
    } catch (e) {
      setError(`이미지를 만들지 못했습니다: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const trend = d.trend.map((t) => ({ name: ymLabel(t.ym).slice(2), 당해: mil(t.amt), 전년: mil(t.prevAmt), 원가율: t.costRate, 할인율: t.dsctRate }))
  const baseName = `비교(${d.base.label})`
  const brandChart = d.brands.map((x) => ({ name: x.brand, 당기: mil(x.amt), [baseName]: mil(x.baseAmt), ...(d.hasGoals ? { 목표: x.goalAmt ? mil(x.goalAmt) : null } : {}) }))
  const tick = { fill: C.tick, fontSize: 10 }
  const kpis: { label: string; value: string; sub: string; delta?: string; cls?: string }[] = [
    { label: `실판금액`, value: eok(k.amt), sub: `${b} ${eok(k.baseAmt)}`, delta: fmtGrowth(k.change), cls: sign(k.change) },
    ...(d.hasGoals ? [{ label: '목표 달성률', value: pct(k.achieve), sub: `목표 ${eok(k.goalAmt)}`, delta: k.goalGap == null ? '-' : `${k.goalGap >= 0 ? '+' : '-'}${eok(Math.abs(k.goalGap))}`, cls: (k.achieve ?? 0) >= 100 ? 'rp-up' : 'rp-down' }] : []),
    { label: `${d.ym.slice(0, 4)}년 누계`, value: eok(k.ytdAmt), sub: `전년 ${eok(k.prevYtdAmt)}`, delta: fmtGrowth(k.ytdYoy), cls: sign(k.ytdYoy) },
    { label: '판매 수량', value: fmtNum(k.qty), sub: `${b} ${fmtNum(k.baseQty)}`, delta: fmtGrowth(k.qtyChange), cls: sign(k.qtyChange) },
    { label: '원가율', value: pct(k.costRate), sub: `${b} ${pct(k.baseCostRate)}`, delta: pp(k.costRateDiff) },
    { label: '할인율', value: pct(k.dsctRate), sub: `${b} ${pct(k.baseDsctRate)}`, delta: pp(k.dsctRateDiff) },
    { label: '판매 매장', value: `${fmtNum(k.shops)}개`, sub: `매장당 ${k.avgPerShop ? eok(k.avgPerShop) : '-'}`, delta: `${k.shops - k.baseShops >= 0 ? '+' : ''}${fmtNum(k.shops - k.baseShops)}개` },
  ]

  return (
    <div className="modal-backdrop top report-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card report-modal" role="dialog" aria-label="한 장 보고서">
        <div className="modal-head report-no-print">
          <h3><FileText size={17} /> 한 장 보고서 <span className="muted small">A4 가로 · 지금 조회한 조건</span></h3>
          <div className="report-actions">
            <button className="btn primary" onClick={printPdf} title="인쇄 창에서 대상을 'PDF로 저장'으로 고르세요 (용지 A4 가로)"><Printer size={15} /> PDF 저장 · 인쇄</button>
            <button className="btn ghost" onClick={savePng} disabled={busy}>{busy ? <Loader2 size={15} className="spin" /> : <FileImage size={15} />} 이미지(PNG)</button>
            <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
          </div>
        </div>
        {error && <div className="alert error report-no-print">{error}</div>}
        <div className="report-scroll">
          <div className="report-page" ref={pageRef}>
            <header className="rp-head">
              <div>
                <div className="rp-title">판매 현황 보고</div>
                <div className="rp-cond">{d.period.label} · 비교 {b} {d.base.label} · 브랜드 {d.brand ?? '전체'} · 마감 매출(실판금액) 기준</div>
              </div>
              <div className="rp-meta">{stamp}{userName ? ` · ${userName}` : ''}<br />ERP 영업 관리</div>
            </header>

            <ul className="rp-highlights">{highlights(d).map((h) => <li key={h}>{h}</li>)}</ul>

            <section className="rp-kpis" style={{ gridTemplateColumns: `repeat(${kpis.length}, 1fr)` }}>
              {kpis.map((x) => (
                <div key={x.label} className="rp-kpi">
                  <div className="rp-kpi-label">{x.label}</div>
                  <div className="rp-kpi-value">{x.value}</div>
                  <div className="rp-kpi-sub"><span className={x.cls}>{x.delta}</span> {x.sub}</div>
                </div>
              ))}
            </section>

            <section className="rp-row">
              <div className="rp-box rp-chart">
                <div className="rp-box-title">최근 13개월 실판금액 <span className="rp-dim">막대 당해 · 선 전년 · 점선 원가율 · 할인율(오른쪽) · 백만원</span></div>
                <ComposedChart width={600} height={196} data={trend} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} interval={0} />
                  <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={50} tickFormatter={(v) => fmtNum(v)} />
                  <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={34} tickFormatter={(v) => `${v}%`} domain={['auto', 'auto']} />
                  <Legend wrapperStyle={{ fontSize: 10 }} iconSize={8} />
                  <Bar yAxisId="l" dataKey="당해" fill={C.bar} radius={[3, 3, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                  <Line yAxisId="l" dataKey="전년" stroke={C.prev} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                  <Line yAxisId="r" dataKey="원가율" stroke={C.cost} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                  <Line yAxisId="r" dataKey="할인율" stroke={C.dsct} strokeWidth={1.5} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
                </ComposedChart>
              </div>
              <div className="rp-box rp-brand">
                <div className="rp-box-title">브랜드별 <span className="rp-dim">{d.period.label}</span></div>
                <BarChart width={400} height={92} data={brandChart} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
                  <YAxis tick={tick} tickLine={false} axisLine={false} width={44} tickFormatter={(v) => fmtNum(v)} />
                  <Bar dataKey="당기" fill={C.bar} maxBarSize={16} isAnimationActive={false} />
                  <Bar dataKey={baseName} fill={C.prev} maxBarSize={16} isAnimationActive={false} />
                  {d.hasGoals && <Bar dataKey="목표" fill={C.goal} maxBarSize={16} isAnimationActive={false} />}
                </BarChart>
                <table className="rp-table">
                  <thead><tr><th>브랜드</th><th className="rp-num">실판</th><th className="rp-num">비중</th><th className="rp-num">증감</th><th className="rp-num">원가율</th><th className="rp-num">할인율</th>{d.hasGoals && <th className="rp-num">달성</th>}</tr></thead>
                  <tbody>
                    {d.brands.map((x) => (
                      <tr key={x.brand}>
                        <td className="rp-name">{x.brand}</td><td className="rp-num">{eok(x.amt)}</td><td className="rp-num">{pct(x.share)}</td>
                        <td className={`rp-num ${sign(x.change)}`}>{fmtGrowth(x.change)}</td><td className="rp-num">{pct(x.costRate)}</td><td className="rp-num">{pct(x.dsctRate)}</td>
                        {d.hasGoals && <td className="rp-num">{pct(x.achieve)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="rp-shops" style={{ gridTemplateColumns: `repeat(${d.hasGoals ? 4 : 3}, 1fr)` }}>
              <ShopTable title="실판금액 상위" rows={d.topShops} mode="amt" n={8} />
              <ShopTable title={`${b} 대비 성장 상위`} rows={d.risers} mode="growth" n={8} />
              <ShopTable title={`${b} 대비 하락 상위`} rows={d.fallers} mode="growth" n={8} />
              {d.hasGoals && <ShopTable title="목표 달성률 하위" rows={d.laggards} mode="goal" n={8} />}
            </section>

            <footer className="rp-foot">
              단위: 억 · 만원(금액), 차트 백만원 · 성장 · 하락은 비교 기간 {eok(d.minBaseForGrowth)} 이상 매장, 폐점 제외 · 원가율 = 원가 금액 ÷ 실판금액 · 할인율 = 할인금액 ÷ (실판금액 + 할인금액)
            </footer>
          </div>
        </div>
      </div>
    </div>
  )
}
