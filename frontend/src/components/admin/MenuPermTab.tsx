import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, Loader2, RotateCcw, Save, Search, ShieldCheck, X } from 'lucide-react'
import { api, type AdminUser, type PageKey, type PageMeta } from '../../api'

type Notify = (text: string, error?: boolean) => void

/** 메뉴를 그룹별로 묶는다 (순서 유지) */
function groupPages(pages: PageMeta[]) {
  const out: { group: string; pages: PageMeta[] }[] = []
  for (const p of pages) {
    const last = out[out.length - 1]
    if (last && last.group === p.group) last.pages.push(p)
    else out.push({ group: p.group, pages: [p] })
  }
  return out
}

const userPages = (u: AdminUser) => u.pages.filter((p) => p !== 'admin') as PageKey[]
const sameSet = (a: PageKey[], b: PageKey[]) => a.length === b.length && a.every((x) => b.includes(x))

// ----------------------------------------------------------------------------
// 메뉴 권한 일괄 관리 (사용자 × 메뉴)
// ----------------------------------------------------------------------------
export default function MenuPermTab({ notify }: { notify: Notify }) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [pages, setPages] = useState<PageMeta[]>([])
  const [q, setQ] = useState('')
  const [draft, setDraft] = useState<Record<string, PageKey[]>>({}) // 바꾼 사용자만
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .users()
      .then((r) => {
        setUsers(r.users)
        setPages(r.pages)
      })
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [notify])
  useEffect(load, [load])

  const groups = useMemo(() => groupPages(pages), [pages])
  const shown = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return kw ? users.filter((u) => u.id.includes(kw) || u.name.toLowerCase().includes(kw)) : users
  }, [users, q])

  const current = (u: AdminUser) => draft[u.id] ?? userPages(u)
  const setFor = (u: AdminUser, next: PageKey[]) =>
    setDraft((d) => {
      const copy = { ...d }
      if (sameSet(next, userPages(u))) delete copy[u.id]
      else copy[u.id] = next
      return copy
    })
  const toggle = (u: AdminUser, key: PageKey) => {
    const cur = current(u)
    setFor(u, cur.includes(key) ? cur.filter((x) => x !== key) : [...cur, key])
  }
  const editable = (u: AdminUser) => !u.superAdmin
  // 메뉴 열 전체: 보이는 사용자 모두에게 부여/회수
  const columnAll = (key: PageKey) => shown.filter(editable).every((u) => current(u).includes(key))
  const toggleColumn = (key: PageKey) => {
    const on = !columnAll(key)
    shown.filter(editable).forEach((u) => {
      const cur = current(u)
      setFor(u, on ? [...new Set([...cur, key])] : cur.filter((x) => x !== key))
    })
  }
  const rowAll = (u: AdminUser) => pages.every((p) => current(u).includes(p.key))

  const changed = Object.keys(draft).length
  const save = async () => {
    setSaving(true)
    try {
      const { users: updated } = await api.admin.savePermissions(Object.entries(draft).map(([id, pages]) => ({ id, pages })))
      setUsers((list) => list.map((u) => updated.find((x) => x.id === u.id) ?? u))
      setDraft({})
      notify(`${updated.length}명의 메뉴 권한을 저장했습니다.`)
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>메뉴 권한</h3>
        <span className="panel-hint">칸을 눌러 부여/회수 · 메뉴 이름을 누르면 보이는 사용자 전체에 적용 · [저장]을 눌러야 반영됩니다</span>
        <div className="grow" />
        <div className="search compact">
          <Search size={15} />
          <input placeholder="ID · 이름 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      <div className="table-wrap tall-ish">
        <table className="table perm-table">
          <thead>
            <tr>
              <th rowSpan={2}>사용자</th>
              {groups.map((g) => <th key={g.group} colSpan={g.pages.length} className="center group-th">{g.group}</th>)}
              <th rowSpan={2} className="center">관리자 메뉴</th>
            </tr>
            <tr>
              {pages.map((p) => (
                <th key={p.key} className="center">
                  <button className="perm-col-btn" onClick={() => toggleColumn(p.key)} title="보이는 사용자 전체에 부여/회수">
                    <input type="checkbox" readOnly checked={shown.some(editable) && columnAll(p.key)} tabIndex={-1} /> {p.label}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((u) => {
              const cur = current(u)
              const dirty = u.id in draft
              return (
                <tr key={u.id} className={`${dirty ? 'perm-dirty' : ''} ${!u.active ? 'inactive' : ''}`}>
                  <td>
                    <div className="perm-user">
                      <span className="strong">{u.name}</span> <span className="muted mono">{u.id}</span>
                      {u.superAdmin && <span className="me-tag">최고관리자</span>}
                      {editable(u) && (
                        <button className="btn-link small" onClick={() => setFor(u, rowAll(u) ? [] : pages.map((p) => p.key))}>
                          {rowAll(u) ? '모두 해제' : '모두 선택'}
                        </button>
                      )}
                    </div>
                  </td>
                  {pages.map((p) => (
                    <td key={p.key} className="center">
                      <input
                        type="checkbox"
                        checked={u.superAdmin || cur.includes(p.key)}
                        disabled={!editable(u)}
                        onChange={() => toggle(u, p.key)}
                        aria-label={`${u.name} ${p.label}`}
                      />
                    </td>
                  ))}
                  <td className="center">{u.role === 'ADMIN' ? <ShieldCheck size={15} className="perm-admin" /> : <span className="muted">-</span>}</td>
                </tr>
              )
            })}
            {!loading && shown.length === 0 && <tr><td colSpan={pages.length + 2} className="empty">사용자가 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="perm-bar">
        <span className="muted">관리자 메뉴는 권한(관리자/일반)으로 정해지며 [사용자 · 권한] 탭에서 바꿉니다. 최고 관리자는 항상 전체 메뉴입니다.</span>
        <div className="grow" />
        {changed > 0 && <span className="perm-count">{changed}명 변경됨</span>}
        <button className="btn ghost" disabled={!changed || saving} onClick={() => setDraft({})}><RotateCcw size={14} /> 되돌리기</button>
        <button className="btn primary" disabled={!changed || saving} onClick={save}>
          {saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} 저장
        </button>
      </div>
    </section>
  )
}

// ----------------------------------------------------------------------------
// 사용자 1명 메뉴 권한 팝업 ([사용자 · 권한] 탭에서 사용)
// ----------------------------------------------------------------------------
export function MenuPermModal({ user, pages, onClose, onSaved }: {
  user: AdminUser
  pages: PageMeta[]
  onClose: () => void
  onSaved: (u: AdminUser) => void
}) {
  const [sel, setSel] = useState<PageKey[]>(userPages(user))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const locked = user.superAdmin
  const flip = (k: PageKey) => setSel((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]))

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const { user: u } = await api.admin.saveUser(user.id, { pages: sel })
      onSaved(u)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card perm-modal">
        <div className="modal-head">
          <h3>메뉴 권한 · {user.name} <span className="muted mono">{user.id}</span></h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        {locked && <div className="alert">최고 관리자는 항상 모든 메뉴를 사용할 수 있습니다.</div>}
        {groupPages(pages).map((g) => (
          <div key={g.group} className="perm-group">
            <div className="perm-group-head">
              <span className="strong">{g.group}</span>
              {!locked && (
                <button
                  className="btn-link small"
                  onClick={() => {
                    const keys = g.pages.map((p) => p.key)
                    const all = keys.every((k) => sel.includes(k))
                    setSel((s) => (all ? s.filter((x) => !keys.includes(x)) : [...new Set([...s, ...keys])]))
                  }}
                >
                  {g.pages.every((p) => sel.includes(p.key)) ? '그룹 해제' : '그룹 전체'}
                </button>
              )}
            </div>
            {g.pages.map((p) => (
              <label key={p.key} className="perm-item">
                <input type="checkbox" checked={locked || sel.includes(p.key)} disabled={locked} onChange={() => flip(p.key)} />
                {p.label}
              </label>
            ))}
          </div>
        ))}
        <div className="perm-group">
          <label className="perm-item muted">
            <input type="checkbox" checked={user.role === 'ADMIN'} disabled /> 관리자 (권한이 '관리자'이면 자동)
          </label>
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="setting-actions">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" onClick={save} disabled={locked || saving}>
            {saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 저장
          </button>
        </div>
      </div>
    </div>
  )
}
