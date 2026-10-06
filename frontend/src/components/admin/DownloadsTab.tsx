import { useCallback, useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, BellRing, Check, Loader2, RefreshCw, ShieldAlert, X } from 'lucide-react'
import { opsApi, type AlertSettings, type DownloadReport } from '../../opsApi'
import { fmtNum } from '../../format'

type Notify = (text: string, error?: boolean) => void
const PERIODS = [7, 30, 90, 365]
const size = (b: number | null) => (b == null ? '' : b < 1024 ? `${b}B` : b < 1024 ** 2 ? `${(b / 1024).toFixed(0)}KB` : `${(b / 1024 ** 2).toFixed(1)}MB`)
const PARAM_LABELS: Record<string, string> = {
  dt: '수집일', q: '검색', mall: '사이트', shops: '매장코드', minRate: '할인율≥', maxRate: '할인율≤', sort: '정렬', shopId: '매장',
  screen: '화면', ymFrom: '시작월', ymTo: '끝월', planYys: '기획년도', seasons: '시즌', ym: '기준월', from: '시작월', cmp: '비교',
  brand: '브랜드', tool: 'AI 도구', selected: '대상', columns: '컬럼',
}
const fmtParams = (p: Record<string, unknown> | null) =>
  p ? Object.entries(p).map(([k, v]) => `${PARAM_LABELS[k] ?? k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ') : ''

/** 다운로드 이력: 누가 언제 어떤 조건으로 엑셀을 받았는지, 매장 매니저 연락처를 조회했는지 */
export default function DownloadsTab({ notify }: { notify: Notify }) {
  const [days, setDays] = useState(30)
  const [usr, setUsr] = useState('')
  const [kind, setKind] = useState('')
  const [data, setData] = useState<DownloadReport | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    opsApi
      .downloads({ days, usr: usr || undefined, kind: kind || undefined })
      .then(setData)
      .catch((e) => notify(e.message, true))
      .finally(() => setLoading(false))
  }, [days, usr, kind, notify])
  useEffect(load, [load])

  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 다운로드 이력을 읽는 중…</div></section>
  const sensitive = data.byUser.reduce((n, u) => n + u.sensitive, 0)
  const tick = { fill: '#8b93a7', fontSize: 12 }

  return (
    <div className="stack">
      <section className="card panel">
        <div className="panel-head row">
          <h3>다운로드 · 민감 정보 조회 이력</h3>
          <span className="panel-hint">
            엑셀 다운로드 · 설정 백업 · 매장 매니저 연락처 조회 · 400일 보관 (T_ERP_WEB_DOWNLOAD_LOG)
          </span>
          <div className="grow" />
          <div className="seg">
            {PERIODS.map((p) => <button key={p} className={days === p ? 'on' : ''} onClick={() => setDays(p)}>{p === 365 ? '1년' : `${p}일`}</button>)}
          </div>
          <select className="input select small" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="종류">
            <option value="">전체 종류</option>
            {Object.entries(data.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {usr && (
            <button className="pill sort-pill" onClick={() => setUsr('')} title="사용자 조건 해제">
              사용자: {data.byUser[0]?.name ?? usr} <X size={12} />
            </button>
          )}
          <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
        </div>
        {!data.table.ready && (
          <div className="notice-box warn">
            <AlertTriangle size={15} />
            <div>
              다운로드 이력 테이블을 쓸 수 없어 기록하지 않고 있습니다 ({data.table.missing.join(', ')}). <b>{data.table.ddl}</b> 를 SS10 스키마에서 실행하세요.
              테이블이 이미 있으면 동의어만 만들면 됩니다: <code>{data.table.missing.map((t) => `CREATE SYNONYM SS10DEV.${t} FOR SS10.${t};`).join(' ')}</code>
            </div>
          </div>
        )}
        <div className="status-grid">
          <div className="status-card"><span className="muted small">다운로드 · 조회</span><span className="status-value">{fmtNum(data.total)}건</span></div>
          <div className="status-card"><span className="muted small">사용자</span><span className="status-value">{fmtNum(data.byUser.length)}명</span></div>
          <div className={`status-card ${sensitive ? 'warn' : ''}`}>
            <span className="muted small">민감 정보 (매니저 연락처 · 설정 백업)</span><span className="status-value">{fmtNum(sensitive)}건</span>
          </div>
          {data.byKind.slice(0, 2).map((k) => (
            <div key={k.kind} className="status-card"><span className="muted small">{k.label}</span><span className="status-value">{fmtNum(k.count)}건</span></div>
          ))}
        </div>
        {data.daily.length > 1 && (
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={data.daily.map((d) => ({ name: d.day.slice(5), 건수: d.count }))}>
              <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
              <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
              <YAxis tick={tick} tickLine={false} axisLine={false} width={36} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="건수" fill="var(--primary-2)" radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </section>

      {data.alertSettings && <AlertsPanel data={{ ...data, alerts: data.alerts ?? [] }} notify={notify} onSaved={load} onPick={setUsr} />}

      {!usr && (
        <section className="card panel">
          <div className="panel-head row"><h3>사용자별</h3><span className="panel-hint">이름을 누르면 그 사용자 기록만 봅니다</span></div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>사용자</th><th className="num">건수</th><th className="num">민감 정보</th><th className="num">행 수 합계</th><th>종류</th><th>마지막</th></tr></thead>
              <tbody>
                {data.byUser.map((u) => (
                  <tr key={u.id}>
                    <td><button className="btn-link strong" onClick={() => setUsr(u.id)}>{u.name}</button> <span className="muted mono small">{u.id}</span></td>
                    <td className="num strong">{fmtNum(u.count)}</td>
                    <td className={`num ${u.sensitive ? 'warn-text strong' : 'muted'}`}>{fmtNum(u.sensitive)}</td>
                    <td className="num">{fmtNum(u.rows)}</td>
                    <td className="small">{Object.entries(u.kinds).map(([k, n]) => `${data.kinds[k] ?? k} ${n}`).join(' · ')}</td>
                    <td className="muted mono nowrap">{u.last ?? '-'}</td>
                  </tr>
                ))}
                {!data.byUser.length && <tr><td colSpan={6} className="empty">기간 내 기록이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card panel">
        <div className="panel-head row">
          <h3>상세 기록</h3>
          <span className="panel-hint">최근 순{data.truncated ? ` · 최근 ${fmtNum(data.rows.length)}건만 표시 (기간·조건을 좁히세요)` : ''}</span>
        </div>
        <div className="table-wrap">
          <table className="table dl-table">
            <thead><tr><th>일시</th><th>사용자</th><th>종류</th><th>파일 · 대상</th><th>조건</th><th className="num">행</th><th className="num">크기</th><th>IP</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono nowrap">{r.at}</td>
                  <td className="nowrap">{r.name} <span className="muted mono small">{r.usrId}</span></td>
                  <td className="nowrap">
                    <span className={`dl-kind ${r.sensitive ? 'sensitive' : ''}`}>{r.sensitive && <ShieldAlert size={12} />} {r.kindLabel}</span>
                  </td>
                  <td className="ellipsis" title={r.title ?? ''}>{r.title}</td>
                  <td className="small dl-params" title={fmtParams(r.params)}>{fmtParams(r.params)}</td>
                  <td className="num">{r.rows != null ? fmtNum(r.rows) : ''}</td>
                  <td className="num muted">{size(r.bytes)}</td>
                  <td className="mono small muted">{r.ip}</td>
                </tr>
              ))}
              {!data.rows.length && <tr><td colSpan={8} className="empty">기간 내 기록이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

/** 대량 다운로드 알림: 최근 1시간 엑셀 n건 · 매니저 연락처 조회 n건, 최근 24시간 한 번에 n행 이상 엑셀 (기준은 관리자가 저장) */
function AlertsPanel({ data, notify, onSaved, onPick }: {
  data: DownloadReport; notify: (text: string, error?: boolean) => void; onSaved: () => void; onPick: (id: string) => void
}) {
  const [cfg, setCfg] = useState<AlertSettings>(data.alertSettings)
  const [saving, setSaving] = useState(false)
  const dirty = cfg.count !== data.alertSettings.count || cfg.phone !== data.alertSettings.phone || cfg.rows !== data.alertSettings.rows
  const save = async () => {
    setSaving(true)
    try {
      await opsApi.saveAlertSettings(cfg)
      notify('알림 기준을 저장했습니다.')
      onSaved()
    } catch (e) {
      notify((e as Error).message, true)
    } finally {
      setSaving(false)
    }
  }
  const num = (k: keyof AlertSettings) => (e: React.ChangeEvent<HTMLInputElement>) => setCfg((c) => ({ ...c, [k]: Number(e.target.value) || 0 }))
  return (
    <section className={`card panel ${data.alerts.length ? 'dl-alert-panel' : ''}`}>
      <div className="panel-head row">
        <h3><BellRing size={16} /> 대량 다운로드 알림 {data.alerts.length > 0 && <span className="count-badge danger">{data.alerts.length}</span>}</h3>
        <span className="panel-hint">기준을 넘으면 여기와 관리자 홈에 표시됩니다 (자동으로 막지는 않음)</span>
      </div>
      <div className="dl-alert-cfg">
        <label className="check-label">1시간에 엑셀 <input className="input small num-input" type="number" min={1} max={1000} value={cfg.count} onChange={num('count')} /> 건 이상</label>
        <label className="check-label">1시간에 매니저 연락처 조회 <input className="input small num-input" type="number" min={1} max={1000} value={cfg.phone} onChange={num('phone')} /> 건 이상</label>
        <label className="check-label">한 번에 <input className="input small num-input wide" type="number" min={1000} step={1000} value={cfg.rows} onChange={num('rows')} /> 행 이상 엑셀</label>
        <button className="btn ghost sm" disabled={!dirty || saving} onClick={save}>{saving ? <Loader2 size={12} className="spin" /> : <Check size={12} />} 기준 저장</button>
      </div>
      {data.alerts.length ? (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>마지막</th><th>사용자</th><th>내용</th><th /></tr></thead>
            <tbody>
              {data.alerts.map((a, i) => (
                <tr key={i}>
                  <td className="mono nowrap">{a.at}</td>
                  <td className="nowrap"><b>{a.name}</b> <span className="muted mono small">{a.usrId}</span></td>
                  <td className="bad-text">{a.message}</td>
                  <td><button className="btn-link small" onClick={() => onPick(a.usrId)}>기록 보기</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="muted small">최근 24시간 기준을 넘은 다운로드가 없습니다.</div>}
    </section>
  )
}
