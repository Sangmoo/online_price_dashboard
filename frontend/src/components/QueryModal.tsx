import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Copy, Database, GitBranch, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { opsApi, type PageQueries, type QueryFeature, type QueryItem, type QueryRun } from '../opsApi'
import { copyText } from '../copy'
import PlanModal from './PlanModal'

type OnPlan = (p: { sql: string; filled?: string; title?: string }) => void

const withSemi = (sql: string) => (/;\s*$/.test(sql) || /^\s*(VARIABLE|EXEC|PRINT)\b/im.test(sql) ? sql : `${sql};`)
const itemName = (it: QueryItem) => it.title ?? it.fn ?? ''
const ranCount = (f: QueryFeature) => f.items.reduce((n, it) => n + (it.runs?.length ?? 0), 0)
/** 기능 전체 복사: 실제 실행 쿼리가 있으면 그것(값 채움), 없으면 코드 기준 SQL */
const featureText = (f: QueryFeature) =>
  [`-- ${f.title}${f.desc ? ` : ${f.desc}` : ''}`, ...f.items.flatMap((it) => {
    const head = `-- ${itemName(it)}${it.file ? ` (${it.file}:${it.line})` : ''}`
    if (it.runs?.length) return it.runs.map((r, i) => `${head}${it.runs.length > 1 ? ` #${i + 1}` : ''} · 실행 ${r.at}\n${withSemi(r.filled)}`)
    return it.sqls.map((s, i) => `${head}${it.sqls.length > 1 ? ` #${i + 1}` : ''} · 코드 기준 (조회 전)\n${withSemi(s)}`)
  })].join('\n\n')

/** 복사 버튼: 누르면 잠깐 '복사됨' */
function CopyBtn({ text, label = '복사', title }: { text: string; label?: string; title?: string }) {
  const [state, setState] = useState<'idle' | 'ok' | 'fail'>('idle')
  const timer = useRef<number>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <button className={`btn ghost sm copy-btn ${state}`} title={title ?? '쿼리를 클립보드에 복사'}
      onClick={async () => {
        setState((await copyText(text)) ? 'ok' : 'fail')
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => setState('idle'), 1500)
      }}>
      {state === 'ok' ? <Check size={12} /> : <Copy size={12} />} {state === 'ok' ? '복사됨' : state === 'fail' ? '복사 실패' : label}
    </button>
  )
}

/** 실제 실행된 쿼리 1개: 값이 채워진 SQL 과 복사 */
function RunCode({ r, n, onPlan, title }: { r: QueryRun; n?: number; onPlan: OnPlan; title: string }) {
  return (
    <div className="q-code">
      <div className="q-code-bar">
        {n != null && <span className="q-num">#{n}</span>}
        <span className="muted small mono">실행 {r.at} · {r.ms.toLocaleString()}ms{r.count > 1 ? ` · ${r.count.toLocaleString()}회` : ''}</span>
        <div className="grow" />
        {/^\s*\(?\s*(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE)\b/i.test(r.sql) && (
          <button className="btn ghost sm" title="실제 · 예상 실행 계획 (쿼리는 실행하지 않음)"
            onClick={() => onPlan({ sql: r.raw ?? r.sql, filled: r.filled, title })}><GitBranch size={12} /> 실행 계획</button>
        )}
        <CopyBtn text={withSemi(r.filled)} />
      </div>
      <pre className="sql-code">{r.filled}</pre>
    </div>
  )
}

function CodeBlock({ sql, n }: { sql: string; n?: number }) {
  return (
    <div className="q-code">
      <div className="q-code-bar">
        {n != null && <span className="q-num">#{n}</span>}
        <span className="muted small">코드 기준</span>
        <div className="grow" />
        <CopyBtn text={withSemi(sql)} />
      </div>
      <pre className="sql-code">{sql}</pre>
    </div>
  )
}

function ItemBlock({ it, me, onPlan }: { it: QueryItem; me: string; onPlan: OnPlan }) {
  const runs = it.runs ?? []
  const older = it.older ?? []
  const [showCode, setShowCode] = useState(false)
  const [showOlder, setShowOlder] = useState(false)
  const by = runs[0]?.usr && runs[0].usr !== me ? `사용자 ${runs[0].usr} 조회` : '내 최근 조회'
  return (
    <div className={`q-item ${runs.length ? 'ran' : ''}`}>
      <div className="q-item-head">
        <span className="mono strong">{itemName(it)}</span>
        {it.file && <span className="muted small mono">{it.file}:{it.line}</span>}
        <div className="grow" />
        {it.fn && (runs.length
          ? <span className="q-badge ok">실제 실행 · {by}</span>
          : <span className="q-badge">조회 전 · 코드 기준</span>)}
      </div>
      {it.error && <div className="alert error small">{it.error}</div>}

      {runs.map((r, i) => <RunCode key={i} r={r} n={runs.length > 1 ? i + 1 : undefined} onPlan={onPlan} title={itemName(it)} />)}
      {!runs.length && it.sqls.map((s, i) => <CodeBlock key={i} sql={s} n={it.sqls.length > 1 ? i + 1 : undefined} />)}
      {!runs.length && !it.sqls.length && !it.error && <div className="muted small">코드에서 SQL 문장을 찾지 못했습니다.</div>}

      {(older.length > 0 || (runs.length > 0 && it.sqls.length > 0)) && (
        <div className="q-more">
          {older.length > 0 && (
            <button className="btn-link small" onClick={() => setShowOlder((v) => !v)}>
              {showOlder ? <ChevronDown size={12} /> : <ChevronRight size={12} />} 이전 실행 {older.length}개
            </button>
          )}
          {runs.length > 0 && it.sqls.length > 0 && (
            <button className="btn-link small" onClick={() => setShowCode((v) => !v)}>
              {showCode ? <ChevronDown size={12} /> : <ChevronRight size={12} />} 코드 기준 SQL {it.sqls.length}개
            </button>
          )}
        </div>
      )}
      {showOlder && older.map((r, i) => <RunCode key={`o${i}`} r={r} onPlan={onPlan} title={itemName(it)} />)}
      {showCode && it.sqls.map((s, i) => <CodeBlock key={`c${i}`} sql={s} n={it.sqls.length > 1 ? i + 1 : undefined} />)}
    </div>
  )
}

/** 관리자 '사용 쿼리': 현재 메뉴에서 조회할 때 실제로 실행된 DB 쿼리(값 포함)를 기능별로 보고 복사 */
export default function QueryModal({ page, me, onClose }: { page: string; me: string; onClose: () => void }) {
  const [data, setData] = useState<PageQueries | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [q, setQ] = useState('')
  const [plan, setPlan] = useState<{ sql: string; filled?: string; title?: string } | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && !document.querySelector('.plan-modal') && closeRef.current()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [])

  const load = () => {
    setLoading(true)
    opsApi.queries(page).then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }
  useEffect(load, [page])   // eslint-disable-line react-hooks/exhaustive-deps

  const features = useMemo(() => {
    const k = q.trim().toLowerCase()
    const all = data?.features ?? []
    if (!k) return all
    return all.filter((f) => [f.title, f.desc, ...f.items.flatMap((it) => [itemName(it), ...it.sqls, ...(it.runs ?? []).map((r) => r.filled)])]
      .join(' ').toLowerCase().includes(k))
  }, [data, q])

  const jump = (i: number) => bodyRef.current?.querySelector(`[data-q="${i}"]`)?.scrollIntoView({ block: 'start', behavior: 'smooth' })

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal query-modal" role="dialog" aria-label="사용 쿼리"
        onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
        <div className="modal-head">
          <h3><Database size={17} /> 사용 쿼리{data?.label ? ` · ${data.label}` : ''}</h3>
          <div className="q-head-actions">
            <button className="icon-btn bordered" onClick={load} title="새로 고침 (화면에서 다시 조회한 뒤)"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
            <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
          </div>
        </div>
        <div className="muted small q-hint">
          화면에서 조회할 때 <b>실제로 실행된 DB 쿼리</b>를 값이 채워진 그대로 보여줍니다 (내가 가장 최근에 조회한 1회분).
          아직 조회하지 않은 기능은 <b>코드 기준</b> SQL(<code>:이름</code> 은 바인드 변수, <code>{'{ }'}</code> 는 조건에 따라 코드가 채우는 부분)이 보입니다.
          <span className="mono"> 서버 시작 {data?.since ?? '-'}</span>
        </div>
        <div className="search help-search">
          <Search size={16} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="기능 · 함수 · 테이블 · 값 검색 (예: 목록, T_SHOP, 202609)" autoFocus />
          {q && <button className="clear" onClick={() => setQ('')} title="지우기"><X size={14} /></button>}
        </div>
        {error && <div className="alert error">{error}</div>}
        {!data && !error && <div className="trend-loading"><Loader2 size={18} className="spin" /> 쿼리를 읽는 중…</div>}
        {data && (
          <div className="q-layout">
            <nav className="q-nav">
              {features.map((f, i) => (
                <button key={f.title} className={`q-nav-item ${ranCount(f) ? 'ran' : ''}`} onClick={() => jump(i)}
                  title={ranCount(f) ? '실제 실행된 쿼리가 있습니다' : '아직 조회 전 (코드 기준)'}>
                  <span>{f.title}</span><span className="small">{ranCount(f) ? `실행 ${ranCount(f)}` : '-'}</span>
                </button>
              ))}
            </nav>
            <div className="help-body q-body" ref={bodyRef}>
              {features.map((f, i) => (
                <section key={f.title} className="q-feature" data-q={i}>
                  <div className="q-feature-head">
                    <div>
                      <h4>{f.title}</h4>
                      {f.desc && <div className="muted small">{f.desc}</div>}
                    </div>
                    <div className="grow" />
                    <CopyBtn text={featureText(f)} label="기능 전체 복사" title="이 기능의 쿼리를 모두 주석과 함께 복사 (실제 실행 쿼리 우선)" />
                  </div>
                  {f.items.map((it) => <ItemBlock key={itemName(it)} it={it} me={me} onPlan={setPlan} />)}
                </section>
              ))}
              {!features.length && <div className="empty muted">{q ? '찾는 내용이 없습니다.' : '이 메뉴에 등록된 쿼리가 없습니다.'}</div>}
            </div>
          </div>
        )}
      </div>
      {plan && <PlanModal sql={plan.sql} filled={plan.filled} title={plan.title} onClose={() => setPlan(null)} />}
    </div>
  )
}
