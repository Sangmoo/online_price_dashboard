import { Paperclip } from 'lucide-react'
import { fileSize, noticeFileUrl, type Notice } from '../opsApi'

/** 공지 본문 · 본문 이미지 · 첨부파일 (팝업과 게시판 공용). 이미지는 누르면 새 창에서 원본 크기로 */
export default function NoticeContent({ notice }: { notice: Pick<Notice, 'id' | 'body' | 'images' | 'files'> }) {
  return (
    <>
      {notice.body && <div className="notice-body">{notice.body}</div>}
      {notice.images.length > 0 && (
        <div className="notice-images">
          {notice.images.map((img) => (
            <a key={img.no} href={noticeFileUrl(notice.id, img.no)} target="_blank" rel="noreferrer" title={`${img.name} — 원본 보기`}>
              <img src={noticeFileUrl(notice.id, img.no)} alt={img.name} loading="lazy" />
            </a>
          ))}
        </div>
      )}
      {notice.files.length > 0 && (
        <ul className="notice-files">
          {notice.files.map((f) => (
            <li key={f.no}>
              <a href={noticeFileUrl(notice.id, f.no)} download={f.name}>
                <Paperclip size={13} /> {f.name}
              </a>
              <span className="muted small">{fileSize(f.size)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
