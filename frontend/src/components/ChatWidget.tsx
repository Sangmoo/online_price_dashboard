import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Bot,
  Check,
  Download,
  Loader2,
  Maximize2,
  MessageCircle,
  Minimize2,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  Table2,
  X,
  AlertCircle,
} from 'lucide-react'
import { exportTable, resetChat, streamChat, type ChatEvent, type Column, type Row } from '../api'
import { fmtNum } from '../format'

type Part =
  | { kind: 'text'; text: string }
  | { kind: 'tool'; id: string; label: string; status: 'running' | 'ok' | 'fail' }
  | { kind: 'table'; id: string; title: string; columns: Column[]; rows: Row[]; totalMatched?: number }
  | { kind: 'notice'; text: string; error?: boolean }

type Message = { role: 'user'; text: string } | { role: 'assistant'; parts: Part[]; streaming: boolean }

const RAW_KEYS = new Set(['ONLINE_ID', 'DT', 'INS_DAY'])

const SUGGESTIONS = [
  '최근 수집일 기준 사이트별 수집 건수와 평균 할인율을 알려줘',
  '이번 주 할인율 30% 이상인 상품을 할인율 높은 순으로 보여줘',
  '쿠팡과 SSG.COM의 평균 할인율을 일자별로 비교해줘',
  '최근 7일간 수집 건수가 가장 많이 변한 사이트는?',
]

export default function ChatWidget({ context }: { context: Record<string, string> }) {
  const [open, setOpen] = useState(false)
  const [wide, setWide] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const sessionRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 150)
  }, [open])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }, [input])

  const updateLast = (fn: (parts: Part[]) => Part[], streaming = true) =>
    setMessages((ms) => {
      const last = ms[ms.length - 1]
      if (!last || last.role !== 'assistant') return ms
      return [...ms.slice(0, -1), { ...last, parts: fn(last.parts), streaming }]
    })

  const handleEvent = (e: ChatEvent) => {
    switch (e.type) {
      case 'session':
        sessionRef.current = e.sessionId
        break
      case 'text_start':
        updateLast((p) => [...p, { kind: 'text', text: '' }])
        break
      case 'text':
        updateLast((p) => {
          const last = p[p.length - 1]
          if (last?.kind === 'text') return [...p.slice(0, -1), { ...last, text: last.text + e.text }]
          return [...p, { kind: 'text', text: e.text }]
        })
        break
      case 'tool':
        updateLast((p) => [...p, { kind: 'tool', id: e.id, label: e.label, status: 'running' }])
        break
      case 'tool_done':
        updateLast((p) => p.map((x) => (x.kind === 'tool' && x.id === e.id ? { ...x, status: e.ok ? 'ok' : 'fail' } : x)))
        break
      case 'table':
        updateLast((p) => [...p, { kind: 'table', id: e.id, title: e.title, columns: e.columns, rows: e.rows, totalMatched: e.totalMatched }])
        break
      case 'notice':
        updateLast((p) => [...p, { kind: 'notice', text: e.message }])
        break
      case 'error':
        updateLast((p) => [...p, { kind: 'notice', text: e.message, error: true }])
        break
      case 'done':
        updateLast((p) => p, false)
        break
    }
  }

  const send = async (text: string) => {
    const msg = text.trim()
    if (!msg || busy) return
    setInput('')
    setBusy(true)
    setMessages((ms) => [...ms, { role: 'user', text: msg }, { role: 'assistant', parts: [], streaming: true }])
    const ctl = new AbortController()
    abortRef.current = ctl
    try {
      await streamChat({ message: msg, sessionId: sessionRef.current, context }, handleEvent, ctl.signal)
    } catch (err) {
      if ((err as Error).name === 'AbortError') updateLast((p) => [...p, { kind: 'notice', text: '응답을 중지했습니다.' }], false)
      else updateLast((p) => [...p, { kind: 'notice', text: (err as Error).message, error: true }], false)
    } finally {
      updateLast((p) => p, false)
      setBusy(false)
      abortRef.current = null
    }
  }

  const reset = () => {
    abortRef.current?.abort()
    if (sessionRef.current) resetChat(sessionRef.current)
    sessionRef.current = null
    setMessages([])
  }

  return (
    <>
      <button className={`chat-fab ${open ? 'open' : ''}`} onClick={() => setOpen((o) => !o)} aria-label="AI 데이터 어시스턴트">
        <span className="fab-icon">{open ? <X size={24} /> : <MessageCircle size={26} />}</span>
        {!open && <span className="fab-spark"><Sparkles size={12} /></span>}
        {!open && <span className="fab-ring" />}
      </button>

      <div className={`chat-panel ${open ? 'show' : ''} ${wide ? 'wide' : ''}`} role="dialog" aria-label="AI 데이터 어시스턴트">
        <div className="chat-head">
          <div className="chat-avatar"><Bot size={18} /></div>
          <div className="chat-head-text">
            <div className="chat-title">AI 데이터 어시스턴트</div>
            <div className="chat-sub"><span className="live-dot" /> Claude · 수집 데이터 기반으로만 답변</div>
          </div>
          <button className="icon-btn ghost" title="새 대화" onClick={reset}><RotateCcw size={16} /></button>
          <button className="icon-btn ghost" title={wide ? '작게' : '크게'} onClick={() => setWide((w) => !w)}>
            {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
          <button className="icon-btn ghost" title="닫기" onClick={() => setOpen(false)}><X size={18} /></button>
        </div>

        <div className="chat-body" ref={listRef}>
          {messages.length === 0 ? (
            <div className="chat-welcome">
              <div className="welcome-badge"><Sparkles size={22} /></div>
              <h4>무엇을 분석해 드릴까요?</h4>
              <p>온라인 가격 수집 데이터(T_SELECT_ONLINE_MNG_R)만 조회해서 답변합니다. 조회된 표는 엑셀로 내려받을 수 있어요.</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="msg user"><div className="bubble">{m.text}</div></div>
              ) : (
                <div key={i} className="msg assistant">
                  <div className="msg-avatar"><Bot size={15} /></div>
                  <div className="msg-content">
                    {m.parts.map((p, j) => <PartView key={j} part={p} />)}
                    {m.streaming && !m.parts.some((p) => p.kind === 'text' && p.text) && (
                      <div className="typing"><span /><span /><span /></div>
                    )}
                  </div>
                </div>
              ),
            )
          )}
        </div>

        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(input) }}>
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            placeholder="데이터에 대해 질문하세요 (Shift+Enter 줄바꿈)"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                send(input)
              }
            }}
          />
          {busy ? (
            <button type="button" className="send stop" title="중지" onClick={() => abortRef.current?.abort()}><Square size={14} /></button>
          ) : (
            <button type="submit" className="send" disabled={!input.trim()} title="보내기"><Send size={16} /></button>
          )}
        </form>
      </div>
    </>
  )
}

function PartView({ part }: { part: Part }) {
  if (part.kind === 'text')
    return part.text ? (
      <div className="md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
      </div>
    ) : null
  if (part.kind === 'tool')
    return (
      <div className={`tool-chip ${part.status}`}>
        {part.status === 'running' ? <Loader2 size={13} className="spin" /> : part.status === 'ok' ? <Check size={13} /> : <AlertCircle size={13} />}
        {part.label}
      </div>
    )
  if (part.kind === 'notice') return <div className={`notice ${part.error ? 'error' : ''}`}>{part.text}</div>
  return <TableCard part={part} />
}

function TableCard({ part }: { part: Extract<Part, { kind: 'table' }> }) {
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const rows = expanded ? part.rows : part.rows.slice(0, 5)
  const cols = part.columns.filter((c) => c.key !== 'URL')
  const save = async () => {
    setSaving(true)
    try {
      await exportTable(part.title, part.columns, part.rows)
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="data-card">
      <div className="data-card-head">
        <Table2 size={14} />
        <span className="data-card-title" title={part.title}>{part.title}</span>
        <span className="muted">
          {fmtNum(part.rows.length)}행{part.totalMatched !== undefined && part.totalMatched > part.rows.length ? ` / 전체 ${fmtNum(part.totalMatched)}` : ''}
        </span>
        <button className="mini-btn" onClick={save} disabled={saving}>
          {saving ? <Loader2 size={12} className="spin" /> : <Download size={12} />} 엑셀
        </button>
      </div>
      <div className={`data-card-table ${expanded ? 'expanded' : ''}`}>
        <table>
          <thead>
            <tr>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c.key} className={typeof r[c.key] === 'number' ? 'num' : ''} title={String(r[c.key] ?? '')}>
                    {typeof r[c.key] === 'number' && !RAW_KEYS.has(c.key) ? fmtNum(r[c.key]) : (r[c.key] ?? '-')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {part.rows.length > 5 && (
        <button className="data-card-more" onClick={() => setExpanded((e) => !e)}>
          {expanded ? '접기' : `전체 ${fmtNum(part.rows.length)}행 보기`}
        </button>
      )}
    </div>
  )
}
