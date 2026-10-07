import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Copy, Database, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { opsApi, type PageQueries, type QueryFeature, type QueryItem } from '../opsApi'
import { copyText } from '../copy'

const withSemi = (sql: string) => (/;\s*$/.test(sql) || /^\s*(VARIABLE|EXEC|PRINT)\b/im.test(sql) ? sql : `${sql};`)
const itemName = (it: QueryItem) => it.title ?? it.fn ?? ''
const featureText = (f: QueryFeature) =>
  [`-- ${f.title}${f.desc ? ` : ${f.desc}` : ''}`, ...f.items.flatMap((it) =>
    it.sqls.map((s, i) => `-- ${itemName(it)}${it.file ? ` (${it.file}:${it.line})` : ''}${it.sqls.length > 1 ? ` #${i + 1}` : ''}\n${withSemi(s)}`))].join('\n\n')

/** 복사 버튼: 누르면 잠깐 '복사됨' */
function CopyBtn({ text, label = '복사', title }: { text: string; label?: string; title?: string }) {
  const [state, setState] = useState<'idle' | 'ok' | 'fail'>('idle')
  const timer = useRef<number>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <button className={`btn ghost sm copy-btn ${state}`} title={title ?? 'SQL 을 클립보드에 복사'}
      onClick={async () => {
        setState((await copyText(text)) ? 'ok' : 'fail')
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => setState('idle'), 1500)
      }}>
      {state === 'ok' ? <Check size={12} /> : <Copy size={12} />} {state === 'ok' ? '복사됨' : state === 'fail' ? '복사 실패' : label}
    </button>
  )
}

function ItemBlock({ it }: { it: QueryItem }) {
  const [tab, setTab] = useState<'code' | 'recent'>('code')
  const recent = it.recent ?? []
  return (
    <div className="q-item">
      <div className="q-item-head">
        <span className="mono strong">{itemName(it)}</span>
        {it.file && <span className="muted small mono">{it.file}:{it.line}</span>}
        <div className="grow" />
        {it.fn && (
          <div className="seg q-seg">
            <button className={tab === 'code' ? 'on' : ''} onClick={() => setTab('code')}>코드 기준 {it.sqls.length}</button>
            <button className={tab === 'recent' ? 'on' : ''} onClick={() => setTab('recent')} disabled={!recent.length}
              title={recent.length ? '이 서버에서 실제로 실행된 SQL 과 바인드 값' : '서버 시작 후 아직 실행되지 않았습니다'}>
              최근 실행 {recent.length}
            </button>
          </div>
        )}
      </div>
      {it.error && <div className="alert error small">{it.error}</div>}
      {tab === 'code' && it.sqls.map((s, i) => (
        <div key={i} className="q-code">
          <div className="q-code-bar float">
            {it.sqls.length > 1 && <span className="muted small">#{i + 1}</span>}
            <CopyBtn text={withSemi(s)} />
          </div>
          <pre className="sql-code">{s}</pre>
        </div>
      ))}
      {tab === 'code' && !it.sqls.length && !it.error && <div className="muted small">코드에서 SQL 문장을 찾지 못했습니다.</div>}
      {tab === 'recent' && recent.map((r, i) => (
        <div key={i} className="q-code">
          <div className="q-code-bar">
            <span className="muted small mono">{r.at} · {r.ms.toLocaleString()}ms · {r.count.toLocaleString()}회</span>
            <div className="grow" />
            <CopyBtn text={withSemi(r.sql)} label="SQL 복사" />
            <CopyBtn text={withSemi(r.filled)} label="값 채워 복사" title="바인드 변수(:이름)를 실제 값으로 바꿔 복사 — SQL 도구에 바로 실행" />
          </div>
          <pre className="sql-code">{r.sql}</pre>
          {Object.keys(r.binds).length > 0 && (
            <div className="q-binds small">
              {Object.entries(r.binds).map(([k, v]) => (
                <span key={k} className="q-bind"><span className="mono muted">:{k}</span> <span className="mono">{v === null ? 'NULL' : String(v)}</span></span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/** 관리자 '사용 쿼리': 현재 메뉴가 기능별로 쓰는 SQL 과 복사 */
export default function QueryModal({ page, onClose }: { page: string; onClose: () => void }) {
  const [data, setData] = useState<PageQueries | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [q, setQ] = useState('')
  const bodyRef = useRef<HTMLDivElement>(null)

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
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
    return all.filter((f) => [f.title, f.desc, ...f.items.flatMap((it) => [itemName(it), ...it.sqls])].join(' ').toLowerCase().includes(k))
  }, [data, q])

  const jump = (i: number) => bodyRef.current?.querySelector(`[data-q="${i}"]`)?.scrollIntoView({ block: 'start', behavior: 'smooth' })

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal query-modal" role="dialog" aria-label="사용 쿼리"
        onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
        <div className="modal-head">
          <h3><Database size={17} /> 사용 쿼리{data?.label ? ` · ${data.label}` : ''}</h3>
          <div className="q-head-actions">
            <button className="icon-btn bordered" onClick={load} title="최근 실행 SQL 새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
            <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
          </div>
        </div>
        <div className="muted small q-hint">
          <b>코드 기준</b>: 소스에서 뽑은 SQL — <code>{'{ }'}</code> 는 조회 조건에 따라 코드가 채우는 부분, <code>:이름</code> 은 바인드 변수.{' '}
          <b>최근 실행</b>: 서버 시작({data?.since ?? '-'}) 이후 실제로 실행된 SQL 과 값 (기능별 최근 5개).
        </div>
        <div className="search help-search">
          <Search size={16} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="기능 · 함수 · 테이블 검색 (예: 목록, T_SHOP, MERGE)" autoFocus />
          {q && <button className="clear" onClick={() => setQ('')} title="지우기"><X size={14} /></button>}
        </div>
        {error && <div className="alert error">{error}</div>}
        {!data && !error && <div className="trend-loading"><Loader2 size={18} className="spin" /> 쿼리를 읽는 중…</div>}
        {data && (
          <div className="q-layout">
            <nav className="q-nav">
              {features.map((f, i) => (
                <button key={f.title} className="q-nav-item" onClick={() => jump(i)}>
                  <span>{f.title}</span><span className="muted small">{f.items.reduce((n, it) => n + it.sqls.length, 0)}</span>
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
                    <CopyBtn text={featureText(f)} label="기능 전체 복사" title="이 기능의 SQL 을 모두 주석과 함께 복사" />
                  </div>
                  {f.items.map((it) => <ItemBlock key={itemName(it)} it={it} />)}
                </section>
              ))}
              {!features.length && <div className="empty muted">{q ? '찾는 내용이 없습니다.' : '이 메뉴에 등록된 쿼리가 없습니다.'}</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
