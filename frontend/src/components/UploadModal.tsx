import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, Upload, X, XCircle } from 'lucide-react'
import { downloadFile } from '../api'
import { opsApi, uploadTemplateUrl, type UploadPreview, type UploadRow } from '../opsApi'

export type UploadCol = { key: string; label: string; fmt?: 'date' | 'num' }
type Kind = 'invt' | 'mall'

const fmt = (v: unknown, f?: UploadCol['fmt']) => {
  if (v == null || v === '') return ''
  if (f === 'date' && typeof v === 'string' && /^\d{8}$/.test(v)) return `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}`
  if (f === 'num' && typeof v === 'number') return v.toLocaleString()
  return String(v)
}
const STATUS = { ok: ['정상', CheckCircle2], warn: ['주의', AlertTriangle], error: ['오류', XCircle] } as const

/** 저장될 행: 실사계획 = 정상 · 주의, 판매처 매장 연결 = 정상이면서 신규 · 변경 · 해제 */
const willSave = (kind: Kind, r: UploadRow) =>
  kind === 'invt' ? r.status !== 'error' : r.status === 'ok' && ['신규', '변경', '해제'].includes(r.change ?? '')

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => resolve(String(fr.result))
    fr.onerror = () => reject(new Error('파일을 읽지 못했습니다.'))
    fr.readAsDataURL(file)
  })
}

/** 엑셀 업로드로 한 번에 등록: 양식 내려받기 → 파일 올리기(미리보기) → 정상 행 저장 */
export default function UploadModal({ kind, title, guide, cols, onSaved, onClose }: {
  kind: Kind; title: string; guide: React.ReactNode; cols: UploadCol[]; onSaved: (msg: string) => void; onClose: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<UploadPreview | null>(null)
  const [busy, setBusy] = useState<'preview' | 'save' | 'template' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'error' | 'warn' | 'ok'>('all')
  const [drag, setDrag] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [])

  const pick = async (f: File | null | undefined) => {
    if (!f) return
    if (!/\.xlsx$/i.test(f.name)) {
      setError('엑셀(.xlsx) 파일만 올릴 수 있습니다.')
      return
    }
    setFile(f)
    setPreview(null)
    setError(null)
    setBusy('preview')
    try {
      setPreview(await opsApi.uploadPreview(kind, await readBase64(f)))
      setFilter('all')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const rows = useMemo(() => (preview?.rows ?? []).filter((r) => filter === 'all' || r.status === filter), [preview, filter])
  const saveRows = useMemo(() => (preview?.rows ?? []).filter((r) => willSave(kind, r)), [preview, kind])

  const save = async () => {
    if (!saveRows.length) return
    const skip = (preview?.rows.length ?? 0) - saveRows.length
    if (!confirm(`${saveRows.length}건을 저장합니다.${skip ? ` (오류 · 저장할 것 없는 ${skip}건은 빠집니다)` : ''} 계속할까요?`)) return
    setBusy('save')
    setError(null)
    try {
      const r = await opsApi.uploadApply(kind, saveRows)
      const msg = kind === 'invt'
        ? `실사계획 ${r.saved}건을 등록했습니다.${r.skipped ? ` (오류 ${r.skipped}건 제외)` : ''}`
        : `판매처 매장 연결을 저장했습니다 · 등록·수정 ${r.saved}건 · 해제 ${r.deleted ?? 0}건${r.skipped ? ` · 제외 ${r.skipped}건` : ''}`
      onSaved(msg)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const template = async () => {
    setBusy('template')
    try {
      await downloadFile(uploadTemplateUrl(kind))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const sm = preview?.summary
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && busy !== 'save' && onClose()}>
      <div className="modal card help-modal upload-modal" role="dialog" aria-label={title}>
        <div className="modal-head">
          <h3><FileSpreadsheet size={17} /> {title}</h3>
          <button className="icon-btn" onClick={onClose} title="닫기" disabled={busy === 'save'}><X size={18} /></button>
        </div>

        <ol className="upload-steps">
          <li>
            <b>1. 양식 내려받기</b>
            <button className="btn ghost sm" onClick={template} disabled={busy === 'template'}>
              {busy === 'template' ? <Loader2 size={13} className="spin" /> : <Download size={13} />} 업로드 양식 (.xlsx)
            </button>
          </li>
          <li><b>2. 작성 후 올리기</b> <span className="muted small">— 미리보기에서 행마다 확인 (아직 저장 안 됨)</span></li>
          <li><b>3. 저장</b> <span className="muted small">— 오류 행은 빼고 저장</span></li>
        </ol>
        <div className="muted small upload-guide">{guide}</div>

        <div className={`drop-zone ${drag ? 'on' : ''}`} onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}>
          {busy === 'preview' ? <><Loader2 size={18} className="spin" /> 확인하는 중… {kind === 'invt' ? '(매장 정보 자동 입력 포함)' : ''}</>
            : <><Upload size={18} /> {file ? <><b>{file.name}</b> · 다른 파일을 올리려면 누르거나 끌어 놓으세요</> : '엑셀 파일을 끌어 놓거나 눌러서 고르세요 (.xlsx · 최대 5MB)'}</>}
          <input ref={inputRef} type="file" accept=".xlsx" hidden aria-label="엑셀 파일"
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
        </div>
        {error && <div className="alert error">{error}</div>}

        {preview && sm && (
          <>
            <div className="upload-summary">
              <div className="seg q-seg">
                {([['all', `전체 ${sm.total}`], ['error', `오류 ${sm.error}`], ['warn', `주의 ${sm.warn}`], ['ok', `정상 ${sm.ok}`]] as const).map(([k, l]) => (
                  <button key={k} className={filter === k ? 'on' : ''} onClick={() => setFilter(k)}>{l}</button>
                ))}
              </div>
              {sm.changes && (
                <span className="muted small">
                  {Object.entries(sm.changes).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(' · ') || '바뀌는 것 없음'}
                </span>
              )}
            </div>
            <div className="table-wrap upload-table">
              <table className="table">
                <thead>
                  <tr>
                    <th className="num">행</th><th>상태</th>
                    {kind === 'mall' && <th>반영</th>}
                    {cols.map((c) => <th key={c.key} className={c.fmt === 'num' ? 'num' : undefined}>{c.label}</th>)}
                    <th>확인 내용</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const [label, Icon] = STATUS[r.status]
                    const v = r.display ?? r.values
                    return (
                      <tr key={r.row} className={`upload-${r.status}`}>
                        <td className="num muted">{r.row}</td>
                        <td className="nowrap"><span className={`up-badge ${r.status}`}><Icon size={12} /> {label}</span></td>
                        {kind === 'mall' && <td className="nowrap small">{r.change ?? '-'}</td>}
                        {cols.map((c) => (
                          <td key={c.key} className={`${c.fmt === 'num' ? 'num' : ''} ${r.auto?.includes(c.key) ? 'auto-cell' : ''}`}
                            title={r.auto?.includes(c.key) ? '매장코드로 자동 입력' : undefined}>{fmt(v[c.key], c.fmt)}</td>
                        ))}
                        <td className="small up-msg">{r.messages.join(' · ')}</td>
                      </tr>
                    )
                  })}
                  {!rows.length && <tr><td colSpan={cols.length + 4} className="empty">해당하는 행이 없습니다.</td></tr>}
                </tbody>
              </table>
            </div>
          </>
        )}

        <div className="modal-foot">
          {kind === 'invt' && preview && <span className="muted small"><span className="auto-cell legend">파란 칸</span> = 매장코드로 자동 입력된 값</span>}
          <div className="grow" />
          <button className="btn ghost" onClick={onClose} disabled={busy === 'save'}>닫기</button>
          <button className="btn primary" onClick={save} disabled={!saveRows.length || !!busy}>
            {busy === 'save' ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />} {saveRows.length ? `${saveRows.length}건 저장` : '저장할 행 없음'}
          </button>
        </div>
      </div>
    </div>
  )
}
