import { Fragment, useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Database, RefreshCw, Search } from 'lucide-react'
import { apiFetch } from '../../api'

type Notify = (text: string, error?: boolean) => void
type AuditRow = {
  id: number
  ts: string
  adminId: string
  action: string
  actionLabel: string
  target: string | null
  summary: string | null
  before: unknown
  after: unknown
  ip: string | null
}
type AuditResp = { logs: AuditRow[]; actions: { key: string; label: string }[]; storage: 'oracle' | 'sqlite' }

const PERIODS = [
  { days: 7, label: '7일' },
  { days: 30, label: '30일' },
  { days: 90, label: '90일' },
  { days: 365, label: '1년' },
]

export default function AuditTab({ notify }: { notify: Notify }) {
  const [action, setAction] = useState('')
  const [q, setQ] = useState('')
  const [days, setDays] = useState(30)
  const [data, setData] = useState<AuditResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    const p = new URLSearchParams({ days: String(days) })
    if (action) p.set('action', action)
    if (q.trim()) p.set('q', q.trim())
    apiFetch(`/api/admin/audit?${p}`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [action, q, days, notify])

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>관리자 변경 이력</h3>
        <span className="panel-hint">사용자·메뉴 권한·AI 설정·AI 도구 변경, 잠금 해제, 강제 로그아웃 · 행을 누르면 변경 전/후</span>
        <div className="grow" />
        {data && (
          <span className={`storage-badge ${data.storage}`}>
            <Database size={13} /> {data.storage === 'oracle' ? 'Oracle' : '서버 로컬 (Oracle 테이블 생성 시 자동 이전)'}
          </span>
        )}
        <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
      </div>
      <div className="log-filters">
        <div className="chips wrap">
          <button className={`chip ${action === '' ? 'active' : ''}`} onClick={() => setAction('')}>전체</button>
          {(data?.actions ?? []).map((a) => (
            <button key={a.key} className={`chip ${action === a.key ? 'active' : ''}`} onClick={() => setAction(a.key)}>{a.label}</button>
          ))}
        </div>
        <div className="audit-right">
          <div className="seg">
            {PERIODS.map((p) => (
              <button key={p.days} className={days === p.days ? 'on' : ''} onClick={() => setDays(p.days)}>{p.label}</button>
            ))}
          </div>
          <div className="search compact">
            <Search size={15} />
            <input placeholder="관리자 · 대상 · 내용 검색" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
      </div>
      <div className="table-wrap tall-ish">
        <table className="table audit-table">
          <thead>
            <tr><th /><th>일시</th><th>관리자</th><th>작업</th><th>대상</th><th>변경 내용</th><th>IP</th></tr>
          </thead>
          <tbody>
            {(data?.logs ?? []).map((r) => {
              const expandable = r.before !== null || r.after !== null
              const isOpen = open === r.id
              return (
                <Fragment key={r.id}>
                  <tr className={expandable ? 'clickable' : ''} onClick={() => expandable && setOpen(isOpen ? null : r.id)}>
                    <td className="muted">{expandable ? isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} /> : null}</td>
                    <td className="mono muted nowrap">{r.ts}</td>
                    <td className="mono">{r.adminId}</td>
                    <td><span className={`audit-action a-${r.action.split('_')[0].toLowerCase()}`}>{r.actionLabel}</span></td>
                    <td className="mono">{r.target ?? '-'}</td>
                    <td className="audit-summary">{r.summary || '-'}</td>
                    <td className="mono muted">{r.ip ?? '-'}</td>
                  </tr>
                  {isOpen && (
                    <tr className="audit-detail">
                      <td />
                      <td colSpan={6}>
                        <div className="audit-json">
                          <div><div className="muted small">변경 전</div><pre>{r.before === null ? '(없음)' : JSON.stringify(r.before, null, 2)}</pre></div>
                          <div><div className="muted small">변경 후</div><pre>{r.after === null ? '(없음)' : JSON.stringify(r.after, null, 2)}</pre></div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {data && data.logs.length === 0 && <tr><td colSpan={7} className="empty">기간 안에 변경 이력이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}
