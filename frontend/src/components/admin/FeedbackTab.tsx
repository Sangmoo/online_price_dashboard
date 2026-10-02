import { useCallback, useEffect, useState } from 'react'
import { Loader2, RefreshCw, Save } from 'lucide-react'
import { fmtNum } from '../../format'
import { api, type Feedback, type FeedbackLeadStats, type FeedbackStatus } from '../../api'
import { FeedbackImages } from '../FeedbackModal'

type Notify = (text: string, error?: boolean) => void

/** 시간 → '3시간' / '2.5일' */
export const fmtHours = (h: number | null | undefined) =>
  h === null || h === undefined ? '-' : h < 24 ? `${h < 1 ? '1시간 미만' : `${Math.round(h)}시간`}` : `${(h / 24).toFixed(1)}일`
const STATUS: { key: FeedbackStatus; label: string }[] = [
  { key: 'NEW', label: '접수' },
  { key: 'DOING', label: '처리 중' },
  { key: 'DONE', label: '완료' },
]

/** 관리자 › 문의·신고: 사용자가 화면에서 남긴 오류·요청·문의와 그때의 화면·조회 조건·최근 오류. 상태와 답변을 남긴다. */
export default function FeedbackTab({ notify, onChange }: { notify: Notify; onChange?: () => void }) {
  const [filter, setFilter] = useState<FeedbackStatus | ''>('')
  const [data, setData] = useState<{ rows: Feedback[]; counts: Record<FeedbackStatus, number>; storage: string; images?: { count: number; bytes: number }; leadStats?: FeedbackLeadStats } | null>(null)
  const [keep, setKeep] = useState<number | null>(null)
  const [keepSaved, setKeepSaved] = useState<number | null>(null)
  useEffect(() => {
    api.admin
      .settings()
      .then((s) => {
        setKeep(s.feedbackImageKeepMonths ?? 12)
        setKeepSaved(s.feedbackImageKeepMonths ?? 12)
      })
      .catch(() => undefined)
  }, [])
  const saveKeep = async () => {
    if (keep === null) return
    try {
      const s = await api.admin.saveSettings({ feedbackImageKeepMonths: keep })
      setKeepSaved(s.feedbackImageKeepMonths ?? keep)
      notify('첨부 이미지 보관 기간을 저장했습니다.')
    } catch (e) {
      notify((e as Error).message, true)
    }
  }
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .feedback(filter || undefined)
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [filter, notify])
  useEffect(load, [load])

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 문의·신고를 읽는 중…</div></section>
  const total = Object.values(data.counts).reduce((s, n) => s + n, 0)

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>문의 · 오류 신고</h3>
        <span className="panel-hint">
          사용자가 화면 오른쪽 위 [문의·신고]로 남긴 내용 · 화면·조회 조건·최근 오류 자동 첨부 · 저장소 {data.storage === 'oracle' ? 'Oracle' : '서버 로컬(SQLite) — db/create_erp_web_feedback.sql 실행 시 Oracle 로 이전'}
        </span>
        <div className="grow" />
        <div className="seg">
          <button className={filter === '' ? 'on' : ''} onClick={() => setFilter('')}>전체 {total}</button>
          {STATUS.map((s) => (
            <button key={s.key} className={filter === s.key ? 'on' : ''} onClick={() => setFilter(s.key)}>{s.label} {data.counts[s.key] ?? 0}</button>
          ))}
        </div>
        <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
      </div>
      {data.leadStats && (
        <div className="summary-pills">
          <div className="pill" title="완료된 문의: 접수부터 마지막 완료까지"><span>평균 처리 시간</span><b>{fmtHours(data.leadStats.avgHours)}</b>
            <span className="muted">완료 {data.leadStats.doneCount}건</span></div>
          <div className="pill"><span>처리 시간 중앙값</span><b>{fmtHours(data.leadStats.medianHours)}</b></div>
          <div className={`pill ${data.leadStats.oldestOpenHours !== null && data.leadStats.oldestOpenHours >= 72 ? 'warn-pill' : ''}`}>
            <span>가장 오래 기다리는 문의</span><b>{fmtHours(data.leadStats.oldestOpenHours)}</b></div>
        </div>
      )}
      <div className="setting-row fb-keep">
        <div>
          <div className="strong">첨부 이미지 보관 기간</div>
          <div className="muted">
            완료된 문의는 이 기간이 지나면 이미지만 지웁니다 (글·답변은 남김, 0 = 계속 보관).
            {data.images && ` 지금 보관 중: 이미지 ${fmtNum(data.images.count)}개 · ${(data.images.bytes / 1024 / 1024).toFixed(1)}MB`}
          </div>
        </div>
        <div className="row">
          <input className="input small num-input" type="number" min={0} max={120} value={keep ?? ''} aria-label="이미지 보관 개월"
            onChange={(e) => setKeep(e.target.value === '' ? null : Math.max(0, Math.min(120, Number(e.target.value))))} />
          <span>개월</span>
          <button className="btn ghost small" disabled={keep === null || keep === keepSaved} onClick={saveKeep}><Save size={14} /> 저장</button>
        </div>
      </div>
      {data.rows.length === 0 ? (
        <div className="muted">해당하는 문의가 없습니다.</div>
      ) : (
        <div className="feedback-list admin">
          {data.rows.map((f) => <FeedbackRow key={f.id} f={f} notify={notify} onSaved={() => { load(); onChange?.() }} />)}
        </div>
      )}
    </section>
  )
}

function FeedbackRow({ f, notify, onSaved }: { f: Feedback; notify: Notify; onSaved: () => void }) {
  const [status, setStatus] = useState<FeedbackStatus>(f.status)
  const [answer, setAnswer] = useState(f.answer ?? '')
  const [saving, setSaving] = useState(false)
  const dirty = status !== f.status || answer !== (f.answer ?? '')
  const ctx = f.context as { conditions?: Record<string, string>; errors?: { at: string; kind: string; status?: number; url?: string; message: string }[]; screen?: string; browser?: string; url?: string }

  const save = async () => {
    setSaving(true)
    try {
      await api.admin.answerFeedback(f.id, { status, answer })
      notify('저장했습니다.')
      onSaved()
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="feedback-item feedback-admin-row">
      <div>
        <div className="meta">
          <span className={`fb-status ${f.status}`}>{f.statusLabel}</span>
          <span className="strong">{f.typeLabel}</span>
          <span>{f.userName ?? f.userId} <span className="mono">{f.userId}</span></span>
          <span>{f.createdAt}</span>
          {f.leadHours !== null && f.leadHours !== undefined && <span className="fb-lead">처리 {fmtHours(f.leadHours)}</span>}
          {f.ageHours !== null && f.ageHours !== undefined && <span className={`fb-lead ${f.ageHours >= 72 ? 'late' : ''}`}>대기 {fmtHours(f.ageHours)}</span>}
          <span>화면: {(f.context as { page?: string }).page ?? f.page ?? '-'}</span>
        </div>
        <div className="content">{f.content}</div>
        <FeedbackImages f={f} />
        <details className="feedback-ctx">
          <summary>
            조회 조건 {ctx.conditions ? Object.keys(ctx.conditions).length : 0}개 · 최근 오류 {ctx.errors?.length ?? 0}건
            {ctx.errors && ctx.errors.length > 0 && <> · 마지막: {ctx.errors[ctx.errors.length - 1].message.slice(0, 60)}</>}
          </summary>
          <pre>{JSON.stringify(f.context, null, 2)}</pre>
        </details>
        {f.answeredAt && <div className="muted small">답변 {f.answerBy} · {f.answeredAt}</div>}
        {f.history && f.history.length > 0 && (
          <details className="fb-history">
            <summary>처리 이력 {f.history.length}건</summary>
            <ol>
              <li><span className="muted">{f.createdAt}</span> 접수 · {f.userName ?? f.userId}</li>
              {f.history.map((h, i) => (
                <li key={i}>
                  <span className="muted">{h.at}</span> {h.by} ·{' '}
                  {h.from !== h.to ? <>{h.fromLabel} → <b>{h.toLabel}</b></> : <>{h.toLabel}</>}
                  {h.answered && ' · 답변 작성/수정'}
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
      <div className="answer-box">
        <select className="input select small" value={status} onChange={(e) => setStatus(e.target.value as FeedbackStatus)} aria-label="상태">
          {STATUS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <textarea className="input" rows={6} placeholder="답변 (사용자의 '내 문의'에 보입니다)" value={answer} onChange={(e) => setAnswer(e.target.value)} />
        <button className="btn primary small" disabled={!dirty || saving} onClick={save}>
          {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} 저장
        </button>
      </div>
    </div>
  )
}
