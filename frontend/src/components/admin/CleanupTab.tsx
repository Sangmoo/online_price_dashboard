import { useCallback, useEffect, useState } from 'react'
import { Check, Loader2, RefreshCw, UserX } from 'lucide-react'
import { opsApi, type CleanupData } from '../../opsApi'

type Notify = (text: string, error?: boolean) => void

/** 계정 정리: 오래 로그인하지 않은 계정 · 쓰지 않는 메뉴 권한을 관리자가 확인하고 골라서 정리 (자동으로 바꾸지 않음) */
export default function CleanupTab({ notify }: { notify: Notify }) {
  const [days, setDays] = useState(90)
  const [data, setData] = useState<CleanupData | null>(null)
  const [loading, setLoading] = useState(false)
  const [deact, setDeact] = useState<Set<string>>(new Set())
  const [revoke, setRevoke] = useState<Record<string, Set<string>>>({})
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    opsApi.cleanup(days).then((d) => { setData(d); setDeact(new Set()); setRevoke({}) }).catch((e) => notify(e.message, true)).finally(() => setLoading(false))
  }, [days, notify])
  useEffect(load, [load])

  const flipUser = (id: string) => setDeact((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const flipPage = (id: string, p: string) => setRevoke((r) => {
    const cur = new Set(r[id] ?? [])
    if (cur.has(p)) cur.delete(p); else cur.add(p)
    return { ...r, [id]: cur }
  })
  const revokeList = Object.entries(revoke).filter(([, s]) => s.size).map(([id, s]) => ({ id, pages: [...s] }))
  const count = deact.size + revokeList.reduce((n, r) => n + r.pages.length, 0)

  const apply = async () => {
    if (!confirm(`계정 ${deact.size}개 사용 중지, 메뉴 권한 ${count - deact.size}건 회수합니다. 변경 이력에 남습니다. 진행할까요?`)) return
    setBusy(true)
    try {
      const r = await opsApi.applyCleanup({ deactivate: [...deact], revoke: revokeList })
      notify(`사용 중지 ${r.deactivated.length}명 · 권한 회수 ${r.revoked.length}명${r.skipped.length ? ` · 제외 ${r.skipped.length}` : ''}`)
      load()
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 정리 후보를 찾는 중…</div></section>
  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3><UserX size={16} /> 계정 · 권한 정리</h3>
          <span className="panel-hint">자동으로 바꾸지 않습니다. 확인 후 고른 것만 정리하며, 최고 관리자와 본인은 제외됩니다. 사용 중지는 [사용자 · 권한] 탭에서 다시 켤 수 있습니다.</span>
          <div className="grow" />
          <div className="seg">{data.periods.map((p) => <button key={p} className={days === p ? 'on' : ''} onClick={() => setDays(p)}>{p}일</button>)}</div>
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
          <button className="btn primary" disabled={!count || busy} onClick={apply}>{busy ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 고른 {count}건 정리</button>
        </div>

        <h4 className="cleanup-h">{data.days}일 넘게 로그인하지 않은 계정 ({data.idle.length})</h4>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>사용 중지</th><th>사용자</th><th>마지막 로그인</th><th>메뉴 권한</th></tr></thead>
            <tbody>
              {data.idle.map((u) => (
                <tr key={u.id} className={deact.has(u.id) ? 'row-picked' : ''}>
                  <td><input type="checkbox" aria-label={`${u.name} 사용 중지`} checked={deact.has(u.id)} onChange={() => flipUser(u.id)} /></td>
                  <td><b>{u.name}</b> <span className="muted mono small">{u.id}</span>{u.role === 'ADMIN' && <span className="role-badge admin">관리자</span>}</td>
                  <td className="nowrap">{u.lastLoginAt ?? <span className="warn-text">로그인 기록 없음</span>}{u.idleDays != null && <span className="muted small"> ({u.idleDays}일 전)</span>}</td>
                  <td className="small">{u.pages.join(', ')}</td>
                </tr>
              ))}
              {!data.idle.length && <tr><td colSpan={4} className="empty">해당 계정이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>

        <h4 className="cleanup-h">{data.days}일 동안 한 번도 열지 않은 메뉴 권한 ({data.unused.length}명)</h4>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>사용자</th><th>회수할 메뉴 (고른 것만)</th><th>유지되는 메뉴</th><th>마지막 로그인</th></tr></thead>
            <tbody>
              {data.unused.map((u) => (
                <tr key={u.id}>
                  <td><b>{u.name}</b> <span className="muted mono small">{u.id}</span></td>
                  <td className="chip-row">
                    {u.pages.map((p) => (
                      <label key={p.key} className={`chip ${revoke[u.id]?.has(p.key) ? 'active' : ''}`}>
                        <input type="checkbox" hidden checked={!!revoke[u.id]?.has(p.key)} onChange={() => flipPage(u.id, p.key)} /> {p.label}
                      </label>
                    ))}
                  </td>
                  <td className="small muted">{u.keep.join(', ') || '없음'}</td>
                  <td className="nowrap muted small">{u.lastLoginAt ?? '-'}</td>
                </tr>
              ))}
              {!data.unused.length && <tr><td colSpan={4} className="empty">해당 권한이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
