import { useMemo, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import type { InvtPlan } from '../invtApi'
import { fmtNum } from '../format'

const WEEK = ['일', '월', '화', '수', '목', '금', '토']
const MAX_CHIPS = 4
const ymd = (d: Date) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
const cost = (p: InvtPlan) => (p.baseFee ?? 0) + (p.expectAmt ?? 0)
const man = (v: number) => `${fmtNum(Math.round(v / 10000))}만원`
const teamClass = (t: string | null) => (t === '1팀' ? 't1' : t === '2팀' ? 't2' : 't0')
const label = (p: InvtPlan) => p.shopNm ?? p.shopId
const ymdText = (v: string) => `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}`

/** 처음 보여 줄 달: 오늘이 든 달 */
function startMonth(): Date {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

function Chip({ p, onOpen }: { p: InvtPlan; onOpen: (p: InvtPlan) => void }) {
  return (
    <button
      className={`cal-chip ${teamClass(p.stlmTeam)}`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', String(p.planId))
        e.dataTransfer.effectAllowed = 'move'
      }}
      onClick={() => onOpen(p)}
      title={`${label(p)} (${p.shopId}) · ${p.brdNm ?? ''} ${p.shopFormNm ?? ''}\n정산 ${p.stlmTeam ?? '-'} · 예상 비용 ${fmtNum(cost(p))}원${p.invtPlanNote ? `\n${p.invtPlanNote}` : ''}\n누르면 수정 · 끌어서 날짜 변경`}
    >
      <span className="cal-chip-name">{label(p)}</span>
      {p.brdNm && <span className="cal-chip-sub">{p.brdNm}</span>}
    </button>
  )
}

/**
 * 실사계획 달력: 실사예정일 기준 월 달력. 목록과 같은 조회 조건의 계획을 보여준다.
 * 칩을 누르면 수정 팝업, 다른 날짜(또는 오른쪽 '미정')로 끌어 놓으면 확인 후 실사예정일을 바꾼다.
 */
export default function InvtCalendar({ rows, onOpen, onMove }: {
  rows: InvtPlan[]; onOpen: (p: InvtPlan) => void; onMove: (p: InvtPlan, ymd: string | null) => Promise<void>
}) {
  const [month, setMonth] = useState(startMonth)
  const [over, setOver] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const today = ymd(new Date())

  const byDay = useMemo(() => {
    const m = new Map<string, InvtPlan[]>()
    for (const p of rows) if (p.invtPlanDt) m.set(p.invtPlanDt, [...(m.get(p.invtPlanDt) ?? []), p])
    for (const list of m.values()) list.sort((a, b) => (a.stlmTeam ?? '').localeCompare(b.stlmTeam ?? '') || label(a).localeCompare(label(b), 'ko'))
    return m
  }, [rows])
  const unset = useMemo(() => rows.filter((p) => !p.invtPlanDt).sort((a, b) => label(a).localeCompare(label(b), 'ko')), [rows])

  // 6주 칸: 그 달 1일이 든 주의 일요일부터
  const days = useMemo(() => {
    const first = new Date(month)
    first.setDate(1 - first.getDay())
    return Array.from({ length: 42 }, (_, i) => new Date(first.getFullYear(), first.getMonth(), first.getDate() + i))
  }, [month])
  const ym = `${month.getFullYear()}${String(month.getMonth() + 1).padStart(2, '0')}`
  const monthPlans = rows.filter((p) => p.invtPlanDt?.startsWith(ym))
  const busiest = Math.max(1, ...days.filter((d) => ymd(d).startsWith(ym)).map((d) => byDay.get(ymd(d))?.length ?? 0))
  const move = (n: number) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1))

  const drop = async (e: React.DragEvent, target: string | null) => {
    e.preventDefault()
    setOver(null)
    const id = Number(e.dataTransfer.getData('text/plain'))
    const p = rows.find((r) => r.planId === id)
    if (!p || (p.invtPlanDt ?? null) === target) return
    const from = p.invtPlanDt ? ymdText(p.invtPlanDt) : '미정'
    const to = target ? ymdText(target) : '미정'
    if (!confirm(`${label(p)} 실사예정일을 ${from} → ${to}(으)로 바꿀까요?`)) return
    await onMove(p, target)
  }
  const dragProps = (key: string, target: string | null) => ({
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (over !== key) setOver(key) },
    onDragLeave: () => setOver((o) => (o === key ? null : o)),
    onDrop: (e: React.DragEvent) => drop(e, target),
  })

  return (
    <section className="card cal-card">
      <div className="cal-head">
        <button className="icon-btn bordered" onClick={() => move(-1)} title="이전 달" aria-label="이전 달"><ChevronLeft size={16} /></button>
        <h3 className="cal-title"><CalendarDays size={17} /> {month.getFullYear()}년 {month.getMonth() + 1}월</h3>
        <button className="icon-btn bordered" onClick={() => move(1)} title="다음 달" aria-label="다음 달"><ChevronRight size={16} /></button>
        <button className="btn ghost sm" onClick={() => setMonth(startMonth())}>이번 달</button>
        <span className="muted small">이 달 {fmtNum(monthPlans.length)}건 · 예상 비용 {man(monthPlans.reduce((a, p) => a + cost(p), 0))}</span>
        <div className="grow" />
        <span className="cal-legend"><i className="t1" /> 정산 1팀 <i className="t2" /> 2팀 <i className="t0" /> 미지정</span>
      </div>
      <div className="cal-body">
        <div className="cal-grid" role="grid" aria-label="실사 달력">
          {WEEK.map((w, i) => <div key={w} className={`cal-wd ${i === 0 ? 'sun' : i === 6 ? 'sat' : ''}`}>{w}</div>)}
          {days.map((d) => {
            const key = ymd(d)
            const list = byDay.get(key) ?? []
            const inMonth = key.startsWith(ym)
            const expanded = open.has(key)
            const shown = expanded ? list : list.slice(0, MAX_CHIPS)
            const heat = inMonth && list.length ? Math.min(1, list.length / busiest) : 0
            return (
              <div key={key} role="gridcell" aria-label={ymdText(key)} data-day={key}
                className={`cal-day ${inMonth ? '' : 'out'} ${key === today ? 'today' : ''} ${over === key ? 'drop' : ''} ${d.getDay() === 0 ? 'sun' : d.getDay() === 6 ? 'sat' : ''}`}
                style={heat ? { ['--heat' as string]: String(0.05 + heat * 0.17) } : undefined}
                {...dragProps(key, key)}>
                <div className="cal-date">
                  <span>{d.getDate()}</span>
                  {list.length > 0 && <span className="cal-count" title={`예상 비용 ${fmtNum(list.reduce((a, p) => a + cost(p), 0))}원`}>{list.length}곳 · {man(list.reduce((a, p) => a + cost(p), 0))}</span>}
                </div>
                <div className="cal-chips">
                  {shown.map((p) => <Chip key={p.planId} p={p} onOpen={onOpen} />)}
                  {list.length > MAX_CHIPS && (
                    <button className="btn-link small cal-more" onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n })}>
                      {expanded ? '접기' : `+${list.length - MAX_CHIPS}곳 더`}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
        <aside className={`cal-unset ${over === 'unset' ? 'drop' : ''}`} aria-label="미정" {...dragProps('unset', null)}>
          <div className="cal-unset-head"><b>미정</b> <span className="muted small">{fmtNum(unset.length)}건 · 날짜로 끌어 놓으면 확정</span></div>
          <div className="cal-unset-list">
            {unset.map((p) => <Chip key={p.planId} p={p} onOpen={onOpen} />)}
            {!unset.length && <div className="muted small">미정 계획이 없습니다.</div>}
          </div>
        </aside>
      </div>
    </section>
  )
}
