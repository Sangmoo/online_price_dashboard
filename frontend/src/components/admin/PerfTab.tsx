import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Copy, GitBranch, Loader2, RefreshCw, RotateCcw } from 'lucide-react'
import { opsApi, type PerfReport, type PerfSql } from '../../opsApi'
import { fmtNum } from '../../format'
import { copyText } from '../../copy'
import PlanModal from '../PlanModal'

type Notify = (text: string, error?: boolean) => void
const PERIODS = [1, 3, 7, 14, 30]
const ms = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}s` : `${fmtNum(v)}ms`)
const where = (w: { menu: string; feature: string }[]) => (w.length ? w.map((x) => `${x.menu} · ${x.feature}`).join(', ') : '-')
const oneLine = (s: string) => s.replace(/\s+/g, ' ').trim()

type SortKey = 'totalMs' | 'avgMs' | 'maxMs' | 'count' | 'slow'

/** 관리자 > 쿼리 성능: 화면 요청 응답 시간(로그) · 기능별 쿼리 시간 · 느린 쿼리 순위 · 실행 계획 */
export default function PerfTab({ notify }: { notify: Notify }) {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<PerfReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [sort, setSort] = useState<SortKey>('totalMs')
  const [plan, setPlan] = useState<{ sql: string; filled?: string; title?: string } | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    opsApi.perf(days).then(setData).catch((e) => notify(e.message, true)).finally(() => setLoading(false))
  }, [days, notify])
  useEffect(load, [load])

  const funcs = useMemo(() => [...(data?.funcs ?? [])].sort((a, b) => b[sort] - a[sort]), [data, sort])
  const closePlan = useCallback(() => setPlan(null), [])

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 성능 기록을 읽는 중…</div></section>
  const slowReq = data.requests.reduce((n, r) => n + r.slow, 0)
  const slowSql = data.funcs.reduce((n, f) => n + f.slow, 0)
  const tick = { fill: '#8b93a7', fontSize: 12 }
  const th = (k: SortKey, label: string) => (
    <th className={`num sortable ${sort === k ? 'on' : ''}`} onClick={() => setSort(k)} title="눌러서 정렬">{label}{sort === k ? ' ▼' : ''}</th>
  )

  const copy = async (s: string) => notify((await copyText(s)) ? '쿼리를 복사했습니다.' : '복사하지 못했습니다.', false)
  const clear = async () => {
    if (!confirm('기능별 쿼리 시간 · 느린 쿼리 순위 기록을 지우고 지금부터 다시 잴까요? (로그 기준 표는 그대로)')) return
    try {
      await opsApi.perfClear()
      notify('기록을 초기화했습니다. 지금부터 다시 잽니다.')
      load()
    } catch (e) {
      notify((e as Error).message, true)
    }
  }
  const sqlRow = (s: PerfSql, i: number) => (
    <tr key={i}>
      <td className="num muted">{i + 1}</td>
      <td className="perf-sql" title={s.sql}><code>{oneLine(s.sql).slice(0, 160)}</code>
        <div className="muted small">{s.fn} · {where(s.where)}</div>
      </td>
      <td className="num">{fmtNum(s.count)}</td>
      <td className="num">{ms(s.avgMs)}</td>
      <td className={`num strong ${s.maxMs >= data.slowSqlSec * 1000 ? 'bad-text' : ''}`}>{ms(s.maxMs)}</td>
      <td className="mono small nowrap">{s.maxAt ?? '-'}{s.maxUsr ? <div className="muted">{s.maxUsr}</div> : null}</td>
      <td className="nowrap">
        <button className="btn ghost sm" onClick={() => setPlan({ sql: s.raw, filled: s.filled, title: s.fn })}><GitBranch size={12} /> 실행 계획</button>{' '}
        <button className="icon-btn" title="가장 오래 걸린 실행의 값을 채운 쿼리 복사" onClick={() => copy(s.filled)}><Copy size={14} /></button>
      </td>
    </tr>
  )

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>쿼리 성능</h3>
          <span className="panel-hint">화면 요청은 서버 로그(최근 {days}일), 쿼리 시간은 {data.since} 이후 이 서버에서 실행된 기록</span>
          <div className="grow" />
          <div className="seg">
            {PERIODS.map((p) => <button key={p} className={days === p ? 'on' : ''} onClick={() => setDays(p)}>{p}일</button>)}
          </div>
          <button className="btn ghost sm" onClick={clear} title="배포 · 인덱스 변경 뒤 새로 잴 때"><RotateCcw size={13} /> 쿼리 기록 초기화</button>
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
        <div className="status-grid">
          <div className="status-card"><span className="muted small">화면 요청 ({days}일)</span><span className="status-value">{fmtNum(data.daily.reduce((n, d) => n + d.requests, 0))}건</span></div>
          <div className={`status-card ${slowReq ? 'warn' : ''}`}><span className="muted small">느린 요청 ({data.slowRequestSec}초 이상)</span><span className="status-value">{fmtNum(slowReq)}건</span></div>
          <div className="status-card"><span className="muted small">쿼리 실행 (기능 {fmtNum(data.funcs.length)}개)</span><span className="status-value">{fmtNum(data.funcs.reduce((n, f) => n + f.count, 0))}회</span></div>
          <div className={`status-card ${slowSql ? 'warn' : ''}`}><span className="muted small">느린 쿼리 실행 ({data.slowSqlSec}초 이상)</span><span className="status-value">{fmtNum(slowSql)}회</span></div>
        </div>
        {data.daily.length > 0 && (
          <ResponsiveContainer width="100%" height={170}>
            <ComposedChart data={data.daily.map((d) => ({ name: d.day.slice(5), 느린요청: d.slow, 'p95(ms)': d.p95Ms }))}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
              <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={48} />
              <Tooltip />
              <Bar yAxisId="l" dataKey="느린요청" fill="#ef4444" radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
              <Line yAxisId="r" dataKey="p95(ms)" stroke="var(--primary-2)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </section>

      <section className="card panel">
        <div className="panel-head row"><h3>화면 요청 응답 시간</h3><span className="panel-hint">서버 로그 기준 · 느린 요청 많은 순 (p95 = 100번 중 95번째로 느린 시간)</span></div>
        <div className="table-wrap perf-table">
          <table className="table">
            <thead><tr><th>메뉴</th><th>요청</th><th className="num">건수</th><th className="num">평균</th><th className="num">p95</th><th className="num">최대</th><th className="num">느린</th><th>마지막</th></tr></thead>
            <tbody>
              {data.requests.slice(0, 60).map((r) => (
                <tr key={r.method + r.path}>
                  <td className="nowrap">{r.menu}</td>
                  <td className="mono small">{r.method} {r.path}</td>
                  <td className="num">{fmtNum(r.count)}</td>
                  <td className="num">{ms(r.avgMs)}</td>
                  <td className="num">{ms(r.p95Ms)}</td>
                  <td className={`num ${r.maxMs >= data.slowRequestSec * 1000 ? 'bad-text strong' : ''}`}>{ms(r.maxMs)}</td>
                  <td className={`num ${r.slow ? 'bad-text strong' : 'muted'}`}>{fmtNum(r.slow)}</td>
                  <td className="mono small muted nowrap">{r.lastAt ?? '-'}</td>
                </tr>
              ))}
              {!data.requests.length && <tr><td colSpan={8} className="empty">기간 내 요청 기록이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head row"><h3>기능별 쿼리 시간</h3><span className="panel-hint">{data.since} 이후 · 머리글을 눌러 정렬 · 합계가 크면 자주 쓰이면서 무거운 기능</span></div>
        <div className="table-wrap perf-table">
          <table className="table">
            <thead><tr><th>메뉴 · 기능</th><th>함수</th>{th('count', '실행')}{th('avgMs', '평균')}{th('maxMs', '최대')}{th('totalMs', '합계')}{th('slow', '느린')}<th>마지막</th></tr></thead>
            <tbody>
              {funcs.map((f) => (
                <tr key={f.fn}>
                  <td className="small">{where(f.where)}</td>
                  <td className="mono small">{f.fn} <span className="muted">· SQL {f.sqls}</span></td>
                  <td className="num">{fmtNum(f.count)}</td>
                  <td className="num">{ms(f.avgMs)}</td>
                  <td className={`num ${f.maxMs >= data.slowSqlSec * 1000 ? 'bad-text strong' : ''}`}>{ms(f.maxMs)}</td>
                  <td className="num">{ms(f.totalMs)}</td>
                  <td className={`num ${f.slow ? 'bad-text strong' : 'muted'}`}>{fmtNum(f.slow)}</td>
                  <td className="mono small muted nowrap">{f.lastAt ?? '-'}</td>
                </tr>
              ))}
              {!funcs.length && <tr><td colSpan={8} className="empty">아직 기록이 없습니다. 화면을 조회하면 쌓입니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head row"><h3>느린 쿼리 순위</h3><span className="panel-hint">가장 오래 걸린 실행 기준 · [실행 계획] 으로 실제 · 예상 계획 확인 · 복사는 그때 값을 채운 쿼리</span></div>
        <div className="table-wrap perf-table">
          <table className="table">
            <thead><tr><th className="num">#</th><th>쿼리 · 기능</th><th className="num">실행</th><th className="num">평균</th><th className="num">최대</th><th>최대일 때</th><th /></tr></thead>
            <tbody>
              {data.slowSql.map(sqlRow)}
              {!data.slowSql.length && <tr><td colSpan={7} className="empty">아직 기록이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head row"><h3>로그 기준 느린 쿼리</h3><span className="panel-hint">최근 {days}일 · {data.slowSqlSec}초 이상 걸린 쿼리 (재시작과 관계없이 · 값은 남기지 않음)</span></div>
        <div className="table-wrap perf-table">
          <table className="table">
            <thead><tr><th>쿼리</th><th className="num">횟수</th><th className="num">평균</th><th className="num">최대</th><th>마지막</th><th /></tr></thead>
            <tbody>
              {data.logSlowSql.map((s, i) => (
                <tr key={i}>
                  <td className="perf-sql" title={s.sql}><code>{s.sql.slice(0, 200)}</code><div className="muted small mono">binds={s.binds}</div></td>
                  <td className="num">{fmtNum(s.count)}</td>
                  <td className="num">{ms(s.avgMs)}</td>
                  <td className="num strong bad-text">{ms(s.maxMs)}</td>
                  <td className="mono small muted nowrap">{s.lastAt ?? '-'}</td>
                  <td className="nowrap">
                    <button className="btn ghost sm" disabled={s.truncated} title={s.truncated ? '로그에 앞부분만 남아 실행 계획을 볼 수 없습니다' : '예상 실행 계획'}
                      onClick={() => setPlan({ sql: s.sql })}><GitBranch size={12} /> 실행 계획</button>
                  </td>
                </tr>
              ))}
              {!data.logSlowSql.length && <tr><td colSpan={6} className="empty">기간 내 느린 쿼리가 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {plan && <PlanModal sql={plan.sql} filled={plan.filled} title={plan.title} onClose={closePlan} />}
    </div>
  )
}
