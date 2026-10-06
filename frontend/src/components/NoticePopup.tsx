import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ChevronRight, Info, Megaphone, MessageSquare, X } from 'lucide-react'
import type { Notice } from '../opsApi'
import { hideForToday } from '../noticeHide'
import NoticeContent from './NoticeContent'

const LEVEL_ICON = { important: AlertTriangle, warn: AlertTriangle, info: Info }

/** 로그인 후 공지 팝업 (게시 기간 중 모든 사용자). auto=true 면 자동으로 뜬 것('오늘 하루 보지 않기' 표시), false 면 상단 [공지] 로 연 것.
 *  onOpen: 공지사항 게시판에서 그 공지 열기 (첨부 · 댓글) */
export default function NoticePopup({ userId, notices, auto, onClose, onOpen }: {
  userId: string; notices: Notice[]; auto: boolean; onClose: () => void; onOpen?: (id: string) => void
}) {
  const [hideToday, setHideToday] = useState(false)
  const close = () => {
    if (hideToday) hideForToday(userId, notices.map((n) => n.id))
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
            return (
              <article key={n.id} className={`notice-item level-${n.level}`}>
                <div className="notice-item-head">
                  <span className={`notice-level level-${n.level}`}><Icon size={12} /> {n.levelLabel}</span>
                  <b>{n.title}</b>
                </div>
                <NoticeContent notice={n} />
                <div className="notice-item-foot">
                  <span className="muted small">게시 {n.start}{n.end !== n.start ? ` ~ ${n.end}` : ''}</span>
                  {onOpen && (
                    <button className="btn-link small" onClick={() => { if (hideToday) hideForToday(userId, notices.map((x) => x.id)); onOpen(n.id) }}>
                      <MessageSquare size={12} /> 댓글 {n.commentCount} · 게시판에서 보기 <ChevronRight size={12} />
                    </button>
                  )}
                </div>
              </article>
            )
          })}
          {!notices.length && <div className="empty">게시 중인 공지가 없습니다.</div>}
        </div>
        <div className="modal-foot">
          {auto && notices.length > 0 && (
            <label className="check-label">
              <input type="checkbox" checked={hideToday} onChange={(e) => setHideToday(e.target.checked)} /> 오늘 하루 보지 않기
            </label>
          )}
          <div className="grow" />
          <button className="btn primary" onClick={close}>닫기</button>
        </div>
      </div>
    </div>
  )
}
