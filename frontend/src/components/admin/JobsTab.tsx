import { Fragment, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Loader2, RefreshCw } from 'lucide-react'
import { opsApi, type JobInfo, type JobRun, type JobStatus, type JobsOverview } from '../../opsApi'

type Notify = (text: string, error?: boolean) => void
const PERIODS = [7, 14, 30]
const STATUS: Record<JobStatus, { label: string; tone: string }> = {
  ok: { label: '정상', tone: 'ok' },
  error: { label: '실패', tone: 'bad' },
  overdue: { label: '실행 안 됨', tone: 'bad' },
  missing: { label: '스케줄 없음', tone: 'bad' },
  disabled: { label: '꺼짐', tone: 'warn' },
  never: { label: '기록 없음', tone: 'off' },
  unknown: { label: '확인 불가', tone: 'off' },
}
const dur = (sec: number | null | undefined) =>
  sec == null ? '' : sec < 60 ? `${sec}초` : sec < 3600 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${Math.floor(sec / 3600)}시간 ${Math.floor((sec % 3600) / 60)}분`

/** 스케줄 · 배치: DB 스케줄(DBMS_SCHEDULER)과 이 서버의 자동 작업 — 마지막 실행 · 성공/실패 · 처리 결과 · 다음 실행 */
export default function JobsTab({ notify }: { notify: Notify }) {
  const [days, setDays] = useState(14)
  const [data, setData] = useState<JobsOverview | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback((fresh = false) => {
    setLoading(true)
    opsApi
      .jobs(days, fresh)
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [days, notify])
  useEffect(() => load(), [load])

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 실행 기록을 읽는 중…</div></section>
  const toggle = (k: string) => setOpen((o) => (o === k ? null : k))

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>DB 스케줄</h3>
          <span className="panel-hint">Oracle DBMS_SCHEDULER (SS10) · 최근 {data.days}일 실행 이력 · 결과 확인은 작업이 만든 데이터를 직접 셉니다</span>
          <div className="grow" />
          <div className="seg">
            {PERIODS.map((p) => <button key={p} className={days === p ? 'on' : ''} onClick={() => setDays(p)}>{p}일</button>)}
          </div>
          <button className="icon-btn bordered" onClick={() => load(true)} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
        {!data.db.ready && (
          <div className="notice-box warn">
            <AlertTriangle size={15} />
            <div>DB 스케줄 상태를 읽을 수 없습니다: {data.db.error}</div>
          </div>
        )}
        <JobTable jobs={data.db.jobs} open={open} onToggle={toggle} db />
      </section>

      <section className="card panel">
        <div className="panel-head row">
          <h3>서버 자동 작업</h3>
          <span className="panel-hint">이 서버가 실행하는 작업 · 실행할 때마다 기록 (T_ERP_WEB_JOB_RUN, 90일 보관)</span>
        </div>
        {!data.appTable.ready && (
          <div className="notice-box warn">
            <AlertTriangle size={15} />
            <div>실행 기록 테이블이 없어 기록하지 않고 있습니다 ({data.appTable.missing.join(', ')}). <b>{data.appTable.ddl}</b> 를 SS10 스키마에서 실행하세요.</div>
          </div>
        )}
        <JobTable jobs={data.app} open={open} onToggle={toggle} />
      </section>
    </div>
  )
}

function JobTable({ jobs, open, onToggle, db }: { jobs: JobInfo[]; open: string | null; onToggle: (k: string) => void; db?: boolean }) {
  const cols = db ? 7 : 6
  return (
    <div className="table-wrap">
      <table className="table jobs-table">
        <thead>
          <tr>
            <th>상태</th><th>작업</th><th>마지막 실행</th><th>결과</th>
            {db ? <><th>다음 실행</th><th className="num">기간 내 실패</th></> : <th className="num">기간 내 실행 · 실패</th>}
            <th />
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => {
            const st = STATUS[j.status] ?? STATUS.unknown
            const warn = j.result?.warn
            return (
              <Fragment key={j.key}>
                <tr className="clickable" onClick={() => onToggle(j.key)}>
                  <td><span className={`job-status tone-${warn && st.tone === 'ok' ? 'warn' : st.tone}`}>{warn && st.tone === 'ok' ? '확인 필요' : st.label}</span></td>
                  <td>
                    <div className="strong">{j.label}</div>
                    <div className="muted small">{j.schedule}{db && <span className="mono"> · {j.key}</span>}</div>
                  </td>
                  <td className="nowrap">
                    {j.last ? <>{j.last.start ?? j.last.end}<div className="muted small">{dur(j.last.sec)}{j.last.by ? ` · ${j.last.by}` : ''}</div></> : <span className="muted">-</span>}
                  </td>
                  <td className="job-result">
                    {j.result && <div className={warn ? 'warn-text strong' : ''}>{j.result.label}</div>}
                    {j.last?.status === 'error' && <div className="bad-text small" title={j.last.detail ?? ''}>{j.last.detail ?? '실패'}</div>}
                    {!db && j.last?.status === 'ok' && j.last.detail && <div className="small">{j.last.detail}</div>}
                    {db && j.status === 'missing' && <div className="small">스케줄이 없습니다 · {j.sql} 실행 필요</div>}
                    {db && j.status === 'overdue' && <div className="small bad-text">다음 실행 시각({j.nextRun})이 지났는데 실행되지 않았습니다</div>}
                  </td>
                  {db ? (
                    <>
                      <td className="nowrap">{j.nextRun ?? '-'}{j.enabled === false && <div className="muted small">꺼짐</div>}</td>
                      <td className={`num ${j.failures ? 'bad-text strong' : ''}`}>{j.failures}</td>
                    </>
                  ) : (
                    <td className={`num ${j.failures ? 'bad-text strong' : ''}`}>{j.count ?? 0} · {j.failures}</td>
                  )}
                  <td>{open === j.key ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                </tr>
                {open === j.key && (
                  <tr className="job-runs-row">
                    <td colSpan={cols}>
                      {j.runs.length ? (
                        <table className="table job-runs">
                          <thead><tr><th>시작</th><th>끝</th><th>걸린 시간</th><th>상태</th><th>내용</th></tr></thead>
                          <tbody>
                            {j.runs.map((r: JobRun, i) => (
                              <tr key={i}>
                                <td className="nowrap mono">{r.start ?? '-'}</td>
                                <td className="nowrap mono">{r.end ?? '-'}</td>
                                <td className="nowrap">{dur(r.sec)}</td>
                                <td><span className={`job-status tone-${r.status === 'ok' ? 'ok' : 'bad'}`}>{r.status === 'ok' ? '성공' : r.rawStatus ?? '실패'}</span></td>
                                <td className="small">{r.detail ?? ''}{r.by ? <span className="muted"> · {r.by}</span> : ''}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : <div className="muted small">기간 내 실행 기록이 없습니다.</div>}
                      {db && j.repeat && <div className="muted small mono">반복: {j.repeat}{j.runCount != null ? ` · 누적 실행 ${j.runCount}회 · 누적 실패 ${j.failureCount}회` : ''}</div>}
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
