import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CornerDownRight, Loader2, Megaphone, MessageSquare, Paperclip, Pencil, Search, Send, Trash2, X } from 'lucide-react'
import type { User } from '../api'
import { opsApi, type Notice, type NoticeComment } from '../opsApi'
import NoticeContent from './NoticeContent'

const STATUS_LABEL: Record<Notice['status'], string> = { active: '게시 중', scheduled: '게시 예정', ended: '지난 공지', off: '사용 안 함' }

/** 공지사항 게시판 (모든 사용자): 게시가 시작된 공지(지난 공지 포함) 목록 · 본문 · 첨부 · 댓글/대댓글. 관리자는 예정 · 사용 안 함 공지도 본다 */
export default function NoticeBoardView({ me, focusId, onChange }: { me: User; focusId?: string; onChange?: () => void }) {
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [list, setList] = useState<Awaited<ReturnType<typeof opsApi.noticeBoard>> | null>(null)
  const [sel, setSel] = useState<string | null>(focusId ?? null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300)
    return () => clearTimeout(t)
  }, [qInput])

  useEffect(() => {
    opsApi
      .noticeBoard(q || undefined)
      .then((r) => {
        setList(r)
        setSel((s) => s ?? r.notices[0]?.id ?? null)
      })
      .catch((e) => setError(e.message))
  }, [q])

  const bumpCount = (id: string, n: number) =>
    setList((l) => (l ? { ...l, notices: l.notices.map((x) => (x.id === id ? { ...x, commentCount: n } : x)) } : l))

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      {list && !list.table.ready && (
        <div className="notice-box warn">
          <AlertTriangle size={15} />
          <div>공지사항 테이블이 아직 없습니다. 관리자가 {list.table.ddl} 를 실행하면 공지가 보입니다.</div>
        </div>
      )}
      <div className="board-layout">
        <section className="card panel board-list">
          <div className="panel-head row">
            <h3><Megaphone size={16} /> 공지사항</h3>
            <span className="panel-hint">{list ? `${list.total}건` : ''}</span>
          </div>
          <div className="search">
            <Search size={15} />
            <input placeholder="제목 · 내용 검색" value={qInput} onChange={(e) => setQInput(e.target.value)} />
            {qInput && <button className="clear" onClick={() => setQInput('')} title="지우기"><X size={14} /></button>}
          </div>
          {!list && <div className="trend-loading"><Loader2 size={18} className="spin" /> 불러오는 중…</div>}
          <ul className="board-items">
            {list?.notices.map((n) => (
              <li key={n.id}>
                <button className={`board-item ${sel === n.id ? 'active' : ''} ${n.status !== 'active' ? 'past' : ''}`} onClick={() => setSel(n.id)}>
                  <div className="board-item-head">
                    <span className={`notice-level level-${n.level}`}>{n.levelLabel}</span>
                    {n.status !== 'active' && <span className={`notice-status ${n.status}`}>{STATUS_LABEL[n.status]}</span>}
                    <b className="board-title">{n.title}</b>
                  </div>
                  <div className="muted small board-meta">
                    {n.start}{n.end !== n.start ? ` ~ ${n.end}` : ''}
                    {n.files.length > 0 && <span><Paperclip size={11} /> {n.files.length}</span>}
                    {n.commentCount > 0 && <span><MessageSquare size={11} /> {n.commentCount}</span>}
                  </div>
                </button>
              </li>
            ))}
            {list && !list.notices.length && <li className="empty">{q ? `‘${q}’ 에 맞는 공지가 없습니다.` : '공지가 없습니다.'}</li>}
          </ul>
        </section>
        <section className="card panel board-detail">
          {sel ? <NoticeDetail key={sel} id={sel} me={me} onComments={(n) => { bumpCount(sel, n); onChange?.() }} /> : <div className="empty">공지를 고르세요.</div>}
        </section>
      </div>
    </div>
  )
}

const countOf = (cs: NoticeComment[]) => cs.reduce((n, c) => n + (c.deleted ? 0 : 1) + (c.replies?.length ?? 0), 0)

function NoticeDetail({ id, me, onComments }: { id: string; me: User; onComments: (count: number) => void }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.noticeDetail>> | null>(null)
  const [comments, setComments] = useState<NoticeComment[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    opsApi
      .noticeDetail(id)
      .then((r) => {
        setData(r)
        setComments(r.notice.comments)
      })
      .catch((e) => setError(e.message))
  }, [id])

  const update = useCallback((cs: NoticeComment[]) => {
    setComments(cs)
    onComments(countOf(cs))
  }, [onComments])

  if (error) return <div className="alert error">{error}</div>
  if (!data) return <div className="trend-loading"><Loader2 size={18} className="spin" /> 불러오는 중…</div>
  const n = data.notice
  return (
    <article className="board-article">
      <header>
        <div className="board-item-head">
          <span className={`notice-level level-${n.level}`}>{n.levelLabel}</span>
          <span className={`notice-status ${n.status}`}>{STATUS_LABEL[n.status]}</span>
        </div>
        <h2>{n.title}</h2>
        <div className="muted small">게시 {n.start} ~ {n.end} · 작성 {n.createdBy} {n.createdAt}{n.updatedAt !== n.createdAt ? ` · 수정 ${n.updatedAt}` : ''}</div>
      </header>
      <div className="board-content">
        <NoticeContent notice={n} />
      </div>
      <Comments noticeId={n.id} me={me} comments={comments} max={data.commentMax} onChange={update} />
    </article>
  )
}

function Comments({ noticeId, me, comments, max, onChange }: {
  noticeId: string; me: User; comments: NoticeComment[]; max: number; onChange: (cs: NoticeComment[]) => void
}) {
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)

  const run = async (p: Promise<{ comments: NoticeComment[] }>) => {
    try {
      onChange((await p).comments)
      return true
    } catch (e) {
      alert((e as Error).message)
      return false
    }
  }
  const remove = (c: NoticeComment) => {
    if (confirm('댓글을 삭제할까요?')) run(opsApi.deleteComment(noticeId, c.id))
  }

  const item = (c: NoticeComment, reply: boolean) => (
    <div key={c.id} className={`comment ${reply ? 'reply' : ''} ${c.deleted ? 'deleted' : ''}`}>
      {reply && <CornerDownRight size={14} className="muted reply-arrow" />}
      <div className="comment-main">
        {c.deleted ? (
          <div className="muted small">삭제된 댓글입니다.</div>
        ) : (
          <>
            <div className="comment-head">
              <b>{c.userName}</b>{c.userId === me.id && <span className="me-tag">나</span>}
              <span className="muted small">{c.createdAt}{c.edited && ' (수정됨)'}</span>
              <div className="grow" />
              {!reply && <button className="btn-link small" onClick={() => setReplyTo(replyTo === c.id ? null : c.id)}>답글</button>}
              {reply && <button className="btn-link small" onClick={() => setReplyTo(replyTo === c.parentId ? null : c.parentId)}>답글</button>}
              {c.canEdit && <button className="btn-link small" onClick={() => setEditing(c.id)}><Pencil size={11} /> 수정</button>}
              {c.canDelete && <button className="btn-link small danger" onClick={() => remove(c)}><Trash2 size={11} /> 삭제</button>}
            </div>
            {editing === c.id ? (
              <CommentForm initial={c.body} max={max} submitLabel="수정" onCancel={() => setEditing(null)}
                onSubmit={async (text) => {
                  const ok = await run(opsApi.editComment(noticeId, c.id, text))
                  if (ok) setEditing(null)
                  return ok
                }} />
            ) : (
              <div className="comment-body">{c.body}</div>
            )}
          </>
        )}
      </div>
    </div>
  )

  return (
    <section className="comments">
      <h4><MessageSquare size={15} /> 댓글 {countOf(comments)}</h4>
      {comments.map((c) => (
        <div key={c.id} className="comment-thread">
          {item(c, false)}
          {c.replies?.map((r) => item(r, true))}
          {replyTo === c.id && (
            <div className="comment reply">
              <CornerDownRight size={14} className="muted reply-arrow" />
              <CommentForm max={max} placeholder={`${c.deleted ? '' : `${c.userName} 님에게 `}답글 쓰기`} submitLabel="답글" autoFocus onCancel={() => setReplyTo(null)}
                onSubmit={async (text) => {
                  const ok = await run(opsApi.addComment(noticeId, text, c.id))
                  if (ok) setReplyTo(null)
                  return ok
                }} />
            </div>
          )}
        </div>
      ))}
      {!comments.length && <div className="muted small">첫 댓글을 남겨 보세요.</div>}
      <CommentForm max={max} placeholder="댓글 쓰기 (Ctrl+Enter 로 등록)" submitLabel="등록" onSubmit={(text) => run(opsApi.addComment(noticeId, text))} />
    </section>
  )
}

function CommentForm({ initial = '', max, placeholder, submitLabel, autoFocus, onSubmit, onCancel }: {
  initial?: string; max: number; placeholder?: string; submitLabel: string; autoFocus?: boolean
  onSubmit: (text: string) => Promise<boolean>; onCancel?: () => void
}) {
  const [text, setText] = useState(initial)
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (!text.trim() || busy) return
    setBusy(true)
    const ok = await onSubmit(text.trim())
    setBusy(false)
    if (ok && !initial) setText('')
  }
  return (
    <div className="comment-form">
      <textarea className="input textarea" rows={2} value={text} maxLength={max} placeholder={placeholder} autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit() }} />
      <div className="comment-form-actions">
        <span className="muted small">{text.length} / {max}</span>
        {onCancel && <button className="btn ghost sm" onClick={onCancel}>취소</button>}
        <button className="btn primary sm" disabled={busy || !text.trim()} onClick={submit}>
          {busy ? <Loader2 size={12} className="spin" /> : <Send size={12} />} {submitLabel}
        </button>
      </div>
    </div>
  )
}
