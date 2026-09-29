import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CalendarDays,
  Check,
  ClipboardList,
  Download,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TrendingUp,
  X,
} from 'lucide-react'
import { invtApi, isoToYmd, ymdToIso, type InvtOptions, type InvtPlan } from '../invtApi'
import { fmtNum } from '../format'
import ShopTrendModal from './ShopTrendModal'
import InvtPlanEditor from './InvtPlanEditor'

type Col = {
  key: keyof InvtPlan
  label: string
  group?: string
  width: number
  align?: 'right' | 'center'
  kind?: 'num' | 'date' | 'rate' | 'yn' | 'planDt' | 'elapsed' | 'text' | 'long'
}

// 이미지와 같은 순서/그룹 구성
const COLS: Col[] = [
  { key: 'shopId', label: '매장코드', width: 88 },
  { key: 'brdNm', label: '브랜드', width: 76 },
  { key: 'shopFormNm', label: '유통', width: 120 },
  { key: 'shopNm', label: '매장명', width: 150 },
  { key: 'prevSaleMil', label: '전년', group: '평균매출(백만원)', width: 64, align: 'right', kind: 'num' },
  { key: 'currSaleMil', label: '당년', group: '평균매출(백만원)', width: 64, align: 'right', kind: 'num' },
  { key: 'saleRate', label: '증감율', group: '평균매출(백만원)', width: 72, align: 'right', kind: 'rate' },
  { key: 'addr', label: '주소', width: 200, kind: 'long' },
  { key: 'areaNm', label: '지역', width: 110 },
  { key: 'regionNm', label: '권역', width: 70, align: 'center' },
  { key: 'lastInvtDt', label: '최종실사일', width: 96, align: 'center', kind: 'date' },
  { key: 'prevInvtType', label: '전실사유형', width: 80, align: 'center' },
  { key: 'prevInvtResult', label: '전실사결과', width: 90, align: 'right', kind: 'num' },
  { key: 'elapsedDays', label: '경과일', width: 70, align: 'right', kind: 'elapsed' },
  { key: 'stockQty', label: '당일기준', group: '재고 수량', width: 84, align: 'right', kind: 'num' },
  { key: 'invtPlanNote', label: '실사예정', width: 150, kind: 'long' },
  { key: 'baseFee', label: '기본료', group: '업체 예상 비용', width: 90, align: 'right', kind: 'num' },
  { key: 'expectAmt', label: '실사예상액', group: '업체 예상 비용', width: 96, align: 'right', kind: 'num' },
  { key: 'invtPlanDt', label: '실사예정일', width: 104, align: 'center', kind: 'planDt' },
  { key: 'rmk', label: '비고', width: 170, kind: 'long' },
  { key: 'twiceYearYn', label: '연2회 실사 매장', width: 84, align: 'center', kind: 'yn' },
  { key: 'shopRankNm', label: '관리등급', width: 70, align: 'center' },
  { key: 'stlmTeam', label: '정산 팀구분', width: 80, align: 'center' },
  { key: 'smasrNm', label: '성함', group: '매니저', width: 80 },
  { key: 'smasrHp', label: '전화번호', group: '매니저', width: 116 },
  { key: 'shopTel', label: '매장번호', group: '매니저', width: 116 },
]

type Sort = { key: keyof InvtPlan; order: 'asc' | 'desc' } | null
type PlanFilter = 'all' | 'set' | 'unset'

export default function InvtPlanView({ onContextChange }: { onContextChange?: (ctx: Record<string, string>) => void }) {
  const [plans, setPlans] = useState<InvtPlan[]>([])
  const [options, setOptions] = useState<InvtOptions | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [lastFrom, setLastFrom] = useState('') // 최종실사일 FROM (YYYY-MM-DD)
  const [lastTo, setLastTo] = useState('') // 최종실사일 TO
  const [planFilter, setPlanFilter] = useState<PlanFilter>('all')
  const [twiceOnly, setTwiceOnly] = useState(false)
  const [sort, setSort] = useState<Sort>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editor, setEditor] = useState<{ plan: InvtPlan | null } | null>(null)
  const [datePop, setDatePop] = useState<{ plan: InvtPlan; x: number; y: number } | null>(null)
  const [trend, setTrend] = useState<InvtPlan | null>(null)
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null)
  const [exporting, setExporting] = useState(false)

  const notify = useCallback((text: string, isError = false) => {
    setToast({ text, error: isError })
    setTimeout(() => setToast(null), 2400)
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    invtApi
      .list()
      .then((r) => {
        setPlans(r.plans)
        setSelected((s) => new Set([...s].filter((id) => r.plans.some((p) => p.planId === id))))
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    invtApi.options().then(setOptions).catch(() => undefined)
  }, [load])

  const rows = useMemo(() => {
    const kw = q.trim().toLowerCase()
    let list = plans.filter((p) => {
      if (lastFrom || lastTo) {
        const d = p.lastInvtDt ?? ''
        if (!d) return false
        if (lastFrom && d < isoToYmd(lastFrom)) return false
        if (lastTo && d > isoToYmd(lastTo)) return false
      }
      if (planFilter === 'set' && !p.invtPlanDt) return false
      if (planFilter === 'unset' && p.invtPlanDt) return false
      if (twiceOnly && p.twiceYearYn !== 'Y') return false
      if (!kw) return true
      return [p.shopId, p.shopNm, p.brdNm, p.shopFormNm, p.addr, p.areaNm, p.smasrNm, p.invtPlanNote, p.rmk]
        .some((v) => String(v ?? '').toLowerCase().includes(kw))
    })
    if (sort) {
      const dir = sort.order === 'asc' ? 1 : -1
      list = [...list].sort((a, b) => {
        const va = a[sort.key]
        const vb = b[sort.key]
        if (va == null || va === '') return 1
        if (vb == null || vb === '') return -1
        if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
        return String(va).localeCompare(String(vb), 'ko') * dir
      })
    }
    return list
  }, [plans, q, lastFrom, lastTo, planFilter, twiceOnly, sort])

  // AI 대화에 현재 화면 조건 전달
  useEffect(() => {
    onContextChange?.({
      lastFrom: isoToYmd(lastFrom),
      lastTo: isoToYmd(lastTo),
      planFilter,
      twiceOnly: twiceOnly ? 'Y' : '',
      q: q.trim(),
    })
  }, [onContextChange, lastFrom, lastTo, planFilter, twiceOnly, q])

  const summary = useMemo(() => {
    const set = plans.filter((p) => p.invtPlanDt).length
    const cost = rows.reduce((acc, p) => acc + (p.baseFee ?? 0) + (p.expectAmt ?? 0), 0)
    return { total: plans.length, set, unset: plans.length - set, twice: plans.filter((p) => p.twiceYearYn === 'Y').length, cost }
  }, [plans, rows])

  const toggleSort = (key: keyof InvtPlan) =>
    setSort((s) => (s?.key !== key ? { key, order: 'asc' } : s.order === 'asc' ? { key, order: 'desc' } : null))

  const allChecked = rows.length > 0 && rows.every((r) => selected.has(r.planId))
  const toggleAll = () =>
    setSelected((s) => {
      const next = new Set(s)
      if (allChecked) rows.forEach((r) => next.delete(r.planId))
      else rows.forEach((r) => next.add(r.planId))
      return next
    })
  const toggleOne = (id: number) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const removeSelected = async () => {
    if (!selected.size) return
    if (!confirm(`선택한 ${selected.size}건의 실사계획을 삭제할까요?`)) return
    try {
      const r = await invtApi.remove([...selected])
      notify(`${r.deleted}건을 삭제했습니다.`)
      setSelected(new Set())
      load()
    } catch (e) {
      notify((e as Error).message, true)
    }
  }

  const exportXlsx = async () => {
    setExporting(true)
    try {
      await invtApi.exportXlsx(rows.map((r) => r.planId))
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setExporting(false)
    }
  }

  const saveDate = async (plan: InvtPlan, ymd: string | null) => {
    try {
      const { plan: updated } = await invtApi.update(plan.planId, { invtPlanDt: ymd })
      setPlans((list) => list.map((p) => (p.planId === updated.planId ? updated : p)))
      notify(ymd ? `실사예정일을 ${ymdToIso(ymd)}로 저장했습니다.` : '실사예정일을 미정으로 변경했습니다.')
    } catch (e) {
      notify((e as Error).message, true)
    }
    setDatePop(null)
  }

  // 헤더 1행: 그룹 병합
  const headRow1: { label: string; span: number; group: boolean; col?: Col }[] = []
  COLS.forEach((c) => {
    const last = headRow1[headRow1.length - 1]
    if (c.group && last?.group && last.label === c.group) last.span += 1
    else headRow1.push(c.group ? { label: c.group, span: 1, group: true } : { label: c.label, span: 1, group: false, col: c })
  })

  const sortIcon = (key: keyof InvtPlan) =>
    sort?.key === key ? sort.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} /> : <ArrowUpDown size={12} className="sort-idle" />

  return (
    <div className="stack">
      <section className="card toolbar">
        <div className="toolbar-title">
          <ClipboardList size={18} /> 매장 재고 실사계획
        </div>
        <div className="search">
          <Search size={16} />
          <input placeholder="매장코드 · 매장명 · 주소 · 매니저 · 비고 검색" value={q} onChange={(e) => setQ(e.target.value)} />
          {q && (
            <button className="clear" onClick={() => setQ('')}>
              <X size={14} />
            </button>
          )}
        </div>
        <div className="date-range" title="최종실사일 기간">
          <span className="date-range-label">최종실사일</span>
          <input type="date" value={lastFrom} max={lastTo || undefined} onChange={(e) => setLastFrom(e.target.value)} aria-label="최종실사일 FROM" />
          <span className="muted">~</span>
          <input type="date" value={lastTo} min={lastFrom || undefined} onChange={(e) => setLastTo(e.target.value)} aria-label="최종실사일 TO" />
          {(lastFrom || lastTo) && (
            <button className="clear" title="기간 지우기" onClick={() => { setLastFrom(''); setLastTo('') }}>
              <X size={13} />
            </button>
          )}
        </div>
        <div className="seg big">
          {(['all', 'set', 'unset'] as PlanFilter[]).map((f) => (
            <button key={f} className={planFilter === f ? 'on' : ''} onClick={() => setPlanFilter(f)}>
              {f === 'all' ? '전체' : f === 'set' ? '예정일 확정' : '미정'}
            </button>
          ))}
        </div>
        <label className="check-label">
          <input type="checkbox" checked={twiceOnly} onChange={(e) => setTwiceOnly(e.target.checked)} /> 연2회만
        </label>
        <div className="toolbar-actions">
          <button className="icon-btn bordered" title="새로고침" onClick={load}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
          </button>
          <button className="btn ghost danger" disabled={!selected.size} onClick={removeSelected}>
            <Trash2 size={15} /> 삭제{selected.size ? ` (${selected.size})` : ''}
          </button>
          <button className="btn success" onClick={exportXlsx} disabled={exporting || rows.length === 0}>
            {exporting ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀 ({fmtNum(rows.length)}건)
          </button>
          <button className="btn primary" onClick={() => setEditor({ plan: null })}>
            <Plus size={15} /> 신규 등록
          </button>
        </div>
      </section>

      <section className="summary-pills">
        <div className="pill strong"><span>전체</span><b>{fmtNum(summary.total)}건</b></div>
        <div className="pill"><span>예정일 확정</span><b>{fmtNum(summary.set)}</b></div>
        <div className="pill"><span>미정</span><b>{fmtNum(summary.unset)}</b></div>
        <div className="pill"><span>연2회 매장</span><b>{fmtNum(summary.twice)}</b></div>
        <div className="pill"><span>업체 예상 비용 합계(조회 결과)</span><b>{fmtNum(summary.cost)}원</b></div>
        <div className="pill hint-pill">실사예정일 셀 더블클릭 → 날짜 지정 · 그 외 행 더블클릭 → 수정</div>
      </section>

      {error && <div className="alert error">{error}</div>}

      <section className="card grid-card">
        <div className="table-wrap tall invt-wrap">
          <table className="table invt-table">
            <colgroup>
              <col style={{ width: 36 }} />
              {COLS.map((c) => <col key={c.key} style={{ width: c.width }} />)}
              <col style={{ width: 44 }} />
            </colgroup>
            <thead>
              <tr>
                <th rowSpan={2} className="center">
                  <input type="checkbox" checked={allChecked} onChange={toggleAll} aria-label="전체 선택" />
                </th>
                {headRow1.map((h, i) =>
                  h.group ? (
                    <th key={i} colSpan={h.span} className="center group-th">{h.label}</th>
                  ) : (
                    <th key={i} rowSpan={2} className={`sortable center ${sort?.key === h.col!.key ? 'active' : ''}`} onClick={() => toggleSort(h.col!.key)}>
                      <span className="th-inner">{h.label}{sortIcon(h.col!.key)}</span>
                    </th>
                  ),
                )}
                <th rowSpan={2} />
              </tr>
              <tr>
                {COLS.filter((c) => c.group).map((c) => (
                  <th key={c.key} className={`sortable center sub-th ${sort?.key === c.key ? 'active' : ''}`} onClick={() => toggleSort(c.key)}>
                    <span className="th-inner">{c.label}{sortIcon(c.key)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.planId} className={selected.has(p.planId) ? 'selected' : ''} onDoubleClick={() => setEditor({ plan: p })}>
                  <td className="center" onDoubleClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(p.planId)} onChange={() => toggleOne(p.planId)} />
                  </td>
                  {COLS.map((c) => (
                    <td
                      key={c.key}
                      className={`${c.align ?? ''} ${c.kind === 'planDt' ? 'plan-dt-cell' : ''}`}
                      onDoubleClick={
                        c.kind === 'planDt'
                          ? (e) => {
                              e.stopPropagation()
                              const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
                              setDatePop({ plan: p, x: r.left, y: r.bottom + 4 })
                            }
                          : undefined
                      }
                    >
                      {c.key === 'shopId' && p.shopId ? (
                        <button className="btn-link mono" title="최근 12개월 판매 추이" onClick={() => setTrend(p)}>{p.shopId}</button>
                      ) : (
                        <Cell col={c} plan={p} />
                      )}
                    </td>
                  ))}
                  <td className="center" onDoubleClick={(e) => e.stopPropagation()}>
                    <button className="icon-btn tiny-visible" title="판매 추이" onClick={() => setTrend(p)}>
                      <TrendingUp size={14} />
                    </button>
                    <button className="icon-btn tiny-visible" title="수정" onClick={() => setEditor({ plan: p })}>
                      <Pencil size={14} />
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={COLS.length + 2} className="empty invt-empty">
                    <span className="empty-sticky">
                      {plans.length === 0 ? '등록된 실사계획이 없습니다. [신규 등록]으로 추가하세요.' : '조건에 맞는 실사계획이 없습니다.'}
                    </span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {trend && (
        <ShopTrendModal
          url={`/api/invt-plans/shops/${encodeURIComponent(trend.shopId)}/sales-trend`}
          title={trend.shopNm ?? trend.shopId}
          onClose={() => setTrend(null)}
        />
      )}

      {datePop && <DatePopover pop={datePop} onClose={() => setDatePop(null)} onSave={saveDate} />}

      {editor && options && (
        <InvtPlanEditor
          plan={editor.plan}
          options={options}
          onClose={() => setEditor(null)}
          onSaved={(saved, isNew) => {
            setEditor(null)
            notify(isNew ? `${saved.shopNm ?? saved.shopId} 실사계획을 등록했습니다.` : '저장했습니다.')
            load()
          }}
        />
      )}

      {toast && (
        <div className={`toast ${toast.error ? 'error' : ''}`}>
          {toast.error ? <X size={15} /> : <Check size={15} />} {toast.text}
        </div>
      )}
    </div>
  )
}

function Cell({ col, plan }: { col: Col; plan: InvtPlan }) {
  const v = plan[col.key]
  switch (col.kind) {
    case 'num':
      return v == null ? <span className="muted">-</span> : <>{fmtNum(v)}</>
    case 'rate':
      if (typeof v !== 'number') return <span className="muted">-</span>
      return <span className={v > 0 ? 'up' : v < 0 ? 'down' : ''}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>
    case 'date':
      return v ? <>{ymdToIso(v)}</> : <span className="muted">-</span>
    case 'planDt':
      return v ? (
        <span className="plan-dt">{ymdToIso(v)}</span>
      ) : (
        <span className="undecided" title="더블클릭하여 날짜 지정">미정</span>
      )
    case 'elapsed':
      if (typeof v !== 'number') return <span className="muted">-</span>
      return <span className={v >= 365 ? 'elapsed-warn' : ''}>{fmtNum(v)}일</span>
    case 'yn':
      return v === 'Y' ? <span className="yn-on"><Check size={13} /></span> : <span className="muted">-</span>
    case 'long':
      return v ? <span className="ellipsis-inline" title={String(v)}>{String(v)}</span> : <span className="muted">-</span>
    default:
      return v == null || v === '' ? <span className="muted">-</span> : <>{String(v)}</>
  }
}

function DatePopover({
  pop,
  onClose,
  onSave,
}: {
  pop: { plan: InvtPlan; x: number; y: number }
  onClose: () => void
  onSave: (plan: InvtPlan, ymd: string | null) => void
}) {
  const [value, setValue] = useState(ymdToIso(pop.plan.invtPlanDt))
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [onClose])
  const left = Math.min(pop.x, window.innerWidth - 260)
  const top = Math.min(pop.y, window.innerHeight - 170)
  return (
    <div className="date-pop" ref={ref} style={{ left, top }}>
      <div className="date-pop-head">
        <CalendarDays size={14} /> 실사예정일 · {pop.plan.shopNm ?? pop.plan.shopId}
      </div>
      <input className="input" type="date" autoFocus value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && value && onSave(pop.plan, isoToYmd(value))} />
      <div className="date-pop-actions">
        <button className="btn ghost sm" onClick={() => onSave(pop.plan, null)}>미정으로</button>
        <button className="btn primary sm" disabled={!value} onClick={() => onSave(pop.plan, isoToYmd(value))}>저장</button>
      </div>
    </div>
  )
}
