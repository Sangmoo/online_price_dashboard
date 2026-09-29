import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, Database, Loader2, Pencil, Play, Plus, RefreshCw, Trash2, Wand2, X } from 'lucide-react'
import {
  api,
  type AiToolTestResult,
  type AiToolsOverview,
  type BuiltinTool,
  type CustomTool,
  type CustomToolDef,
  type DataStatus,
  type MvRefresh,
  type PageMeta,
  type ToolParam,
} from '../../api'
import { fmtNum } from '../../format'

type Notify = (text: string, error?: boolean) => void

function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button className={`toggle ${on ? 'on' : ''}`} disabled={disabled} onClick={() => onChange(!on)} role="switch" aria-checked={on}>
      <span className="knob" />
      <span className="toggle-label">{on ? '사용' : '중지'}</span>
    </button>
  )
}

export default function AiToolsTab({ notify }: { notify: Notify }) {
  const [data, setData] = useState<AiToolsOverview | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [noteFor, setNoteFor] = useState<BuiltinTool | null>(null)
  const [editing, setEditing] = useState<{ tool: CustomToolDef; isNew: boolean } | null>(null)

  const load = useCallback(() => {
    api.admin.aiTools().then(setData).catch((e) => notify(e.message, true))
  }, [notify])
  useEffect(load, [load])

  const run = async (key: string, fn: () => Promise<AiToolsOverview>, ok: string) => {
    setBusy(key)
    try {
      setData(await fn())
      notify(ok)
      return true
    } catch (e) {
      notify((e as Error).message, true)
      return false
    } finally {
      setBusy(null)
    }
  }

  if (!data) return <div className="card panel"><div className="shimmer panel-shimmer" /></div>
  const pageLabel = (k: string) => data.pages.find((p) => p.key === k)?.label ?? k

  return (
    <div className="stack">
      <DataStatusCard notify={notify} />
      <section className="card panel">
        <div className="panel-head row">
          <h3>기본 도구</h3>
          <span className="panel-hint">프로그램에 들어 있는 조회 도구 · 끄면 AI 가 쓰지 않음 · ✎ 로 AI 에게 주는 설명·추가 안내 수정 (조회 방식은 고정)</span>
          <div className="grow" />
          <span className={`storage-badge ${data.storage}`} title={data.storage === 'sqlite' ? 'db/create_erp_web_ai_tool.sql 로 Oracle 테이블을 만들면 자동으로 옮겨집니다.' : ''}>
            <Database size={13} /> 저장 위치: {data.storage === 'oracle' ? 'Oracle' : '서버 로컬 (Oracle 테이블 생성 시 자동 이전)'}
          </span>
        </div>
        <div className="table-wrap">
          <table className="table tool-table">
            <thead>
              <tr><th>도구</th><th>데이터 · 필요 메뉴</th><th>설명 (AI 에게 전달)</th><th>추가 안내</th><th className="center">사용</th></tr>
            </thead>
            <tbody>
              {data.builtin.map((t) => (
                <tr key={t.name} className={t.enabled ? '' : 'inactive'}>
                  <td><div className="strong">{t.label}</div><div className="muted mono small">{t.name}</div></td>
                  <td><div>{t.group}</div><div className="muted small">{t.pages.map((p) => p.label).join(', ')}</div></td>
                  <td>
                    {t.customized && <span className="tool-badge">설명 변경됨</span>}
                    <div className="tool-desc" title={t.description}>{t.description}</div>
                  </td>
                  <td className="tool-note">
                    {t.extraDesc ? <span>{t.extraDesc}</span> : <span className="muted">-</span>}
                    <button className="icon-btn tiny-visible" title="설명 · 추가 안내 편집" onClick={() => setNoteFor(t)}><Pencil size={13} /></button>
                  </td>
                  <td className="center">
                    <Toggle on={t.enabled} disabled={busy === t.name}
                      onChange={(v) => run(t.name, () => api.admin.saveBuiltinTool(t.name, { enabled: v, extraDesc: t.extraDesc }),
                        `${t.label} 도구를 ${v ? '사용' : '중지'}했습니다.`)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head row">
          <h3>관리자 정의 도구</h3>
          <span className="panel-hint">조회 SQL 로 새 도구를 만듭니다 · 연결한 메뉴 권한이 있는 사용자에게만 제공 · 읽기 전용으로 실행</span>
          <div className="grow" />
          <button className="btn primary" onClick={() => setEditing({ isNew: true, tool: emptyTool(data.pages) })}>
            <Plus size={15} /> 새 도구
          </button>
        </div>
        <div className="table-wrap">
          <table className="table tool-table">
            <thead>
              <tr><th>도구</th><th>연결 메뉴</th><th>설명</th><th>입력값</th><th className="num">최대 행</th><th>수정</th><th className="center">사용</th><th /></tr>
            </thead>
            <tbody>
              {data.custom.map((t) => (
                <tr key={t.name} className={t.enabled ? '' : 'inactive'}>
                  <td><div className="strong">{t.label}</div><div className="muted mono small">{t.name}</div></td>
                  <td>{pageLabel(t.page)}</td>
                  <td className="tool-desc" title={t.description}>{t.description}</td>
                  <td className="small">{t.params.length ? t.params.map((p) => p.name + (p.required ? '*' : '')).join(', ') : <span className="muted">없음</span>}</td>
                  <td className="num">{fmtNum(t.maxRows)}</td>
                  <td className="muted small">{t.updatedAt ? `${t.updatedAt.slice(0, 8)} · ${t.updatedBy ?? ''}` : '-'}</td>
                  <td className="center">
                    <Toggle on={t.enabled} disabled={busy === t.name}
                      onChange={(v) => run(t.name, () => api.admin.updateTool({ ...stripMeta(t), enabled: v }), `${t.label} 도구를 ${v ? '사용' : '중지'}했습니다.`)} />
                  </td>
                  <td className="nowrap">
                    <button className="icon-btn tiny-visible" title="수정" onClick={() => setEditing({ isNew: false, tool: stripMeta(t) })}><Pencil size={14} /></button>
                    <button className="icon-btn tiny-visible danger" title="삭제" disabled={busy === t.name}
                      onClick={() => confirm(`'${t.label}' 도구를 삭제할까요? AI 가 더 이상 이 도구를 쓰지 않습니다.`) &&
                        run(t.name, () => api.admin.deleteTool(t.name), `${t.label} 도구를 삭제했습니다.`)}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
              {data.custom.length === 0 && (
                <tr><td colSpan={8} className="empty">아직 만든 도구가 없습니다. [새 도구]로 조회 SQL 을 등록하면 AI 가 그 데이터로 답할 수 있습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {noteFor && (
        <NoteModal
          tool={noteFor}
          onClose={() => setNoteFor(null)}
          onSave={async (description, extraDesc) => {
            if (await run(noteFor.name, () => api.admin.saveBuiltinTool(noteFor.name, { enabled: noteFor.enabled, extraDesc, description }),
              `${noteFor.label} 도구 설명을 저장했습니다.`))
              setNoteFor(null)
          }}
        />
      )}
      {editing && (
        <ToolEditor
          initial={editing.tool}
          isNew={editing.isNew}
          overview={data}
          onClose={() => setEditing(null)}
          onSave={async (tool) => {
            const ok = await run(tool.name, () => (editing.isNew ? api.admin.createTool(tool) : api.admin.updateTool(tool)),
              `${tool.label} 도구를 ${editing.isNew ? '추가' : '수정'}했습니다.`)
            if (ok) setEditing(null)
          }}
        />
      )}
    </div>
  )
}

// ----------------------------------------------------------------------------
// 사전 집계 뷰 상태 (AI 합계 도구 · 판매 현황 · 요약 화면이 사용)
// ----------------------------------------------------------------------------
function DataStatusCard({ notify }: { notify: Notify }) {
  const [st, setSt] = useState<DataStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState<MvRefresh | null>(null)
  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .dataStatus()
      .then((d) => {
        setSt(d)
        setRefresh(d.refresh)
      })
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [notify])
  useEffect(load, [load])

  // 갱신 중이면 3초마다 상태 확인, 끝나면 뷰 상태를 다시 읽는다
  const running = refresh?.status === 'running'
  useEffect(() => {
    if (!running) return
    const t = setTimeout(() => {
      api.admin
        .refreshState()
        .then(({ refresh: r }) => {
          setRefresh(r)
          if (r.status === 'done') {
            notify(`사전 집계 뷰를 갱신했습니다 (${r.elapsedSec ?? '-'}초).`)
            load()
          } else if (r.status === 'error') {
            notify(`갱신 실패: ${r.error}`, true)
          }
        })
        .catch(() => undefined)
    }, 3000)
    return () => clearTimeout(t)
  }, [refresh, running, load, notify])

  const startRefresh = async () => {
    if (!st) return
    const msg =
      `사전 집계 뷰를 지금 갱신할까요?\n\n` +
      `· 원본(T_CLOSE_SALE_BASE) 전체를 월×매장으로 다시 집계합니다 (몇 분 걸릴 수 있음).\n` +
      `· 갱신이 끝날 때까지 화면·AI 는 이전 데이터로 조회되고, 끝나면 바로 새 데이터를 씁니다.\n` +
      `· 전월 마감 적재가 끝난 뒤에 실행하세요. (현재 원본 최신 월: ${ym(st.baseMaxMonth)})`
    if (!confirm(msg)) return
    try {
      const { refresh: r } = await api.admin.refreshMv()
      setRefresh(r)
    } catch (e) {
      notify((e as Error).message, true)
    }
  }

  const ym = (v: string | null) => (v ? `${v.slice(0, 4)}-${v.slice(4)}` : '-')
  const ok = !!st && st.usable && !st.behind
  return (
    <section className="card panel">
      <div className="panel-head row">
        <h3>사전 집계 뷰</h3>
        <span className="panel-hint">월×매장 합계 · 판매 현황, 판매 요약(월·매장), AI 합계 도구가 사용 · 최신이 아니면 원본으로 계산(느려짐)</span>
        <div className="grow" />
        <button className="icon-btn bordered" onClick={load} title="상태 새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        <button className={`btn ${ok ? 'ghost' : 'primary'}`} onClick={startRefresh} disabled={!st || running}
          title="전월 마감 적재가 끝난 뒤 눌러 주세요">
          {running ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} {running ? `갱신 중 ${refresh?.elapsedSec ?? 0}초` : '지금 갱신'}
        </button>
      </div>
      {st && (
        <div className="summary-pills">
          <div className={`pill strong ${ok ? '' : 'warn-pill'}`}>
            <span>상태</span>
            <b>{!st.mvMaxMonth ? '뷰 없음' : st.staleness === 'FRESH' ? (st.behind ? '최근 월 없음' : '최신') : '갱신 필요'}</b>
          </div>
          <div className="pill"><span>마지막 갱신</span><b>{st.lastRefresh ?? '-'}</b></div>
          <div className="pill"><span>뷰 최신 월</span><b>{ym(st.mvMaxMonth)}</b><span className="muted">/ 원본 {ym(st.baseMaxMonth)}</span></div>
          <div className="pill"><span>행 수</span><b>{st.rows === null ? '-' : fmtNum(st.rows)}</b></div>
          <div className="pill"><span>원가 컬럼</span><b>{st.hasCostColumn ? '있음' : '없음'}</b></div>
        </div>
      )}
      {st && !ok && !running && (
        <div className="alert warn-inline">
          <AlertTriangle size={14} />
          {st.behind ? `원본에 ${ym(st.baseMaxMonth)} 데이터가 들어왔지만 뷰에는 아직 없습니다.` : '원본이 바뀌어 뷰가 최신이 아닙니다.'}
          {' '}마감 적재가 끝났으면 [지금 갱신]을 눌러 주세요. 그동안은 원본 테이블로 계산합니다(결과는 같고 느릴 뿐).
        </div>
      )}
      {refresh && refresh.status !== 'idle' && (
        <div className={`muted small mv-refresh-line ${refresh.status}`}>
          {refresh.status === 'running' && `갱신 중 · ${refresh.by} · ${refresh.started} 시작 · ${refresh.elapsedSec ?? 0}초 경과 (다른 화면으로 가도 계속됩니다)`}
          {refresh.status === 'done' && `최근 갱신 완료 · ${refresh.by} · ${refresh.finished} · ${refresh.elapsedSec}초`}
          {refresh.status === 'error' && `최근 갱신 실패 · ${refresh.by} · ${refresh.finished} · ${refresh.error}`}
        </div>
      )}
    </section>
  )
}

const emptyTool = (pages: PageMeta[]): CustomToolDef => ({
  name: '', label: '', description: '', page: pages[0]?.key ?? '', sql: 'SELECT ...\n  FROM ...\n WHERE MAKE_YYMM = :ym', params: [], maxRows: 100, enabled: true,
})
const stripMeta = (t: CustomTool): CustomToolDef => ({
  name: t.name, label: t.label, description: t.description, page: t.page, sql: t.sql, params: t.params, maxRows: t.maxRows, enabled: t.enabled,
})
const bindsIn = (sql: string) => {
  const out: string[] = []
  sql.replace(/'(?:[^']|'')*'|:([A-Za-z_][A-Za-z0-9_]*)/g, (m, name) => {
    if (name && !out.includes(name.toLowerCase())) out.push(name.toLowerCase())
    return m
  })
  return out
}

// ----------------------------------------------------------------------------
function NoteModal({ tool, onClose, onSave }: { tool: BuiltinTool; onClose: () => void; onSave: (description: string, extraDesc: string) => void }) {
  const [desc, setDesc] = useState(tool.description)
  const [text, setText] = useState(tool.extraDesc)
  const isDefault = desc.trim() === tool.defaultDescription.trim()
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card tool-editor">
        <div className="modal-head">
          <h3>설명 편집 · {tool.label} <span className="muted mono small">{tool.name}</span></h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <label className="tool-field">
          <span>
            설명 (AI 에게 전달) — AI 가 이 도구를 언제·어떻게 쓸지 판단하는 글입니다. 조회 조건·계산 방식은 바뀌지 않습니다.
            {!isDefault && <span className="tool-badge">기본 설명과 다름</span>}
          </span>
          <textarea className="input tool-textarea size-xl" rows={18} maxLength={4000} value={desc} onChange={(e) => setDesc(e.target.value)} />
        </label>
        <div className="tool-desc-actions">
          <span className="muted small">{desc.length}/4000 · 입력값: {tool.params.join(', ') || '없음'}</span>
          <button className="btn-link small" disabled={isDefault} onClick={() => setDesc(tool.defaultDescription)}>기본값으로 되돌리기</button>
        </div>
        <label className="tool-field">
          <span>추가 안내 — 설명 끝에 "[관리자 안내]"로 덧붙습니다. 예: "원가율은 소수 첫째 자리까지", "자사몰(S51012)은 온라인 매장으로 구분"</span>
          <textarea className="input tool-textarea size-md" rows={7} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        {!isDefault && (
          <div className="alert warn-inline"><AlertTriangle size={14} /> 설명을 바꾸면 AI 가 도구를 고르는 방식이 달라질 수 있습니다. 바꾼 뒤 몇 가지 질문으로 확인해 보세요.</div>
        )}
        <div className="setting-actions">
          <span className="muted small">{text.length}/1000</span>
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" disabled={desc.trim().length < 10} onClick={() => onSave(desc, text)}><Check size={15} /> 저장</button>
        </div>
      </div>
    </div>
  )
}

// ----------------------------------------------------------------------------
function ToolEditor({ initial, isNew, overview, onClose, onSave }: {
  initial: CustomToolDef
  isNew: boolean
  overview: AiToolsOverview
  onClose: () => void
  onSave: (t: CustomToolDef) => void
}) {
  const [t, setT] = useState<CustomToolDef>(initial)
  const [args, setArgs] = useState<Record<string, string>>({})
  const [test, setTest] = useState<AiToolTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const set = <K extends keyof CustomToolDef>(k: K, v: CustomToolDef[K]) => setT((x) => ({ ...x, [k]: v }))
  const setParam = (i: number, patch: Partial<ToolParam>) => set('params', t.params.map((p, j) => (j === i ? { ...p, ...patch } : p)))

  const binds = bindsIn(t.sql)
  const missing = binds.filter((b) => !t.params.some((p) => p.name === b))
  const unused = t.params.filter((p) => !binds.includes(p.name)).map((p) => p.name)

  const syncParams = () =>
    set('params', [
      ...t.params.filter((p) => binds.includes(p.name)),
      ...missing.map((name) => ({ name, type: /ym$|yymm/.test(name) ? 'yyyymm' : /dt$|date|day/.test(name) ? 'date' : 'string', required: true, description: '' })),
    ])

  const runTest = async () => {
    setTesting(true)
    setTest(null)
    try {
      setTest(await api.admin.testTool(t, args))
    } catch (e) {
      setTest({ ok: false, stage: 'sql', message: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card tool-editor">
        <div className="modal-head">
          <h3>{isNew ? '새 도구' : `도구 수정 · ${initial.label}`}</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="tool-grid">
          <label>
            <span>도구 이름 (AI 호출용)</span>
            <input className="input mono" value={t.name} disabled={!isNew} placeholder="shop_stock_status" onChange={(e) => set('name', e.target.value.toLowerCase())} />
          </label>
          <label>
            <span>표시 이름</span>
            <input className="input" value={t.label} maxLength={50} placeholder="매장 재고 현황" onChange={(e) => set('label', e.target.value)} />
          </label>
          <label>
            <span>연결 메뉴 (이 권한이 있는 사용자만)</span>
            <select className="input select" value={t.page} onChange={(e) => set('page', e.target.value as CustomToolDef['page'])}>
              {overview.pages.map((p) => <option key={p.key} value={p.key}>{p.group} › {p.label}</option>)}
            </select>
          </label>
          <label>
            <span>최대 행 수</span>
            <input className="input" type="number" min={1} max={overview.maxRowsLimit} value={t.maxRows} onChange={(e) => set('maxRows', Number(e.target.value))} />
          </label>
        </div>

        <label className="tool-field">
          <span>설명 — AI 가 언제 이 도구를 쓰는지 판단하는 글입니다. 무엇을 조회하는지, 결과 컬럼의 뜻, 단위를 적어 주세요.</span>
          <textarea className="input tool-textarea size-lg" rows={7} maxLength={2000} value={t.description} onChange={(e) => set('description', e.target.value)}
            placeholder="예: 판매년월을 받아 그 달 실판금액 상위 매장을 조회합니다. AMT 는 실판금액(원)입니다." />
          <span className="muted small tool-count">{t.description.length}/2000</span>
        </label>

        <label className="tool-field">
          <span>조회 SQL — SELECT/WITH 한 문장, 값은 :이름 바인드로만 (주석·세미콜론·쓰기 구문 불가)</span>
          <textarea className="input tool-textarea size-sql mono" rows={14} spellCheck={false} value={t.sql} onChange={(e) => set('sql', e.target.value)} />
        </label>
        {(missing.length > 0 || unused.length > 0) && (
          <div className="alert warn-inline">
            <AlertTriangle size={14} />
            {missing.length > 0 && <span>SQL 에 있는 {missing.map((m) => ':' + m).join(', ')} 가 입력값에 없습니다. </span>}
            {unused.length > 0 && <span>입력값 {unused.join(', ')} 가 SQL 에 없습니다. </span>}
            <button className="btn-link" onClick={syncParams}><Wand2 size={13} /> SQL 기준으로 맞추기</button>
          </div>
        )}

        <div className="tool-field">
          <span>입력값 (AI 가 채워서 호출)</span>
          <table className="table tool-params">
            <thead><tr><th>이름</th><th>형식</th><th className="center">필수</th><th>설명</th><th>선택값 (쉼표 구분)</th><th>기본값</th><th /></tr></thead>
            <tbody>
              {t.params.map((p, i) => (
                <tr key={i}>
                  <td><input className="input mono small-input" value={p.name} onChange={(e) => setParam(i, { name: e.target.value.toLowerCase() })} /></td>
                  <td>
                    <select className="input select small-input" value={p.type} onChange={(e) => setParam(i, { type: e.target.value })}>
                      {overview.paramTypes.map((pt) => <option key={pt.key} value={pt.key}>{pt.label}</option>)}
                    </select>
                  </td>
                  <td className="center"><input type="checkbox" checked={p.required} onChange={(e) => setParam(i, { required: e.target.checked })} /></td>
                  <td><input className="input small-input" value={p.description} onChange={(e) => setParam(i, { description: e.target.value })} /></td>
                  <td>
                    <input className="input small-input" disabled={p.type !== 'enum'} value={(p.enum ?? []).join(', ')}
                      onChange={(e) => setParam(i, { enum: e.target.value.split(',').map((x) => x.trim()) })} />
                  </td>
                  <td><input className="input small-input" value={p.default ?? ''} onChange={(e) => setParam(i, { default: e.target.value })} /></td>
                  <td><button className="icon-btn" onClick={() => set('params', t.params.filter((_, j) => j !== i))}><X size={14} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn ghost sm" onClick={() => set('params', [...t.params, { name: '', type: 'string', required: true, description: '' }])}>
            <Plus size={13} /> 입력값 추가
          </button>
        </div>

        <div className="tool-test">
          <div className="tool-test-head">
            <b>시험 실행</b>
            {t.params.map((p) => (
              <label key={p.name} className="tool-arg">
                <span className="mono">{p.name}</span>
                <input className="input small-input" value={args[p.name] ?? ''} placeholder={p.type === 'yyyymm' ? '202608' : p.type === 'date' ? '20260801' : ''}
                  onChange={(e) => setArgs((a) => ({ ...a, [p.name]: e.target.value }))} />
              </label>
            ))}
            <button className="btn ghost" onClick={runTest} disabled={testing}>
              {testing ? <Loader2 size={14} className="spin" /> : <Play size={14} />} 실행 (최대 20행)
            </button>
          </div>
          {test && !test.ok && <div className="alert error">{test.stage === 'definition' ? '정의 오류' : test.stage === 'args' ? '입력값 오류' : 'SQL 실행 오류'}: {test.message}</div>}
          {test && test.ok && (
            <div className="table-wrap tool-result">
              <div className="muted small">{fmtNum(test.rows.length)}행{test.truncated ? ' (더 있음)' : ''} · {test.elapsedMs}ms</div>
              <table className="table">
                <thead><tr>{test.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                <tbody>
                  {test.rows.map((r, i) => <tr key={i}>{test.columns.map((c) => <td key={c.key}>{typeof r[c.key] === 'number' ? fmtNum(r[c.key] as number) : String(r[c.key] ?? '')}</td>)}</tr>)}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="setting-actions">
          <label className="check-label"><input type="checkbox" checked={t.enabled} onChange={(e) => set('enabled', e.target.checked)} /> 사용</label>
          <div className="grow" />
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" onClick={() => onSave({ ...t, params: t.params.map((p) => ({ ...p, enum: p.type === 'enum' ? (p.enum ?? []).filter(Boolean) : undefined })) })}>
            <Check size={15} /> 저장
          </button>
        </div>
      </div>
    </div>
  )
}
