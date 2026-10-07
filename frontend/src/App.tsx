import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ComponentType } from 'react'
import {
  BarChart3,
  BookOpen,
  ChartLine,
  ClipboardList,
  Clock,
  Database,
  DatabaseZap,
  Home,
  Loader2,
  Link2,
  LogOut,
  Megaphone,
  MessageSquareWarning,
  Moon,
  Wrench,
  UserRound,
  Eye,
  CalendarClock,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Sun,
  Table2,
  TrendingDown,
} from 'lucide-react'
import { api, ApiError, MAINTENANCE_EVENT, SESSION_EXPIRED_EVENT, SESSION_EXTENDED_EVENT, type DataFreshness, type DateInfo, type PageKey, type User } from './api'
import { opsApi, type Notice, type UpcomingMaintenance } from './opsApi'
import { hiddenToday } from './noticeHide'
import NoticePopup from './components/NoticePopup'
import { applyAccent, loadAccent, storedAccent } from './palette'
import { endViewAs, viewAsId } from './viewAs'

applyAccent(storedAccent(), false)   // 첫 화면부터 마지막에 쓴 강조 색 (로그인 후 서버 설정으로 맞춤)
import MaintenanceScreen from './components/MaintenanceScreen'
import { addDays } from './format'
import type { DetailState } from './components/DetailView'
import LoginView from './components/LoginView'
import { OPEN_HELP_EVENT } from './help/openHelp'
import type { Tab as AdminTab } from './components/AdminView'

// 메뉴별 화면은 처음 열 때 내려받는다 (첫 접속 파일 크기 축소). 로그인 화면만 기본 파일에 포함.
// 배포(deploy.bat)로 파일 이름이 바뀐 뒤 예전 화면에서 메뉴를 열면 옛 파일이 없어 실패한다 → 한 번만 새로고침해 새 화면을 받는다.
const RELOAD_KEY = 'chunk-reload-at'
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function lazyView<T extends ComponentType<any>>(load: () => Promise<{ default: T }>) {
  return lazy(() =>
    load().catch((err) => {
      let last = 0
      try {
        last = Number(sessionStorage.getItem(RELOAD_KEY) || 0)
        if (Date.now() - last > 30_000) sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
      } catch {
        /* storage 사용 불가 */
      }
      if (Date.now() - last > 30_000) window.location.reload()
      throw err
    }),
  )
}
const DashboardView = lazyView(() => import('./components/DashboardView'))
const DetailView = lazyView(() => import('./components/DetailView'))
const ChatWidget = lazyView(() => import('./components/ChatWidget'))
const AdminView = lazyView(() => import('./components/AdminView'))
const InvtPlanView = lazyView(() => import('./components/InvtPlanView'))
const SaleMonthlyView = lazyView(() => import('./components/SaleMonthlyView'))
const SaleDashboardView = lazyView(() => import('./components/SaleDashboardView'))
const FeedbackModal = lazyView(() => import('./components/FeedbackModal'))
const MallShopView = lazyView(() => import('./components/MallShopView'))
const HelpModal = lazyView(() => import('./components/HelpModal'))
const QueryModal = lazyView(() => import('./components/QueryModal'))
const NoticeBoardView = lazyView(() => import('./components/NoticeBoardView'))
const MyPage = lazyView(() => import('./components/MyPage'))

type Theme = 'light' | 'dark'

const TOUCH_INTERVAL_MS = 5 * 60 * 1000 // 화면 조작 시 세션 연장 호출 최소 간격
const BADGE_INTERVAL_MS = 5 * 60 * 1000 // 문의·신고 배지 확인 주기 (새 답변 · 관리자 미처리 건수)
const FRESHNESS_INTERVAL_MS = 10 * 60 * 1000 // 관리자: 새 월 마감 데이터 확인 주기 (서버는 1분 캐시)
const WARN_BEFORE_SEC = 5 * 60 // 만료 5분 전 경고

function readStorage(key: string) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function writeStorage(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage 사용 불가 */
  }
}

function initialTheme(): Theme {
  const saved = readStorage('theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function initialCollapsed(): boolean {
  if (window.innerWidth < 800) return true
  return readStorage('sidebar') === 'collapsed'
}

type MenuGroup = 'view' | 'sales' | 'data' | 'common' | 'admin'
// 화면 = 메뉴 권한이 있는 페이지 + 공지사항(모든 사용자)
type ViewKey = PageKey | 'notice' | 'mypage'
const MENU: { key: ViewKey; label: string; desc: string; icon: typeof Home; group: MenuGroup }[] = [
  { key: 'dashboard', label: '대시보드', desc: '기간별 수집 현황', icon: Home, group: 'view' },
  { key: 'detail', label: '일자별 상세', desc: '일자별 원본 · 엑셀', icon: Table2, group: 'view' },
  { key: 'mall_shop', label: '판매처 매장 연결', desc: '사이트 · 판매자 → 매장코드', icon: Link2, group: 'view' },
  { key: 'sale_dashboard', label: '판매 현황', desc: '월 실적 · 전년 대비', icon: ChartLine, group: 'sales' },
  { key: 'sale_monthly', label: '월별 매장별 판매 집계', desc: '마감 매출 · 엑셀', icon: BarChart3, group: 'sales' },
  { key: 'invt_plan', label: '매장 재고 실사계획', desc: '실사 일정 · 예상 비용', icon: ClipboardList, group: 'data' },
  { key: 'notice', label: '공지사항', desc: '공지 · 첨부 · 댓글', icon: Megaphone, group: 'common' },
  { key: 'mypage', label: '마이페이지', desc: '내 정보 · 화면 설정', icon: UserRound, group: 'common' },
  { key: 'admin', label: '관리자', desc: '사용자 · 권한 · AI 설정', icon: ShieldCheck, group: 'admin' },
]
const GROUP_LABELS: Record<MenuGroup, string> = { view: '온라인 가격', sales: '판매 분석', data: '데이터 관리', common: '공통', admin: '시스템' }

// ----------------------------------------------------------------------------
// URL 상태 (링크 공유)
// ----------------------------------------------------------------------------
type UrlState = { view?: ViewKey; start?: string; end?: string; detail: Partial<DetailState> }

function readUrl(): UrlState {
  const p = new URLSearchParams(window.location.search)
  const num = (k: string) => {
    const v = p.get(k)
    return v !== null && v !== '' && !isNaN(Number(v)) ? Number(v) : undefined
  }
  const view = p.get('view') as ViewKey | null
  const order = p.get('order')
  return {
    view: view && MENU.some((m) => m.key === view) ? view : undefined,
    start: p.get('start') || undefined,
    end: p.get('end') || undefined,
    detail: {
      dt: p.get('dt') || undefined,
      q: p.get('q') || undefined,
      mall: p.get('mall') || undefined,
      sort: p.get('sort') || undefined,
      order: order === 'desc' || order === 'asc' ? order : undefined,
      minRate: num('minRate'),
      maxRate: num('maxRate'),
      shops: p.get('shops') || undefined,
    },
  }
}

function writeUrl(params: Record<string, string | number | undefined | null>) {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const next = `${window.location.pathname}${s.toString() ? `?${s}` : ''}`
  if (next !== `${window.location.pathname}${window.location.search}`) window.history.replaceState(null, '', next)
}

const fmtYm = (v: string | null) => (v ? `${v.slice(0, 4)}-${v.slice(4)}` : '-')
const fmtRemain = (sec: number) => `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [user, setUser] = useState<User | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [maintenance, setMaintenance] = useState<string | null>(null)
  const [loginNotice, setLoginNotice] = useState<string | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    writeStorage('theme', theme)
  }, [theme])

  // 다크 모드도 강조 색처럼 사용자별 서버 설정(ui.theme)으로: 다른 PC · 브라우저에서도 같게
  const loadTheme = () =>
    api.getPref<string>('ui.theme').then(({ value }) => {
      if (value === 'light' || value === 'dark') setTheme(value)
    }).catch(() => undefined)

  // 최초 로그인 상태 확인
  useEffect(() => {
    api
      .me()
      .then(async ({ user }) => {
        const target = viewAsId()
        if (target && user.role === 'ADMIN') {
          // 사용자 화면 미리보기 (이 탭에서만): 대상 사용자 권한으로 화면을 그린다 (읽기 전용)
          try {
            setUser((await opsApi.viewAs(target, true)).user)
            return
          } catch (e) {
            alert(`미리보기를 열 수 없습니다: ${(e as Error).message}`)
            sessionStorage.removeItem('erp.viewAs')
          }
        } else if (target) sessionStorage.removeItem('erp.viewAs')
        setUser(user)
        loadAccent()
        loadTheme()
      })
      .catch((e) => {
        if (e instanceof ApiError && e.code === 'MAINTENANCE') setMaintenance(e.message)
        else setUser(null)
      })
      .finally(() => setAuthChecked(true))
  }, [])

  // 점검 모드(관리자 외 접속 차단): 어느 API 에서든 503 MAINTENANCE → 점검 안내 화면
  useEffect(() => {
    const on = (e: Event) => setMaintenance((e as CustomEvent<string>).detail || '시스템 점검 중입니다.')
    window.addEventListener(MAINTENANCE_EVENT, on)
    return () => window.removeEventListener(MAINTENANCE_EVENT, on)
  }, [])

  // 어느 API 에서든 401 → 로그인 화면
  useEffect(() => {
    const onExpired = (e: Event) => {
      setLoginNotice((e as CustomEvent<string>).detail || '로그인이 필요합니다.')
      setUser(null)
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  const handleLogout = useCallback((notice?: string) => {
    setLoginNotice(notice ?? null)
    setUser(null)
  }, [])

  if (!authChecked) {
    return (
      <div className="boot">
        <Loader2 className="spin" size={28} />
      </div>
    )
  }
  if (maintenance) {
    return (
      <MaintenanceScreen
        message={maintenance}
        onRetry={async () => {
          try {
            const { user } = await api.me()
            setMaintenance(null)
            setUser(user)
          } catch (e) {
            if (e instanceof ApiError && e.code === 'MAINTENANCE') setMaintenance(e.message)
            else {
              setMaintenance(null)
              setUser(null)
            }
          }
        }}
        onLogin={() => {
          api.logout().catch(() => undefined)
          setMaintenance(null)
          setUser(null)
        }}
      />
    )
  }
  if (!user) {
    return (
      <LoginView
        notice={loginNotice === '로그인이 필요합니다.' ? null : loginNotice}
        onLogin={(u) => {
          setLoginNotice(null)
          setUser(u)
          loadAccent()
          loadTheme()
        }}
      />
    )
  }
  return (
    <Shell
      key={user.id}
      user={user}
      theme={theme}
      onTheme={() => {
        const next = theme === 'dark' ? 'light' : 'dark'
        setTheme(next)
        if (!user.viewAs) api.setPref('ui.theme', next).catch(() => undefined)   // 미리보기 중에는 관리자 본인 설정을 바꾸지 않는다
      }}
      onLogout={handleLogout}
    />
  )
}

// ----------------------------------------------------------------------------
// 로그인 후 화면
// ----------------------------------------------------------------------------
type ShellProps = { user: User; theme: Theme; onTheme: () => void; onLogout: (notice?: string) => void }

function Shell({ user, theme, onTheme, onLogout }: ShellProps) {
  const [initialUrl] = useState(readUrl)
  const allowed = MENU.filter((m) => m.key === 'notice' || m.key === 'mypage' || user.pages.includes(m.key))
  const [view, setView] = useState<ViewKey | null>(() =>
    initialUrl.view && allowed.some((m) => m.key === initialUrl.view) ? initialUrl.view : (allowed[0]?.key ?? null),
  )
  const [noticeFocus, setNoticeFocus] = useState<{ id: string; nonce: number } | null>(null)
  const openNotice = useCallback((id: string) => {
    setNoticeFocus({ id, nonce: Date.now() })
    setView('notice')
  }, [])
  const [collapsed, setCollapsed] = useState(initialCollapsed)
  const [dates, setDates] = useState<DateInfo[]>([])
  const [datesError, setDatesError] = useState<string | null>(null)
  const [range, setRange] = useState<{ start: string; end: string } | null>(null)
  const [detail, setDetail] = useState<{ state: DetailState; nonce: number } | null>(null)
  const [invtCtx, setInvtCtx] = useState<Record<string, string>>({})
  const [saleCtx, setSaleCtx] = useState<Record<string, string>>({})
  const [saleDashCtx, setSaleDashCtx] = useState<Record<string, string>>({})
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  // 지표 정의 · 도움말: 상단 [도움말] 또는 화면의 (?) 아이콘(openHelp 이벤트)으로 연다
  const [help, setHelp] = useState<{ focus?: string } | null>(null)
  const closeHelp = useCallback(() => setHelp(null), [])
  const [queryOpen, setQueryOpen] = useState(false)
  const closeQuery = useCallback(() => setQueryOpen(false), [])
  useEffect(() => {
    const open = (e: Event) => setHelp({ focus: (e as CustomEvent<string | undefined>).detail })
    window.addEventListener(OPEN_HELP_EVENT, open)
    return () => window.removeEventListener(OPEN_HELP_EVENT, open)
  }, [])
  const [badge, setBadge] = useState<{ newAnswers: number; open: number | null }>({ newAnswers: 0, open: null })
  // 공지: 게시 중인 공지 중 오늘 숨기지 않았고 이번 접속에서 아직 닫지 않은 것을 팝업으로. 상단 [공지] 로 다시 볼 수 있다
  const [notices, setNotices] = useState<Notice[]>([])
  const [noticePopup, setNoticePopup] = useState<{ list: Notice[]; auto: boolean } | null>(null)
  const seenNotices = useRef(new Set<string>())
  const [upcomingMaint, setUpcomingMaint] = useState<UpcomingMaintenance | null>(null)
  const checkNotices = useCallback(() => {
    opsApi
      .activeNotices()
      .then(({ notices, maintenance }) => {
        setNotices(notices)
        setUpcomingMaint(maintenance ?? null)
        const hidden = hiddenToday(user.id)
        // 이번 접속에서 아직 닫지 않은 공지 중: 필독(확인 전)은 '오늘 하루 보지 않기' 와 관계없이, 그 밖은 오늘 숨기지 않은 것
        const fresh = notices.filter((n) => !seenNotices.current.has(n.id) && ((n.mustAck && !n.acked) || !hidden.includes(n.id)))
        if (fresh.length) {
          setNoticePopup((cur) => cur ?? { list: fresh, auto: true })
          if (!user.viewAs) opsApi.markRead(fresh.map((n) => n.id)).catch(() => undefined)   // 읽음 기록 (미리보기 중 제외)
        }
      })
      .catch(() => undefined)
  }, [user.id, user.viewAs])
  const ackNotice = useCallback(async (id: string) => {
    await opsApi.ackNotice(id)
    setNotices((list) => list.map((n) => (n.id === id ? { ...n, acked: true, read: true } : n)))
  }, [])
  const closeNotices = useCallback(() => {
    setNoticePopup((cur) => {
      cur?.list.forEach((n) => seenNotices.current.add(n.id))
      return null
    })
  }, [])
  const [expiresAt, setExpiresAt] = useState<number>(user.sessionExpiresAt ?? Math.floor(Date.now() / 1000) + 3600)
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000))
  const lastTouch = useRef(0)
  const [freshness, setFreshness] = useState<DataFreshness | null>(null)
  const [adminTab, setAdminTab] = useState<{ tab: AdminTab; nonce: number } | null>(null)
  const isAdmin = user.pages.includes('admin')

  // 관리자: 원본에 사전 집계 뷰보다 새로운 마감 월이 들어오면 상단 배너로 갱신을 알린다
  useEffect(() => {
    if (!isAdmin) return
    const check = () => api.admin.dataFreshness().then(setFreshness).catch(() => undefined)
    check()
    const t = setInterval(check, FRESHNESS_INTERVAL_MS)
    return () => clearInterval(t)
  }, [isAdmin])
  useEffect(() => {
    if (isAdmin && view === 'admin') api.admin.dataFreshness().then(setFreshness).catch(() => undefined)
  }, [isAdmin, view])

  useEffect(() => writeStorage('sidebar', collapsed ? 'collapsed' : 'expanded'), [collapsed])

  // 문의·신고 배지: 사용자는 새 답변, 관리자는 미처리 건수. 탭으로 돌아오거나 창을 닫을 때도 다시 확인
  const checkBadge = useCallback(() => {
    api.feedbackBadge().then(setBadge).catch(() => undefined)
  }, [])
  useEffect(() => {
    checkBadge()
    const t = setInterval(checkBadge, BADGE_INTERVAL_MS)
    const onVisible = () => document.visibilityState === 'visible' && checkBadge()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [checkBadge])
  useEffect(() => {
    checkNotices()
    const t = setInterval(checkNotices, BADGE_INTERVAL_MS)
    const onVisible = () => document.visibilityState === 'visible' && checkNotices()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [checkNotices])
  useEffect(() => {
    if (!feedbackOpen) checkBadge()
  }, [feedbackOpen, view, checkBadge])

  useEffect(() => {
    lastTouch.current = Date.now()
    api
      .dates()
      .then(({ dates }) => {
        setDates(dates)
        if (!dates.length) return
        const latest = dates[0].dt
        setRange({ start: initialUrl.start ?? addDays(latest, -6), end: initialUrl.end ?? latest })
        const d = initialUrl.detail
        setDetail({
          state: {
            dt: d.dt && dates.some((x) => x.dt === d.dt) ? d.dt : latest,
            q: d.q ?? '',
            mall: d.mall ?? '',
            sort: d.sort,
            order: d.order ?? 'asc',
            minRate: d.minRate,
            maxRate: d.maxRate,
            shops: d.shops ?? '',
          },
          nonce: 0,
        })
      })
      .catch((e) => setDatesError(e.message))
  }, [initialUrl])

  // ---- 세션 타이머 (서비스 이용 시 1시간 연장) ----
  useEffect(() => {
    const onExtended = (e: Event) => {
      setExpiresAt((e as CustomEvent<number>).detail)
      lastTouch.current = Date.now()
    }
    window.addEventListener(SESSION_EXTENDED_EVENT, onExtended)
    const tick = () => setNowSec(Math.floor(Date.now() / 1000))
    const t = setInterval(tick, 1000)
    // 다른 탭을 보는 동안 브라우저가 타이머를 늦추므로, 돌아오면 바로 남은 시간을 다시 계산 (지났으면 즉시 로그아웃)
    const onVisible = () => document.visibilityState === 'visible' && tick()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener(SESSION_EXTENDED_EVENT, onExtended)
      document.removeEventListener('visibilitychange', onVisible)
      clearInterval(t)
    }
  }, [])

  const touch = useCallback(() => {
    lastTouch.current = Date.now()
    api.touch().catch(() => undefined)
  }, [])

  // 클릭·키 입력 등 화면 조작도 서비스 이용으로 보고 세션 연장 (최대 5분에 1회 호출)
  useEffect(() => {
    const onActivity = () => {
      if (Date.now() - lastTouch.current > TOUCH_INTERVAL_MS) touch()
    }
    window.addEventListener('pointerdown', onActivity)
    window.addEventListener('keydown', onActivity)
    return () => {
      window.removeEventListener('pointerdown', onActivity)
      window.removeEventListener('keydown', onActivity)
    }
  }, [touch])

  const remain = Math.max(0, expiresAt - nowSec)
  useEffect(() => {
    if (remain <= 0) {
      api.logout().catch(() => undefined)
      onLogout('1시간 동안 사용하지 않아 로그아웃되었습니다.')
    }
  }, [remain, onLogout])

  // ---- 메뉴 이용 기록 (관리자 > 메뉴 이용 통계): 메뉴를 열 때 한 번 ----
  useEffect(() => {
    if (view) api.menuOpen(view).catch(() => undefined)
  }, [view])

  // ---- URL 동기화 (현재 화면/조건을 링크로 공유) ----
  useEffect(() => {
    if (view === 'dashboard' && range) writeUrl({ view, start: range.start, end: range.end })
    else if (view === 'detail' && detail) {
      const s = detail.state
      writeUrl({ view, dt: s.dt, q: s.q, mall: s.mall, sort: s.sort, order: s.sort ? s.order : undefined, minRate: s.minRate, maxRate: s.maxRate, shops: s.shops })
    } else if (view) writeUrl({ view })
  }, [view, range, detail])

  const openDetail = (dt: string, q?: string, shops?: string) => {
    if (!user.pages.includes('detail')) return
    setDetail({ state: { dt, q: q ?? '', mall: '', order: 'asc', shops: shops ?? '' }, nonce: Date.now() })
    setView('detail')
  }

  const logout = async () => {
    await api.logout().catch(() => undefined)
    onLogout('로그아웃되었습니다.')
  }

  const current = MENU.find((m) => m.key === view)
  const chatContext: Record<string, string> =
    view === 'dashboard' && range
      ? { view, start: range.start, end: range.end }
      : view === 'detail' && detail
        ? { view, dt: detail.state.dt }
        : view === 'invt_plan'
          ? { view, ...invtCtx }
          : view === 'sale_monthly'
            ? { view, ...saleCtx }
            : view === 'sale_dashboard'
              ? { view, ...saleDashCtx }
              : { view: view ?? '' }

  return (
    <div className={`app ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        {/* 서비스명 · 메뉴 · 화면 설정은 스크롤 (메뉴가 늘어나도 잘리지 않게), 로그인 정보는 아래에 고정 */}
        <div className="sidebar-scroll">
        <div className="sidebar-brand">
          <div className="brand-mark">
            <TrendingDown size={18} strokeWidth={2.6} />
          </div>
          <div className="sidebar-brand-text">
            <div className="brand-title">ERP 영업 관리</div>
            <div className="brand-sub">영업 데이터 · 분석 서비스</div>
          </div>
        </div>

        <nav className="side-nav">
          {allowed.map(({ key, label, desc, icon: Icon, group }, i) => (
            <div key={key} className="side-entry">
            {(i === 0 || allowed[i - 1].group !== group) && (
              <div className="side-group">
                <span className="side-group-label">{GROUP_LABELS[group]}</span>
              </div>
            )}
            <button
              key={key}
              className={`side-item ${view === key ? 'active' : ''} ${key === 'admin' ? 'admin-item' : ''}`}
              onClick={() => setView(key)}
              title={collapsed ? label : undefined}
              aria-current={view === key ? 'page' : undefined}
            >
              <span className="side-icon">
                <Icon size={20} strokeWidth={view === key ? 2.4 : 2} />
              </span>
              <span className="side-text">
                <span className="side-label">{label}</span>
                {key === 'admin' && !!badge.open && <span className="count-badge danger" title={`처리하지 않은 문의·신고 ${badge.open}건`}>{badge.open}</span>}
                <span className="side-desc">{desc}</span>
              </span>
              {collapsed && <span className="side-tooltip">{label}</span>}
            </button>
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <button className="side-item small" onClick={onTheme} title={collapsed ? (theme === 'dark' ? '라이트 모드' : '다크 모드') : undefined}>
            <span className="side-icon">{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</span>
            <span className="side-text">
              <span className="side-label">{theme === 'dark' ? '라이트 모드' : '다크 모드'}</span>
            </span>
          </button>
          <button className="side-item small" onClick={() => setCollapsed((c) => !c)} title={collapsed ? '메뉴 펼치기' : '메뉴 접기'}>
            <span className="side-icon">{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</span>
            <span className="side-text">
              <span className="side-label">메뉴 접기</span>
            </span>
          </button>
        </div>
        </div>

          <div className="user-card" title={collapsed ? `${user.name} (${user.id}) · 세션 ${fmtRemain(remain)}` : undefined}>
            <div className={`avatar ${user.role === 'ADMIN' ? 'admin' : ''}`}>{user.name.slice(0, 1)}</div>
            <div className="side-text user-text">
              <span className="side-label">
                {user.name} <span className={`role-badge ${user.role === 'ADMIN' ? 'admin' : ''}`}>{user.role === 'ADMIN' ? '관리자' : '일반'}</span>
              </span>
              <span className={`session-left ${remain <= WARN_BEFORE_SEC ? 'warn' : ''}`}>
                <Clock size={11} /> 세션 {fmtRemain(remain)}
              </span>
            </div>
            <button className="icon-btn logout-btn" title="로그아웃" onClick={logout}>
              <LogOut size={16} />
            </button>
          </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="topbar-inner">
            <button className="icon-btn" title={collapsed ? '메뉴 펼치기' : '메뉴 접기'} onClick={() => setCollapsed((c) => !c)}>
              {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
            <div>
              <div className="page-title">{current?.label ?? 'ERP 영업 관리'}</div>
              <div className="brand-sub">{view === 'invt_plan' ? '데이터 관리 · T_SHOP_INVT_PLAN' : view === 'mall_shop' ? '온라인 가격 · T_SELECT_ONLINE_MALL_SHOP' : view === 'sale_monthly' ? '판매 분석 · T_CLOSE_SALE_BASE' : view === 'sale_dashboard' ? '판매 분석 · 월×매장 사전 집계' : view === 'admin' ? '시스템 관리' : view === 'notice' ? '공통 · T_ERP_WEB_NOTICE' : view === 'mypage' ? '공통' : 'T_SELECT_ONLINE_MNG_R'} · {current?.desc ?? ''}</div>
            </div>
            {notices.length > 0 && (
              <button className="btn ghost notice-btn" onClick={() => {
                setNoticePopup({ list: notices, auto: false })
                if (!user.viewAs) opsApi.markRead(notices.map((n) => n.id)).catch(() => undefined)
              }} title="게시 중인 공지 보기">
                <Megaphone size={15} /> <span>공지</span> <span className="count-badge">{notices.length}</span>
              </button>
            )}
            {user.role === 'ADMIN' && !user.viewAs && view && (
              <button className="btn ghost query-btn" onClick={() => setQueryOpen(true)} title="이 메뉴가 기능별로 쓰는 SQL 보기 · 복사 (관리자)">
                <Database size={15} /> <span>사용 쿼리</span>
              </button>
            )}
            <button className="btn ghost help-btn" onClick={() => setHelp({})} title="지표 정의 · 계산식 · 원천 테이블">
              <BookOpen size={15} /> <span>도움말</span>
            </button>
            <button className="btn ghost feedback-btn" onClick={() => setFeedbackOpen(true)} title="오류 신고 · 기능 요청 · 문의 (현재 화면과 조회 조건이 함께 전달됩니다)">
              <MessageSquareWarning size={15} /> 문의·신고
              {badge.newAnswers > 0 && <span className="count-badge danger" title="새 답변이 있습니다">새 답변 {badge.newAnswers}</span>}
            </button>
          </div>
        </header>
        {noticePopup && <NoticePopup userId={user.id} notices={noticePopup.list} auto={noticePopup.auto} onClose={closeNotices} onOpen={(id) => { closeNotices(); openNotice(id) }}
          onAck={user.viewAs ? undefined : ackNotice} />}
        {help && (
          <Suspense fallback={null}>
            <HelpModal focus={help.focus} onClose={closeHelp} />
          </Suspense>
        )}
        {queryOpen && view && (
          <Suspense fallback={null}>
            <QueryModal page={view} me={user.id} onClose={closeQuery} />
          </Suspense>
        )}
        {feedbackOpen && (
          <Suspense fallback={null}>
            <FeedbackModal page={view ?? ''} pageLabel={current?.label ?? '-'} context={chatContext} onClose={() => setFeedbackOpen(false)} />
          </Suspense>
        )}

        {remain > 0 && remain <= WARN_BEFORE_SEC && (
          <div className="session-warn">
            <Clock size={15} /> 사용이 없어 {fmtRemain(remain)} 후 자동 로그아웃됩니다.
            <button className="btn-link" onClick={touch}>
              세션 연장
            </button>
          </div>
        )}

        {user.viewAs && (
          <div className="fresh-warn viewas-warn">
            <Eye size={15} /> <b>{user.name}({user.id})</b> 님 화면을 미리보는 중입니다 — 읽기 전용 (저장 · 엑셀 · AI 질문 불가) · 미리보기: {user.viewAs.byName}
            <button className="btn-link" onClick={endViewAs}>미리보기 끝내기</button>
          </div>
        )}
        {upcomingMaint && (
          <div className="fresh-warn maint-warn">
            <CalendarClock size={15} /> {upcomingMaint.start.slice(11)} ~ {upcomingMaint.until.slice(11)} 시스템 점검 예정입니다 — {upcomingMaint.message} 그 시간에는 접속할 수 없으니 작업을 저장해 주세요.
          </div>
        )}
        {freshness?.maintenance?.on && (
          <div className="fresh-warn maint-warn">
            <Wrench size={15} /> 점검 모드가 켜져 있습니다 — 관리자 외 사용자는 로그인·사용할 수 없습니다.
            <button className="btn-link" onClick={() => { setAdminTab({ tab: 'notices', nonce: Date.now() }); setView('admin') }}>
              점검 모드 관리
            </button>
          </div>
        )}
        {freshness?.behind && (
          <div className="fresh-warn">
            <DatabaseZap size={15} />
            {freshness.refreshing
              ? '사전 집계 뷰를 갱신하는 중입니다. 끝나면 판매 현황·AI 에 새 마감 월이 바로 반영됩니다.'
              : `새 마감 월 ${fmtYm(freshness.baseMaxMonth)} 데이터가 원본에 들어왔습니다. 사전 집계 뷰(현재 ${fmtYm(freshness.mvMaxMonth)})를 갱신해 주세요.`}
            {!freshness.refreshing && (
              <button className="btn-link" onClick={() => { setAdminTab({ tab: 'aitools', nonce: Date.now() }); setView('admin') }}>
                갱신하러 가기
              </button>
            )}
          </div>
        )}

        <main className="container">
          <Suspense fallback={<div className="skeleton-page" />}>
          {datesError && <div className="alert error">수집일 목록을 불러오지 못했습니다: {datesError}</div>}
          {!view && <div className="empty-state">접근 가능한 페이지가 없습니다. 관리자에게 권한을 요청하세요.</div>}
          {range && user.pages.includes('dashboard') && (
            <div hidden={view !== 'dashboard'}>
              <DashboardView
                dates={dates}
                range={range}
                onRangeChange={setRange}
                onOpenDetail={openDetail}
                canOpenDetail={user.pages.includes('detail')}
              />
            </div>
          )}
          {detail && user.pages.includes('detail') && (
            <div hidden={view !== 'detail'}>
              <DetailView
                key={detail.nonce}
                userId={user.id}
                canFillShop={user.pages.includes('mall_shop')}
                dates={dates}
                initial={detail.state}
                onStateChange={(state) => setDetail((d) => (d ? { ...d, state } : d))}
              />
            </div>
          )}
          {view === 'sale_dashboard' && user.pages.includes('sale_dashboard') && <SaleDashboardView onContextChange={setSaleDashCtx} canOnline={user.pages.includes('dashboard') || user.pages.includes('detail')} />}
          {user.pages.includes('sale_monthly') && (
            <div hidden={view !== 'sale_monthly'}>
              <SaleMonthlyView onContextChange={setSaleCtx} />
            </div>
          )}
          {view === 'invt_plan' && user.pages.includes('invt_plan') && <InvtPlanView onContextChange={setInvtCtx} />}
          {view === 'mall_shop' && user.pages.includes('mall_shop') && <MallShopView />}
          {view === 'mypage' && (
            <MyPage me={user} theme={theme} onTheme={onTheme} onShowNotices={() => { seenNotices.current.clear(); checkNotices() }} />
          )}
          {view === 'notice' && <NoticeBoardView key={noticeFocus?.nonce ?? 0} me={user} focusId={noticeFocus?.id} onChange={checkNotices} />}
          {view === 'admin' && user.pages.includes('admin') && <AdminView key={adminTab?.nonce ?? 0} me={user} initialTab={adminTab?.tab} feedbackOpen={badge.open ?? 0} onFeedbackChange={checkBadge}
            onOpsChange={() => { api.admin.dataFreshness().then(setFreshness).catch(() => undefined); checkNotices() }} />}
          {!range && !datesError && (view === 'dashboard' || view === 'detail') && <div className="skeleton-page" />}
          </Suspense>
        </main>
      </div>

      {user.ai.enabled && (
        <Suspense fallback={null}>
          <ChatWidget user={user} context={chatContext} />
        </Suspense>
      )}
    </div>
  )
}
