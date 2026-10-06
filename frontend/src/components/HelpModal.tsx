import { useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, Search, X } from 'lucide-react'
import { HELP, HELP_GROUPS, type HelpEntry } from '../help/metrics'

/** 지표 정의 · 도움말: 계산식 · 원천 테이블 · 기준. focus 로 연 지표는 강조하고 그 위치로 스크롤한다. */
export default function HelpModal({ focus, onClose }: { focus?: string; onClose: () => void }) {
  const [q, setQ] = useState('')
  const bodyRef = useRef<HTMLDivElement>(null)

  // Esc 로 닫기: 화면이 1초마다 다시 그려져도(세션 타이머) 감시를 다시 걸지 않도록 한 번만 등록하고 최신 onClose 를 부른다
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [])

  useEffect(() => {
    if (!focus) return
    const el = bodyRef.current?.querySelector(`[data-help="${CSS.escape(focus)}"]`)
    el?.scrollIntoView({ block: 'start' })
  }, [focus])

  const list = useMemo(() => {
    const k = q.trim().toLowerCase()
    if (!k) return HELP
    return HELP.filter((h) => [h.name, ...h.formula, h.source, ...(h.notes ?? []), ...h.where].join(' ').toLowerCase().includes(k))
  }, [q])

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal" role="dialog" aria-label="지표 정의 · 도움말"
        onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
        <div className="modal-head">
          <h3><BookOpen size={17} /> 지표 정의 · 도움말</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        <div className="search help-search">
          <Search size={16} />
          <input placeholder="지표 · 계산식 · 테이블 검색 (예: 할인율, 원가율, T_SHOP)" value={q} onChange={(e) => setQ(e.target.value)} />
          {q && <button className="clear" onClick={() => setQ('')} title="지우기"><X size={14} /></button>}
        </div>
        <nav className="help-nav">
          {HELP_GROUPS.map((g) => (
            <button key={g.key} className="chip" onClick={() => bodyRef.current?.querySelector(`[data-group="${g.key}"]`)?.scrollIntoView({ block: 'start' })}>
              {g.label}
            </button>
          ))}
        </nav>
        <div className="help-body" ref={bodyRef}>
          {HELP_GROUPS.map((g) => {
            const items = list.filter((h) => h.group === g.key)
            if (!items.length) return null
            return (
              <section key={g.key} data-group={g.key} className="help-group">
                <div className="help-group-head"><b>{g.label}</b> <span className="muted small">{g.desc}</span></div>
                {items.map((h) => <Entry key={h.id} h={h} active={h.id === focus} />)}
              </section>
            )
          })}
          {!list.length && <div className="empty">‘{q}’ 에 맞는 지표가 없습니다.</div>}
        </div>
      </div>
    </div>
  )
}

function Entry({ h, active }: { h: HelpEntry; active: boolean }) {
  return (
    <article className={`help-entry ${active ? 'active' : ''}`} data-help={h.id}>
      <h4>{h.name}</h4>
      <div className="help-formula">
        {h.formula.map((f) => <div key={f}>{f}</div>)}
      </div>
      <dl>
        <dt>원천</dt>
        <dd className="mono-soft">{h.source}</dd>
        {!!h.notes?.length && (
          <>
            <dt>기준</dt>
            <dd><ul>{h.notes.map((n) => <li key={n}>{n}</li>)}</ul></dd>
          </>
        )}
        <dt>화면</dt>
        <dd>{h.where.join(' · ')}</dd>
        {h.code && (
          <>
            <dt>계산 위치</dt>
            <dd className="mono-soft muted">{h.code}</dd>
          </>
        )}
      </dl>
    </article>
  )
}
