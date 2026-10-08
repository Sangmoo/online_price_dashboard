import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Loader2 } from 'lucide-react'
import { ApiError } from '../api'
import { fmtNum } from '../format'

// 재고 재배치 추천 화면들이 함께 쓰는 작은 도구 (100행씩 넘겨 보기 · 날짜 · 오류 문구 · 계산 중 표시)

export const PAGE_SIZE = 100
export const PAGE_SIZES = [100, 500, 1000, 3000]
const SIZE_KEY = 'stock-page-size'

/** 한 페이지 행 수 (100 · 500 · 1,000 · 3,000) — 화면마다 같은 값을 쓰고 브라우저에 기억 */
export function usePageSize(): [number, (n: number) => void] {
  const [size, setSize] = useState(() => {
    try {
      const v = Number(localStorage.getItem(SIZE_KEY))
      return PAGE_SIZES.includes(v) ? v : PAGE_SIZE
    } catch { return PAGE_SIZE }
  })
  const set = (n: number) => {
    setSize(n)
    try { localStorage.setItem(SIZE_KEY, String(n)) } catch { /* 저장 못 해도 이번 화면에는 적용 */ }
  }
  return [size, set]
}
export const iso = (d8: string) => `${d8.slice(0, 4)}-${d8.slice(4, 6)}-${d8.slice(6, 8)}`
export const addDaysIso = (isoDate: string, n: number) => {
  const d = new Date(`${isoDate}T00:00:00`)
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
export const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))
export const pct = (a: number, b: number) => (b ? `${Math.round((a * 1000) / b) / 10}%` : '-')
export const won = (v: number) => (Math.abs(v) >= 1e8 ? `${Math.round(v / 1e7) / 10}억` : Math.abs(v) >= 1e4 ? `${fmtNum(Math.round(v / 1e4))}만` : fmtNum(v))
export const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])

export type Paged<T> = { page: number; pages: number; total: number; size: number; slice: T[]; setPage: (p: number) => void }

/** 행을 100행씩 나눠 보여 준다. 행 목록이 바뀌면(검색 · 다시 계산) 첫 페이지로 */
export function usePaged<T>(rows: T[], size = PAGE_SIZE): Paged<T> {
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [rows, size])
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const p = Math.min(page, pages - 1)
  return { page: p, pages, total: rows.length, size, slice: rows.slice(p * size, (p + 1) * size), setPage }
}

export function Pager<T>({ pg, children, label = '건' }: { pg: Paged<T>; children?: React.ReactNode; label?: string }) {
  if (pg.total <= pg.size && !children) return null
  const from = pg.total ? pg.page * pg.size + 1 : 0
  const to = Math.min(pg.total, (pg.page + 1) * pg.size)
  return (
    <div className="stock-pager" role="navigation" aria-label="페이지">
      <span className="muted small">{fmtNum(from)}–{fmtNum(to)} / {fmtNum(pg.total)}{label}</span>
      {pg.pages > 1 && (
        <div className="stock-pager-btns">
          <button className="icon-btn" disabled={pg.page === 0} onClick={() => pg.setPage(0)} title="처음" aria-label="처음 페이지"><ChevronsLeft size={15} /></button>
          <button className="icon-btn" disabled={pg.page === 0} onClick={() => pg.setPage(pg.page - 1)} title="이전" aria-label="이전 페이지"><ChevronLeft size={15} /></button>
          <select className="input sm" value={pg.page} onChange={(e) => pg.setPage(Number(e.target.value))} aria-label="페이지 번호">
            {Array.from({ length: pg.pages }, (_, i) => <option key={i} value={i}>{i + 1} / {pg.pages}</option>)}
          </select>
          <button className="icon-btn" disabled={pg.page >= pg.pages - 1} onClick={() => pg.setPage(pg.page + 1)} title="다음" aria-label="다음 페이지"><ChevronRight size={15} /></button>
          <button className="icon-btn" disabled={pg.page >= pg.pages - 1} onClick={() => pg.setPage(pg.pages - 1)} title="끝" aria-label="마지막 페이지"><ChevronsRight size={15} /></button>
        </div>
      )}
      {children}
    </div>
  )
}

export type Pick = { key: string; label: string; count: number; qty: number }

/** 표 위 선택 바: 고른 건수 · 장수 · 걸친 페이지, 검색 결과 전체 · 이 페이지 · 해제, 매장으로 고르기, 선택한 것만 보기, 한 페이지 행 수 */
export function SelectBar({ total, sel, setMany, allKeys, pageKeys, selShown, selQty, pages, onlySel, setOnlySel, size, setSize, groups, unit = '장' }: {
  total: number; sel: Set<string>; setMany: (keys: string[], on: boolean) => void; allKeys: string[]; pageKeys: string[]
  selShown: number; selQty: number; pages: number; onlySel: boolean; setOnlySel: (v: boolean) => void; size: number; setSize: (n: number) => void
  groups?: { label: string; picks: Pick[]; keysOf: (key: string) => string[] }[]; unit?: string
}) {
  const allOn = allKeys.length > 0 && allKeys.every((k) => sel.has(k))
  const pageOn = pageKeys.length > 0 && pageKeys.every((k) => sel.has(k))
  return (
    <div className="stock-selbar" role="toolbar" aria-label="선택">
      <span className={`stock-selbar-count ${sel.size ? 'on' : ''}`}>
        {sel.size ? <>선택 <b>{fmtNum(sel.size)}건</b> · <b>{fmtNum(selQty)}{unit}</b>{pages > 1 ? ` · ${fmtNum(pages)}페이지에 걸침` : ''}
          {selShown < sel.size ? <span className="muted"> (지금 목록에 {fmtNum(selShown)}건)</span> : null}</> : <span className="muted">고른 행 없음</span>}
      </span>
      <button className="btn ghost sm" disabled={!allKeys.length} onClick={() => setMany(allKeys, !allOn)} title="검색 · 필터로 걸러진 모든 페이지의 행">
        {allOn ? `전체 ${fmtNum(allKeys.length)}건 해제` : `전체 ${fmtNum(allKeys.length)}건 선택`}
      </button>
      {total > size && (
        <button className="btn ghost sm" disabled={!pageKeys.length} onClick={() => setMany(pageKeys, !pageOn)}>{pageOn ? '이 페이지 해제' : '이 페이지만 선택'}</button>
      )}
      {groups?.map((g) => (
        <select key={g.label} className="input sm stock-selbar-pick" value="" aria-label={g.label}
          onChange={(e) => { if (e.target.value) setMany(g.keysOf(e.target.value), true) }}>
          <option value="">{g.label}</option>
          {g.picks.map((p) => <option key={p.key} value={p.key}>{p.label} · {fmtNum(p.count)}건 · {fmtNum(p.qty)}{unit}</option>)}
        </select>
      ))}
      <button className="btn ghost sm" disabled={!sel.size} onClick={() => setMany([...sel], false)}>선택 해제</button>
      <label className="check-label"><input type="checkbox" checked={onlySel} onChange={(e) => setOnlySel(e.target.checked)} disabled={!sel.size && !onlySel} /> 선택한 것만 보기</label>
      <label className="stock-selbar-size">한 페이지
        <select className="input sm" value={size} onChange={(e) => setSize(Number(e.target.value))} aria-label="한 페이지 행 수">
          {PAGE_SIZES.map((n) => <option key={n} value={n}>{fmtNum(n)}행</option>)}
        </select>
      </label>
    </div>
  )
}

/** 행 목록에서 고르기 그룹(매장 등)별 건수 · 수량 — 많은 순 */
export function groupPicks<T>(rows: T[], keyOf: (r: T) => string, groupOf: (r: T) => [string, string], qtyOf: (r: T) => number) {
  const m = new Map<string, Pick & { keys: string[] }>()
  for (const r of rows) {
    const [g, label] = groupOf(r)
    const x = m.get(g) ?? { key: g, label, count: 0, qty: 0, keys: [] }
    x.count += 1
    x.qty += qtyOf(r)
    x.keys.push(keyOf(r))
    m.set(g, x)
  }
  const list = [...m.values()].sort((a, b) => b.qty - a.qty)
  return { picks: list as Pick[], keysOf: (g: string) => m.get(g)?.keys ?? [] }
}

export function useElapsed(on: boolean) {
  const [sec, setSec] = useState(0)
  useEffect(() => {
    if (!on) return
    setSec(0)
    const t = window.setInterval(() => setSec((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [on])
  return sec
}

export function Busy({ sec, text }: { sec: number; text: string }) {
  return <div className="stock-loading"><Loader2 size={16} className="spin" /> {text} {sec > 2 ? `${sec}초` : ''}</div>
}
