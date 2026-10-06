import { useCallback, useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Loader2, RefreshCw } from 'lucide-react'
import { api, type MenuUsage } from '../../api'
import { fmtNum } from '../../format'

type Notify = (text: string, error?: boolean) => void
const PERIODS = [7, 30, 90]

export default function MenuUsageTab({ notify }: { notify: Notify }) {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<MenuUsage | null>(null)
  const [loading, setLoading] = useState(false)
  const [onlyUnused, setOnlyUnused] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .menuUsage(days)
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [days, notify])
  useEffect(load, [load])

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 메뉴 이용 기록을 읽는 중…</div></section>
  const pages = data.pages
  const users = onlyUnused ? data.users.filter((u) => u.active && u.unusedPages.length) : data.users
  const tick = { fill: '#8b93a7', fontSize: 12 }

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>메뉴별 이용</h3>
          <span className="panel-hint">
            {data.since} 이후 · 메뉴를 연 횟수 기준 (AI 는 질문 수) · 저장 위치 {data.storage === 'oracle' ? 'Oracle' : '서버 로컬 (db/create_erp_web_menu_usage.sql 실행 시 Oracle 로 이전)'}
          </span>
          <div className="grow" />
          <div className="seg">
            {PERIODS.map((p) => (
              <button key={p} className={days === p ? 'on' : ''} onClick={() => setDays(p)}>{p}일</button>
            ))}
          </div>
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>메뉴</th><th className="num">연 횟수</th><th className="num">이용자</th><th className="num">권한 있는 사용자</th><th className="num">이용률</th><th className="num">이용 일수</th><th>마지막 이용</th></tr>
            </thead>
            <tbody>
              {pages.map((p) => (
                <tr key={p.page}>
                  <td className="strong">{p.label}</td>
                  <td className="num">{fmtNum(p.opens)}</td>
                  <td className="num">{fmtNum(p.users)}명</td>
                  <td className="num muted">{fmtNum(p.grantedUsers)}명</td>
                  <td className="num">{p.grantedUsers ? `${Math.round((p.users * 100) / p.grantedUsers)}%` : '-'}</td>
                  <td className="num">{fmtNum(p.activeDays)}일</td>
                  <td className="muted mono nowrap">{p.last ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.daily.length > 1 && (
        <section className="card panel">
          <div className="panel-head"><h3>일별 메뉴 열람</h3></div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={data.daily.map((d) => ({ name: d.day.slice(5), 열람: d.opens }))}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis tick={tick} tickLine={false} axisLine={false} width={40} />
              <Tooltip />
              <Bar dataKey="열람" fill="var(--primary-2)" radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      <section className="card panel">
        <div className="panel-head row">
          <h3>사용자별 이용</h3>
          <span className="panel-hint">
            숫자 = 연 횟수 · <span className="usage-unused-sample">미사용</span> = 권한은 있는데 기간 내 한 번도 안 연 메뉴 ({fmtNum(data.unusedGrants)}건) · 빈 칸 = 권한 없음
          </span>
          <div className="grow" />
          <label className="check-label">
            <input type="checkbox" checked={onlyUnused} onChange={(e) => setOnlyUnused(e.target.checked)} /> 미사용 권한이 있는 사용자만
          </label>
        </div>
        <div className="table-wrap">
          <table className="table usage-matrix">
            <thead>
              <tr>
                <th>사용자</th>
                <th className="num">합계</th>
                {pages.map((p) => <th key={p.page} className="num">{p.label}</th>)}
                <th>최근 로그인</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.active ? '' : 'inactive'}>
                  <td><div className="strong">{u.name}</div><div className="muted mono small">{u.id}</div></td>
                  <td className="num strong">{fmtNum(u.opens)}</td>
                  {pages.map((p) => {
                    const c = u.cells[p.page]
                    if (!c) return <td key={p.page} />
                    if (c.granted && !c.opens) return <td key={p.page} className="num"><span className="usage-unused">미사용</span></td>
                    return (
                      <td key={p.page} className="num" title={`${c.days}일 이용 · 마지막 ${c.last ?? '-'}${c.granted ? '' : ' · 지금은 권한 없음'}`}>
                        {fmtNum(c.opens)}{!c.granted && <span className="muted small"> (회수)</span>}
                      </td>
                    )
                  })}
                  <td className="muted mono nowrap">{u.lastLoginAt ?? '-'}</td>
                </tr>
              ))}
              {users.length === 0 && <tr><td colSpan={pages.length + 3} className="empty">해당 사용자가 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
