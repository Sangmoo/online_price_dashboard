import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, Layers, Loader2, Pencil, Plus, RefreshCw, Trash2, UserPlus, X } from 'lucide-react'
import { api, type AdminUser } from '../../api'
import { opsApi, type Role, type RoleConf, type RolesData } from '../../opsApi'

type Notify = (text: string, error?: boolean) => void
const EMPTY: RoleConf = { pages: [], brands: null, aiEnabled: true, dailyQuestions: null, dailyCostUsd: null }

/** 권한 묶음 (역할 템플릿): 메뉴 · 브랜드 · AI 설정을 묶어 두고 사용자에게 한 번에 적용 */
export default function RolesTab({ notify }: { notify: Notify }) {
  const [data, setData] = useState<RolesData | null>(null)
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Role | 'new' | null>(null)
  const [applying, setApplying] = useState<Role | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    opsApi.roles().then(setData).catch((e) => notify(e.message, true)).finally(() => setLoading(false))
  }, [notify])
  useEffect(load, [load])

  const remove = async (r: Role) => {
    if (!confirm(`'${r.name}' 묶음을 삭제할까요? 이미 적용된 사용자 권한은 그대로 남습니다.`)) return
    try {
      await opsApi.deleteRole(r.id)
      notify('묶음을 삭제했습니다.')
      load()
    } catch (e) {
      notify((e as Error).message, true)
    }
  }

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 권한 묶음을 읽는 중…</div></section>
  const labelOf = (k: string) => data.pages.find((p) => p.key === k)?.label ?? k

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3><Layers size={16} /> 권한 묶음</h3>
        <span className="panel-hint">메뉴 · 브랜드 · AI 설정을 이름 붙여 묶어 두고 여러 사용자에게 한 번에 적용합니다. 관리자 권한(관리자/일반)은 바꾸지 않습니다.</span>
        <div className="grow" />
        <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        <button className="btn primary" disabled={!data.table.ready} onClick={() => setEditing('new')}><Plus size={15} /> 새 묶음</button>
      </div>
      {!data.table.ready && (
        <div className="notice-box warn"><AlertTriangle size={15} />
          <div>권한 묶음 테이블을 쓸 수 없습니다 ({data.table.missing.join(', ')}). <b>{data.table.ddl}</b> 를 SS10 스키마에서 실행하세요.</div>
        </div>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>묶음</th><th>메뉴</th><th>브랜드</th><th>AI</th><th className="num">적용 사용자</th><th>수정</th><th /></tr></thead>
          <tbody>
            {data.roles.map((r) => (
              <tr key={r.id}>
                <td><div className="strong">{r.name}</div>{r.description && <div className="muted small">{r.description}</div>}</td>
                <td className="small">{r.pageLabels.join(', ')}</td>
                <td className="small">{r.conf.brands?.length ? r.conf.brands.join(', ') : '모든 브랜드'}</td>
                <td className="small nowrap">{r.conf.aiEnabled ? `사용 · ${r.conf.dailyQuestions ?? '기본'}회 · $${r.conf.dailyCostUsd ?? '기본'}` : '사용 안 함'}</td>
                <td className="num" title={r.members.map((m) => m.name).join(', ')}>{r.members.length}명</td>
                <td className="muted small nowrap">{r.updatedBy} {r.updatedAt}</td>
                <td className="nowrap">
                  <button className="btn ghost sm" onClick={() => setApplying(r)}><UserPlus size={12} /> 사용자에게 적용</button>{' '}
                  <button className="btn ghost sm" onClick={() => setEditing(r)}><Pencil size={12} /> 수정</button>{' '}
                  <button className="btn ghost sm danger" onClick={() => remove(r)}><Trash2 size={12} /></button>
                </td>
              </tr>
            ))}
            {data.table.ready && !data.roles.length && <tr><td colSpan={7} className="empty">등록된 묶음이 없습니다. [새 묶음] 으로 예: '영업팀 기본', 'MD', '매장관리' 를 만들어 보세요.</td></tr>}
          </tbody>
        </table>
      </div>
      {editing && (
        <RoleEditor role={editing === 'new' ? null : editing} data={data} labelOf={labelOf}
          onClose={() => setEditing(null)}
          onSaved={(msg) => { setEditing(null); notify(msg); load() }} notify={notify} />
      )}
      {applying && <ApplyModal role={applying} onClose={() => setApplying(null)} onDone={(msg) => { setApplying(null); notify(msg); load() }} />}
    </section>
  )
}

function RoleEditor({ role, data, labelOf, onClose, onSaved, notify }: {
  role: Role | null; data: RolesData; labelOf: (k: string) => string; onClose: () => void; onSaved: (msg: string) => void; notify: Notify
}) {
  const [name, setName] = useState(role?.name ?? '')
  const [desc, setDesc] = useState(role?.description ?? '')
  const [conf, setConf] = useState<RoleConf>(role?.conf ?? EMPTY)
  const [reapply, setReapply] = useState(false)
  const [saving, setSaving] = useState(false)
  const toggle = (k: string) => setConf((c) => ({ ...c, pages: c.pages.includes(k) ? c.pages.filter((x) => x !== k) : [...c.pages, k] }))
  const toggleBrand = (b: string) => setConf((c) => {
    const cur = c.brands ?? []
    const next = cur.includes(b) ? cur.filter((x) => x !== b) : [...cur, b]
    return { ...c, brands: next.length ? next : [] }
  })
  const save = async () => {
    setSaving(true)
    try {
      const r = await opsApi.saveRole({ name, description: desc, conf, reapply }, role?.id)
      const re = r.reapplied
      onSaved(re ? `저장하고 ${re.applied.length}명에게 다시 반영했습니다.${re.skipped.length ? ` (${re.skipped.length}명 제외)` : ''}` : '묶음을 저장했습니다.')
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card role-editor">
        <div className="modal-head"><h3>{role ? '권한 묶음 수정' : '새 권한 묶음'}</h3><button className="icon-btn" onClick={onClose}><X size={18} /></button></div>
        <div className="role-form">
          <label className="field"><span className="field-label">이름</span>
            <input className="input" value={name} maxLength={30} onChange={(e) => setName(e.target.value)} placeholder="예: 영업팀 기본" autoFocus /></label>
          <label className="field"><span className="field-label">설명</span>
            <input className="input" value={desc} maxLength={150} onChange={(e) => setDesc(e.target.value)} placeholder="누구에게 주는 묶음인지" /></label>
          <div className="field full"><span className="field-label">메뉴 권한</span>
            <div className="chip-row">{data.pages.map((p) => (
              <button key={p.key} type="button" className={`chip ${conf.pages.includes(p.key) ? 'active' : ''}`} onClick={() => toggle(p.key)}>{labelOf(p.key)}</button>
            ))}</div>
          </div>
          <div className="field full"><span className="field-label">브랜드 권한 {!data.brandReady && <span className="field-hint err">브랜드 권한 테이블 없음</span>}</span>
            <div className="chip-row">
              <button type="button" className={`chip ${!conf.brands?.length ? 'active' : ''}`} onClick={() => setConf((c) => ({ ...c, brands: null }))}>모든 브랜드</button>
              {data.brandOptions.map((b) => (
                <button key={b} type="button" disabled={!data.brandReady} className={`chip ${conf.brands?.includes(b) ? 'active' : ''}`} onClick={() => toggleBrand(b)}>{b}</button>
              ))}
            </div>
          </div>
          <div className="field full role-ai"><span className="field-label">AI</span>
            <label className="check-label"><input type="checkbox" checked={conf.aiEnabled} onChange={(e) => setConf((c) => ({ ...c, aiEnabled: e.target.checked }))} /> AI 사용</label>
            <label className="check-label">일일 질문 <input className="input small num-input" type="number" min={0} max={1000} placeholder="기본" value={conf.dailyQuestions ?? ''}
              onChange={(e) => setConf((c) => ({ ...c, dailyQuestions: e.target.value === '' ? null : Number(e.target.value) }))} /> 회</label>
            <label className="check-label">일일 비용 $ <input className="input small num-input" type="number" min={0} max={1000} step={0.5} placeholder="기본" value={conf.dailyCostUsd ?? ''}
              onChange={(e) => setConf((c) => ({ ...c, dailyCostUsd: e.target.value === '' ? null : Number(e.target.value) }))} /></label>
          </div>
          {role && role.members.length > 0 && (
            <label className="check-label full"><input type="checkbox" checked={reapply} onChange={(e) => setReapply(e.target.checked)} />
              저장하면서 이 묶음을 적용한 사용자 {role.members.length}명에게도 다시 반영</label>
          )}
        </div>
        <div className="modal-foot"><div className="grow" />
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" disabled={saving || !name.trim() || !conf.pages.length} onClick={save}>{saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 저장</button>
        </div>
      </div>
    </div>
  )
}

function ApplyModal({ role, onClose, onDone }: { role: Role; onClose: () => void; onDone: (msg: string) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.admin.users().then((r) => setUsers(r.users.filter((u) => !u.superAdmin))).catch((e) => setErr(e.message))
  }, [])
  const members = new Set(role.members.map((m) => m.id))
  const shown = users.filter((u) => !q || u.name.includes(q) || u.id.includes(q))
  const flip = (id: string) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const apply = async () => {
    if (!confirm(`${sel.size}명의 메뉴 · 브랜드 · AI 설정을 '${role.name}' 묶음으로 바꿉니다. 진행할까요?`)) return
    setBusy(true)
    try {
      const r = await opsApi.applyRole(role.id, [...sel])
      onDone(`${r.applied.length}명에게 적용했습니다.${r.skipped.length ? ` 제외 ${r.skipped.length}명: ${r.skipped.map((x) => `${x.id}(${x.reason})`).join(', ')}` : ''}`)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card role-apply">
        <div className="modal-head"><h3>'{role.name}' 적용할 사용자</h3><button className="icon-btn" onClick={onClose}><X size={18} /></button></div>
        <input className="input" placeholder="이름 · ID 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="role-user-list">
          {shown.map((u) => (
            <label key={u.id} className={`role-user ${!u.active ? 'inactive' : ''}`}>
              <input type="checkbox" checked={sel.has(u.id)} onChange={() => flip(u.id)} />
              <b>{u.name}</b> <span className="muted mono small">{u.id}</span>
              {members.has(u.id) && <span className="chip small">적용됨</span>}
              {!u.active && <span className="muted small">사용 중지</span>}
            </label>
          ))}
        </div>
        {err && <div className="alert error">{err}</div>}
        <div className="modal-foot"><span className="muted small">{sel.size}명 선택</span><div className="grow" />
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" disabled={busy || !sel.size} onClick={apply}>{busy ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 적용</button>
        </div>
      </div>
    </div>
  )
}
