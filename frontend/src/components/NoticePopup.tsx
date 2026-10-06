import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, BadgeCheck, ChevronRight, Info, Loader2, Megaphone, MessageSquare, Pin, X } from 'lucide-react'
import type { Notice } from '../opsApi'
import { hideForToday } from '../noticeHide'
import NoticeContent from './NoticeContent'

const LEVEL_ICON = { important: AlertTriangle, warn: AlertTriangle, info: Info }

/** 로그인 후 공지 팝업 (게시 기간 중 대상 사용자). auto=true 면 자동으로 뜬 것('오늘 하루 보지 않기' 표시), false 면 상단 [공지] 로 연 것.
 *  필독 공지는 [확인했습니다] 를 눌러야 다음 접속 때 다시 뜨지 않는다 ('오늘 하루 보지 않기' 로는 숨겨지지 않음).
 *  onOpen: 공지사항 게시판에서 그 공지 열기 (첨부 · 댓글) · onAck: 필독 확인 */
export default function NoticePopup({ userId, notices, auto, onClose, onOpen, onAck }: {
  userId: string; notices: Notice[]; auto: boolean; onClose: () => void; onOpen?: (id: string) => void
  onAck?: (id: string) => Promise<void>
}) {
  const [hideToday, setHideToday] = useState(false)
  const [acking, setAcking] = useState<string | null>(null)
  const [acked, setAcked] = useState<Set<string>>(() => new Set(notices.filter((n) => n.acked).map((n) => n.id)))
  const hideable = notices.filter((n) => !n.mustAck).map((n) => n.id)
  const close = () => {
    if (hideToday && hideable.length) hideForToday(userId, hideable)
    onClose()
  }
  const closeRef = useRef(onClose)   // Esc 감시는 한 번만 등록 (화면이 다시 그려져도 유지)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [])

  const ack = async (id: string) => {
    if (!onAck) return
    setAcking(id)
    try {
      await onAck(id)
      setAcked((s) => new Set(s).add(id))
    } catch (e) {
      alert((e as Error).message)
    } finally {
      setAcking(null)
    }
  }

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal card notice-modal" role="dialog" aria-label="공지사항">
        <div className="modal-head">
          <h3><Megaphone size={17} /> 공지사항 {notices.length > 1 && <span className="muted small">{notices.length}건</span>}</h3>
          <button className="icon-btn" onClick={close} title="닫기"><X size={18} /></button>
        </div>
        <div className="notice-list">
          {notices.map((n) => {
            const Icon = LEVEL_ICON[n.level] ?? Info
            const done = acked.has(n.id)
            return (
              <article key={n.id} className={`notice-item level-${n.level} ${n.mustAck && !done ? 'must-ack' : ''}`}>
                <div className="notice-item-head">
                  <span className={`notice-level level-${n.level}`}><Icon size={12} /> {n.levelLabel}</span>
                  {n.mustAck && <span className="notice-must"><BadgeCheck size={12} /> 필독</span>}
                  {n.pin && <Pin size={13} className="muted" aria-label="상단 고정" />}
                  <b>{n.title}</b>
                </div>
                <NoticeContent notice={n} />
                <div className="notice-item-foot">
                  <span className="muted small">게시 {n.start}{n.end !== n.start ? ` ~ ${n.end}` : ''}</span>
                  <div className="notice-item-actions">
                    {onOpen && (
                      <button className="btn-link small" onClick={() => { if (hideToday && hideable.length) hideForToday(userId, hideable); onOpen(n.id) }}>
                        <MessageSquare size={12} /> 댓글 {n.commentCount} · 게시판에서 보기 <ChevronRight size={12} />
                      </button>
                    )}
                    {n.mustAck && (done
                      ? <span className="notice-acked"><BadgeCheck size={13} /> 확인함</span>
                      : onAck && (
                        <button className="btn primary sm" disabled={acking === n.id} onClick={() => ack(n.id)}>
                          {acking === n.id ? <Loader2 size={12} className="spin" /> : <BadgeCheck size={12} />} 확인했습니다
                        </button>
                      ))}
                  </div>
                </div>
              </article>
            )
          })}
          {!notices.length && <div className="empty">게시 중인 공지가 없습니다.</div>}
        </div>
        <div className="modal-foot">
          {auto && hideable.length > 0 && (
            <label className="check-label">
              <input type="checkbox" checked={hideToday} onChange={(e) => setHideToday(e.target.checked)} /> 오늘 하루 보지 않기
              {hideable.length < notices.length && <span className="muted small">(필독 제외)</span>}
            </label>
          )}
          <div className="grow" />
          <button className="btn primary" onClick={close}>닫기</button>
        </div>
      </div>
    </div>
  )
}
