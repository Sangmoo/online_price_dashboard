import { useEffect, useMemo, useRef, useState } from 'react'
import { ImagePlus, Loader2, MessageSquareWarning, Send, X } from 'lucide-react'
import { api, recentErrors, type Feedback, type FeedbackLimits, type FeedbackType } from '../api'

const TYPES: { key: FeedbackType; label: string; hint: string }[] = [
  { key: 'BUG', label: '오류', hint: '어떤 조작을 했을 때 무엇이 잘못 보였는지 적어 주세요.\n화면 캡처를 붙여넣으면(Ctrl+V) 이미지로 첨부됩니다.' },
  { key: 'REQ', label: '요청', hint: '추가·변경되었으면 하는 기능이나 화면을 적어 주세요.' },
  { key: 'ASK', label: '문의', hint: '숫자의 기준·사용 방법 등 궁금한 점을 적어 주세요.' },
]
const DEFAULT_LIMITS: FeedbackLimits = { maxText: 10_000, maxFiles: 3, maxFileBytes: 5 * 1024 * 1024, types: ['image/gif', 'image/jpeg', 'image/png', 'image/webp'] }

type Pending = { id: number; name: string; size: number; dataUrl: string }

const fmtSize = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`)
const readAsDataUrl = (f: File) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result))
    r.onerror = () => reject(r.error)
    r.readAsDataURL(f)
  })

/** 첨부 이미지 미리보기 (본인·관리자만 받을 수 있는 주소) */
export function FeedbackImages({ f }: { f: Feedback }) {
  if (!f.files?.length) return null
  return (
    <div className="fb-thumbs">
      {f.files.map((x) => {
        const url = `/api/feedback/${encodeURIComponent(f.id)}/files/${x.no}`
        return (
          <a key={x.no} href={url} target="_blank" rel="noreferrer" title={`${x.name} · ${fmtSize(x.size)} (새 창에서 원본 보기)`}>
            <img src={url} alt={x.name} loading="lazy" />
          </a>
        )
      })}
    </div>
  )
}

/** 화면 내 문의·오류 신고: 현재 화면·조회 조건·최근 오류가 자동으로 함께 저장된다. 이미지 최대 3개. 아래에 내 문의와 답변. */
export default function FeedbackModal({ page, pageLabel, context, onClose }: {
  page: string
  pageLabel: string
  context: Record<string, string>
  onClose: () => void
}) {
  const [type, setType] = useState<FeedbackType>('BUG')
  const [content, setContent] = useState('')
  const [images, setImages] = useState<Pending[]>([])
  const [dragging, setDragging] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [mine, setMine] = useState<Feedback[] | null>(null)
  const [limits, setLimits] = useState<FeedbackLimits>(DEFAULT_LIMITS)
  const fileInput = useRef<HTMLInputElement>(null)
  const seq = useRef(0)

  // 창을 연 순간의 화면 상태를 붙인다
  const attached = useMemo(
    () => ({
      page: pageLabel,
      conditions: context,
      url: window.location.pathname + window.location.search,
      screen: `${window.innerWidth}×${window.innerHeight}`,
      browser: navigator.userAgent.replace(/^Mozilla\/5\.0 /, '').slice(0, 160),
      at: new Date().toLocaleString('ko-KR', { hour12: false }),
      errors: recentErrors.slice(-5),
    }),
    [],
  )

  const loadMine = () =>
    api
      .myFeedback()
      .then((d) => {
        setMine(d.rows)
        if (d.limits) setLimits(d.limits)
      })
      .catch(() => setMine([]))
  useEffect(() => {
    loadMine()
  }, [])

  const addFiles = async (files: File[]) => {
    setError(null)
    const imgs = files.filter((f) => f.type.startsWith('image/'))
    if (files.length && !imgs.length) return setError('이미지 파일(PNG · JPG · GIF · WEBP)만 첨부할 수 있습니다.')
    const room = limits.maxFiles - images.length
    if (room <= 0) return setError(`이미지는 최대 ${limits.maxFiles}개까지 첨부할 수 있습니다.`)
    const msgs: string[] = []
    if (imgs.length > room) msgs.push(`이미지는 최대 ${limits.maxFiles}개까지라 ${imgs.length - room}개는 빼었습니다.`)
    const added: Pending[] = []
    for (const f of imgs.slice(0, room)) {
      if (!limits.types.includes(f.type)) {
        msgs.push(`${f.name}: PNG · JPG · GIF · WEBP 만 첨부할 수 있습니다.`)
        continue
      }
      if (f.size > limits.maxFileBytes) {
        msgs.push(`${f.name}: ${fmtSize(f.size)} — 이미지 하나는 ${fmtSize(limits.maxFileBytes)}까지입니다.`)
        continue
      }
      const name = f.name && f.name !== 'image.png' ? f.name : `캡처_${new Date().toTimeString().slice(0, 8).replace(/:/g, '')}.${f.type.split('/')[1]}`
      added.push({ id: ++seq.current, name, size: f.size, dataUrl: await readAsDataUrl(f) })
    }
    setImages((cur) => [...cur, ...added].slice(0, limits.maxFiles))
    if (msgs.length) setError(msgs.join(' '))
  }

  const onPaste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files)
    if (files.length) {
      e.preventDefault()
      addFiles(files)
    }
  }

  const send = async () => {
    setSending(true)
    setError(null)
    try {
      const fb = await api.sendFeedback({
        type, content, page, context: attached, images: images.map((i) => ({ name: i.name, data: i.dataUrl })),
      })
      setDone(`접수되었습니다 (번호 ${fb.id}${fb.files.length ? ` · 이미지 ${fb.files.length}개` : ''}). 답변은 이 창 아래 '내 문의'에서 볼 수 있습니다.`)
      setContent('')
      setImages([])
      loadMine()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSending(false)
    }
  }

  const over = content.length > limits.maxText
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card feedback-modal">
        <div className="modal-head">
          <h3><MessageSquareWarning size={16} /> 문의 · 오류 신고</h3>
          <button className="icon-btn" onClick={onClose} aria-label="닫기"><X size={18} /></button>
        </div>
        <div className="feedback-types seg big" role="radiogroup" aria-label="구분">
          {TYPES.map((t) => (
            <button key={t.key} className={type === t.key ? 'on' : ''} onClick={() => setType(t.key)} role="radio" aria-checked={type === t.key}>{t.label}</button>
          ))}
        </div>
        <div
          className={`feedback-editor ${dragging ? 'dragging' : ''}`}
          onDragOver={(e) => {
            if (Array.from(e.dataTransfer.types).includes('Files')) {
              e.preventDefault()
              setDragging(true)
            }
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            addFiles(Array.from(e.dataTransfer.files))
          }}
        >
          <textarea
            className="input"
            placeholder={TYPES.find((t) => t.key === type)?.hint}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onPaste={onPaste}
            aria-label="내용"
          />
          <div className={`fb-count ${over ? 'over' : ''}`}>{content.length.toLocaleString()} / {limits.maxText.toLocaleString()}자</div>
          {dragging && <div className="fb-drop">여기에 놓으면 이미지가 첨부됩니다</div>}
        </div>
        <div className="fb-attach">
          <button className="btn ghost small" onClick={() => fileInput.current?.click()} disabled={images.length >= limits.maxFiles}>
            <ImagePlus size={15} /> 이미지 첨부 ({images.length}/{limits.maxFiles})
          </button>
          <span className="muted small">파일 선택 · 끌어놓기 · 캡처 붙여넣기(Ctrl+V) · PNG/JPG/GIF/WEBP · 각 {fmtSize(limits.maxFileBytes)}까지</span>
          <input
            ref={fileInput}
            type="file"
            accept={limits.types.join(',')}
            multiple
            hidden
            aria-label="이미지 파일"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
        </div>
        {images.length > 0 && (
          <div className="fb-thumbs pending">
            {images.map((i) => (
              <div key={i.id} className="fb-thumb" title={`${i.name} · ${fmtSize(i.size)}`}>
                <img src={i.dataUrl} alt={i.name} />
                <button className="icon-btn" aria-label={`${i.name} 빼기`} onClick={() => setImages((cur) => cur.filter((x) => x.id !== i.id))}><X size={13} /></button>
                <span>{fmtSize(i.size)}</span>
              </div>
            ))}
          </div>
        )}
        <details className="feedback-ctx">
          <summary>자동으로 함께 보내는 정보: {pageLabel} 화면 · 조회 조건 {Object.keys(context).length}개 · 최근 오류 {attached.errors.length}건</summary>
          <pre>{JSON.stringify(attached, null, 2)}</pre>
        </details>
        {error && <div className="alert error">{error}</div>}
        {done && <div className="alert ok-inline">{done}</div>}
        <div className="row-end">
          <button className="btn ghost" onClick={onClose}>닫기</button>
          <button className="btn primary" disabled={sending || content.trim().length < 2 || over} onClick={send}>
            {sending ? <Loader2 size={15} className="spin" /> : <Send size={15} />} 보내기
          </button>
        </div>

        <h4 className="feedback-mine-title">내 문의</h4>
        {mine === null ? (
          <div className="muted small"><Loader2 size={14} className="spin" /> 불러오는 중…</div>
        ) : mine.length === 0 ? (
          <div className="muted small">아직 남긴 문의가 없습니다.</div>
        ) : (
          <div className="feedback-list">
            {mine.map((f) => (
              <div key={f.id} className="feedback-item">
                <div className="meta">
                  <span className={`fb-status ${f.status}`}>{f.statusLabel}</span>
                  <span>{f.typeLabel}</span>
                  <span>{f.createdAt}</span>
                  <span className="mono">{f.id}</span>
                </div>
                <div className="content">{f.content}</div>
                <FeedbackImages f={f} />
                {f.answer && <div className="answer">{f.answer} <span className="muted small">— {f.answeredAt}</span></div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
