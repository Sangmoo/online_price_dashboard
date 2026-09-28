import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Download,
  Loader2,
  RotateCcw,
  Search,
  Store,
  X,
} from 'lucide-react'
import { apiFetch, downloadFile } from '../api'
import type { ShopRow } from '../invtApi'
import { fmtNum } from '../format'

type Col = { key: string; label: string; type: 'text' | 'int' }
type Options = { seasons: string[]; planYears: string[]; columns: Col[]; pageSize: number; maxMonths: number; maxExportRows: number }
type Summary = { rows: number; qty: number; realSaleAmt: number; dsctAmt: number }
type Row = Record<string, string | number | null>
type Cond = { ymFrom: string; ymTo: string; shops: { id: string; name: string }[]; planYys: string[]; seasons: string[] }

const json = async <T,>(url: string) => (await apiFetch(url)).json() as Promise<T>

const lastMonth = () => {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
const monthsBetween = (f: string, t: string) => (Number(t.slice(0, 4)) - Number(f.slice(0, 4))) * 12 + Number(t.slice(5)) - Number(f.slice(5)) + 1
const fmtYm = (v: unknown) => (typeof v === 'string' && v.length === 6 ? `${v.slice(0, 4)}-${v.slice(4)}` : String(v ?? ''))

function toQuery(c: Cond, extra: Record<string, string | number> = {}) {
  const p = new URLSearchParams({ ymFrom: c.ymFrom, ymTo: c.ymTo })
  if (c.shops.length) p.set('shops', c.shops.map((s) => s.id).join(','))
  if (c.planYys.length) p.set('planYys', c.planYys.join(','))
  if (c.seasons.length) p.set('seasons', c.seasons.join(','))
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v))
  return p.toString()
}

// 엑셀 1행당 대략 시간 (측정값: 31.8만 행 ≈ 60초)
const SEC_PER_ROW = 60 / 318_000

export default function SaleMonthlyView({ onContextChange }: { onContextChange?: (ctx: Record<string, string>) => void }) {
  const [opts, setOpts] = useState<Options | null>(null)
  const [cond, setCond] = useState<Cond>(() => ({ ymFrom: lastMonth(), ymTo: lastMonth(), shops: [], planYys: [], seasons: [] }))
  const [applied, setApplied] = useState<Cond | null>(null)
  const [page, setPage] = useState(1)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [picker, setPicker] = useState(false)
  const [exporting, setExporting] = useState<number | null>(null) // 시작 시각(ms)
  const [, setTick] = useState(0)
  const reqId = useRef(0)

  useEffect(() => {
    json<Options>('/api/sale-monthly/options').then(setOpts).catch((e) => setError(e.message))
  }, [])

  const run = useCallback((c: Cond, p: number, withTotal: boolean) => {
    const id = ++reqId.current
    setLoading(true)
    setError(null)
    json<{ rows: Row[]; summary?: Summary }>(`/api/sale-monthly?${toQuery(c, { page: p, total: String(withTotal) })}`)
      .then((r) => {
        if (id !== reqId.current) return
        setRows(r.rows)
        if (r.summary) setSummary(r.summary)
      })
      .catch((e) => id === reqId.current && setError(e.message))
      .finally(() => id === reqId.current && setLoading(false))
  }, [])

  const search = () => {
    if (!cond.ymFrom || !cond.ymTo) return setError('판매년월을 입력하세요.')
    if (cond.ymFrom > cond.ymTo) return setError('판매년월 시작이 종료보다 늦습니다.')
    if (opts && monthsBetween(cond.ymFrom, cond.ymTo) > opts.maxMonths) return setError(`판매년월은 최대 ${opts.maxMonths}개월까지 조회할 수 있습니다.`)
    setApplied(cond)
    setPage(1)
    run(cond, 1, true)
  }

  // 첫 진입 시 지난달로 자동 조회
  const booted = useRef(false)
  useEffect(() => {
    if (!opts || booted.current) return
    booted.current = true
    setApplied(cond)
    run(cond, 1, true)
  }, [opts, cond, run])

  const goPage = (p: number) => {
    if (!applied) return
    setPage(p)
    run(applied, p, false)
  }

  useEffect(() => {
    if (!applied) return
    onContextChange?.({
      ymFrom: applied.ymFrom,
      ymTo: applied.ymTo,
      shops: applied.shops.map((s) => s.id).join(','),
      planYys: applied.planYys.join(','),
      seasons: applied.seasons.join(','),
    })
  }, [applied, onContextChange])

  useEffect(() => {
    if (exporting === null) return
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [exporting])

  const total = summary?.rows ?? 0
  const pageSize = opts?.pageSize ?? 100
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const pageNumbers = useMemo(() => {
    const start = Math.max(1, Math.min(page - 4, pages - 9))
    return Array.from({ length: Math.min(10, pages) }, (_, i) => start + i)
  }, [page, pages])
  const tooMany = !!opts && total > opts.maxExportRows
  const estSec = Math.round(total * SEC_PER_ROW)

  const exportXlsx = async () => {
    if (!applied || !total) return
    if (estSec >= 60 && !window.confirm(`${fmtNum(total)}건을 엑셀로 만듭니다. 약 ${Math.ceil(estSec / 60)}분 걸릴 수 있습니다. 계속할까요?`)) return
    setExporting(Date.now())
    try {
      await downloadFile(`/api/sale-monthly/export?${toQuery(applied)}`, undefined, '월별매장별판매집계.xlsx')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setExporting(null)
    }
  }

  const toggle = (key: 'planYys' | 'seasons', v: string) =>
    setCond((c) => ({ ...c, [key]: c[key].includes(v) ? c[key].filter((x) => x !== v) : [...c[key], v] }))

  const reset = () => setCond({ ymFrom: lastMonth(), ymTo: lastMonth(), shops: [], planYys: [], seasons: [] })
  const cols = opts?.columns ?? []

  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><BarChart3 size={18} /> 월별 매장별 판매 집계</div>
          <div className="date-range" title="판매년월 기간">
            <span className="date-range-label">판매년월</span>
            <input type="month" value={cond.ymFrom} max={cond.ymTo || undefined} onChange={(e) => setCond({ ...cond, ymFrom: e.target.value })} aria-label="판매년월 FROM" />
            <span className="muted">~</span>
            <input type="month" value={cond.ymTo} min={cond.ymFrom || undefined} onChange={(e) => setCond({ ...cond, ymTo: e.target.value })} aria-label="판매년월 TO" />
          </div>
          <div className="toolbar-actions">
            <button className="btn ghost" onClick={reset} title="조건 초기화"><RotateCcw size={15} /> 초기화</button>
            <button className="btn primary" onClick={search} disabled={loading}>
              {loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 조회
            </button>
            <button
              className="btn success"
              onClick={exportXlsx}
              disabled={exporting !== null || !total || tooMany}
              title={tooMany ? `엑셀은 최대 ${fmtNum(opts!.maxExportRows)}건까지 내려받을 수 있습니다. 조건을 좁혀 주세요.` : '조회 조건의 전체 결과를 엑셀로 내려받습니다.'}
            >
              {exporting !== null ? <Loader2 size={15} className="spin" /> : <Download size={15} />}
              {exporting !== null ? ` 엑셀 생성 중 ${Math.floor((Date.now() - exporting) / 1000)}초` : ` 엑셀 전체 (${fmtNum(total)}건)`}
            </button>
          </div>
        </div>

        <div className="sale-filter-row">
          <span className="filter-label">매장코드</span>
          <div className="shop-tags">
            {cond.shops.length === 0 && <span className="muted">전체 매장</span>}
            {cond.shops.map((s) => (
              <span key={s.id} className="shop-tag" title={s.name}>
                <b className="mono">{s.id}</b> {s.name}
                <button onClick={() => setCond({ ...cond, shops: cond.shops.filter((x) => x.id !== s.id) })} aria-label={`${s.id} 제외`}><X size={12} /></button>
              </span>
            ))}
            <button className="btn ghost sm" onClick={() => setPicker(true)}><Store size={13} /> 매장 선택</button>
            {cond.shops.length > 0 && <button className="btn-link" onClick={() => setCond({ ...cond, shops: [] })}>모두 지우기</button>}
          </div>
        </div>

        <div className="sale-filter-row">
          <span className="filter-label">기획년도</span>
          <div className="chips wrap">
            {(opts?.planYears ?? []).map((y) => (
              <button key={y} className={`chip ${cond.planYys.includes(y) ? 'active' : ''}`} onClick={() => toggle('planYys', y)}>{y}</button>
            ))}
          </div>
        </div>

        <div className="sale-filter-row">
          <span className="filter-label">시즌</span>
          <div className="chips wrap">
            {(opts?.seasons ?? []).map((s) => (
              <button key={s} className={`chip ${cond.seasons.includes(s) ? 'active' : ''}`} onClick={() => toggle('seasons', s)}>{s}</button>
            ))}
            <span className="muted small">선택하지 않으면 전체</span>
          </div>
        </div>
      </section>

      {summary && (
        <section className="summary-pills">
          <div className="pill strong"><span>조회 건수</span><b>{fmtNum(summary.rows)}건</b></div>
          <div className="pill"><span>수량 합계</span><b>{fmtNum(summary.qty)}</b></div>
          <div className="pill"><span>실판금액 합계</span><b>{fmtNum(summary.realSaleAmt)}원</b></div>
          <div className="pill"><span>할인금액 합계</span><b>{fmtNum(summary.dsctAmt)}원</b></div>
          {applied && (
            <div className="pill hint-pill">
              {applied.ymFrom === applied.ymTo ? applied.ymFrom : `${applied.ymFrom} ~ ${applied.ymTo}`}
              {applied.shops.length ? ` · 매장 ${applied.shops.length}개` : ''}
              {applied.planYys.length ? ` · ${applied.planYys.join(', ')}` : ''}
              {applied.seasons.length ? ` · ${applied.seasons.join(', ')}` : ''}
            </div>
          )}
        </section>
      )}

      {error && <div className="alert error">{error}</div>}
      {tooMany && <div className="alert">결과가 {fmtNum(total)}건이라 엑셀 최대 {fmtNum(opts!.maxExportRows)}건을 넘습니다. 기간·매장·시즌 조건을 좁히면 내려받을 수 있습니다.</div>}

      <section className="card grid-card">
        <div className={`table-wrap tall sale-wrap ${loading ? 'is-loading' : ''}`}>
          <table className="table sale-table">
            <thead>
              <tr>
                <th className="num">#</th>
                {cols.map((c) => <th key={c.key} className={c.type === 'int' ? 'num' : ''}>{c.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="num muted">{fmtNum((page - 1) * pageSize + i + 1)}</td>
                  {cols.map((c) => (
                    <td key={c.key} className={c.type === 'int' ? 'num' : c.key === 'SHOP_ID' || c.key === 'PRDT_CD' ? 'mono' : ''}>
                      {c.type === 'int' ? (r[c.key] === null ? '' : fmtNum(Number(r[c.key]))) : c.key === 'MAKE_YYMM' ? fmtYm(r[c.key]) : (r[c.key] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
              {!loading && applied && rows.length === 0 && (
                <tr><td colSpan={cols.length + 1} className="empty">조회된 데이터가 없습니다.</td></tr>
              )}
            </tbody>
          </table>
          {loading && <div className="table-loading"><Loader2 size={22} className="spin" /></div>}
        </div>

        {total > 0 && (
          <div className="pager">
            <div className="muted">
              {fmtNum((page - 1) * pageSize + 1)}–{fmtNum(Math.min(page * pageSize, total))} / {fmtNum(total)}건 · {fmtNum(page)}/{fmtNum(pages)} 페이지
            </div>
            <div className="pager-btns">
              <button className="icon-btn" disabled={page <= 1 || loading} onClick={() => goPage(1)}><ChevronsLeft size={16} /></button>
              <button className="icon-btn" disabled={page <= 1 || loading} onClick={() => goPage(page - 1)}><ChevronLeft size={16} /></button>
              {pageNumbers.map((n) => (
                <button key={n} className={`page-btn ${n === page ? 'active' : ''}`} disabled={loading} onClick={() => goPage(n)}>{n}</button>
              ))}
              <button className="icon-btn" disabled={page >= pages || loading} onClick={() => goPage(page + 1)}><ChevronRight size={16} /></button>
              <button className="icon-btn" disabled={page >= pages || loading} onClick={() => goPage(pages)}><ChevronsRight size={16} /></button>
            </div>
            <span className="muted">100건씩</span>
          </div>
        )}
      </section>

      {picker && (
        <ShopMultiPicker
          initial={cond.shops}
          onClose={() => setPicker(false)}
          onApply={(shops) => {
            setCond((c) => ({ ...c, shops }))
            setPicker(false)
          }}
        />
      )}
    </div>
  )
}

// ----------------------------------------------------------------------------
// 매장코드 다중 선택 팝업 (매장 재고 실사계획의 매장 검색과 같은 조회)
// ----------------------------------------------------------------------------
function ShopMultiPicker({ initial, onClose, onApply }: {
  initial: { id: string; name: string }[]
  onClose: () => void
  onApply: (shops: { id: string; name: string }[]) => void
}) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<ShopRow[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sel, setSel] = useState(initial)

  useEffect(() => {
    const kw = q.trim()
    if (!kw) {
      setRows([])
      setSearched(false)
      return
    }
    const t = setTimeout(() => {
      setLoading(true)
      setError(null)
      json<{ shops: ShopRow[] }>(`/api/sale-monthly/shops?q=${encodeURIComponent(kw)}`)
        .then((r) => {
          setRows(r.shops)
          setSearched(true)
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(t)
  }, [q])

  const has = (id: string) => sel.some((s) => s.id === id)
  const flip = (r: ShopRow) => setSel((s) => (has(r.shopId) ? s.filter((x) => x.id !== r.shopId) : [...s, { id: r.shopId, name: r.shopNm }]))
  const allOn = rows.length > 0 && rows.every((r) => has(r.shopId))
  const flipAll = () =>
    setSel((s) => (allOn ? s.filter((x) => !rows.some((r) => r.shopId === x.id)) : [...s, ...rows.filter((r) => !has(r.shopId)).map((r) => ({ id: r.shopId, name: r.shopNm }))]))

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card picker-modal">
        <div className="modal-head">
          <h3><Store size={16} /> 매장코드 선택 <span className="muted small">여러 개 선택 가능</span></h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="search">
          <Search size={16} />
          <input autoFocus placeholder="매장코드 또는 매장명 (예: S31019, 가산)" value={q} onChange={(e) => setQ(e.target.value)} />
          {loading && <Loader2 size={15} className="spin" />}
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="picker-list">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 36 }}><input type="checkbox" checked={allOn} disabled={!rows.length} onChange={flipAll} aria-label="검색 결과 전체 선택" /></th>
                <th>매장코드</th><th>매장명</th><th>유통</th><th>유통보고형태</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.shopId} className={`clickable ${has(r.shopId) ? 'selected' : ''}`} onClick={() => flip(r)}>
                  <td><input type="checkbox" checked={has(r.shopId)} readOnly /></td>
                  <td className="mono strong">{r.shopId}</td>
                  <td>{r.shopNm}</td>
                  <td className="muted">{r.shopFormNm ?? '-'}</td>
                  <td className="muted">{r.shopForm2Nm ?? '-'}</td>
                </tr>
              ))}
              {searched && !loading && rows.length === 0 && <tr><td colSpan={5} className="empty">검색 결과가 없습니다.</td></tr>}
              {!searched && !loading && <tr><td colSpan={5} className="empty">매장코드나 매장명을 입력하세요.</td></tr>}
            </tbody>
          </table>
        </div>
        {rows.length >= 100 && <div className="muted small">검색 결과가 많아 100건까지 표시합니다. 검색어를 더 구체적으로 입력하세요.</div>}
        <div className="picked-bar">
          <div className="shop-tags">
            {sel.length === 0 && <span className="muted">선택한 매장이 없습니다 (전체 매장)</span>}
            {sel.map((s) => (
              <span key={s.id} className="shop-tag" title={s.name}>
                <b className="mono">{s.id}</b> {s.name}
                <button onClick={() => setSel(sel.filter((x) => x.id !== s.id))} aria-label={`${s.id} 제외`}><X size={12} /></button>
              </span>
            ))}
          </div>
          <div className="setting-actions">
            {sel.length > 0 && <button className="btn ghost" onClick={() => setSel([])}>선택 해제</button>}
            <button className="btn primary" onClick={() => onApply(sel)}><Check size={15} /> {sel.length}개 적용</button>
          </div>
        </div>
      </div>
    </div>
  )
}
