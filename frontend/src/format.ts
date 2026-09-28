const nf = new Intl.NumberFormat('ko-KR')

export const fmtNum = (v: unknown) => (typeof v === 'number' ? nf.format(v) : v == null ? '-' : String(v))
export const fmtWon = (v: unknown) => (typeof v === 'number' ? `${nf.format(v)}원` : '-')
export const fmtPct = (v: unknown, digits = 1) => (typeof v === 'number' ? `${v.toFixed(digits)}%` : '-')

export const compact = (v: number) =>
  v >= 1e8 ? `${(v / 1e8).toFixed(1)}억` : v >= 1e4 ? `${(v / 1e4).toFixed(1)}만` : nf.format(v)

/** 20260922 → 2026-09-22 */
export const dtToIso = (dt: string) => (dt?.length === 8 ? `${dt.slice(0, 4)}-${dt.slice(4, 6)}-${dt.slice(6, 8)}` : dt)
/** 2026-09-22 → 20260922 */
export const isoToDt = (iso: string) => iso.replaceAll('-', '')
/** 20260922 → 09.22 */
export const dtShort = (dt: string) => (dt?.length === 8 ? `${dt.slice(4, 6)}.${dt.slice(6, 8)}` : dt)

const WEEK = ['일', '월', '화', '수', '목', '금', '토']
export const dtLabel = (dt: string) => {
  const d = new Date(dtToIso(dt))
  return `${dtToIso(dt)} (${WEEK[d.getDay()]})`
}

/** 202609221211 → 2026-09-22 12:11 */
export const insDay = (v: unknown) => {
  const s = String(v ?? '')
  return s.length >= 12 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)} ${s.slice(8, 10)}:${s.slice(10, 12)}` : s || '-'
}

export const addDays = (dt: string, n: number) => {
  const d = new Date(dtToIso(dt))
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

export const daysBetween = (a: string, b: string) =>
  Math.round((new Date(dtToIso(b)).getTime() - new Date(dtToIso(a)).getTime()) / 86400000)
