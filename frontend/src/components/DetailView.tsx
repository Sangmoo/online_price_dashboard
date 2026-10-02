import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Columns3,
  Download,
  ExternalLink,
  Link2,
  Loader2,
  Percent,
  Search,
  X,
} from 'lucide-react'
import { api, downloadFile, type Column, type DateInfo, type RowsResponse } from '../api'
import { dtLabel, fmtNum, fmtPct, insDay } from '../format'
import { RateBadge } from './DashboardView'
import ProductInsightModal from './ProductInsightModal'

export type DetailState = {
  dt: string
  q: string
  mall: string
  sort?: string
  order: 'asc' | 'desc'
  minRate?: number
  maxRate?: number
}

type Props = {
  userId: string
  dates: DateInfo[]
  initial: DetailState
  onStateChange: (s: DetailState) => void
}

type Sort = { key: string; order: 'asc' | 'desc' } | null

const NUMERIC = new Set(['ONLINE_ID', 'PRICE', 'DC_PRICE', 'DC_RATE'])
const PREF_KEY = 'detail.columns'

const toNum = (s: string) => (s.trim() === '' || isNaN(Number(s)) ? undefined : Number(s))

export default function DetailView({ userId, dates, initial, onStateChange }: Props) {
  const [productCd, setProductCd] = useState<string | null>(null)
  const [dt, setDt] = useState(initial.dt)
  const [qInput, setQInput] = useState(initial.q)
  const [q, setQ] = useState(initial.q)
  const [mall, setMall] = useState(initial.mall)
  const [sort, setSort] = useState<Sort>(initial.sort ? { key: initial.sort, order: initial.order } : null)
  const [minInput, setMinInput] = useState(initial.minRate?.toString() ?? '')
  const [maxInput, setMaxInput] = useState(initial.maxRate?.toString() ?? '')
  const [rate, setRate] = useState<{ min?: number; max?: number }>({ min: initial.minRate, max: initial.maxRate })
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(100)
  const [data, setData] = useState<RowsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [hidden, setHidden] = useState<string[]>([])
  const [colMenu, setColMenu] = useState(false)
  const [copied, setCopied] = useState(false)
  const colMenuRef = useRef<HTMLDivElement>(null)

  // 사용자별 컬럼 표시 설정 불러오기
  useEffect(() => {
    api
      .getPref<string[]>(PREF_KEY)
      .then(({ value }) => Array.isArray(value) && setHidden(value))
      .catch(() => undefined)
  }, [userId])

  const saveHidden = (next: string[]) => {
    setHidden(next)
    api.setPref(PREF_KEY, next).catch(() => undefined)
  }

  useEffect(() => {
    if (!colMenu) return
    const close = (e: MouseEvent) => {
      if (colMenuRef.current && !colMenuRef.current.contains(e.target as Node)) setColMenu(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [colMenu])

  // 검색어 · 할인율 입력 디바운스
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(qInput.trim())
      setRate({ min: toNum(minInput), max: toNum(maxInput) })
      setPage(1)
    }, 400)
    return () => clearTimeout(t)
  }, [qInput, minInput, maxInput])

  // 상위(App)에 현재 조건 전달 → URL 공유
  useEffect(() => {
    onStateChange({ dt, q, mall, sort: sort?.key, order: sort?.order ?? 'asc', minRate: rate.min, maxRate: rate.max })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dt, q, mall, sort, rate])

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    setError(null)
    api
      .rows({ dt, page, size, sort: sort?.key, order: sort?.order ?? 'asc', q, mall, minRate: rate.min, maxRate: rate.max }, ctl.signal)
      .then(setData)
      .catch((e) => e.name !== 'AbortError' && setError(e.message))
      .finally(() => !ctl.signal.aborted && setLoading(false))
    return () => ctl.abort()
  }, [dt, page, size, sort, q, mall, rate])

  const visibleCols: Column[] = useMemo(() => (data?.columns ?? []).filter((c) => !hidden.includes(c.key)), [data, hidden])

  const dtIndex = dates.findIndex((d) => d.dt === dt)
  const changeDt = (next: string) => {
    setDt(next)
    setPage(1)
    setMall('')
  }

  const toggleSort = (key: string) => {
    setPage(1)
    setSort((s) => (s?.key !== key ? { key, order: 'asc' } : s.order === 'asc' ? { key, order: 'desc' } : null))
  }

  const exportXlsx = async () => {
    setExporting(true)
    try {
      await downloadFile(
        api.rowsExportUrl({
          dt,
          sort: sort?.key,
          order: sort?.order ?? 'asc',
          q,
          mall,
          minRate: rate.min,
          maxRate: rate.max,
          cols: hidden.length ? visibleCols.map((c) => c.key).join(',') : undefined,
        }),
        undefined,
        `온라인가격수집_${dt}.xlsx`,
      )
    } catch (e) {
      alert((e as Error).message)
    } finally {
      setExporting(false)
    }
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
    } catch {
      window.prompt('아래 링크를 복사하세요', window.location.href)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  const resetFilters = () => {
    setQInput('')
    setMinInput('')
    setMaxInput('')
    setMall('')
    setSort(null)
  }

  const pageNumbers = useMemo(() => {
    if (!data) return []
    const total = data.pages
    const from = Math.max(1, Math.min(page - 2, total - 4))
    return Array.from({ length: Math.min(5, total) }, (_, i) => from + i)
  }, [data, page])

  const filtered = !!(q || mall || rate.min !== undefined || rate.max !== undefined)

  return (
    <div className="stack">
      <section className="card toolbar">
        <div className="date-nav">
          <button className="icon-btn bordered" title="이전 수집일" disabled={dtIndex < 0 || dtIndex >= dates.length - 1} onClick={() => changeDt(dates[dtIndex + 1].dt)}>
            <ChevronLeft size={18} />
          </button>
          <select className="input select date-select" value={dt} onChange={(e) => changeDt(e.target.value)}>
            {dates.map((d) => (
              <option key={d.dt} value={d.dt}>
                {dtLabel(d.dt)} · {fmtNum(d.count)}건
              </option>
            ))}
          </select>
          <button className="icon-btn bordered" title="다음 수집일" disabled={dtIndex <= 0} onClick={() => changeDt(dates[dtIndex - 1].dt)}>
            <ChevronRight size={18} />
          </button>
        </div>

        <div className="search">
          <Search size={16} />
          <input placeholder="상품코드 · 상품명 · 사이트 · 매장정보 · 판매자ID 검색" value={qInput} onChange={(e) => setQInput(e.target.value)} />
          {qInput && (
            <button className="clear" onClick={() => setQInput('')} title="지우기">
              <X size={14} />
            </button>
          )}
        </div>

        <select className="input select" value={mall} onChange={(e) => { setMall(e.target.value); setPage(1) }}>
          <option value="">전체 사이트</option>
          {data?.malls.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>

        <div className="rate-range" title="할인율(%) 범위">
          <Percent size={14} />
          <input inputMode="decimal" placeholder="최소" value={minInput} onChange={(e) => setMinInput(e.target.value)} />
          <span>~</span>
          <input inputMode="decimal" placeholder="최대" value={maxInput} onChange={(e) => setMaxInput(e.target.value)} />
        </div>

        <div className="toolbar-actions">
          <div className="col-menu-wrap" ref={colMenuRef}>
            <button className={`btn ghost ${hidden.length ? 'on' : ''}`} onClick={() => setColMenu((o) => !o)}>
              <Columns3 size={15} /> 컬럼{hidden.length ? ` (${(data?.columns.length ?? 12) - hidden.length})` : ''}
            </button>
            {colMenu && data && (
              <div className="col-menu">
                <div className="col-menu-head">
                  표시할 컬럼
                  <button className="btn-link" onClick={() => saveHidden([])}>전체 표시</button>
                </div>
                {data.columns.map((c) => {
                  const on = !hidden.includes(c.key)
                  return (
                    <button
                      key={c.key}
                      className={`col-opt ${on ? 'on' : ''}`}
                      disabled={on && visibleCols.length <= 1}
                      onClick={() => saveHidden(on ? [...hidden, c.key] : hidden.filter((k) => k !== c.key))}
                    >
                      <span className="check">{on && <Check size={12} />}</span>
                      {c.label}
                    </button>
                  )
                })}
                <div className="col-menu-foot">설정은 내 계정에 저장되며 엑셀에도 적용됩니다.</div>
              </div>
            )}
          </div>
          <button className="btn ghost" onClick={copyLink} title="현재 날짜·검색·정렬 조건이 담긴 링크 복사">
            {copied ? <Check size={15} /> : <Link2 size={15} />} {copied ? '복사됨' : '링크 복사'}
          </button>
          <button className="btn success" onClick={exportXlsx} disabled={exporting || !data || data.total === 0}>
            {exporting ? <Loader2 size={15} className="spin" /> : <Download size={15} />}
            엑셀 다운로드{data ? ` (${fmtNum(data.total)}건)` : ''}
          </button>
        </div>
      </section>

      <section className="summary-pills">
        <Pill label={filtered ? '검색 결과' : '전체 건수'} value={data ? `${fmtNum(data.total)}건` : '-'} strong />
        {filtered && data && <Pill label="해당일 전체" value={`${fmtNum(data.totalAll)}건`} />}
        <Pill label="상품 수" value={data ? fmtNum(data.summary.products) : '-'} />
        <Pill label="사이트 수" value={data ? fmtNum(data.summary.malls) : '-'} />
        <Pill label="평균 할인율" value={data ? fmtPct(data.summary.avgDcRate, 2) : '-'} />
        {sort && (
          <button className="pill sort-pill" onClick={() => setSort(null)} title="정렬 해제">
            정렬: {data?.columns.find((c) => c.key === sort.key)?.label} {sort.order === 'asc' ? '오름차순' : '내림차순'} <X size={12} />
          </button>
        )}
        {(filtered || sort) && (
          <button className="pill sort-pill" onClick={resetFilters}>
            조건 초기화 <X size={12} />
          </button>
        )}
      </section>

      {error && <div className="alert error">{error}</div>}

      <section className="card grid-card">
        <div className={`table-wrap tall ${loading ? 'is-loading' : ''}`}>
          {loading && (
            <div className="table-loading">
              <Loader2 size={22} className="spin" />
            </div>
          )}
          <table className="table data">
            <thead>
              <tr>
                {visibleCols.map((c) => {
                  const active = sort?.key === c.key
                  return (
                    <th key={c.key} className={`sortable ${NUMERIC.has(c.key) ? 'num' : ''} ${active ? 'active' : ''} col-${c.key}`} onClick={() => toggleSort(c.key)} title="클릭하여 정렬">
                      <span className="th-inner">
                        {c.label}
                        {active ? sort!.order === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} /> : <ArrowUpDown size={13} className="sort-idle" />}
                      </span>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r, i) => (
                <tr key={`${data.page}-${i}`}>
                  {visibleCols.map((c) => (
                    <td key={c.key} className={`${NUMERIC.has(c.key) ? 'num' : ''} col-${c.key}`}>
                      <CellValue k={c.key} v={r[c.key]} onProduct={setProductCd} />
                    </td>
                  ))}
                </tr>
              ))}
              {data && data.rows.length === 0 && (
                <tr>
                  <td colSpan={visibleCols.length} className="empty">
                    조건에 맞는 데이터가 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {data && data.total > 0 && (
          <div className="pager">
            <div className="muted">
              {fmtNum((data.page - 1) * data.size + 1)}–{fmtNum(Math.min(data.page * data.size, data.total))} / {fmtNum(data.total)}건
            </div>
            <div className="pager-btns">
              <button className="icon-btn" disabled={page <= 1} onClick={() => setPage(1)}><ChevronsLeft size={16} /></button>
              <button className="icon-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={16} /></button>
              {pageNumbers.map((n) => (
                <button key={n} className={`page-btn ${n === data.page ? 'active' : ''}`} onClick={() => setPage(n)}>
                  {n}
                </button>
              ))}
              <button className="icon-btn" disabled={page >= data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={16} /></button>
              <button className="icon-btn" disabled={page >= data.pages} onClick={() => setPage(data.pages)}><ChevronsRight size={16} /></button>
            </div>
            <select className="input select small" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(1) }}>
              {[50, 100, 200, 500].map((n) => (
                <option key={n} value={n}>{n}건씩</option>
              ))}
            </select>
          </div>
        )}
      </section>
      {productCd && <ProductInsightModal prdtCd={productCd} onClose={() => setProductCd(null)} />}
    </div>
  )
}

function Pill({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`pill ${strong ? 'strong' : ''}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  )
}

function CellValue({ k, v, onProduct }: { k: string; v: string | number | null | undefined; onProduct?: (cd: string) => void }) {
  if (v === null || v === undefined || v === '') return <span className="muted">-</span>
  switch (k) {
    case 'PRICE':
    case 'DC_PRICE':
      return <>{fmtNum(v)}</>
    case 'DC_RATE':
      return <RateBadge v={v} />
    case 'DT':
      return <>{String(v).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')}</>
    case 'INS_DAY':
      return <span className="muted">{insDay(v)}</span>
    case 'URL':
      return (
        <a className="link" href={String(v)} target="_blank" rel="noreferrer noopener" title={String(v)}>
          <ExternalLink size={13} /> 열기
        </a>
      )
    case 'TITLE':
    case 'RMK':
      return <span className="ellipsis-inline" title={String(v)}>{v}</span>
    case 'PRDT_CD':
      return onProduct ? (
        <button className="btn-link mono" title="온라인 가격 · 매장 판매 비교" onClick={() => onProduct(String(v))}>{v}</button>
      ) : (
        <span className="mono">{v}</span>
      )
    default:
      return <>{v}</>
  }
}
