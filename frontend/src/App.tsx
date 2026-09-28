import { useEffect, useState } from 'react'
import { Home, Moon, PanelLeftClose, PanelLeftOpen, Sun, Table2, TrendingDown } from 'lucide-react'
import { api, type DateInfo } from './api'
import { addDays } from './format'
import DashboardView from './components/DashboardView'
import DetailView from './components/DetailView'
import ChatWidget from './components/ChatWidget'

type View = 'dashboard' | 'detail'
type Theme = 'light' | 'dark'

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem('theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* storage 사용 불가 */
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function initialCollapsed(): boolean {
  if (window.innerWidth < 800) return true
  try {
    return localStorage.getItem('sidebar') === 'collapsed'
  } catch {
    return false
  }
}

const MENU: { key: View; label: string; desc: string; icon: typeof Home }[] = [
  { key: 'dashboard', label: '대시보드', desc: '기간별 수집 현황', icon: Home },
  { key: 'detail', label: '일자별 상세', desc: '일자별 원본 · 엑셀', icon: Table2 },
]

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [collapsed, setCollapsed] = useState(initialCollapsed)
  const [dates, setDates] = useState<DateInfo[]>([])
  const [datesError, setDatesError] = useState<string | null>(null)
  const [range, setRange] = useState<{ start: string; end: string } | null>(null)
  const [detail, setDetail] = useState<{ dt: string; q?: string; nonce: number } | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('theme', theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  useEffect(() => {
    try {
      localStorage.setItem('sidebar', collapsed ? 'collapsed' : 'expanded')
    } catch {
      /* ignore */
    }
  }, [collapsed])

  useEffect(() => {
    api
      .dates()
      .then(({ dates }) => {
        setDates(dates)
        if (dates.length) {
          const latest = dates[0].dt
          setRange({ start: addDays(latest, -6), end: latest })
          setDetail({ dt: latest, nonce: 0 })
        }
      })
      .catch((e) => setDatesError(e.message))
  }, [])

  const openDetail = (dt: string, q?: string) => {
    setDetail({ dt, q, nonce: Date.now() })
    setView('detail')
  }

  const chatContext: Record<string, string> =
    view === 'dashboard' && range
      ? { view, start: range.start, end: range.end }
      : view === 'detail' && detail
        ? { view, dt: detail.dt }
        : { view }

  const current = MENU.find((m) => m.key === view)!

  return (
    <div className={`app ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">
            <TrendingDown size={18} strokeWidth={2.6} />
          </div>
          <div className="sidebar-brand-text">
            <div className="brand-title">온라인 가격 모니터</div>
            <div className="brand-sub">가격 수집 현황</div>
          </div>
        </div>

        <nav className="side-nav">
          {MENU.map(({ key, label, desc, icon: Icon }) => (
            <button
              key={key}
              className={`side-item ${view === key ? 'active' : ''}`}
              onClick={() => setView(key)}
              title={collapsed ? label : undefined}
              aria-current={view === key ? 'page' : undefined}
            >
              <span className="side-icon">
                <Icon size={20} strokeWidth={view === key ? 2.4 : 2} />
              </span>
              <span className="side-text">
                <span className="side-label">{label}</span>
                <span className="side-desc">{desc}</span>
              </span>
              {collapsed && <span className="side-tooltip">{label}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <button
            className="side-item small"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title={collapsed ? (theme === 'dark' ? '라이트 모드' : '다크 모드') : undefined}
          >
            <span className="side-icon">{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</span>
            <span className="side-text">
              <span className="side-label">{theme === 'dark' ? '라이트 모드' : '다크 모드'}</span>
            </span>
          </button>
          <button
            className="side-item small"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? '메뉴 펼치기' : '메뉴 접기'}
          >
            <span className="side-icon">{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</span>
            <span className="side-text">
              <span className="side-label">메뉴 접기</span>
            </span>
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
              <div className="page-title">{current.label}</div>
              <div className="brand-sub">T_SELECT_ONLINE_MNG_R · {current.desc}</div>
            </div>
          </div>
        </header>

        <main className="container">
          {datesError && (
            <div className="alert error">
              수집일 목록을 불러오지 못했습니다: {datesError}
              <br />
              백엔드(포트 8000)가 실행 중인지, DB 접속 정보가 올바른지 확인하세요.
            </div>
          )}
          {range && (
            <div hidden={view !== 'dashboard'}>
              <DashboardView dates={dates} range={range} onRangeChange={setRange} onOpenDetail={openDetail} />
            </div>
          )}
          {detail && (
            <div hidden={view !== 'detail'}>
              <DetailView key={detail.nonce} dates={dates} initialDt={detail.dt} initialQuery={detail.q} onDtChange={(dt) => setDetail((d) => (d ? { ...d, dt } : d))} />
            </div>
          )}
          {!range && !datesError && <div className="skeleton-page" />}
        </main>
      </div>

      <ChatWidget context={chatContext} />
    </div>
  )
}
