import { useCallback, useEffect, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  Activity,
  Archive,
  BarChart3,
  History,
  Bot,
  Check,
  KeyRound,
  LayoutGrid,
  Loader2,
  LogOut,
  MessageSquareWarning,
  MonitorSmartphone,
  RefreshCw,
  ScrollText,
  Server,
  Wrench,
  Search,
  ShieldCheck,
  Tags,
  Unlock,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import {
  api,
  type AdminSettings,
  type AdminUsage,
  type AdminUser,
  type AdminUserUpdate,
  type LockInfo,
  type LoginLog,
  type PageKey,
  type PageMeta,
  type ServerLog,
  type SessionInfo,
  type User,
} from '../api'
import { fmtNum } from '../format'
import AiToolsTab from './admin/AiToolsTab'
import AuditTab from './admin/AuditTab'
import MenuPermTab, { MenuPermModal } from './admin/MenuPermTab'
import ServerStatusTab from './admin/ServerStatusTab'
import MenuUsageTab from './admin/MenuUsageTab'
import BackupTab from './admin/BackupTab'
import FeedbackTab from './admin/FeedbackTab'
import AiToolStatsCard from './admin/AiToolStatsCard'

export type Tab = 'users' | 'menus' | 'ai' | 'aitools' | 'usage' | 'menuusage' | 'feedback' | 'logins' | 'sessions' | 'audit' | 'backup' | 'status' | 'serverlogs'

const TABS: { key: Tab; label: string; icon: typeof Users }[] = [
  { key: 'users', label: '사용자 · 권한', icon: Users },
  { key: 'menus', label: '메뉴 권한', icon: LayoutGrid },
  { key: 'ai', label: 'AI 사용 설정', icon: Bot },
  { key: 'aitools', label: 'AI 도구', icon: Wrench },
  { key: 'usage', label: 'AI 사용 현황', icon: Activity },
  { key: 'menuusage', label: '메뉴 이용', icon: BarChart3 },
  { key: 'feedback', label: '문의·신고', icon: MessageSquareWarning },
  { key: 'logins', label: '로그인 · 잠금', icon: KeyRound },
  { key: 'sessions', label: '접속 세션', icon: MonitorSmartphone },
  { key: 'audit', label: '변경 이력', icon: History },
  { key: 'backup', label: '설정 백업', icon: Archive },
  { key: 'status', label: '서버 상태', icon: Server },
  { key: 'serverlogs', label: '서버 로그', icon: ScrollText },
]

export default function AdminView({ me, initialTab, feedbackOpen = 0, onFeedbackChange }: {
  me: User
  initialTab?: Tab
  feedbackOpen?: number
  onFeedbackChange?: () => void
}) {
  const [tab, setTab] = useState<Tab>(initialTab ?? 'users')
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null)

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error })
    setTimeout(() => setToast(null), 2200)
  }, [])

  return (
    <div className="stack">
      <div className="admin-tabs card">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} className={`admin-tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
            <Icon size={16} /> {label}
            {key === 'feedback' && feedbackOpen > 0 && <span className="count-badge danger">{feedbackOpen}</span>}
          </button>
        ))}
      </div>
      {tab === 'users' && <UsersTab me={me} notify={notify} />}
      {tab === 'menus' && <MenuPermTab notify={notify} />}
      {tab === 'ai' && <AiTab notify={notify} />}
      {tab === 'aitools' && <AiToolsTab notify={notify} />}
      {tab === 'usage' && <UsageTab />}
      {tab === 'menuusage' && <MenuUsageTab notify={notify} />}
      {tab === 'feedback' && <FeedbackTab notify={notify} onChange={onFeedbackChange} />}
      {tab === 'logins' && <LoginsTab notify={notify} />}
      {tab === 'sessions' && <SessionsTab notify={notify} />}
      {tab === 'audit' && <AuditTab notify={notify} />}
      {tab === 'backup' && <BackupTab notify={notify} />}
      {tab === 'status' && <ServerStatusTab notify={notify} />}
      {tab === 'serverlogs' && <ServerLogsTab notify={notify} />}
      {toast && <div className={`toast ${toast.error ? 'error' : ''}`}>{toast.error ? <X size={15} /> : <Check size={15} />} {toast.text}</div>}
    </div>
  )
}

type Notify = (text: string, error?: boolean) => void

// ----------------------------------------------------------------------------
// 사용자 · 권한
// ----------------------------------------------------------------------------
function UsersTab({ me, notify }: { me: User; notify: Notify }) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [pages, setPages] = useState<PageMeta[]>([])
  const [brandInfo, setBrandInfo] = useState<{ options: string[]; ready: boolean }>({ options: [], ready: false })
  const [brandFor, setBrandFor] = useState<AdminUser | null>(null)
  const [permFor, setPermFor] = useState<AdminUser | null>(null)
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .users(q || undefined)
      .then((r) => {
        setUsers(r.users)
        setPages(r.pages)
        setBrandInfo({ options: r.brandOptions, ready: r.brandReady })
      })
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [q, notify])

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  const save = async (u: AdminUser, body: Partial<AdminUserUpdate>) => {
    setSaving(u.id)
    try {
      const { user } = await api.admin.saveUser(u.id, body)
      setUsers((list) => list.map((x) => (x.id === u.id ? user : x)))
      notify(`${user.name} 설정을 저장했습니다.`)
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(null)
    }
  }

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>사용자 · 권한 관리</h3>
        <span className="panel-hint">등록된 사용자만 로그인할 수 있습니다 · 신규 사용자는 '사용자 추가'로 등록</span>
        <div className="grow" />
        <div className="search compact">
          <Search size={15} />
          <input placeholder="ID · 이름 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className="btn primary" onClick={() => setAdding(true)}>
          <UserPlus size={15} /> 사용자 추가
        </button>
      </div>

      <div className="table-wrap">
        <table className="table admin-table">
          <thead>
            <tr>
              <th>사용자</th>
              <th>권한</th>
              <th>페이지 권한</th>
              <th>브랜드 권한</th>
              <th>AI 사용</th>
              <th className="num">일일 질문 한도</th>
              <th className="num">일일 비용 한도($)</th>
              <th className="num">오늘 사용</th>
              <th>계정</th>
              <th>최근 로그인</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const locked = u.superAdmin
              return (
                <tr key={u.id} className={!u.active ? 'inactive' : ''}>
                  <td>
                    <div className="user-cell">
                      <div className={`avatar sm ${u.role === 'ADMIN' ? 'admin' : ''}`}>{u.name.slice(0, 1)}</div>
                      <div>
                        <div className="strong">
                          {u.name} {u.online && <span className="online-dot" title="접속 중" />}
                          {u.id === me.id && <span className="me-tag">나</span>}
                        </div>
                        <div className="muted mono">{u.id}{u.superAdmin && ' · 최고관리자'}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <select
                      className="input select small role-select"
                      value={u.role}
                      disabled={locked || saving === u.id}
                      onChange={(e) => save(u, { role: e.target.value as 'ADMIN' | 'USER' })}
                    >
                      <option value="USER">일반</option>
                      <option value="ADMIN">관리자</option>
                    </select>
                  </td>
                  <td>
                    <div className="perm-summary">
                      <span className="muted small" title={pages.filter((p) => u.pages.includes(p.key)).map((p) => p.label).join(', ')}>
                        {u.superAdmin ? '전체 메뉴' : `${pages.filter((p) => u.pages.includes(p.key)).length} / ${pages.length}개`}
                        {u.role === 'ADMIN' && ' + 관리자'}
                      </span>
                      <button className="btn ghost sm" disabled={saving === u.id} onClick={() => setPermFor(u)}>
                        <ShieldCheck size={12} /> 설정
                      </button>
                    </div>
                  </td>
                  <td>
                    <div className="perm-summary">
                      <span className={`small ${u.brands ? 'strong' : 'muted'}`}>{u.brands ? u.brands.join(', ') : '모든 브랜드'}</span>
                      {!u.superAdmin && (
                        <button className="btn ghost sm" disabled={saving === u.id} onClick={() => setBrandFor(u)}>
                          <Tags size={12} /> 설정
                        </button>
                      )}
                    </div>
                  </td>
                  <td>
                    <Toggle on={u.rawAiEnabled} disabled={saving === u.id} onChange={(v) => save(u, { aiEnabled: v })} />
                  </td>
                  <td className="num">
                    <LimitInput value={u.rawDailyQuestions} placeholder={`기본 ${u.ai.dailyQuestions}`} step={1} onSave={(v) => save(u, { dailyQuestions: v === null ? null : Math.round(v) })} />
                  </td>
                  <td className="num">
                    <LimitInput value={u.rawDailyCostUsd} placeholder={`기본 ${u.ai.dailyCostUsd.toFixed(2)}`} step={0.5} onSave={(v) => save(u, { dailyCostUsd: v })} />
                  </td>
                  <td className="num">
                    <div className="usage-cell">
                      <span>{u.todayQuestions}/{u.ai.dailyQuestions}회</span>
                      <span className="muted">${u.todayCostUsd.toFixed(2)}</span>
                    </div>
                  </td>
                  <td>
                    <Toggle on={u.active} disabled={locked || saving === u.id} onChange={(v) => save(u, { active: v })} labels={['사용', '중지']} />
                  </td>
                  <td className="muted">{u.lastLoginAt ?? '-'}</td>
                </tr>
              )
            })}
            {!loading && users.length === 0 && (
              <tr>
                <td colSpan={10} className="empty">등록된 사용자가 없습니다.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {permFor && (
        <MenuPermModal
          user={permFor}
          pages={pages}
          onClose={() => setPermFor(null)}
          onSaved={(user) => {
            setUsers((list) => list.map((x) => (x.id === user.id ? user : x)))
            setPermFor(null)
            notify(`${user.name} 메뉴 권한을 저장했습니다.`)
          }}
        />
      )}
      {brandFor && (
        <BrandModal
          user={brandFor}
          info={brandInfo}
          onClose={() => setBrandFor(null)}
          onSave={async (brands) => {
            await save(brandFor, { brands })
            setBrandFor(null)
          }}
        />
      )}
      {adding && (
        <AddUserModal
          pages={pages}
          brandInfo={brandInfo}
          onClose={() => setAdding(false)}
          onAdded={(name) => {
            notify(`${name} 사용자를 등록했습니다.`)
            setAdding(false)
            load()
          }}
          notify={notify}
        />
      )}
    </section>
  )
}

function Toggle({ on, onChange, disabled, labels }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; labels?: [string, string] }) {
  return (
    <button className={`toggle ${on ? 'on' : ''}`} disabled={disabled} onClick={() => onChange(!on)} role="switch" aria-checked={on}>
      <span className="knob" />
      {labels && <span className="toggle-label">{on ? labels[0] : labels[1]}</span>}
    </button>
  )
}

function LimitInput({ value, placeholder, step, onSave }: { value: number | null; placeholder: string; step: number; onSave: (v: number | null) => void }) {
  const [text, setText] = useState(value?.toString() ?? '')
  useEffect(() => setText(value?.toString() ?? ''), [value])
  const commit = () => {
    const t = text.trim()
    const next = t === '' ? null : Number(t)
    if (next !== null && (isNaN(next) || next < 0)) {
      setText(value?.toString() ?? '')
      return
    }
    if (next !== value) onSave(next)
  }
  return (
    <input
      className="input limit-input"
      type="number"
      min={0}
      step={step}
      value={text}
      placeholder={placeholder}
      title="비우면 기본값 적용"
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    />
  )
}

/** 브랜드 권한 선택: null = 모든 브랜드, 목록 = 그 브랜드만, undefined = 아직 고르지 않음 */
function BrandPicker({ options, value, onChange, ready }: {
  options: string[]
  value: string[] | null | undefined
  onChange: (v: string[] | null) => void
  ready: boolean
}) {
  const sel = value ?? []
  return (
    <div className="brand-picker">
      <div className="page-chips">
        <button className={`page-chip ${value === null ? 'on' : ''}`} onClick={() => onChange(null)}>
          {value === null && <Check size={11} />} 모든 브랜드
        </button>
        {options.map((b) => {
          const on = !!value && sel.includes(b)
          return (
            <button
              key={b}
              className={`page-chip ${on ? 'on' : ''}`}
              disabled={!ready}
              onClick={() => {
                const next = on ? sel.filter((x) => x !== b) : [...sel, b]
                onChange(next.length ? options.filter((o) => next.includes(o)) : null)
              }}
            >
              {on && <Check size={11} />} {b}
            </button>
          )
        })}
      </div>
      <div className="muted small">
        {ready
          ? '판매 현황 · 월별 매장별 판매 집계 · AI 판매 답변에 적용됩니다. 브랜드를 고르면 그 브랜드만 보입니다.'
          : '브랜드를 제한하려면 먼저 db/create_erp_web_user_brand.sql 을 실행하세요 (그 전에는 모두 모든 브랜드).'}
      </div>
    </div>
  )
}

function BrandModal({ user, info, onClose, onSave }: {
  user: AdminUser
  info: { options: string[]; ready: boolean }
  onClose: () => void
  onSave: (brands: string[] | null) => Promise<void>
}) {
  const [value, setValue] = useState<string[] | null>(user.brands)
  const [saving, setSaving] = useState(false)
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>브랜드 권한 · {user.name}</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <BrandPicker options={info.options} value={value} onChange={setValue} ready={info.ready} />
        <div className="setting-actions">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button
            className="btn primary"
            disabled={saving || JSON.stringify(value) === JSON.stringify(user.brands)}
            onClick={async () => {
              setSaving(true)
              try {
                await onSave(value)
              } finally {
                setSaving(false)
              }
            }}
          >
            {saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 저장
          </button>
        </div>
      </div>
    </div>
  )
}

function AddUserModal({ pages, brandInfo, onClose, onAdded, notify }: {
  pages: PageMeta[]
  brandInfo: { options: string[]; ready: boolean }
  onClose: () => void
  onAdded: (name: string) => void
  notify: Notify
}) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<{ id: string; name: string; registered: boolean }[]>([])
  const [loading, setLoading] = useState(false)
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(null)
  const [role, setRole] = useState<'ADMIN' | 'USER'>('USER')
  const [sel, setSel] = useState<PageKey[]>(pages.map((p) => p.key))
  const [aiEnabled, setAiEnabled] = useState(true)
  const [brands, setBrands] = useState<string[] | null | undefined>(brandInfo.ready ? undefined : null)
  const [dq, setDq] = useState('')
  const [dc, setDc] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([])
      return
    }
    const t = setTimeout(() => {
      setLoading(true)
      api.admin
        .directory(q.trim())
        .then((r) => setResults(r.users))
        .catch((e) => notify(e.message, true))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(t)
  }, [q, notify])

  const num = (t: string) => (t.trim() === '' ? null : Number(t))
  const add = async () => {
    if (!picked) return
    const q_ = num(dq)
    const c_ = num(dc)
    if (sel.length === 0) return notify('메뉴 권한을 하나 이상 선택하세요.', true)
    if (brands === undefined) return notify('브랜드 권한을 선택하세요 (모든 브랜드 또는 브랜드 선택).', true)
    if ((q_ !== null && (isNaN(q_) || q_ < 0)) || (c_ !== null && (isNaN(c_) || c_ < 0))) return notify('한도는 0 이상 숫자로 입력하세요.', true)
    setSaving(true)
    try {
      await api.admin.createUser({
        id: picked.id,
        role,
        pages: sel,
        aiEnabled,
        dailyQuestions: q_ === null ? null : Math.round(q_),
        dailyCostUsd: c_,
        active: true,
        brands,
      })
      onAdded(picked.name)
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>사용자 추가</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        {picked ? (
          <div className="add-user-form">
            <div className="dir-row picked">
              <div>
                <div className="strong">{picked.name}</div>
                <div className="muted mono">사번 {picked.id}</div>
              </div>
              <button className="btn ghost sm" onClick={() => setPicked(null)}>다시 선택</button>
            </div>
            <label className="form-row">
              <span>권한</span>
              <select className="input select small" value={role} onChange={(e) => setRole(e.target.value as 'ADMIN' | 'USER')}>
                <option value="USER">일반</option>
                <option value="ADMIN">관리자</option>
              </select>
            </label>
            <div className="form-row">
              <span>메뉴 권한</span>
              <div className="page-chips">
                {pages.map((p) => {
                  const on = sel.includes(p.key)
                  return (
                    <button key={p.key} className={`page-chip ${on ? 'on' : ''}`} onClick={() => setSel(on ? sel.filter((x) => x !== p.key) : [...sel, p.key])}>
                      {on && <Check size={11} />} {p.label}
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="form-row">
              <span>브랜드 권한</span>
              <BrandPicker options={brandInfo.options} value={brands} onChange={setBrands} ready={brandInfo.ready} />
            </div>
            <div className="form-row">
              <span>AI 사용</span>
              <Toggle on={aiEnabled} onChange={setAiEnabled} labels={['사용', '중지']} />
            </div>
            <label className="form-row">
              <span>일일 질문 한도</span>
              <input className="input limit-input" type="number" min={0} step={1} value={dq} placeholder="비우면 기본값" onChange={(e) => setDq(e.target.value)} />
            </label>
            <label className="form-row">
              <span>일일 비용 한도($)</span>
              <input className="input limit-input" type="number" min={0} step={0.5} value={dc} placeholder="비우면 기본값" onChange={(e) => setDc(e.target.value)} />
            </label>
            <div className="setting-actions">
              <button className="btn ghost" onClick={onClose}>취소</button>
              <button className="btn primary" onClick={add} disabled={saving}>
                {saving ? <Loader2 size={15} className="spin" /> : <UserPlus size={15} />} 등록
              </button>
            </div>
          </div>
        ) : (
        <>
        <p className="muted">사내 계정(T_USR, 사용 중)에서 사번 또는 이름으로 검색합니다. 사번(6자리 숫자) 계정만 등록할 수 있고, 등록된 사용자만 로그인할 수 있습니다.</p>
        <div className="search">
          <Search size={16} />
          <input autoFocus placeholder="ID 또는 이름 (2자 이상)" value={q} onChange={(e) => setQ(e.target.value)} />
          {loading && <Loader2 size={15} className="spin" />}
        </div>
        <div className="dir-list">
          {results.map((r) => (
            <div key={r.id} className="dir-row">
              <div>
                <div className="strong">{r.name}</div>
                <div className="muted mono">{r.id}</div>
              </div>
              {r.registered ? <span className="muted">등록됨</span> : <button className="btn primary sm" onClick={() => setPicked({ id: r.id, name: r.name })}>선택</button>}
            </div>
          ))}
          {q.trim().length >= 2 && !loading && results.length === 0 && <div className="muted small-pad">검색 결과가 없습니다.</div>}
        </div>
        </>
        )}
      </div>
    </div>
  )
}

// ----------------------------------------------------------------------------
// AI 설정
// ----------------------------------------------------------------------------
function AiTab({ notify }: { notify: Notify }) {
  const [s, setS] = useState<AdminSettings | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.admin.settings().then(setS).catch((e) => notify(e.message, true))
  }, [notify])

  if (!s) return <div className="card panel"><div className="shimmer panel-shimmer" /></div>

  const submit = async () => {
    setSaving(true)
    try {
      setS(
        await api.admin.saveSettings({
          aiEnabled: s.aiEnabled,
          defaultDailyQuestions: Number(s.defaultDailyQuestions),
          defaultDailyCostUsd: Number(s.defaultDailyCostUsd),
          model: s.model,
          effort: s.effort,
          autoModel: s.autoModel,
          simpleModel: s.simpleModel,
        }),
      )
      notify('AI 설정을 저장했습니다.')
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card panel settings-panel">
      <div className="panel-head"><h3>AI 사용 설정</h3><span className="panel-hint">전체 사용자에게 적용되는 기본값 (사용자별 한도를 지정하면 그 값이 우선)</span></div>
      <div className="setting-row">
        <div>
          <div className="strong">AI 대화 기능</div>
          <div className="muted">끄면 모든 사용자의 대화 버튼이 숨겨지고 질문이 차단됩니다.</div>
        </div>
        <Toggle on={s.aiEnabled} onChange={(v) => setS({ ...s, aiEnabled: v })} labels={['사용', '중지']} />
      </div>
      <div className="setting-row">
        <div>
          <div className="strong">기본 일일 질문 수 한도</div>
          <div className="muted">사용자 1명이 하루에 할 수 있는 질문 수</div>
        </div>
        <div className="input-suffix">
          <input className="input" type="number" min={0} value={s.defaultDailyQuestions} onChange={(e) => setS({ ...s, defaultDailyQuestions: Number(e.target.value) })} />
          <span>회</span>
        </div>
      </div>
      <div className="setting-row">
        <div>
          <div className="strong">기본 일일 비용 한도</div>
          <div className="muted">사용자 1명의 하루 토큰 비용 상한 (도달 시 즉시 중단)</div>
        </div>
        <div className="input-suffix">
          <span>$</span>
          <input className="input" type="number" min={0} step={0.5} value={s.defaultDailyCostUsd} onChange={(e) => setS({ ...s, defaultDailyCostUsd: Number(e.target.value) })} />
        </div>
      </div>
      <div className="setting-row">
        <div>
          <div className="strong">모델</div>
          <div className="muted">.env 기본값: {s.envModel}</div>
        </div>
        <select className="input select" value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })}>
          {s.models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="setting-row">
        <div>
          <div className="strong">사고 강도 (effort)</div>
          <div className="muted">높을수록 정확하지만 느리고 비용이 큽니다. .env 기본값: {s.envEffort}</div>
        </div>
        <select className="input select" value={s.effort} onChange={(e) => setS({ ...s, effort: e.target.value })}>
          {s.efforts.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="setting-row">
        <div>
          <div className="strong">질문에 따라 모델 자동 선택</div>
          <div className="muted">
            값·목록을 바로 묻는 짧은 질문(예: "지난달 실판금액 얼마야?")은 아래 저렴한 모델(effort low)로, 분석·원인·비교·제안 질문과
            애매한 질문은 위 모델로 답합니다. 저렴한 모델이 도구 사용을 거듭 틀리면 그 질문은 위 모델로 넘깁니다.
          </div>
        </div>
        <Toggle on={s.autoModel} onChange={(v) => setS({ ...s, autoModel: v })} labels={['사용', '중지']} />
      </div>
      <div className="setting-row">
        <div>
          <div className="strong">단순 조회용 모델</div>
          <div className="muted">자동 선택이 켜져 있을 때 단순 조회 질문에 쓰는 모델</div>
        </div>
        <select className="input select" value={s.simpleModel} disabled={!s.autoModel} onChange={(e) => setS({ ...s, simpleModel: e.target.value })}>
          {s.models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="setting-actions">
        <button className="btn primary" onClick={submit} disabled={saving}>
          {saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 저장
        </button>
      </div>
    </section>
  )
}

// ----------------------------------------------------------------------------
// 사용 현황
// ----------------------------------------------------------------------------
function UsageTab() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<AdminUsage | null>(null)
  useEffect(() => {
    api.admin.usage(days).then(setData).catch(() => undefined)
  }, [days])
  const t = data?.total
  const tick = { fill: '#8b93a7', fontSize: 12 }
  return (
    <div className="stack">
      <section className="card toolbar">
        <div className="toolbar-title"><Activity size={18} /> AI 사용 현황</div>
        <div className="chips">
          {[7, 30, 90].map((d) => (
            <button key={d} className={`chip ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>최근 {d}일</button>
          ))}
        </div>
      </section>
      <section className="kpi-grid four">
        <MiniKpi label="질문 수" value={t ? `${fmtNum(t.questions)}회` : '-'} />
        <MiniKpi label="사용 비용" value={t ? `$${Number(t.cost).toFixed(2)}` : '-'} />
        <MiniKpi label="토큰 (입력/출력)" value={t ? `${fmtNum(t.input_tokens)} / ${fmtNum(t.output_tokens)}` : '-'} />
        <MiniKpi label="사용자 수" value={t ? `${fmtNum(t.users)}명` : '-'} />
      </section>
      <AiToolStatsCard days={days} />
      <section className="card panel">
        <div className="panel-head"><h3>일자별 사용량</h3><span className="panel-hint">막대: 비용($) · 선: 질문 수</span></div>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data?.daily ?? []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
            <XAxis dataKey="day" tick={tick} tickLine={false} axisLine={false} tickFormatter={(d) => String(d).slice(5)} />
            <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} width={48} />
            <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={36} allowDecimals={false} />
            <Tooltip />
            <Bar yAxisId="l" dataKey="cost" name="비용($)" fill="#6366f1" radius={[5, 5, 0, 0]} maxBarSize={28} />
            <Line yAxisId="r" dataKey="questions" name="질문 수" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </section>
      {(data?.byModel ?? []).length > 0 && (
        <section className="card panel">
          <div className="panel-head"><h3>모델별 사용량</h3><span className="panel-hint">모델 자동 선택 효과 확인용 · API 호출 기준</span></div>
          <table className="table sd-table">
            <thead><tr><th>모델</th><th className="num">API 호출</th><th className="num">입력 토큰</th><th className="num">출력 토큰</th><th className="num">비용($)</th><th className="num">호출당 비용($)</th></tr></thead>
            <tbody>
              {(data?.byModel ?? []).map((m) => (
                <tr key={m.model ?? '-'}>
                  <td className="mono">{m.model ?? '-'}</td>
                  <td className="num">{fmtNum(m.calls)}</td>
                  <td className="num">{fmtNum(m.input_tokens)}</td>
                  <td className="num">{fmtNum(m.output_tokens)}</td>
                  <td className="num strong">${Number(m.cost).toFixed(4)}</td>
                  <td className="num">${m.calls ? (Number(m.cost) / m.calls).toFixed(4) : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <section className="card panel">
        <div className="panel-head"><h3>사용자별 사용량</h3></div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>사용자</th>
                <th className="num">질문 수</th>
                <th className="num">API 호출</th>
                <th className="num">입력 토큰</th>
                <th className="num">출력 토큰</th>
                <th className="num">비용($)</th>
                <th>최근 사용</th>
              </tr>
            </thead>
            <tbody>
              {(data?.byUser ?? []).map((u) => (
                <tr key={u.usr_id}>
                  <td><span className="strong">{u.usr_nm ?? '-'}</span> <span className="muted mono">{u.usr_id}</span></td>
                  <td className="num">{fmtNum(u.questions)}</td>
                  <td className="num">{fmtNum(u.calls)}</td>
                  <td className="num">{fmtNum(u.input_tokens)}</td>
                  <td className="num">{fmtNum(u.output_tokens)}</td>
                  <td className="num strong">${Number(u.cost).toFixed(4)}</td>
                  <td className="muted">{u.last_used}</td>
                </tr>
              ))}
              {data && data.byUser.length === 0 && (
                <tr><td colSpan={7} className="empty">사용 기록이 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function MiniKpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="card kpi">
      <div className="kpi-body">
        <div className="kpi-label">{label}</div>
        <div className="kpi-value sm">{value}</div>
      </div>
    </div>
  )
}

// ----------------------------------------------------------------------------
// 로그인 · 잠금
// ----------------------------------------------------------------------------
const REASON: Record<string, string> = { OK: '성공', BAD_CREDENTIALS: '불일치', LOCKED: '잠금', INACTIVE: '사용중지 계정', NOT_REGISTERED: '미등록 사용자' }

function LoginsTab({ notify }: { notify: Notify }) {
  const [q, setQ] = useState('')
  const [logins, setLogins] = useState<LoginLog[]>([])
  const [locks, setLocks] = useState<LockInfo[]>([])
  const load = useCallback(() => {
    api.admin.logins(q || undefined).then((r) => {
      setLogins(r.logins)
      setLocks(r.locks)
    }).catch((e) => notify(e.message, true))
  }, [q, notify])
  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>로그인 실패 · 잠금 현황</h3>
          <span className="panel-hint">5회 연속 실패 시 1분간 잠금</span>
          <div className="grow" />
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} /></button>
        </div>
        {locks.length === 0 ? (
          <div className="muted small-pad">현재 실패 누적 또는 잠금된 계정이 없습니다.</div>
        ) : (
          <div className="lock-list">
            {locks.map((l) => (
              <div key={l.usr_id} className={`lock-row ${l.locked ? 'locked' : ''}`}>
                <span className="mono strong">{l.usr_id}</span>
                <span>{l.locked ? `잠김 · ${l.remainSec}초 남음` : `실패 ${l.fail_count}회 누적`}</span>
                <button className="btn ghost sm" onClick={() => api.admin.unlock(l.usr_id).then(() => { notify(`${l.usr_id} 잠금을 해제했습니다.`); load() })}>
                  <Unlock size={13} /> 해제
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="card panel">
        <div className="panel-head row">
          <h3>로그인 기록</h3>
          <div className="grow" />
          <div className="search compact">
            <Search size={15} />
            <input placeholder="ID 검색" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <div className="table-wrap tall-ish">
          <table className="table">
            <thead>
              <tr><th>일시</th><th>ID</th><th>이름</th><th>결과</th><th>IP</th></tr>
            </thead>
            <tbody>
              {logins.map((l) => (
                <tr key={l.id}>
                  <td className="muted">{l.ts}</td>
                  <td className="mono">{l.usr_id}</td>
                  <td>{l.usr_nm ?? '-'}</td>
                  <td><span className={`status ${l.success ? 'ok' : 'fail'}`}>{REASON[l.reason] ?? l.reason}</span></td>
                  <td className="muted mono">{l.ip ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

// ----------------------------------------------------------------------------
// 접속 세션
// ----------------------------------------------------------------------------
const tsFmt = (sec: number) => new Date(sec * 1000).toLocaleString('ko-KR', { hour12: false })

function SessionsTab({ notify }: { notify: Notify }) {
  const [list, setList] = useState<SessionInfo[]>([])
  const load = useCallback(() => {
    api.admin.sessions().then((r) => setList(r.sessions)).catch((e) => notify(e.message, true))
  }, [notify])
  useEffect(load, [load])

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>접속 세션</h3>
        <span className="panel-hint">1시간 동안 사용이 없으면 자동 만료 · 강제 로그아웃 가능</span>
        <div className="grow" />
        <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} /></button>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>사용자</th><th>로그인</th><th>마지막 사용</th><th>만료 예정</th><th>IP</th><th>브라우저</th><th /></tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.sid}>
                <td><span className="strong">{s.usr_nm ?? '-'}</span> <span className="muted mono">{s.usr_id}</span></td>
                <td className="muted">{tsFmt(s.created_at)}</td>
                <td>{tsFmt(s.last_seen)}</td>
                <td className="muted">{tsFmt(s.expires_at)}</td>
                <td className="mono muted">{s.ip ?? '-'}</td>
                <td className="ellipsis muted" title={s.user_agent ?? ''}>{s.user_agent ?? '-'}</td>
                <td>
                  <button className="btn ghost sm danger" onClick={() => api.admin.killSession(s.sid).then(() => { notify('세션을 종료했습니다.'); load() })}>
                    <LogOut size={13} /> 로그아웃
                  </button>
                </td>
              </tr>
            ))}
            {list.length === 0 && <tr><td colSpan={7} className="empty">접속 중인 세션이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ----------------------------------------------------------------------------
// 서버 로그 (backend/logs/app.log)
// ----------------------------------------------------------------------------
const LOG_CATEGORIES: { key: string; label: string }[] = [
  { key: '', label: '전체' },
  { key: 'request', label: '요청' },
  { key: 'sql', label: '느린 쿼리·SQL 오류' },
  { key: 'export', label: '엑셀 작업' },
  { key: 'auth', label: '로그인' },
  { key: 'ai', label: 'AI' },
  { key: 'app', label: '서버' },
]
const LOG_LEVELS = [
  { key: 'INFO', label: '전체' },
  { key: 'WARNING', label: '경고 이상' },
  { key: 'ERROR', label: '오류만' },
]

function ServerLogsTab({ notify }: { notify: Notify }) {
  const [level, setLevel] = useState('INFO')
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [list, setList] = useState<ServerLog[]>([])
  const [slowSec, setSlowSec] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .logs({ level, category: category || undefined, q: q || undefined })
      .then((r) => {
        setList(r.logs)
        setSlowSec(r.slowSqlSec)
      })
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [level, category, q, notify])

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>서버 로그</h3>
        <span className="panel-hint">최근 300건 · 느린 쿼리 기준 {slowSec ?? '-'}초 · 비밀번호·바인드 값은 기록하지 않음</span>
        <div className="grow" />
        <div className="search compact">
          <Search size={15} />
          <input placeholder="내용 검색 (사용자ID, 경로 등)" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
      </div>
      <div className="log-filters">
        <div className="chips wrap">
          {LOG_CATEGORIES.map((c) => (
            <button key={c.key} className={`chip ${category === c.key ? 'active' : ''}`} onClick={() => setCategory(c.key)}>{c.label}</button>
          ))}
        </div>
        <div className="seg">
          {LOG_LEVELS.map((l) => (
            <button key={l.key} className={level === l.key ? 'on' : ''} onClick={() => setLevel(l.key)}>{l.label}</button>
          ))}
        </div>
      </div>
      <div className="table-wrap tall-ish">
        <table className="table log-table">
          <thead>
            <tr><th>일시</th><th>수준</th><th>분류</th><th>내용</th></tr>
          </thead>
          <tbody>
            {list.map((l, i) => {
              const multi = l.message.includes('\n')
              return (
                <tr key={i} className={`log-${l.level.toLowerCase()} ${multi ? 'clickable' : ''}`} onClick={() => multi && setOpen(open === i ? null : i)}>
                  <td className="muted mono nowrap">{l.ts}</td>
                  <td><span className={`status ${l.level === 'ERROR' || l.level === 'CRITICAL' ? 'fail' : l.level === 'WARNING' ? 'warn' : 'ok'}`}>{l.level}</span></td>
                  <td className="muted">{LOG_CATEGORIES.find((c) => c.key === l.category)?.label ?? l.category}</td>
                  <td className="log-msg">
                    {open === i ? <pre>{l.message}</pre> : l.message.split('\n')[0]}
                    {multi && open !== i && <span className="muted"> (상세 보기)</span>}
                  </td>
                </tr>
              )
            })}
            {!loading && list.length === 0 && <tr><td colSpan={4} className="empty">조건에 맞는 기록이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}
