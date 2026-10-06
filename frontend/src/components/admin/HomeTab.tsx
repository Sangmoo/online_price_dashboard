import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  Bot,
  CalendarClock,
  ChevronRight,
  Database,
  Download,
  Loader2,
  Megaphone,
  MessageSquareWarning,
  RefreshCw,
  Server,
  Users,
} from 'lucide-react'
import { opsApi, type AdminHome } from '../../opsApi'
import { fmtNum } from '../../format'
import type { Tab } from '../AdminView'

type Notify = (text: string, error?: boolean) => void
type Tone = 'ok' | 'warn' | 'bad' | 'off'

const ym = (v: string | null) => (v ? `${v.slice(0, 4)}-${v.slice(4, 6)}` : '-')
const ymd = (v: string | null) => (v ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}` : '-')
const uptime = (sec: number) => {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  return d ? `${d}일 ${h}시간` : `${h}시간 ${Math.floor((sec % 3600) / 60)}분`
}

/** 관리자 홈: 흩어진 운영 상태를 카드로 모은다. 카드를 누르면 해당 탭으로 이동 */
export default function HomeTab({ notify, go }: { notify: Notify; go: (tab: Tab) => void }) {
  const [data, setData] = useState<AdminHome | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback((fresh = false) => {
    setLoading(true)
    opsApi
      .home(fresh)
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [notify])
  useEffect(() => load(), [load])

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 운영 상태를 모으는 중…</div></section>
  const { feedback: fb, users: us, server: sv, data: dt, ai, jobs, downloads: dl, notices: nt } = data

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>운영 현황</h3>
          <span className="panel-hint">카드를 누르면 해당 탭으로 이동 · 집계 {data.generatedAt} (1분마다 새로 계산)</span>
          <div className="grow" />
          <button className="icon-btn bordered" onClick={() => load(true)} title="지금 다시 계산"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>

        <div className="home-grid">
          <Card icon={<MessageSquareWarning size={18} />} title="문의 · 신고" error={fb.error} onClick={() => go('feedback')}
            tone={fb.open ? 'warn' : 'ok'} value={fb.error ? null : `미처리 ${fmtNum(fb.open)}건`}>
            {fb.open ? '답변을 기다리는 문의가 있습니다.' : '모두 처리했습니다.'}
          </Card>

          <Card icon={<CalendarClock size={18} />} title="스케줄 · 배치" error={jobs.error} onClick={() => go('jobs')}
            tone={jobs.problems ? 'bad' : !jobs.dbReady || !jobs.appReady ? 'warn' : 'ok'}
            value={jobs.error ? null : jobs.problems ? `문제 ${jobs.problems}건` : '정상'}>
            {jobs.problems ? jobs.problemNames.join(', ') : `자동 작업 ${jobs.total}개`}
            {(!jobs.dbReady || !jobs.appReady) && <div className="home-sub warn">DDL 실행 필요: db/create_erp_web_admin_ops.sql</div>}
          </Card>

          <Card icon={<Server size={18} />} title="서버 · 최근 24시간" error={sv.error} onClick={() => go('status')}
            tone={sv.errors5xx || sv.crashRestarts ? 'bad' : sv.errors || sv.sqlErrors ? 'warn' : 'ok'}
            value={sv.error ? null : `오류 ${fmtNum(sv.errors)}건`}>
            요청 {fmtNum(sv.requests)} · 5xx {fmtNum(sv.errors5xx)} · 느린 요청 {fmtNum(sv.slowRequests)} · 느린 SQL {fmtNum(sv.slowSql)}
            <div className="home-sub">가동 {uptime(sv.uptimeSec ?? 0)}{sv.crashRestarts ? ` · 비정상 재시작 ${sv.crashRestarts}회` : ''} · 디스크 여유 {sv.diskFreeGb}GB{sv.diskFreePct != null ? ` (${sv.diskFreePct}%)` : ''}</div>
            {!!sv.recentErrors?.length && (
              <ul className="home-errors">
                {sv.recentErrors.map((e) => <li key={e.ts + e.message} title={e.message}><span className="mono">{e.ts.slice(11, 16)}</span> {e.message}</li>)}
              </ul>
            )}
          </Card>

          <Card icon={<Database size={18} />} title="데이터" error={dt.error} onClick={() => go('aitools')}
            tone={dt.mvBehind || !dt.onlineToday ? 'warn' : 'ok'}
            value={dt.error ? null : `온라인 ${ymd(dt.onlineLatest)}`}>
            온라인 수집 {fmtNum(dt.onlineLatestRows)}건{!dt.onlineToday && <b className="warn-text"> · 오늘 수집 없음</b>}
            <div className="home-sub">마감 매출 원본 {ym(dt.saleBaseMonth)} · 사전 집계 뷰 {ym(dt.saleMvMonth)}{dt.mvBehind && <b className="warn-text"> · 갱신 필요</b>}</div>
            {dt.shopFill && (
              <div className="home-sub">전일 매장코드 {fmtNum(dt.shopFill.filled)} / {fmtNum(dt.shopFill.rows)}건{dt.shopFill.pct != null ? ` (${dt.shopFill.pct}%)` : ''}</div>
            )}
          </Card>

          <Card icon={<Users size={18} />} title="접속" error={us.error} onClick={() => go('sessions')}
            tone={us.locked || us.loginFailsToday >= 5 ? 'warn' : 'ok'}
            value={us.error ? null : `접속 중 ${fmtNum(us.online)}명`}>
            세션 {fmtNum(us.sessions)} · 오늘 로그인 {fmtNum(us.loginsToday)}명
            <div className="home-sub">오늘 로그인 실패 {fmtNum(us.loginFailsToday)}회{us.locked ? ` · 잠긴 계정 ${us.locked}` : ''}</div>
          </Card>

          <Card icon={<Download size={18} />} title="다운로드 · 민감 정보" error={dl.error} onClick={() => go('downloads')}
            tone={dl.ready === false ? 'warn' : 'ok'} value={dl.error ? null : dl.ready === false ? '테이블 없음' : `오늘 ${fmtNum(dl.today)}건`}>
            최근 7일 {fmtNum(dl.week)}건 · 매니저 연락처 조회 등 {fmtNum(dl.sensitiveWeek)}건
            {dl.topUser && <div className="home-sub">7일 최다: {dl.topUser.name} {fmtNum(dl.topUser.count)}건</div>}
            {dl.ready === false && <div className="home-sub warn">DDL 실행 필요: db/create_erp_web_admin_ops.sql</div>}
          </Card>

          <Card icon={<Megaphone size={18} />} title="공지 · 점검" error={nt.error} onClick={() => go('notices')}
            tone={nt.maintenance?.on ? 'bad' : nt.table && !nt.table.ready ? 'warn' : 'ok'}
            value={nt.error ? null : nt.maintenance?.on ? '점검 모드 켜짐' : `게시 중 ${fmtNum(nt.active)}건`}>
            {nt.maintenance?.on ? '관리자 외 사용자 접속 차단 중' : nt.titles?.length ? nt.titles.join(' · ') : '게시 중인 공지가 없습니다.'}
            {!!nt.endingSoon && <div className="home-sub">3일 안에 끝나는 공지 {nt.endingSoon}건</div>}
            {nt.table && !nt.table.ready && <div className="home-sub warn">공지 테이블 없음 · DDL 실행 필요</div>}
          </Card>

          <Card icon={<Bot size={18} />} title="AI · 오늘" error={ai.error} onClick={() => go('usage')}
            tone={ai.enabled ? 'ok' : 'off'} value={ai.error ? null : ai.enabled ? `질문 ${fmtNum(ai.questions)}건` : '꺼짐'}>
            비용 ${ai.costUsd?.toFixed(2)} · 사용자 {fmtNum(ai.users)}명
          </Card>
        </div>
      </section>
    </div>
  )
}

function Card({ icon, title, value, tone, error, onClick, children }: {
  icon: ReactNode; title: string; value: string | null; tone: Tone; error?: string; onClick: () => void; children: ReactNode
}) {
  return (
    <button className={`home-card tone-${error ? 'warn' : tone}`} onClick={onClick}>
      <div className="home-card-head">
        <span className="home-icon">{icon}</span>
        <span className="home-title">{title}</span>
        {(tone === 'bad' || tone === 'warn' || error) && <AlertTriangle size={14} className="home-alert" />}
        <ChevronRight size={15} className="home-go" />
      </div>
      {error ? (
        <div className="home-sub warn">불러오지 못했습니다: {error}</div>
      ) : (
        <>
          <div className="home-value">{value}</div>
          <div className="home-body">{children}</div>
        </>
      )}
    </button>
  )
}

