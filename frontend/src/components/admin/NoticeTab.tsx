import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, ImagePlus, Loader2, Megaphone, MessageSquare, Paperclip, Pencil, Plus, RefreshCw, Trash2, Wrench, X } from 'lucide-react'
import {
  fileSize,
  noticeFileUrl,
  opsApi,
  type Maintenance,
  type NewNoticeFile,
  type Notice,
  type NoticeFile,
  type NoticeInput,
  type NoticeLevel,
  type NoticeLimits,
} from '../../opsApi'
import NoticePopup from '../NoticePopup'

type Notify = (text: string, error?: boolean) => void
const STATUS_LABEL: Record<Notice['status'], string> = { active: '게시 중', scheduled: '게시 예정', ended: '종료', off: '사용 안 함' }
const todayIso = () => new Date().toLocaleDateString('sv-SE')
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() + n)
  return d.toLocaleDateString('sv-SE')
}

/** 공지 · 점검: 게시 기간이 있는 공지(로그인 후 팝업, 사용자는 '오늘 하루 보지 않기' 가능)와 점검 모드(관리자 외 접속 차단) */
export default function NoticeTab({ notify, onChange }: { notify: Notify; onChange?: () => void }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.notices>> | null>(null)
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Notice | 'new' | null>(null)
  const [preview, setPreview] = useState<Notice[] | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    opsApi
      .notices()
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [notify])
  useEffect(load, [load])

  const remove = async (n: Notice) => {
    if (!confirm(`'${n.title}' 공지를 삭제할까요? 첨부파일과 댓글도 함께 지워집니다.`)) return
    try {
      await opsApi.deleteNotice(n.id)
      notify('공지를 삭제했습니다.')
      load()
      onChange?.()
    } catch (e) {
      notify((e as Error).message, true)
    }
  }

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 공지를 읽는 중…</div></section>
  const active = data.notices.filter((n) => n.status === 'active')

  return (
    <div className="stack">
      <MaintenancePanel value={data.maintenance} notify={notify} onSaved={(m) => { setData((d) => (d ? { ...d, maintenance: m } : d)); onChange?.() }} />

      <section className="card panel">
        <div className="panel-head row">
          <h3><Megaphone size={16} /> 공지</h3>
          <span className="panel-hint">
            게시 기간(시작일 ~ 종료일, 양 끝 포함) 동안 로그인한 모든 사용자 화면에 팝업으로 뜹니다 · '오늘 하루 보지 않기' 로 그날은 숨길 수 있고,
            왼쪽 메뉴 [공지사항] 게시판에서 지난 공지 · 첨부 · 댓글을 봅니다
          </span>
          <div className="grow" />
          <button className="btn ghost" disabled={!active.length} onClick={() => setPreview(active)} title="오늘 사용자에게 보이는 팝업 미리보기">미리보기 ({active.length})</button>
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
          <button className="btn primary" disabled={!data.table.ready} onClick={() => setEditing('new')}><Plus size={15} /> 새 공지</button>
        </div>
        {!data.table.ready && (
          <div className="notice-box warn">
            <AlertTriangle size={15} />
            <div>공지사항 테이블이 없습니다 ({data.table.missing.join(', ')}). <b>{data.table.ddl}</b> 를 SS10 스키마에서 실행하세요. 실행 후 1분 안에 등록할 수 있습니다.</div>
          </div>
        )}
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>상태</th><th>구분</th><th>제목</th><th>게시 기간</th><th>수정</th><th /></tr></thead>
            <tbody>
              {data.notices.map((n) => (
                <tr key={n.id} className={n.status === 'ended' || n.status === 'off' ? 'inactive' : ''}>
                  <td><span className={`notice-status ${n.status}`}>{STATUS_LABEL[n.status]}</span></td>
                  <td><span className={`notice-level level-${n.level}`}>{n.levelLabel}</span></td>
                  <td>
                    <div className="strong">{n.title}</div>
                    {n.body && <div className="muted small ellipsis-inline" title={n.body}>{n.body}</div>}
                    <div className="muted small notice-counts">
                      {n.files.length > 0 && <span><Paperclip size={11} /> 첨부 {n.files.length}</span>}
                      {n.images.length > 0 && <span><ImagePlus size={11} /> 이미지 {n.images.length}</span>}
                      {n.commentCount > 0 && <span><MessageSquare size={11} /> 댓글 {n.commentCount}</span>}
                    </div>
                  </td>
                  <td className="nowrap">{n.start} ~ {n.end}</td>
                  <td className="muted small nowrap">{n.updatedBy} {n.updatedAt}</td>
                  <td className="nowrap">
                    <button className="btn ghost sm" onClick={() => setEditing(n)}><Pencil size={12} /> 수정</button>{' '}
                    <button className="btn ghost sm danger" onClick={() => remove(n)}><Trash2 size={12} /> 삭제</button>
                  </td>
                </tr>
              ))}
              {!data.notices.length && <tr><td colSpan={6} className="empty">등록된 공지가 없습니다. [새 공지] 로 추가하세요.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {editing && (
        <NoticeEditor
          notice={editing === 'new' ? null : editing}
          levels={data.levels}
          titleMax={data.titleMax}
          bodyMax={data.bodyMax}
          limits={data.limits}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); notify('공지를 저장했습니다.'); load(); onChange?.() }}
        />
      )}
      {preview && <NoticePopup userId="__preview__" notices={preview} auto={false} onClose={() => setPreview(null)} />}
    </div>
  )
}

function MaintenancePanel({ value, notify, onSaved }: { value: Maintenance; notify: Notify; onSaved: (m: Maintenance) => void }) {
  const [msg, setMsg] = useState(value.message)
  const [until, setUntil] = useState(value.until ? value.until.replace(' ', 'T') : '')
  const [saving, setSaving] = useState(false)

  const save = async (on: boolean) => {
    if (on && !value.on && !confirm('점검 모드를 켜면 관리자 외 사용자는 바로 로그인·사용이 막히고 점검 안내 화면을 봅니다.\n켤까요?')) return
    setSaving(true)
    try {
      const m = await opsApi.setMaintenance({ on, message: msg.trim() || undefined, until: until ? until.replace('T', ' ') : undefined })
      onSaved(m)
      notify(on ? (value.on ? '안내 문구를 저장했습니다.' : '점검 모드를 켰습니다.') : '점검 모드를 껐습니다.')
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={`card panel maint-panel ${value.on ? 'on' : ''}`}>
      <div className="panel-head row">
        <h3><Wrench size={16} /> 점검 모드</h3>
        <span className={`notice-status ${value.on ? 'maint-on' : 'off'}`}>{value.on ? '켜짐 · 관리자 외 접속 차단 중' : '꺼짐'}</span>
        <span className="panel-hint">켜면 관리자 외 사용자는 로그인·사용이 막히고 아래 안내 문구를 봅니다 (이미 접속한 사용자도 다음 요청부터). 관리자는 그대로 쓸 수 있습니다.</span>
      </div>
      <div className="maint-form">
        <label className="field wide">
          <span className="field-label">안내 문구</span>
          <input className="input" value={msg} maxLength={300} onChange={(e) => setMsg(e.target.value)} placeholder="시스템 점검 중입니다. 잠시 후 다시 접속해 주세요." />
        </label>
        <label className="field">
          <span className="field-label">종료 예정 (선택)</span>
          <input className="input" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
        <div className="maint-actions">
          {value.on ? (
            <>
              <button className="btn ghost" disabled={saving} onClick={() => save(true)}><Check size={15} /> 문구 저장</button>
              <button className="btn success" disabled={saving} onClick={() => save(false)}>{saving ? <Loader2 size={15} className="spin" /> : <X size={15} />} 점검 모드 끄기</button>
            </>
          ) : (
            <button className="btn danger-fill" disabled={saving} onClick={() => save(true)}>{saving ? <Loader2 size={15} className="spin" /> : <Wrench size={15} />} 점검 모드 켜기</button>
          )}
        </div>
      </div>
    </section>
  )
}

type Pending = NewNoticeFile & { size: number; key: string }

const readAsDataUrl = (f: File) =>
  new Promise<string>((ok, fail) => {
    const r = new FileReader()
    r.onload = () => ok(String(r.result))
    r.onerror = () => fail(r.error)
    r.readAsDataURL(f)
  })

function NoticeEditor({ notice, levels, titleMax, bodyMax, limits, onClose, onSaved }: {
  notice: Notice | null; levels: Record<NoticeLevel, string>; titleMax: number; bodyMax: number; limits: NoticeLimits
  onClose: () => void; onSaved: () => void
}) {
  const t = todayIso()
  const [form, setForm] = useState<NoticeInput>(notice
    ? { title: notice.title, body: notice.body, level: notice.level, start: notice.start, end: notice.end, use: notice.use }
    : { title: '', body: '', level: 'info', start: t, end: addDays(t, 6), use: true })
  const [kept, setKept] = useState<NoticeFile[]>(notice ? [...notice.images, ...notice.files] : [])
  const [added, setAdded] = useState<Pending[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof NoticeInput>(k: K, v: NoticeInput[K]) => setForm((f) => ({ ...f, [k]: v }))
  const days = form.start && form.end ? Math.round((new Date(form.end).getTime() - new Date(form.start).getTime()) / 86400000) + 1 : null
  const count = (kind: 'image' | 'file') => kept.filter((f) => f.kind === kind).length + added.filter((f) => f.kind === kind).length

  /** 파일 추가 (선택 · 끌어놓기 · 클립보드 붙여넣기). 개수 · 크기 · 형식은 화면에서 먼저 확인하고, 서버가 파일 내용으로 다시 확인한다 */
  const addFiles = async (files: File[], kind: 'image' | 'file') => {
    const max = kind === 'image' ? limits.images : limits.attach
    const mb = kind === 'image' ? limits.imageMb : limits.attachMb
    const label = kind === 'image' ? '본문 이미지' : '첨부파일'
    const out: Pending[] = []
    for (const f of files) {
      const ext = f.name.includes('.') ? f.name.split('.').pop()!.toLowerCase() : ''
      if (kind === 'image' && !/^image\/(png|jpeg|gif|webp)$/.test(f.type)) {
        setError(`본문 이미지는 PNG · JPG · GIF · WEBP 만 넣을 수 있습니다: ${f.name}`)
        continue
      }
      if (kind === 'file' && !limits.attachTypes.includes(ext)) {
        setError(`첨부할 수 없는 형식입니다: ${f.name} (${limits.attachTypes.join(', ')})`)
        continue
      }
      if (f.size > mb * 1024 * 1024) {
        setError(`${label} 하나는 ${mb}MB 까지입니다: ${f.name}`)
        continue
      }
      if (count(kind) + out.length >= max) {
        setError(`${label}는 최대 ${max}개까지입니다.`)
        break
      }
      out.push({ kind, name: f.name, data: await readAsDataUrl(f), size: f.size, key: crypto.randomUUID() })
    }
    if (out.length) setAdded((a) => [...a, ...out])
  }
  // 클립보드 이미지(캡처)는 본문 이미지로. 글자 붙여넣기는 그대로 둔다
  const onPaste = (e: React.ClipboardEvent) => {
    const imgs = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'))
    if (!imgs.length) return
    e.preventDefault()
    setError(null)
    const base = count('image')
    addFiles(imgs.map((f, i) => new File([f], `붙여넣은 이미지 ${base + i + 1}.${f.type.split('/')[1] === 'jpeg' ? 'jpg' : f.type.split('/')[1]}`, { type: f.type })), 'image')
  }
  const drop = (kind: 'image' | 'file') => (e: React.DragEvent) => {
    e.preventDefault()
    setError(null)
    addFiles(Array.from(e.dataTransfer.files), kind)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const body: NoticeInput = { ...form, keepFiles: kept.map((f) => f.no), newFiles: added.map(({ kind, name, data }) => ({ kind, name, data })) }
      if (notice) await opsApi.updateNotice(notice.id, body)
      else await opsApi.createNotice(body)
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const images = [
    ...kept.filter((f) => f.kind === 'image').map((f) => ({ key: `k${f.no}`, src: noticeFileUrl(notice!.id, f.no), name: f.name, remove: () => setKept((k) => k.filter((x) => x !== f)) })),
    ...added.filter((f) => f.kind === 'image').map((f) => ({ key: f.key, src: f.data, name: f.name, remove: () => setAdded((a) => a.filter((x) => x !== f)) })),
  ]
  const files = [
    ...kept.filter((f) => f.kind === 'file').map((f) => ({ key: `k${f.no}`, name: f.name, size: f.size, remove: () => setKept((k) => k.filter((x) => x !== f)) })),
    ...added.filter((f) => f.kind === 'file').map((f) => ({ key: f.key, name: f.name, size: f.size, remove: () => setAdded((a) => a.filter((x) => x !== f)) })),
  ]

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card notice-editor" onPaste={onPaste}>
        <div className="modal-head">
          <h3>{notice ? '공지 수정' : '새 공지'}</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="notice-form">
          <label className="field wide">
            <span className="field-label">제목 <span className="field-hint">{form.title.length} / {titleMax}</span></span>
            <input className="input" value={form.title} maxLength={titleMax} autoFocus onChange={(e) => set('title', e.target.value)} placeholder="예: 10/10(금) 13시 마감 매출 적재 안내" />
          </label>
          <label className="field">
            <span className="field-label">구분</span>
            <select className="input select" value={form.level} onChange={(e) => set('level', e.target.value as NoticeLevel)}>
              {Object.entries(levels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-label">게시 시작일</span>
            <input className="input" type="date" value={form.start} onChange={(e) => set('start', e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">게시 종료일 <span className="field-hint">{days && days > 0 ? `${days}일간` : ''}</span></span>
            <input className="input" type="date" value={form.end} min={form.start} onChange={(e) => set('end', e.target.value)} />
          </label>
          <label className="check-label notice-use" title="끄면 게시 기간 중에도 보이지 않습니다">
            <input type="checkbox" checked={form.use} onChange={(e) => set('use', e.target.checked)} /> 사용
          </label>
          <label className="field full">
            <span className="field-label">내용 <span className="field-hint">{form.body.length} / {bodyMax}</span></span>
            <textarea className="input textarea" rows={6} value={form.body} maxLength={bodyMax} onChange={(e) => set('body', e.target.value)}
              placeholder="줄바꿈은 그대로 보입니다. 캡처한 이미지는 Ctrl+V 로 붙여넣으면 아래 본문 이미지로 들어갑니다." />
          </label>

          <div className="field full">
            <span className="field-label">본문 이미지 <span className="field-hint">{count('image')} / {limits.images}개 · 각 {limits.imageMb}MB · Ctrl+V 붙여넣기 · 끌어놓기</span></span>
            <div className="attach-zone" onDragOver={(e) => e.preventDefault()} onDrop={drop('image')}>
              {images.map((im) => (
                <div key={im.key} className="attach-thumb" title={im.name}>
                  <img src={im.src} alt={im.name} />
                  <button type="button" className="attach-remove" onClick={im.remove} title="빼기"><X size={12} /></button>
                </div>
              ))}
              {count('image') < limits.images && (
                <label className="attach-add">
                  <ImagePlus size={18} /> 이미지 추가
                  <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple hidden
                    onChange={(e) => { setError(null); addFiles(Array.from(e.target.files ?? []), 'image'); e.target.value = '' }} />
                </label>
              )}
            </div>
          </div>

          <div className="field full">
            <span className="field-label">첨부파일 <span className="field-hint">{count('file')} / {limits.attach}개 · 각 {limits.attachMb}MB · {limits.attachTypes.join(', ')}</span></span>
            <div className="attach-zone files" onDragOver={(e) => e.preventDefault()} onDrop={drop('file')}>
              {files.map((f) => (
                <div key={f.key} className="attach-file">
                  <Paperclip size={13} /> <span className="attach-name">{f.name}</span> <span className="muted small">{fileSize(f.size)}</span>
                  <button type="button" className="attach-remove inline" onClick={f.remove} title="빼기"><X size={12} /></button>
                </div>
              ))}
              {count('file') < limits.attach && (
                <label className="attach-add">
                  <Paperclip size={16} /> 파일 선택 · 끌어놓기
                  <input type="file" multiple hidden accept={limits.attachTypes.map((x) => `.${x}`).join(',')}
                    onChange={(e) => { setError(null); addFiles(Array.from(e.target.files ?? []), 'file'); e.target.value = '' }} />
                </label>
              )}
            </div>
          </div>
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="modal-foot">
          <div className="grow" />
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" disabled={saving || !form.title.trim()} onClick={save}>
            {saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} 저장
          </button>
        </div>
      </div>
    </div>
  )
}
