import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { apiFetch } from '../api'
import { growthClass } from './ShopTrendModal'

type Shop = {
  shopId: string; shopNm: string | null; event: boolean; team: string; brand: string; amt: number; discAmt: number
  share: number | null; brandShare: number | null; diff: number | null; baseShare: number | null; shareChange: number | null
}
type Data = {
  period: string; base: string; baseKind: string; brand: string | null; minMonthlyAmt: number; rule: string; includeEvent: boolean
  shops: Shop[]; candidateCount: number; eventShops: number; brandAverages: { brand: string; share: number | null; baseShare: number | null }[]
}

const eok = (v: number) =>
  Math.abs(v) >= 100_000_000 ? `${(v / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억` : `${Math.round(v / 10_000).toLocaleString('ko-KR')}만`
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v.toFixed(1)}%`)
const pp = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%p`)

/** 판매 현황 아래: 세일 비중이 같은 브랜드 평균보다 크게 높은 매장. 매장명을 누르면 매장 정보 팝업. */
export default function SaleHeavyShopsPanel({ query, onShop }: { query: string; onShop: (id: string, name: string) => void }) {
  const [includeEvent, setIncludeEvent] = useState(false)
  const [data, setData] = useState<Data | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    apiFetch(`/api/sale-dashboard/sale-heavy-shops${query}${includeEvent ? '&includeEvent=true' : ''}`)
      .then((r) => r.json())
      .then((d: Data) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [query, includeEvent])

  if (loading && !data) return <section className="card panel"><div className="trend-loading"><Loader2 size={18} className="spin" /> 매장별 세일 비중을 계산하는 중…</div></section>
  if (error) return <div className="alert error">세일 비중 높은 매장: {error}</div>
  if (!data) return null

  return (
    <section className="card panel sale-heavy-panel">
      <div className="panel-head row">
        <h3>세일 비중이 높은 매장</h3>
        <span className="panel-hint">
          {data.period} · 매장 실판금액 중 세일 판매 비중 − 같은 브랜드 전체 비중 · 월평균 {eok(data.minMonthlyAmt)} 이상 · 폐점 제외 ·
          {' '}대상 {data.candidateCount}개{loading ? ' · 갱신 중…' : ''}
        </span>
        <div className="grow" />
        <label className="check-label" title={`매장명이 (행)·(특)으로 시작하거나 사내행사인 매장 ${data.eventShops}개`}>
          <input type="checkbox" checked={includeEvent} onChange={(e) => setIncludeEvent(e.target.checked)} /> 행사·특판 매장 포함
        </label>
      </div>
      <div className="summary-pills">
        {data.brandAverages.map((b) => (
          <div key={b.brand} className="pill"><span>{b.brand} 평균</span><b>{pct(b.share)}</b><span className="muted">{data.baseKind} {pct(b.baseShare)}</span></div>
        ))}
      </div>
      <div className="table-wrap tall-ish">
        <table className="table sd-table">
          <thead>
            <tr>
              <th>#</th><th>매장</th><th>팀</th><th className="num">실판금액</th><th className="num">세일 비중</th><th className="num">브랜드 평균</th>
              <th className="num">차이</th><th className="num">{data.baseKind}</th><th className="num">변화</th>
            </tr>
          </thead>
          <tbody>
            {data.shops.map((s, i) => (
              <tr key={s.shopId}>
                <td className="muted">{i + 1}</td>
                <td><button className="btn-link" onClick={() => onShop(s.shopId, s.shopNm ?? s.shopId)}>{s.shopNm ?? s.shopId}</button> <span className="muted mono small">{s.shopId}</span></td>
                <td className="small">{s.team}</td>
                <td className="num">{eok(s.amt)}</td>
                <td className="num strong">{pct(s.share)}</td>
                <td className="num muted">{pct(s.brandShare)}</td>
                <td className="num up">{pp(s.diff)}</td>
                <td className="num muted">{pct(s.baseShare)}</td>
                <td className={`num ${growthClass(s.shareChange)}`}>{pp(s.shareChange)}</td>
              </tr>
            ))}
            {data.shops.length === 0 && <tr><td colSpan={9} className="empty">해당 매장이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="muted small">{data.rule} · 반품이 다른 판매형태에 잡히면 100%를 넘을 수 있습니다.</div>
    </section>
  )
}
