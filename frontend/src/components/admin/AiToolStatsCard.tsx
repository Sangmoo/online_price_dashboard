import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api, type AiToolStats } from '../../api'
import { fmtNum } from '../../format'

/** AI 사용 현황 › 도구별 사용 (서버 로그 기준 — 로그 보관 기간까지만) */
export default function AiToolStatsCard({ days }: { days: number }) {
  const [data, setData] = useState<AiToolStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setError(null)
    api.admin
      .aiToolStats(days)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [days])

  if (error) return <div className="alert error">도구별 사용: {error}</div>
  if (!data) return <section className="card panel"><div className="trend-loading"><Loader2 size={16} className="spin" /> 서버 로그에서 도구 사용을 집계하는 중…</div></section>
  const short = data.keepDays < days
  const routes = Object.entries(data.routes)
  const ROUTE_LABELS: Record<string, string> = { simple: '단순 조회 모델', base: '기본 모델(분석)', off: '자동 선택 꺼짐' }
  return (
    <section className="card panel ai-tool-stats">
      <div className="panel-head">
        <h3>도구별 사용</h3>
        <span className="panel-hint">
          {data.since}부터 서버 로그 기준 · 질문 {fmtNum(data.questions)}회 · 모델 선택 {routes.map(([k, v]) => `${ROUTE_LABELS[k] ?? k} ${v}`).join(' · ') || '-'}
          {' '}· 기본 모델로 전환 {data.modelSwitches}회
        </span>
      </div>
      {short && <div className="muted small">로그 보관 기간이 {data.keepDays}일이라 그 전 기록은 빠져 있습니다 (관리자 › 서버 상태에서 보관 기간 변경).</div>}
      <div className="table-wrap">
        <table className="table sd-table">
          <thead>
            <tr>
              <th>도구</th><th className="num">호출</th><th className="num">성공</th><th className="num">입력 오류</th><th className="num">조회 실패</th>
              <th className="num">오류율</th><th className="num">평균</th><th className="num">95%</th><th className="num">최대</th><th className="num">사용자</th>
              <th>자주 나는 오류</th><th>마지막</th>
            </tr>
          </thead>
          <tbody>
            {data.tools.map((t) => (
              <tr key={t.name}>
                <td><span className="strong">{t.label}</span> <span className="muted mono small">{t.name}</span></td>
                <td className="num strong">{fmtNum(t.calls)}</td>
                <td className="num">{fmtNum(t.ok)}</td>
                <td className={`num ${t.inputErrors ? 'up' : 'muted'}`}>{fmtNum(t.inputErrors)}</td>
                <td className={`num ${t.failures ? 'up' : 'muted'}`}>{fmtNum(t.failures)}</td>
                <td className="num">{t.errorRate === null ? '-' : `${t.errorRate}%`}</td>
                <td className="num">{t.avgSec === null ? '-' : `${t.avgSec}초`}</td>
                <td className="num">{t.p95Sec === null ? '-' : `${t.p95Sec}초`}</td>
                <td className={`num ${t.maxSec !== null && t.maxSec >= 10 ? 'up' : ''}`}>{t.maxSec === null ? '-' : `${t.maxSec}초`}</td>
                <td className="num">{t.users}</td>
                <td className="small">{t.topErrors.length ? t.topErrors.map((e) => `${e.message} (${e.count})`).join(' / ') : <span className="muted">-</span>}</td>
                <td className="small muted">{t.last?.slice(5, 16) ?? '-'}</td>
              </tr>
            ))}
            {data.tools.length === 0 && <tr><td colSpan={12} className="empty">이 기간에 도구 호출 기록이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
      {data.unusedTools.length > 0 && (
        <div className="muted small">이 기간에 쓰이지 않은 기본 도구: {data.unusedTools.map((u) => u.label).join(', ')}</div>
      )}
    </section>
  )
}
