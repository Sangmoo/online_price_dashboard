import { useEffect, useRef, useState } from 'react'
import { GitBranch, Loader2, X } from 'lucide-react'
import { opsApi, type ExplainResult } from '../opsApi'
import { copyText } from '../copy'

/** 계획 줄 강조: 전체 스캔(FULL) · 카티전(MERGE JOIN CARTESIAN) 은 느릴 수 있는 지점 */
function PlanText({ text }: { text: string }) {
  return (
    <pre className="sql-code plan-code">
      {text.split('\n').map((ln, i) => (
        <span key={i} className={/TABLE ACCESS FULL|INDEX FULL SCAN|CARTESIAN/i.test(ln) ? 'plan-hot' : undefined}>{ln}{'\n'}</span>
      ))}
    </pre>
  )
}

/**
 * 실행 계획 (쿼리는 실행하지 않음).
 * - 실제 계획: 이 SQL 이 Oracle 커서 캐시(V$SQL)에 있으면 실제로 쓰인 계획과 실행 통계
 * - 예상 계획: EXPLAIN PLAN — 바인드 변수 그대로 / 값 채운 문장 중 골라 볼 수 있다
 */
export default function PlanModal({ sql, filled, title, onClose }: { sql: string; filled?: string; title?: string; onClose: () => void }) {
  const [mode, setMode] = useState<'raw' | 'filled'>('raw')
  const [res, setRes] = useState<ExplainResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const text = mode === 'filled' && filled ? filled : sql

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        closeRef.current()
      }
    }
    document.addEventListener('keydown', esc, true)   // 위에 뜬 팝업만 닫히게 (사용 쿼리 팝업 위에서 열 때)
    return () => document.removeEventListener('keydown', esc, true)
  }, [])

  useEffect(() => {
    let alive = true
    setRes(null)
    setError(null)
    opsApi.explain(text).then((r) => alive && setRes(r)).catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [text])

  const act = res?.actual && !('error' in res.actual && res.actual.error) ? res.actual as Exclude<ExplainResult['actual'], null | { error: string }> : null
  const actErr = res?.actual && 'error' in res.actual ? res.actual.error : null

  return (
    <div className="modal-backdrop top plan-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal plan-modal" role="dialog" aria-label="실행 계획">
        <div className="modal-head">
          <h3><GitBranch size={17} /> 실행 계획{title ? ` · ${title}` : ''}</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        <div className="plan-scroll">
          <div className="plan-bar">
            {filled && filled !== sql && (
              <div className="seg q-seg">
                <button className={mode === 'raw' ? 'on' : ''} onClick={() => setMode('raw')} title="앱이 보낸 문장 그대로 (바인드 변수)">바인드 그대로</button>
                <button className={mode === 'filled' ? 'on' : ''} onClick={() => setMode('filled')} title="바인드 변수를 실제 값으로 바꾼 문장">값 채운 쿼리</button>
              </div>
            )}
            <span className="muted small">쿼리는 실행하지 않고 계획만 봅니다. <b className="plan-hot-label">빨간 줄</b> = 전체 스캔 등 느릴 수 있는 지점</span>
            <div className="grow" />
            <button className="btn ghost sm" onClick={async () => { setCopied(await copyText(text)); setTimeout(() => setCopied(false), 1500) }}>
              {copied ? '복사됨' : 'SQL 복사'}
            </button>
          </div>
          <details className="plan-sql">
            <summary className="small muted">SQL 보기{res?.sqlId ? ` · SQL_ID ${res.sqlId}` : ''}</summary>
            <pre className="sql-code">{text}</pre>
          </details>
          {error && <div className="alert error">{error}</div>}
          {!res && !error && <div className="trend-loading"><Loader2 size={18} className="spin" /> 실행 계획을 읽는 중…</div>}
          {res && (
            <>
              <section className="plan-section">
                <h4>실제 실행 계획 <span className="muted small">(Oracle 커서 캐시 · 지금 쓰이고 있는 계획)</span></h4>
                {act ? (
                  <>
                    <div className="plan-stats">
                      <span>실행 <b>{act.executions.toLocaleString()}</b>회</span>
                      <span>평균 <b>{act.avgMs?.toLocaleString() ?? '-'}</b>ms</span>
                      <span>1회 평균 읽은 블록 <b>{act.bufferGets?.toLocaleString() ?? '-'}</b></span>
                      <span>디스크 읽기 <b>{act.diskReads?.toLocaleString() ?? '-'}</b></span>
                      <span>결과 행 <b>{act.rows?.toLocaleString() ?? '-'}</b></span>
                      <span className="muted">마지막 {act.lastActive ?? '-'}{act.children > 1 ? ` · 계획 ${act.children}개` : ''}</span>
                    </div>
                    <PlanText text={act.plan} />
                  </>
                ) : (
                  <div className="muted small">
                    {actErr ? `커서 캐시를 볼 수 없습니다: ${actErr}` : mode === 'filled'
                      ? '값 채운 쿼리는 앱이 실제로 보낸 문장이 아니라 커서 캐시에 없습니다 — 아래 예상 계획을 보세요.'
                      : '커서 캐시에 없습니다 (오래전에 실행됐거나 아직 실행 전). 화면에서 다시 조회한 뒤 열면 보입니다.'}
                  </div>
                )}
              </section>
              <section className="plan-section">
                <h4>예상 실행 계획 <span className="muted small">(EXPLAIN PLAN)</span></h4>
                {res.estimate.error ? <div className="alert error small">{res.estimate.error}</div> : <PlanText text={res.estimate.plan ?? ''} />}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
