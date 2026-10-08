import { useEffect, useRef, useState } from 'react'
import { printReport, saveReportPng } from '../reportExport'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { FileImage, Loader2, Printer, RefreshCw, Sparkles, X } from 'lucide-react'
import { apiFetch, qs } from '../api'
import { fmtNum } from '../format'

// AI 주간 브리핑: 지난주(월~일) 판매 · 재고 재배치 · 재고 건강 숫자 + AI 요약 한 장 (A4 가로, PDF 는 브라우저 인쇄)

type Num = number | null | undefined
type SaleBrand = { brand: string; brandNm: string; curAmt: number; curQty: number; prevAmt?: number; lyAmt?: number; vsPrev: Num; vsLy: Num
  topShops: { shopId: string; shopNm: string | null; amt: number }[]; topStyles: { prdtCd: string; amt: number; qty: number }[]
  days: { day: string; amt: number }[] }
type StockPart = { brand: string; brandNm: string
  rt?: { total: number; accepted: number; denied: number; autoDenied: number; pending: number; acceptRate: Num; avgHours: Num; soldRate: Num }
  pending?: { rows: number; shops: number; urgent: number; topShops: { shopNm: string | null; rows: number; urgent: number }[] }
  short?: { allocQty: number; demand: number; short: number; noStockSkus: number; shortRows: number }
  turnover?: { cover: Num; sellThru: Num; shortRows: number; overRows: number; overStock: number }
  aging?: { qty: number; agedQty: number; agedAmt: number; agedRate: Num; agedShops: number }
  initial?: { alloc: number; sold: number; sellThru: Num; overlap: Num; lowOverlap: number; products: number; period: string } }
export type Briefing = {
  period: { from: string; to: string }; brands: string[]
  sales?: { brands: SaleBrand[]; ranges: Record<string, string[]> }; stock?: StockPart[]
  ai: { text: string | null; blocked?: string; model?: string; costUsd?: number }
  errors: string[]; asOf: string; sec: number; cached: boolean
  /** 오늘 AI 주간 브리핑 사용 · 한도 (대화 질문 · 비용 한도와 별도) */
  quota?: { used: number; limit: number }
}

const eok = (v: number) => (Math.abs(v) >= 1e8 ? `${(v / 1e8).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억` : `${Math.round(v / 1e4).toLocaleString('ko-KR')}만`)
const pct = (v: Num) => (v == null ? '-' : `${v.toFixed(1)}%`)
const growth = (v: Num) => (v == null ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)
const sign = (v: Num) => (v == null ? '' : v >= 0 ? 'rp-up' : 'rp-down')
const dd = (v: Num) => (v == null ? '판매 없음' : `${fmtNum(Math.round(v))}일`)

/** [AI 주간 브리핑] 버튼 — 판매 현황 · 재고 재배치 추천 화면 위 */
export function BriefingButton({ brand, className = 'btn ghost' }: { brand?: string; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button className={className} onClick={() => setOpen(true)} title="지난주(월~일) 판매 · RT · 재고 숫자를 모아 AI 가 한 장으로 요약합니다 (브리핑 하루 횟수 1회 사용 · AI 대화 한도와 별도, 1시간 동안 다시 열면 그대로)">
        <Sparkles size={15} /> AI 주간 브리핑
      </button>
      {open && <WeeklyBriefingModal brand={brand} onClose={() => setOpen(false)} />}
    </>
  )
}

export default function WeeklyBriefingModal({ brand, onClose }: { brand?: string; onClose: () => void }) {
  const [d, setD] = useState<Briefing | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sec, setSec] = useState(0)
  const [busy, setBusy] = useState(false)
  const pageRef = useRef<HTMLDivElement>(null)
  const load = (refresh = false) => {
    setLoading(true)
    setError('')
    setSec(0)
    apiFetch(`/api/briefing/weekly?${qs({ brand, refresh: refresh ? 'true' : undefined })}`).then((r) => r.json()).then(setD)
      .catch((e) => setError((e as Error).message)).finally(() => setLoading(false))
  }
  useEffect(() => load(), []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!loading) return
    const t = window.setInterval(() => setSec((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [loading])
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', esc)
    document.documentElement.classList.add('printing-report')
    return () => {
      document.removeEventListener('keydown', esc)
      document.documentElement.classList.remove('printing-report')
    }
  }, [])
  const fileBase = `AI주간브리핑_${d?.period.from ?? ''}_${d?.period.to ?? ''}`
  const printPdf = () => pageRef.current && printReport(pageRef.current, fileBase)   // 'PDF로 저장' 기본 파일 이름
  const savePng = async () => {
    if (!pageRef.current) return
    setBusy(true)
    try {
      await saveReportPng(pageRef.current, fileBase)
    } catch (e) {
      setError(`이미지를 만들지 못했습니다: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="modal-backdrop top report-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card report-modal" role="dialog" aria-label="AI 주간 브리핑">
        <div className="modal-head report-no-print">
          <h3><Sparkles size={17} /> AI 주간 브리핑 <span className="muted small">{d ? `${d.period.from} ~ ${d.period.to} · ${d.brands.join(', ')}` : '지난주 월~일'}</span></h3>
          <div className="report-actions">
            <button className="btn ghost" onClick={() => load(true)} disabled={loading} title={`지금 숫자로 다시 모으고 AI 요약을 다시 만듭니다 (브리핑 1회 사용${d?.quota ? ` · 오늘 ${d.quota.used}/${d.quota.limit}회` : ''})`}><RefreshCw size={15} /> 다시 만들기{d?.quota ? <span className="muted small"> {d.quota.used}/{d.quota.limit}</span> : null}</button>
            <button className="btn primary" onClick={printPdf} disabled={!d || loading} title="인쇄 창에서 'PDF로 저장'을 고르세요 (A4 가로)"><Printer size={15} /> PDF 저장 · 인쇄</button>
            <button className="btn ghost" onClick={savePng} disabled={!d || loading || busy}>{busy ? <Loader2 size={15} className="spin" /> : <FileImage size={15} />} 이미지(PNG)</button>
            <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
          </div>
        </div>
        {error && <div className="alert error report-no-print">{error}</div>}
        {loading && (
          <div className="stock-loading report-no-print"><Loader2 size={16} className="spin" /> 지난주 판매 · RT · 재고 숫자를 모으고 AI 가 요약하는 중… {sec}초 (보통 20초~1분)</div>
        )}
        {d && !loading && (
          <div className="report-scroll">
            <div className="report-page brief-page" ref={pageRef}>
              <header className="rp-head">
                <div>
                  <div className="rp-title">AI 주간 브리핑</div>
                  <div className="rp-cond">{d.period.from} ~ {d.period.to} (월~일) · {d.brands.join(' · ')} · 판매는 매장 판매 원장 실판금액, 재고는 지금 기준</div>
                </div>
                <div className="rp-meta">{d.asOf}{d.cached ? ' (저장된 브리핑)' : ''}<br />ERP 영업 관리{d.ai.model ? ` · ${d.ai.model}` : ''}</div>
              </header>
              <div className="brief-body">
                <section className="brief-ai">
                  {d.ai.text
                    ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{d.ai.text}</ReactMarkdown>
                    : <div className="brief-blocked">{d.ai.blocked ?? 'AI 요약이 없습니다.'} — 오른쪽 숫자만 보여 드립니다.</div>}
                </section>
                <section className="brief-nums">
                  {d.sales && (
                    <div className="rp-box">
                      <div className="rp-box-title">판매 <span className="rp-dim">전주 {d.sales.ranges.prev?.join('~')} · 전년 같은 요일 {d.sales.ranges.ly?.join('~')}</span></div>
                      <table className="rp-table">
                        <thead><tr><th>브랜드</th><th className="rp-num">실판</th><th className="rp-num">수량</th><th className="rp-num">전주 대비</th><th className="rp-num">전년 대비</th></tr></thead>
                        <tbody>
                          {d.sales.brands.map((b) => (
                            <tr key={b.brand}><td className="rp-name">{b.brandNm}</td><td className="rp-num">{eok(b.curAmt)}</td><td className="rp-num">{fmtNum(b.curQty)}</td>
                              <td className={`rp-num ${sign(b.vsPrev)}`}>{growth(b.vsPrev)}</td><td className={`rp-num ${sign(b.vsLy)}`}>{growth(b.vsLy)}</td></tr>
                          ))}
                        </tbody>
                      </table>
                      {d.sales.brands.length === 1 && (
                        <div className="brief-two">
                          <div><div className="rp-dim">매출 상위 매장</div>{d.sales.brands[0].topShops.slice(0, 3).map((s) => <div key={s.shopId} className="brief-li">{s.shopNm ?? s.shopId} <b>{eok(s.amt)}</b></div>)}</div>
                          <div><div className="rp-dim">판매 수량 상위 스타일</div>{d.sales.brands[0].topStyles.slice(0, 3).map((s) => <div key={s.prdtCd} className="brief-li mono">{s.prdtCd} <b>{fmtNum(s.qty)}</b></div>)}</div>
                        </div>
                      )}
                    </div>
                  )}
                  {d.stock && (
                    <div className="rp-box">
                      <div className="rp-box-title">재고 재배치 · 재고 건강 <span className="rp-dim">행사 · 가상 매장 제외</span></div>
                      <table className="rp-table">
                        <thead><tr><th>브랜드</th><th className="rp-num" title="지난주 본사지시 RT 수락률">RT 수락</th><th className="rp-num" title="지금 매장 미처리 RT (자동거부 임박)">미처리</th>
                          <th className="rp-num" title="어제 판매분 창고 배분의 창고 부족">창고 부족</th><th className="rp-num" title="최근 28일 판매 기준">재고일수</th>
                          <th className="rp-num" title="90일 넘게 안 팔린 매장 재고 비중">장기 재고</th><th className="rp-num" title="초도 배분 적중률 · 판매율">초도 적중</th></tr></thead>
                        <tbody>
                          {d.stock.map((x) => (
                            <tr key={x.brand}>
                              <td className="rp-name">{x.brandNm}</td>
                              <td className="rp-num">{x.rt ? `${pct(x.rt.acceptRate)}` : '-'}<div className="rp-dim">{x.rt ? `${fmtNum(x.rt.total)}장` : ''}</div></td>
                              <td className="rp-num">{x.pending ? fmtNum(x.pending.rows) : '-'}<div className="rp-dim">{x.pending?.urgent ? `임박 ${x.pending.urgent}` : ''}</div></td>
                              <td className="rp-num">{x.short ? `${fmtNum(x.short.short)}장` : '-'}</td>
                              <td className="rp-num">{x.turnover ? dd(x.turnover.cover) : '-'}<div className="rp-dim">{x.turnover ? `품절 위험 ${fmtNum(x.turnover.shortRows)}` : ''}</div></td>
                              <td className="rp-num">{x.aging ? pct(x.aging.agedRate) : '-'}<div className="rp-dim">{x.aging ? eok(x.aging.agedAmt) : ''}</div></td>
                              <td className="rp-num">{x.initial ? pct(x.initial.overlap) : '-'}<div className="rp-dim">{x.initial ? `판매율 ${pct(x.initial.sellThru)}` : ''}</div></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {d.sales && d.sales.brands.length > 0 && (
                    <div className="rp-box">
                      <div className="rp-box-title">일별 실판 <span className="rp-dim">브랜드 합계</span></div>
                      <div className="brief-days">
                        {(() => {
                          const days = d.sales.brands[0].days.map((x, i) => ({ day: x.day, amt: d.sales!.brands.reduce((a, b) => a + (b.days[i]?.amt ?? 0), 0) }))
                          const max = Math.max(1, ...days.map((x) => x.amt))
                          return days.map((x) => (
                            <div key={x.day} className="brief-day"><span className="brief-bar" style={{ height: `${(x.amt / max) * 100}%` }} /><b>{eok(x.amt)}</b><span className="rp-dim">{x.day.slice(5)}</span></div>
                          ))
                        })()}
                      </div>
                    </div>
                  )}
                  {d.errors.length > 0 && <div className="rp-dim">일부 숫자를 모으지 못했습니다: {d.errors.join(' · ')}</div>}
                </section>
              </div>
              <footer className="rp-foot">AI 요약은 오른쪽 숫자만 근거로 썼습니다. 판매 = 매장 판매 원장(반품 차감) · 재고 재배치 = 재고 재배치 추천 메뉴와 같은 계산 · {d.sec}초</footer>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
