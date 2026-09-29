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
import { ApiError, apiFetch } from '../api'
import type { ShopRow } from '../invtApi'
import { fmtNum } from '../format'

type Col = { key: string; label: string; type: 'text' | 'int' }
type Options = { seasons: string[]; planYears: string[]; columns: Col[]; pageSize: number; maxMonths: number; sheetRows: number }
type ExportJob = {
  id: string
  status: 'running' | 'done' | 'error' | 'cancelled'
  total: number
  written: number
  sheets: number
  elapsedSec: number
  fileName: string
  fileSize: number | null
  error: string | null
}
type Summary = { rows: number; qty: number; realSaleAmt: number }
type Row = Record<string, string | number | null>
type Cond = { ymFrom: string; ymTo: string; shops: { id: string; name: string }[]; planYys: string[]; seasons: string[] }

const json = async <T,>(url: string, init?: RequestInit) => (await apiFetch(url, init)).json() as Promise<T>
const fmtSec = (sec: number) => (sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`)
const fmtSize = (b: number) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(2)}GB` : `${Math.max(1, Math.round(b / 1024 ** 2))}MB`)

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

// 엑셀 생성 대략 속도 (측정값 기준, 조회 포함)
const ROWS_PER_SEC = 35_000

export default function SaleMonthlyView({ onContextChange }: { onContextChange?: (ctx: Record<string, string>) => void }) {
  const [opts, setOpts] = useState<Options | null>(null)
  const [cond, setCond] = useState<Cond>(() => ({ ymFrom: lastMonth(), ymTo: lastMonth(), shops: [], planYys: [], seasons: [] }))
  const [applied, setApplied] = useState<Cond | null>(null)
  const [page, setPage] = useState(1)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [dsct, setDsct] = useState<number | null | 'error'>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [picker, setPicker] = useState(false)
  const [job, setJob] = useState<ExportJob | null>(null)
  const [starting, setStarting] = useState(false)
  const downloaded = useRef<string | null>(null)
  const reqId = useRef(0)
  const dsctReq = useRef(0)

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
    if (withTotal) {
      // 할인금액 합계는 테이블 전체를 읽어야 해서 따로 계산 (긴 기간은 수십 초)
      const did = ++dsctReq.current
      setDsct(null)
      json<{ dsctAmt: number }>(`/api/sale-monthly/dsct?${toQuery(c)}`)
        .then((r) => did === dsctReq.current && setDsct(r.dsctAmt))
        .catch(() => did === dsctReq.current && setDsct('error'))
    }
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

  // 화면 재진입 시 진행 중이거나 받을 수 있는 작업 이어서 표시
  useEffect(() => {
    json<{ job: ExportJob | null }>('/api/sale-monthly/exports/current')
      .then((r) => {
        if (r.job) {
          if (r.job.status === 'done') downloaded.current = r.job.id // 이미 끝난 작업은 자동으로 다시 받지 않음
          setJob(r.job)
        }
      })
      .catch(() => undefined)
  }, [])

  // 진행률 조회
  useEffect(() => {
    if (!job || job.status !== 'running') return
    const t = setTimeout(() => {
      json<ExportJob>(`/api/sale-monthly/exports/${job.id}`)
        .then(setJob)
        .catch((e) => {
          setError(e.message)
          setJob(null)
        })
    }, 1500)
    return () => clearTimeout(t)
  }, [job])

  // 완료되면 파일 받기 (브라우저 기본 다운로드 → 대용량도 메모리에 올리지 않고 디스크로 저장)
  const download = useCallback((j: ExportJob) => {
    downloaded.current = j.id
    const a = document.createElement('a')
    a.href = `/api/sale-monthly/exports/${j.id}/file`
    a.download = j.fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
  }, [])
  useEffect(() => {
    if (job?.status === 'done' && downloaded.current !== job.id) download(job)
    if (job?.status === 'error') setError(job.error)
  }, [job, download])

  const total = summary?.rows ?? 0
  const pageSize = opts?.pageSize ?? 100
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const pageNumbers = useMemo(() => {
    const start = Math.max(1, Math.min(page - 4, pages - 9))
    return Array.from({ length: Math.min(10, pages) }, (_, i) => start + i)
  }, [page, pages])
  const sheetRows = opts?.sheetRows ?? 1_000_000
  const running = job?.status === 'running'

  const exportXlsx = async () => {
    if (!applied || !total) return
    const estSec = Math.round(total / ROWS_PER_SEC)
    const sheets = Math.ceil(total / sheetRows)
    if (
      (estSec >= 60 || sheets > 1) &&
      !window.confirm(
        `${fmtNum(total)}건을 엑셀로 만듭니다.\n` +
          (sheets > 1 ? `시트당 ${fmtNum(sheetRows)}행씩 ${sheets}개 시트로 나눠 담습니다.\n` : '') +
          `예상 소요 시간: 약 ${fmtSec(Math.max(estSec, 5))} (서버에서 만들고, 끝나면 자동으로 내려받습니다)\n계속할까요?`,
      )
    )
      return
    setStarting(true)
    setError(null)
    try {
      const body = { ymFrom: applied.ymFrom, ymTo: applied.ymTo, shops: applied.shops.map((s) => s.id).join(','), planYys: applied.planYys.join(','), seasons: applied.seasons.join(',') }
      setJob(await json<ExportJob>('/api/sale-monthly/exports', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }))
    } catch (e) {
      const ex = e as ApiError
      if (ex.code === 'EXPORT_RUNNING' && ex.extra?.job) setJob(ex.extra.job as ExportJob)
      setError(ex.message)
    } finally {
      setStarting(false)
    }
  }

  const cancelExport = async () => {
    if (!job) return
    try {
      await apiFetch(`/api/sale-monthly/exports/${job.id}`, { method: 'DELETE' })
    } finally {
      setJob(null)
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
              disabled={running || starting || !total}
              title={`조회 조건의 전체 결과를 엑셀로 내려받습니다. ${fmtNum(sheetRows)}행을 넘으면 다음 시트에 이어서 담습니다.`}
            >
              {running || starting ? <Loader2 size={15} className="spin" /> : <Download size={15} />}
              {running ? ' 엑셀 생성 중' : ` 엑셀 전체 (${fmtNum(total)}건)`}
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
          <div className="pill">
            <span>할인금액 합계</span>
            <b>{dsct === null ? <Loader2 size={13} className="spin" /> : dsct === 'error' ? '계산 실패' : `${fmtNum(dsct)}원`}</b>
          </div>
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
      {job && job.status !== 'cancelled' && job.status !== 'error' && (
        <section className={`card export-job ${job.status}`}>
          <div className="export-job-head">
            {job.status === 'running' ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
            <b>{job.status === 'running' ? '엑셀 만드는 중' : '엑셀 준비 완료'}</b>
            <span className="muted">
              {fmtNum(job.written)} / {fmtNum(job.total)}건 · {job.sheets || 1}개 시트 · {fmtSec(job.elapsedSec)}
              {job.status === 'running' && job.written > 0 && job.written < job.total &&
                ` · 약 ${fmtSec(Math.max(1, Math.round(((job.total - job.written) * job.elapsedSec) / job.written)))} 남음`}
              {job.status === 'done' && job.fileSize ? ` · ${fmtSize(job.fileSize)}` : ''}
            </span>
            <div className="grow" />
            {job.status === 'done' && (
              <button className="btn success sm" onClick={() => download(job)}><Download size={13} /> 다시 받기</button>
            )}
            <button className="btn ghost sm" onClick={cancelExport}>{job.status === 'running' ? '취소' : '닫기'}</button>
          </div>
          <div className="progress"><div style={{ width: `${job.total ? Math.min(100, (job.written * 100) / job.total) : 0}%` }} /></div>
          {job.status === 'running' && <div className="muted small">다른 메뉴로 이동해도 서버에서 계속 만들고, 이 화면으로 돌아오면 이어서 보여 줍니다. 완료 후 2시간 동안 다시 받을 수 있습니다.</div>}
        </section>
      )}

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
