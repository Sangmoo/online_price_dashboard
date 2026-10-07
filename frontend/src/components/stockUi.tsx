import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Loader2 } from 'lucide-react'
import { ApiError } from '../api'
import { fmtNum } from '../format'

// 재고 재배치 추천 화면들이 함께 쓰는 작은 도구 (100행씩 넘겨 보기 · 날짜 · 오류 문구 · 계산 중 표시)

export const PAGE_SIZE = 100
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
  useEffect(() => setPage(0), [rows])
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

/** 고르기: 지금 페이지는 표 머리 체크박스, 걸러진 전체는 이 버튼 */
export function SelectAllFiltered({ keys, sel, setMany }: { keys: string[]; sel: Set<string>; setMany: (keys: string[], on: boolean) => void }) {
  const on = keys.length > 0 && keys.every((k) => sel.has(k))
  if (!keys.length) return null
  return (
    <button className="btn ghost sm" onClick={() => setMany(keys, !on)} title="검색 · 필터로 걸러진 모든 페이지의 행">
      {on ? `전체 ${fmtNum(keys.length)}건 선택 해제` : `전체 ${fmtNum(keys.length)}건 선택`}
    </button>
  )
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
