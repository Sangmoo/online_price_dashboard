import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  ChevronDown,
  ChevronUp,
  AlertCircle,
  BarChart3,
  Bot,
  Check,
  CheckCircle2,
  Download,
  History,
  Loader2,
  Maximize2,
  MessageCircle,
  Minimize2,
  Pencil,
  Plus,
  Send,
  Sparkles,
  Square,
  Star,
  Table2,
  Trash2,
  X,
} from 'lucide-react'
import {
  api,
  exportFullTable,
  exportTable,
  streamChat,
  type ChatEvent,
  type Column,
  type ConversationSummary,
  type Favorite,
  type MallShopSaveItem,
  type Row,
  type Usage,
  type User,
} from '../api'
import { compact, fmtNum } from '../format'

type Part =
  | { kind: 'text'; text: string }
  | { kind: 'tool'; id: string; label: string; status: 'running' | 'ok' | 'fail'; name?: string; input?: Record<string, unknown> }
  | {
      kind: 'table'
      id: string
      title: string
      columns: Column[]
      rows: Row[]
      totalMatched?: number
      truncated?: boolean
      source?: { tool: string; input: Record<string, unknown> } // 잘린 표: 전체 결과 엑셀용
    }
  | { kind: 'notice'; text: string; error?: boolean }
  // AI 가 만든 변경안: 사용자가 [적용]을 눌러야 저장 (예: 판매처 매장 연결)
  | { kind: 'action'; id: string; actionKind: 'mall_shop_save'; title: string; items: MallShopSaveItem[]; lines: string[]; warnings: string[] }

type Message = { role: 'user'; text: string } | { role: 'assistant'; parts: Part[]; streaming?: boolean }

const PRICE_SUGGESTIONS = [
  '최근 수집일 기준 사이트별 수집 건수와 평균 할인율을 알려줘',
  '이번 주 할인율 30% 이상인 상품을 할인율 높은 순으로 보여줘',
  '최근 7일간 일자별 수집 건수 추이를 보여줘',
]
const INVT_SUGGESTIONS = [
  '실사예정일이 미정인 매장 목록을 경과일 순으로 보여줘',
  '권역별 실사계획 건수와 업체 예상 비용 합계를 알려줘',
  '실사예정월별 계획 건수와 예상 비용을 정리해줘',
]
const SALE_SUGGESTIONS = [
  '지난달 매장별 실판금액 상위 10개 매장을 알려줘',
  '최근 12개월 월별 수량과 실판금액 추이를 보여줘',
  '지난달 시즌별 판매 수량과 실판금액을 정리해줘',
]
const SALE_DASH_SUGGESTIONS = [
  '지난달 판매 현황을 전년 동월과 비교해서 요약해줘',
  '올해 누계 실판금액과 원가율을 전년과 비교해줘',
  '지난달 브랜드별·팀별 목표 달성률을 정리해줘',
  '올해 1월부터 지난달까지 목표 달성률이 낮은 매장을 알려줘',
  '지난달 전년 대비 많이 하락한 매장과 이유가 될 만한 점을 알려줘',
]
const RAW_KEYS = new Set(['ONLINE_ID', 'DT', 'INS_DAY', 'PLAN_ID', 'MAKE_YYMM', 'PLAN_YY', 'ym', 'rank'])

export default function ChatWidget({ user, context }: { user: User; context: Record<string, string> }) {
  const [open, setOpen] = useState(false)
  const [wide, setWide] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [convId, setConvId] = useState<string | null>(null)
  const [convTitle, setConvTitle] = useState<string>('')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState<ConversationSummary[]>([])
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [favOpen, setFavOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const refreshHistory = useCallback(() => api.conversations().then((r) => setHistory(r.conversations)).catch(() => undefined), [])

  useEffect(() => {
    if (!open) return
    setTimeout(() => inputRef.current?.focus(), 150)
    api.usage().then(setUsage).catch(() => undefined)
    api.favorites().then((r) => setFavorites(r.favorites)).catch(() => undefined)
    refreshHistory()
  }, [open, refreshHistory])

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

  const limitReached = !!usage && (usage.questions >= usage.questionLimit || usage.costUsd >= usage.costLimitUsd)
  const favSet = useMemo(() => new Set(favorites.map((f) => f.text)), [favorites])
  // 메뉴 권한에 맞는 추천 질문 (보고 있는 화면의 데이터를 먼저)
  const suggestions = useMemo(() => {
    const price = user.pages.includes('dashboard') || user.pages.includes('detail') ? PRICE_SUGGESTIONS : []
    const invt = user.pages.includes('invt_plan') ? INVT_SUGGESTIONS : []
    const sale = user.pages.includes('sale_monthly') ? SALE_SUGGESTIONS : []
    const dash = user.pages.includes('sale_dashboard') || user.pages.includes('sale_monthly') ? SALE_DASH_SUGGESTIONS : []
    if (context.view === 'invt_plan') return [...invt, ...dash, ...sale, ...price].slice(0, 4)
    if (context.view === 'sale_dashboard') return [...dash, ...sale, ...invt, ...price].slice(0, 4)
    if (context.view === 'sale_monthly') return [...sale, ...dash, ...invt, ...price].slice(0, 4)
    return [...price, ...dash, ...sale, ...invt].slice(0, 4)
  }, [user.pages, context.view])

  const updateLast = (fn: (parts: Part[]) => Part[], streaming = true) =>
    setMessages((ms) => {
      const last = ms[ms.length - 1]
      if (!last || last.role !== 'assistant') return ms
      return [...ms.slice(0, -1), { ...last, parts: fn(last.parts), streaming }]
    })

  const handleEvent = (e: ChatEvent) => {
    switch (e.type) {
      case 'conversation':
        setConvId(e.id)
        setConvTitle(e.title)
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
        updateLast((p) => [...p, { kind: 'tool', id: e.id, label: e.label, status: 'running', name: e.name, input: (e.input ?? undefined) as Record<string, unknown> | undefined }])
        break
      case 'tool_done':
        updateLast((p) => p.map((x) => (x.kind === 'tool' && x.id === e.id ? { ...x, status: e.ok ? 'ok' : 'fail' } : x)))
        break
      case 'table':
        updateLast((p) => [...p, { kind: 'table', id: e.id, title: e.title, columns: e.columns, rows: e.rows, totalMatched: e.totalMatched, truncated: e.truncated, source: e.source }])
        break
      case 'notice':
        updateLast((p) => [...p, { kind: 'notice', text: e.message }])
        break
      case 'action':
        updateLast((p) => [...p, { kind: 'action', id: e.id, actionKind: e.actionKind, title: e.title, items: e.items, lines: e.lines, warnings: e.warnings ?? [] }])
        break
      case 'error':
        updateLast((p) => [...p, { kind: 'notice', text: e.message, error: true }])
        break
      case 'usage': {
        const { type: _t, ...u } = e
        void _t
        setUsage(u)
        break
      }
      case 'done':
        updateLast((p) => p, false)
        break
    }
  }

  const send = async (text: string) => {
    const msg = text.trim()
    if (!msg || busy) return
    setInput('')
    setFavOpen(false)
    setHistoryOpen(false)
    setBusy(true)
    setMessages((ms) => [...ms, { role: 'user', text: msg }, { role: 'assistant', parts: [], streaming: true }])
    const ctl = new AbortController()
    abortRef.current = ctl
    try {
      await streamChat({ message: msg, conversationId: convId, context }, handleEvent, ctl.signal)
    } catch (err) {
      if ((err as Error).name === 'AbortError') updateLast((p) => [...p, { kind: 'notice', text: '응답을 중지했습니다.' }], false)
      else updateLast((p) => [...p, { kind: 'notice', text: (err as Error).message, error: true }], false)
    } finally {
      updateLast((p) => p, false)
      setBusy(false)
      abortRef.current = null
      refreshHistory()
    }
  }

  const newChat = () => {
    abortRef.current?.abort()
    setConvId(null)
    setConvTitle('')
    setMessages([])
    setHistoryOpen(false)
  }

  const openConversation = async (id: string) => {
    abortRef.current?.abort()
    try {
      const c = await api.conversation(id)
      setConvId(c.id)
      setConvTitle(c.title)
      setMessages(c.messages as Message[])
      setHistoryOpen(false)
    } catch (e) {
      alert((e as Error).message)
    }
  }

  const removeConversation = async (id: string) => {
    if (!confirm('이 대화를 삭제할까요?')) return
    await api.deleteConversation(id).catch(() => undefined)
    if (id === convId) newChat()
    refreshHistory()
  }

  const renameConversation = async (c: ConversationSummary) => {
    const title = prompt('대화 제목', c.title)?.trim()
    if (!title) return
    await api.renameConversation(c.id, title).catch(() => undefined)
    if (c.id === convId) setConvTitle(title)
    refreshHistory()
  }

  const toggleFavorite = async (text: string) => {
    const existing = favorites.find((f) => f.text === text.split(/\s+/).join(' '))
    const r = existing ? await api.deleteFavorite(existing.id) : await api.addFavorite(text)
    setFavorites(r.favorites)
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
            <div className="chat-title" title={convTitle}>{convTitle || 'AI 데이터 어시스턴트'}</div>
            <div className="chat-sub"><span className="live-dot" /> Claude · 서비스 데이터 기반으로만 답변</div>
          </div>
          <button className={`icon-btn ghost ${historyOpen ? 'on' : ''}`} title="대화 기록" onClick={() => setHistoryOpen((h) => !h)}><History size={16} /></button>
          <button className="icon-btn ghost" title="새 대화" onClick={newChat}><Plus size={17} /></button>
          <button className="icon-btn ghost" title={wide ? '작게' : '크게'} onClick={() => setWide((w) => !w)}>
            {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
          <button className="icon-btn ghost" title="닫기" onClick={() => setOpen(false)}><X size={18} /></button>
        </div>

        {usage && <UsageBar usage={usage} />}

        <div className="chat-main">
          {historyOpen && (
            <div className="chat-history">
              <div className="chat-history-head">
                <span>대화 기록</span>
                <button className="btn-link" onClick={newChat}><Plus size={13} /> 새 대화</button>
              </div>
              {history.length === 0 && <div className="muted small-pad">저장된 대화가 없습니다.</div>}
              {history.map((c) => (
                <div key={c.id} className={`history-item ${c.id === convId ? 'active' : ''}`} onClick={() => openConversation(c.id)}>
                  <div className="history-text">
                    <div className="history-title">{c.title}</div>
                    <div className="history-date">{c.updatedAt}</div>
                  </div>
                  <button className="icon-btn tiny" title="이름 변경" onClick={(e) => { e.stopPropagation(); renameConversation(c) }}><Pencil size={13} /></button>
                  <button className="icon-btn tiny danger" title="삭제" onClick={(e) => { e.stopPropagation(); removeConversation(c.id) }}><Trash2 size={13} /></button>
                </div>
              ))}
            </div>
          )}

          <div className="chat-body" ref={listRef}>
            {messages.length === 0 ? (
              <div className="chat-welcome">
                <div className="welcome-badge"><Sparkles size={22} /></div>
                <h4>{user.name}님, 무엇을 분석해 드릴까요?</h4>
                <p>ERP 영업 관리의 데이터(온라인 가격, 매장 재고 실사계획) 중 권한이 있는 메뉴의 데이터만 조회해서 답변합니다. 조회된 표는 차트로 보거나 엑셀로 내려받을 수 있어요.</p>
                {favorites.length > 0 && (
                  <>
                    <div className="welcome-section"><Star size={13} /> 즐겨찾는 질문</div>
                    <div className="suggestions">
                      {favorites.slice(0, 6).map((f) => (
                        <button key={f.id} className="fav" onClick={() => send(f.text)} disabled={limitReached}>{f.text}</button>
                      ))}
                    </div>
                  </>
                )}
                <div className="welcome-section"><Sparkles size={13} /> 추천 질문</div>
                <div className="suggestions">
                  {suggestions.map((s) => (
                    <button key={s} onClick={() => send(s)} disabled={limitReached}>{s}</button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) =>
                m.role === 'user' ? (
                  <div key={i} className="msg user">
                    <button
                      className={`fav-toggle ${favSet.has(m.text.split(/\s+/).join(' ')) ? 'on' : ''}`}
                      title={favSet.has(m.text.split(/\s+/).join(' ')) ? '즐겨찾기 해제' : '즐겨찾기에 추가'}
                      onClick={() => toggleFavorite(m.text)}
                    >
                      <Star size={13} />
                    </button>
                    <div className="bubble">{m.text}</div>
                  </div>
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
        </div>

        {favOpen && (
          <div className="fav-pop">
            <div className="fav-pop-head">즐겨찾는 질문</div>
            {favorites.length === 0 && <div className="muted small-pad">질문 말풍선의 ☆ 를 눌러 추가하세요.</div>}
            {favorites.map((f) => (
              <div key={f.id} className="fav-row">
                <button className="fav-text" onClick={() => send(f.text)} disabled={limitReached || busy}>{f.text}</button>
                <button className="icon-btn tiny danger" title="삭제" onClick={() => api.deleteFavorite(f.id).then((r) => setFavorites(r.favorites))}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        )}

        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(input) }}>
          <button type="button" className={`fav-btn ${favOpen ? 'on' : ''}`} title="즐겨찾는 질문" onClick={() => setFavOpen((o) => !o)}>
            <Star size={16} />
          </button>
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            maxLength={2000}
            disabled={limitReached}
            placeholder={limitReached ? '오늘 사용 한도에 도달했습니다.' : '데이터에 대해 질문하세요 (Shift+Enter 줄바꿈)'}
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
            <button type="submit" className="send" disabled={!input.trim() || limitReached} title="보내기"><Send size={16} /></button>
          )}
        </form>
      </div>
    </>
  )
}

function UsageBar({ usage }: { usage: Usage }) {
  const qPct = Math.min(100, (usage.questions / Math.max(usage.questionLimit, 1)) * 100)
  const cPct = Math.min(100, (usage.costUsd / Math.max(usage.costLimitUsd, 0.0001)) * 100)
  const tone = (p: number) => (p >= 100 ? 'full' : p >= 80 ? 'warn' : '')
  return (
    <div className="usage-bar">
      <div className="usage-item" title="오늘 질문 수 / 일일 한도">
        <span>질문</span>
        <div className={`meter ${tone(qPct)}`}><i style={{ width: `${qPct}%` }} /></div>
        <b>{usage.questions}/{usage.questionLimit}</b>
      </div>
      <div className="usage-item" title="오늘 AI 사용 비용 / 일일 한도 (USD)">
        <span>비용</span>
        <div className={`meter ${tone(cPct)}`}><i style={{ width: `${cPct}%` }} /></div>
        <b>${usage.costUsd.toFixed(2)}/${usage.costLimitUsd.toFixed(2)}</b>
      </div>
    </div>
  )
}

function PartView({ part }: { part: Part }) {
  if (part.kind === 'text')
    return part.text ? (
      <div className="md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
      </div>
    ) : null
  if (part.kind === 'tool') return <ToolChip part={part} />
  if (part.kind === 'notice') return <div className={`notice ${part.error ? 'error' : ''}`}>{part.text}</div>
  if (part.kind === 'action') return <ActionCard part={part} />
  return <TableCard part={part} />
}

/** AI 변경안 카드: 사용자가 내용을 보고 [적용]을 눌러야 화면과 같은 저장 경로(같은 권한·검증·변경 이력)로 저장된다. */
function ActionCard({ part }: { part: Extract<Part, { kind: 'action' }> }) {
  const [state, setState] = useState<'idle' | 'saving' | 'done' | 'error'>('idle')
  const [msg, setMsg] = useState<string | null>(null)
  const apply = async () => {
    if (!confirm(`${part.title}을 저장할까요?\n\n${part.lines.join('\n')}`)) return
    setState('saving')
    try {
      const r = await api.mallShops.save(part.items)
      setState('done')
      setMsg(`저장했습니다 · 등록·수정 ${r.saved}건 · 해제 ${r.deleted}건`)
    } catch (e) {
      setState('error')
      setMsg((e as Error).message)
    }
  }
  return (
    <div className={`action-card ${state}`}>
      <div className="action-head"><b>{part.title}</b><span className="muted small">아직 저장 전 · 확인 후 [적용]</span></div>
      <ul>{part.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
      {part.warnings.length > 0 && <div className="action-warn">{part.warnings.map((w, i) => <div key={i}><AlertCircle size={12} /> {w}</div>)}</div>}
      <div className="action-foot">
        {msg && <span className={state === 'error' ? 'up small' : 'small'}>{state === 'done' && <CheckCircle2 size={13} />} {msg}</span>}
        <button className="btn primary small" disabled={state === 'saving' || state === 'done'} onClick={apply}>
          {state === 'saving' ? <Loader2 size={14} className="spin" /> : <Check size={14} />} {state === 'done' ? '적용됨' : '적용'}
        </button>
      </div>
    </div>
  )
}

// AI 가 도구에 넘긴 조회 조건 이름 (답변 근거 보기)
const ARG_LABELS: Record<string, string> = {
  ym: '기준 월', ym_from: '시작 판매년월', ym_to: '끝 판매년월', compare: '비교 기준', compare_from: '비교 시작 월', compare_to: '비교 끝 월',
  brand: '브랜드', sections: '조회 부분', group_by: '묶음', metrics: '지표', order_by: '정렬', order_dir: '정렬 방향', limit: '최대 행 수',
  shop_ids: '매장코드', shop_nm: '매장명', team_cd: '팀', team: '팀', rep: '담당 영업직원', include_closed: '폐점 포함',
  plan_yys: '기획년도', seasons: '시즌', prdt_grp_nm: '품군', item_nm: '아이템', prdt_cd: '상품코드', date_from: '시작일', date_to: '끝일',
  mall_nm: '사이트', title_contains: '제목 포함', min_dc_rate: '최소 할인율', max_dc_rate: '최대 할인율', q: '검색어',
  plan_yy: '기획년도', season: '시즌', only_alerts: '주의 상품만', parts: '조회 부분', by_item: '아이템별', include_event: '행사·특판 매장 포함',
}
const CMP_LABELS: Record<string, string> = { yoy: '전년 동기', prev: '직전 기간', custom: '직접 선택' }

function fmtArg(k: string, v: unknown): string {
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'boolean') return v ? '예' : '아니오'
  if (k === 'compare' && typeof v === 'string') return CMP_LABELS[v] ?? v
  if (typeof v === 'string' && /^\d{6}$/.test(v) && /ym/.test(k)) return `${v.slice(0, 4)}-${v.slice(4)}`
  return String(v)
}

/** 도구 실행 표시. 누르면 AI 가 어떤 조건으로 조회했는지(답변 근거) 펼친다. */
function ToolChip({ part }: { part: Extract<Part, { kind: 'tool' }> }) {
  const [open, setOpen] = useState(false)
  const args = Object.entries(part.input ?? {}).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && v.length === 0))
  const icon = part.status === 'running' ? <Loader2 size={13} className="spin" /> : part.status === 'ok' ? <Check size={13} /> : <AlertCircle size={13} />
  if (!part.input) return <div className={`tool-chip ${part.status}`}>{icon}{part.label}</div>
  return (
    <div className="tool-basis">
      <button className={`tool-chip ${part.status} clickable`} onClick={() => setOpen((o) => !o)} title="조회 조건 보기" aria-expanded={open}>
        {icon}
        {part.label}
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <div className="tool-args">
          <div className="muted small">조회 조건{part.name ? ` · 도구 ${part.name}` : ''}</div>
          {args.length ? (
            <dl>
              {args.map(([k, v]) => (
                <div key={k}><dt>{ARG_LABELS[k] ?? k}</dt><dd>{fmtArg(k, v)}</dd></div>
              ))}
            </dl>
          ) : (
            <div className="small">조건 없음 (도구 기본값)</div>
          )}
        </div>
      )}
    </div>
  )
}

function TableCard({ part }: { part: Extract<Part, { kind: 'table' }> }) {
  const [mode, setMode] = useState<'table' | 'chart'>('table')
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savingFull, setSavingFull] = useState(false)
  const [fullError, setFullError] = useState<string | null>(null)
  const cols = part.columns.filter((c) => c.key !== 'URL')
  const rows = expanded ? part.rows : part.rows.slice(0, 5)

  // 차트: 범주(문자) 컬럼 1개 + 숫자 지표 선택
  const categoryCol = useMemo(() => {
    const prefer = ['DT', 'PLAN_MONTH', 'LAST_INVT_YEAR', 'MALL_NM', 'REGION_NM', 'AREA_NM', 'BRD_NM', 'STLM_TEAM',
      'SHOP_FORM_NM', 'PREV_INVT_TYPE', 'SHOP_RANK_NM', 'SHOP_NM', 'PRDT_CD', 'NAVER_PAY_SELL_NO', 'TITLE']
    return prefer.find((k) => part.columns.some((c) => c.key === k)) ?? part.columns.find((c) => typeof part.rows[0]?.[c.key] === 'string')?.key
  }, [part])
  const metrics = useMemo(
    () => part.columns.filter((c) => !RAW_KEYS.has(c.key) && part.rows.some((r) => typeof r[c.key] === 'number')),
    [part],
  )
  const [metric, setMetric] = useState(() => metrics.find((m) => m.key === 'AVG_DC_RATE' || m.key === 'ROW_CNT' || m.key === 'DC_RATE')?.key ?? metrics[0]?.key)
  const canChart = !!categoryCol && metrics.length > 0 && part.rows.length > 1

  const save = async () => {
    setSaving(true)
    try {
      await exportTable(part.title, part.columns, part.rows)
    } finally {
      setSaving(false)
    }
  }

  const saveFull = async () => {
    if (!part.source) return
    setSavingFull(true)
    setFullError(null)
    try {
      await exportFullTable(part.title, part.source)
    } catch (e) {
      setFullError((e as Error).message)
    } finally {
      setSavingFull(false)
    }
  }
  const fullLabel = part.totalMatched !== undefined ? `전체 ${fmtNum(Math.min(part.totalMatched, 100_000))}행` : '전체'

  return (
    <div className="data-card">
      <div className="data-card-head">
        <Table2 size={14} />
        <span className="data-card-title" title={part.title}>{part.title}</span>
        <span className="muted">
          {fmtNum(part.rows.length)}행{part.totalMatched !== undefined && part.totalMatched > part.rows.length ? ` / 전체 ${fmtNum(part.totalMatched)}` : ''}
        </span>
        {canChart && (
          <div className="seg">
            <button className={mode === 'table' ? 'on' : ''} onClick={() => setMode('table')} title="표"><Table2 size={12} /></button>
            <button className={mode === 'chart' ? 'on' : ''} onClick={() => setMode('chart')} title="차트"><BarChart3 size={12} /></button>
          </div>
        )}
        <button className="mini-btn" onClick={save} disabled={saving}>
          {saving ? <Loader2 size={12} className="spin" /> : <Download size={12} />} 엑셀
        </button>
        {part.source && (
          <button className="mini-btn" onClick={saveFull} disabled={savingFull} title="AI 에게 보인 일부가 아니라, 같은 조건의 전체 결과(최대 10만 행)를 다시 조회해 엑셀로 받습니다.">
            {savingFull ? <Loader2 size={12} className="spin" /> : <Download size={12} />} {fullLabel} 엑셀
          </button>
        )}
      </div>
      {fullError && <div className="notice error">{fullError}</div>}

      {mode === 'chart' && canChart ? (
        <ResultChart part={part} categoryCol={categoryCol!} metric={metric!} metrics={metrics} onMetric={setMetric} />
      ) : (
        <>
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
        </>
      )}
    </div>
  )
}

function ResultChart({
  part,
  categoryCol,
  metric,
  metrics,
  onMetric,
}: {
  part: Extract<Part, { kind: 'table' }>
  categoryCol: string
  metric: string
  metrics: Column[]
  onMetric: (k: string) => void
}) {
  const isTime = categoryCol === 'DT'
  const data = useMemo(() => {
    let rows = part.rows.filter((r) => typeof r[metric] === 'number')
    if (isTime) rows = [...rows].sort((a, b) => String(a.DT).localeCompare(String(b.DT)))
    else rows = rows.slice(0, 20)
    // 같은 범주가 여러 행이면(예: 일자+사이트 그룹) 범주명에 두 번째 문자열 컬럼을 덧붙임
    const second = part.columns.find((c) => c.key !== categoryCol && typeof part.rows[0]?.[c.key] === 'string')?.key
    const dup = new Set<string>()
    const hasDup = rows.some((r) => {
      const k = String(r[categoryCol])
      if (dup.has(k)) return true
      dup.add(k)
      return false
    })
    return rows.map((r) => {
      let label = String(r[categoryCol] ?? '-')
      if (isTime && label.length === 8) label = `${label.slice(4, 6)}.${label.slice(6)}`
      if (hasDup && second) label = `${label} ${r[second] ?? ''}`
      return { label, value: r[metric] as number }
    })
  }, [part, categoryCol, metric, isTime])
  const label = metrics.find((m) => m.key === metric)?.label ?? metric
  const height = isTime ? 220 : Math.max(160, data.length * 22 + 30)
  const tick = { fill: '#8b93a7', fontSize: 11 }

  return (
    <div className="result-chart">
      <div className="result-chart-head">
        <select className="input select small" value={metric} onChange={(e) => onMetric(e.target.value)}>
          {metrics.map((m) => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
        {!isTime && part.rows.length > 20 && <span className="muted">상위 20개</span>}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        {isTime ? (
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
            <XAxis dataKey="label" tick={tick} tickLine={false} axisLine={false} />
            <YAxis tick={tick} tickLine={false} axisLine={false} width={44} tickFormatter={(v) => compact(Number(v))} />
            <Tooltip formatter={(v) => [fmtNum(v), label]} />
            <Line dataKey="value" name={label} stroke="var(--primary-2)" strokeWidth={2.5} dot={{ r: 3 }} type="monotone" />
          </LineChart>
        ) : (
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,.18)" horizontal={false} />
            <XAxis type="number" tick={tick} tickLine={false} axisLine={false} tickFormatter={(v) => compact(Number(v))} />
            <YAxis type="category" dataKey="label" tick={tick} tickLine={false} axisLine={false} width={110} />
            <Tooltip formatter={(v) => [fmtNum(v), label]} />
            <Bar dataKey="value" name={label} fill="var(--primary-2)" radius={[0, 5, 5, 0]} barSize={14} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
