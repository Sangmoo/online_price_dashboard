import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { apiFetch } from '../api'
import { fmtNum } from '../format'

type Row = {
  rank: number
  prdtCd: string
  itemNm: string | null
  prdtGrpNm: string | null
  storeAmt: number
  storeQty: number
  storeDsctRate: number | null
  online: { recentRate: number | null; baseRate: number | null; lowPrice: number | null; malls: number; lastDt: string | null } | null
  diff: number | null
  flag: 'rise' | 'new' | null
}
type Alerts = {
  period: string
  brand: string | null
  recentDays: number
  baseDays: number
  alertDiff: number
  alertNew: number
  recentFrom: string
  baseFrom: string
  unavailable?: string
  rows: Row[]
  alertCount: number
  withOnline?: number
  total?: number
}

const eok = (v: number) =>
  Math.abs(v) >= 100_000_000 ? `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억` : `${Math.round(v / 10_000).toLocaleString('ko-KR')}만`
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v.toFixed(1)}%`)

/** 판매 현황 아래: 매장 실판금액 상위 상품 중 최근 온라인 할인율이 오른 상품 (온라인 가격 메뉴 권한이 있을 때만) */
export default function OnlineAlertPanel({ query, onProduct }: { query: string; onProduct: (prdtCd: string) => void }) {
  const [data, setData] = useState<Alerts | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [all, setAll] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    apiFetch(`/api/sale-dashboard/online-alerts${query}`)
      .then((r) => r.json())
      .then((d: Alerts) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [query])

  if (loading && !data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 온라인 할인 주의 상품을 찾는 중…</div></section>
  if (error) return <div className="alert error">온라인 할인 주의 상품: {error}</div>
  if (!data) return null
  if (data.unavailable) return null // 상품 패널이 같은 안내를 보여준다
  const rows = all ? data.rows : data.rows.filter((r) => r.flag)

  return (
    <section className="card panel online-alert-panel">
      <div className="panel-head row">
        <h3>
          {data.alertCount > 0 && <AlertTriangle size={16} className="warn-icon" />} 온라인 할인 주의 상품
          {data.alertCount > 0 && <span className="count-badge warn">{data.alertCount}</span>}
        </h3>
        <span className="panel-hint">
          매장 {data.period} 실판금액 상위 {data.total}개 상품 중 온라인 최근 {data.recentDays}일({data.recentFrom}~) 평균 할인율이 그 전 4주보다
          {' '}{data.alertDiff}%p 이상 오른 상품 · 온라인 수집 {data.withOnline}개{loading ? ' · 갱신 중…' : ''}
        </span>
        <div className="grow" />
        <div className="seg">
          <button className={!all ? 'on' : ''} onClick={() => setAll(false)}>주의만</button>
          <button className={all ? 'on' : ''} onClick={() => setAll(true)}>상위 {data.total}개 전체</button>
        </div>
      </div>
      <div className="table-wrap tall-ish">
        <table className="table sd-table">
          <thead>
            <tr>
              <th>매장 순위</th><th>품번</th><th>아이템 · 품군</th><th className="num">매장 실판금액</th><th className="num">매장 할인율</th>
              <th className="num">온라인 최근 {data.recentDays}일</th><th className="num">그 전 4주</th><th className="num">변화</th>
              <th className="num">최근 최저가</th><th className="num">사이트</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.prdtCd} className={r.flag ? 'warn-row' : ''}>
                <td className="muted">{r.rank}</td>
                <td><button className="btn-link mono" title="온라인 가격 · 매장 판매 비교" onClick={() => onProduct(r.prdtCd)}>{r.prdtCd}</button></td>
                <td className="small">{r.itemNm ?? '-'} <span className="muted">· {r.prdtGrpNm ?? '-'}</span></td>
                <td className="num">{eok(r.storeAmt)}</td>
                <td className="num">{pct(r.storeDsctRate)}</td>
                <td className="num strong">{pct(r.online?.recentRate)}</td>
                <td className="num">{pct(r.online?.baseRate)}</td>
                <td className={`num ${r.flag ? 'up' : ''}`}>
                  {r.diff === null ? (r.flag === 'new' ? '새로 할인' : '-') : `${r.diff > 0 ? '+' : ''}${r.diff.toFixed(1)}%p`}
                </td>
                <td className="num">{r.online?.lowPrice ? `${fmtNum(r.online.lowPrice)}원` : '-'}</td>
                <td className="num">{r.online ? r.online.malls : '-'}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={10} className="empty">{all ? '상품이 없습니다.' : '최근 온라인 할인율이 크게 오른 상위 상품이 없습니다.'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
