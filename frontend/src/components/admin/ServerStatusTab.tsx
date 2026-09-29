import { useCallback, useEffect, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Eraser, Loader2, RefreshCw, Save } from 'lucide-react'
import { api, type ServerStatus } from '../../api'
import { fmtNum } from '../../format'

type Notify = (text: string, error?: boolean) => void

const PERIODS = [1, 7, 30]
const fmtBytes = (b: number) =>
  b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(1)}GB` : b >= 1024 ** 2 ? `${(b / 1024 ** 2).toFixed(1)}MB` : `${Math.round(b / 1024)}KB`
const fmtUptime = (sec: number) => {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${m}분` : `${m}분`
}
const EVENT_LABEL: Record<string, string> = { crash: '자동 재시작(멈춤·종료)', deploy: '배포 재시작', service: '서비스' }

export default function ServerStatusTab({ notify }: { notify: Notify }) {
  const [days, setDays] = useState(7)
  const [st, setSt] = useState<ServerStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [keep, setKeep] = useState<number | ''>('')
  const [saving, setSaving] = useState(false)
  const [openSql, setOpenSql] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.admin
      .serverStatus(days)
      .then((s) => {
        setSt(s)
        setKeep((k) => (k === '' ? s.keepDays ?? 7 : k))
      })
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [days, notify])
  useEffect(load, [load])

  const saveKeep = async () => {
    if (keep === '' || keep < 1 || keep > 365) return notify('보관 기간은 1~365일입니다.', true)
    setSaving(true)
    try {
      await api.admin.saveSettings({ logKeepDays: keep })
      notify(`로그 보관 기간을 ${keep}일로 저장했습니다. 지난 파일은 바로 정리했습니다.`)
      load()
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }
  const cleanupNow = async () => {
    try {
      const r = await api.admin.cleanupLogs()
      notify(r.deleted.length ? `${r.deleted.length}개 파일(${fmtBytes(r.freedBytes)})을 정리했습니다.` : '정리할 파일이 없습니다.')
      load()
    } catch (e) {
      notify((e as Error).message, true)
    }
  }

  if (!st) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 서버 상태를 읽는 중…</div></section>
  const r = st.requests
  const sv = st.supervisor
  const tick = { fill: '#8b93a7', fontSize: 12 }

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>서버 상태</h3>
          <span className="panel-hint">최근 {st.days}일 ({st.since} 이후) · 서버 로그 기준 · 1분마다 새로 계산</span>
          <div className="grow" />
          <div className="seg">
            {PERIODS.map((p) => (
              <button key={p} className={days === p ? 'on' : ''} onClick={() => setDays(p)}>{p}일</button>
            ))}
          </div>
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
        <div className="status-grid">
          <Stat label="가동 시간" value={fmtUptime(st.server.uptimeSec)} sub={`${st.server.startedAt} 시작 · pid ${st.server.pid}`} />
          <Stat
            label="자동 재시작"
            value={`${fmtNum(sv.crashRestarts)}회`}
            tone={sv.crashRestarts ? 'warn' : 'ok'}
            sub={`${sv.running ? '감시 실행기 동작 중' : '감시 실행기 없음 (start.bat 실행?)'} · 배포 재시작 ${fmtNum(sv.deployRestarts)}회`}
          />
          <Stat label="요청" value={`${fmtNum(r.count)}건`} sub={`평균 ${r.avgMs ?? '-'}ms · 95% ${r.p95Ms ?? '-'}ms`} />
          <Stat label={`느린 요청 (${r.slowSec}초 이상)`} value={`${fmtNum(r.slow)}건`} tone={r.slow ? 'warn' : 'ok'} sub={`서버 오류(5xx) ${fmtNum(r.errors5xx)}건`} />
          <Stat label={`느린 SQL (${st.slowSql.thresholdSec}초 이상)`} value={`${fmtNum(st.slowSql.count)}건`} tone={st.slowSql.count ? 'warn' : 'ok'}
            sub={`SQL 오류 ${fmtNum(st.sqlErrors.count)}건`} />
          <Stat label="오류 기록" value={`${fmtNum(st.errors.count)}건`} tone={st.errors.count ? 'warn' : 'ok'} sub="서버 로그 > 오류만 에서 상세 확인" />
          <Stat label="DB 연결" value={st.pool ? `${st.pool.busy} / ${st.pool.opened}` : '-'} sub={st.pool ? `사용 중 / 열린 연결 · 최대 ${st.pool.max}` : '아직 연결 전'} />
          <Stat label="디스크 여유" value={fmtBytes(st.disk.freeBytes)} tone={st.disk.freeBytes < 5 * 1024 ** 3 ? 'warn' : 'ok'}
            sub={`로그 ${fmtBytes(st.disk.logsBytes)} · 엑셀 임시 ${fmtBytes(st.disk.exportsBytes)}`} />
        </div>
      </section>

      {st.daily.length > 1 && (
        <section className="card panel">
          <div className="panel-head"><h3>일별 요청 · 느린 SQL · 오류</h3></div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={st.daily.map((d) => ({ name: d.day.slice(5), 요청: d.requests, '느린 SQL': d.slowSql, 오류: d.errors }))}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={50} />
              <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={36} />
              <Tooltip />
              <Legend />
              <Bar yAxisId="l" dataKey="요청" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={26} />
              <Bar yAxisId="r" dataKey="느린 SQL" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={14} />
              <Bar yAxisId="r" dataKey="오류" fill="#ef4444" radius={[4, 4, 0, 0]} maxBarSize={14} />
            </ComposedChart>
          </ResponsiveContainer>
        </section>
      )}

      <section className="card panel">
        <div className="panel-head row">
          <h3>느린 SQL 상위</h3>
          <span className="panel-hint">같은 SQL 끼리 묶음 · 횟수 × 시간 순 · 행을 누르면 전체 SQL</span>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th className="num">횟수</th><th className="num">평균</th><th className="num">최대</th><th>마지막</th><th>SQL</th></tr></thead>
            <tbody>
              {st.slowSql.top.map((g, i) => (
                <tr key={i} className="clickable" onClick={() => setOpenSql(openSql === i ? null : i)}>
                  <td className="num">{fmtNum(g.count)}</td>
                  <td className="num">{g.avgSec}초</td>
                  <td className="num strong">{g.maxSec}초</td>
                  <td className="muted mono nowrap">{g.last}</td>
                  <td className="log-msg mono small">{openSql === i ? <pre>{g.sql}</pre> : g.sql.slice(0, 140) + (g.sql.length > 140 ? ' …' : '')}</td>
                </tr>
              ))}
              {st.slowSql.top.length === 0 && <tr><td colSpan={5} className="empty">느린 SQL 이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sd-grid two">
        <div className="card panel">
          <div className="panel-head"><h3>느린 요청 경로</h3><span className="panel-hint">{r.slowSec}초 이상</span></div>
          <table className="table sd-table">
            <thead><tr><th>경로</th><th className="num">횟수</th><th className="num">최대</th></tr></thead>
            <tbody>
              {r.slowPaths.map((p) => (
                <tr key={p.path}><td className="mono small">{p.path}</td><td className="num">{fmtNum(p.count)}</td><td className="num">{(p.maxMs / 1000).toFixed(1)}초</td></tr>
              ))}
              {r.slowPaths.length === 0 && <tr><td colSpan={3} className="empty">없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card panel">
          <div className="panel-head"><h3>서버 시작 · 재시작 기록</h3><span className="panel-hint">감시 실행기(service.log)</span></div>
          <table className="table sd-table">
            <thead><tr><th>일시</th><th>구분</th><th>내용</th></tr></thead>
            <tbody>
              {sv.events.map((e, i) => (
                <tr key={i}>
                  <td className="muted mono nowrap">{e.ts}</td>
                  <td><span className={`status ${e.kind === 'crash' ? 'fail' : e.kind === 'deploy' ? 'ok' : 'warn'}`}>{EVENT_LABEL[e.kind]}</span></td>
                  <td className="log-msg small">{e.message}</td>
                </tr>
              ))}
              {sv.events.length === 0 && <tr><td colSpan={3} className="empty">기록이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head row">
          <h3>로그 보관</h3>
          <span className="panel-hint">
            매일 자정 날짜별 파일로 나뉘고, 보관 기간이 지난 파일은 6시간마다 자동 삭제 · 로그 폴더 최대 1GB · 현재 파일 {fmtNum(st.disk.logFiles)}개
            {st.disk.oldestLog ? ` · 가장 오래된 파일 ${st.disk.oldestLog}` : ''}
          </span>
        </div>
        <div className="keep-row">
          <label>
            보관 기간
            <input className="input small-num" type="number" min={1} max={365} value={keep} onChange={(e) => setKeep(e.target.value === '' ? '' : Number(e.target.value))} />일
          </label>
          <button className="btn primary sm" onClick={saveKeep} disabled={saving || keep === st.keepDays}>
            {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} 저장
          </button>
          <button className="btn ghost sm" onClick={cleanupNow}><Eraser size={14} /> 지금 정리</button>
          <span className="muted small">관리자 변경 이력·로그인 기록·AI 사용 기록(DB)은 삭제하지 않습니다.</span>
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'ok' | 'warn' }) {
  return (
    <div className={`status-card ${tone ?? ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="status-value">{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  )
}
