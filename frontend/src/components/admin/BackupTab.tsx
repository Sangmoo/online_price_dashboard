import { useRef, useState } from 'react'
import { Download, FileUp, Loader2, RotateCcw } from 'lucide-react'
import { api, downloadFile, type RestorePreview } from '../../api'

type Notify = (text: string, error?: boolean) => void
type Section = 'users' | 'settings' | 'aiTools'
const SECTION_LABEL: Record<Section, string> = { users: '사용자 · 권한', settings: '전역 설정', aiTools: 'AI 도구' }
const KEY_LABEL: Record<string, string> = {
  role: '권한', pages: '메뉴', brands: '브랜드', aiEnabled: 'AI 사용', dailyQuestions: '질문 한도', dailyCostUsd: '비용 한도', dailyBriefings: '브리핑 횟수', active: '계정 사용',
  defaultDailyQuestions: '기본 질문 한도', defaultDailyCostUsd: '기본 비용 한도', defaultDailyBriefings: '기본 브리핑 횟수', model: '모델', effort: 'effort', logKeepDays: '로그 보관 일수',
  autoModel: '모델 자동 선택', simpleModel: '단순 조회 모델',
}
const show = (v: unknown) => (v === null || v === undefined ? '기본/전체' : Array.isArray(v) ? v.join(', ') || '(없음)' : typeof v === 'boolean' ? (v ? '예' : '아니오') : String(v))

export default function BackupTab({ notify }: { notify: Notify }) {
  const [file, setFile] = useState<{ name: string; data: unknown } | null>(null)
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  const [sections, setSections] = useState<Section[]>([])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ applied: string[]; failed: { item: string; reason: string }[] } | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const counts = (p: RestorePreview): Record<Section, number> => ({
    users: p.users.added.length + p.users.changed.length,
    settings: p.settings.changed.length,
    aiTools: p.aiTools.builtinChanged.length + p.aiTools.customAdded.length + p.aiTools.customChanged.length,
  })

  const pick = async (f: File) => {
    setResult(null)
    setPreview(null)
    try {
      const data = JSON.parse(await f.text())
      setBusy(true)
      const p = await api.admin.restorePreview(data)
      setFile({ name: f.name, data })
      setPreview(p)
      const c = counts(p)
      setSections((Object.keys(c) as Section[]).filter((k) => c[k] > 0))
    } catch (e) {
      notify(e instanceof SyntaxError ? 'JSON 파일이 아닙니다.' : (e as Error).message, true)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const apply = async () => {
    if (!file || !sections.length) return
    if (!confirm(`선택한 항목(${sections.map((s) => SECTION_LABEL[s]).join(', ')})을 백업 파일 내용으로 바꿉니다. 계속할까요?`)) return
    setBusy(true)
    try {
      const r = await api.admin.restoreApply(file.data, sections)
      setResult(r)
      setPreview(null)
      notify(`복원했습니다: 적용 ${r.applied.length}건${r.failed.length ? ` · 실패 ${r.failed.length}건` : ''}`, r.failed.length > 0)
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setBusy(false)
    }
  }

  const c = preview ? counts(preview) : null
  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>설정 백업</h3>
          <span className="panel-hint">사용자·메뉴·브랜드 권한, AI 사용·한도, 전역 설정, AI 도구를 파일 하나로 받습니다 · 비밀번호·대화·로그는 담지 않음</span>
          <div className="grow" />
          <button className="btn success" onClick={() => downloadFile('/api/admin/backup', undefined, '설정백업.json').catch((e) => notify(e.message, true))}>
            <Download size={15} /> 백업 파일 받기
          </button>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head row">
          <h3>복원</h3>
          <span className="panel-hint">파일을 고르면 무엇이 바뀌는지 먼저 보여줍니다 · 파일에 없는 사용자·도구는 지우지 않음 · 최고 관리자는 바뀌지 않음</span>
          <div className="grow" />
          <input ref={input} type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])} />
          <button className="btn primary" onClick={() => input.current?.click()} disabled={busy}>
            {busy ? <Loader2 size={15} className="spin" /> : <FileUp size={15} />} 백업 파일 선택
          </button>
        </div>

        {preview && file && c && (
          <div className="restore-preview">
            <div className="muted small">{file.name} · 백업 시각 {preview.file.createdAt ?? '-'} · 만든 사람 {preview.file.createdBy ?? '-'}</div>
            <div className="restore-sections">
              {(Object.keys(SECTION_LABEL) as Section[]).map((s) => (
                <label key={s} className={`restore-section ${c[s] ? '' : 'none'}`}>
                  <input type="checkbox" disabled={!c[s]} checked={sections.includes(s)}
                    onChange={(e) => setSections(e.target.checked ? [...sections, s] : sections.filter((x) => x !== s))} />
                  <b>{SECTION_LABEL[s]}</b> <span className="muted">{c[s] ? `${c[s]}건 바뀜` : '변경 없음'}</span>
                </label>
              ))}
            </div>
            <details open={c.users > 0}>
              <summary>사용자 · 추가 {preview.users.added.length} · 변경 {preview.users.changed.length} · 같음 {preview.users.same}
                {preview.users.notInFile.length ? ` · 파일에 없음 ${preview.users.notInFile.length}(그대로 둠)` : ''}</summary>
              <ul className="restore-list">
                {preview.users.added.map((u) => <li key={u.id}><b className="up">추가</b> {u.name} <span className="mono muted">{u.id}</span></li>)}
                {preview.users.changed.map((u) => (
                  <li key={u.id}>
                    <b>변경</b> {u.name} <span className="mono muted">{u.id}</span> ·{' '}
                    {Object.entries(u.diff).map(([k, d]) => `${KEY_LABEL[k] ?? k}: ${show(d.before)} → ${show(d.after)}`).join(' / ')}
                  </li>
                ))}
                {preview.users.skipped.map((u) => <li key={u.id} className="muted">제외 {u.name} ({u.reason})</li>)}
              </ul>
            </details>
            <details open={c.settings > 0}>
              <summary>전역 설정 · 변경 {preview.settings.changed.length}</summary>
              <ul className="restore-list">
                {preview.settings.changed.map((s) => <li key={s.key}>{KEY_LABEL[s.key] ?? s.key}: {show(s.before)} → <b>{show(s.after)}</b></li>)}
              </ul>
            </details>
            <details open={c.aiTools > 0}>
              <summary>AI 도구 · 기본 도구 변경 {preview.aiTools.builtinChanged.length} · 추가 {preview.aiTools.customAdded.length} · 변경 {preview.aiTools.customChanged.length}</summary>
              <ul className="restore-list">
                {preview.aiTools.builtinChanged.map((t) => <li key={t.name}>기본 도구 <span className="mono">{t.name}</span> 설정</li>)}
                {preview.aiTools.customAdded.map((t) => <li key={t.name}><b className="up">추가</b> {t.label} <span className="mono muted">{t.name}</span></li>)}
                {preview.aiTools.customChanged.map((t) => <li key={t.name}>변경 {t.label} <span className="mono muted">{t.name}</span> ({t.keys.join(', ')})</li>)}
              </ul>
            </details>
            <div className="setting-actions">
              <button className="btn ghost" onClick={() => setPreview(null)}>취소</button>
              <button className="btn primary" onClick={apply} disabled={busy || sections.length === 0}>
                {busy ? <Loader2 size={15} className="spin" /> : <RotateCcw size={15} />} 선택한 항목 복원
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="restore-preview">
            <b>복원 결과</b> · 적용 {result.applied.length}건 · 실패 {result.failed.length}건 (변경 이력에 기록됨)
            {result.failed.length > 0 && (
              <ul className="restore-list">{result.failed.map((f) => <li key={f.item} className="down">{f.item}: {f.reason}</li>)}</ul>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
