import { useEffect, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Loader2, TrendingUp, X } from 'lucide-react'
import { apiFetch } from '../api'
import { fmtNum } from '../format'

type Month = { ym: string; qty: number; amt: number; prevQty: number; prevAmt: number; growth: number | null }
type Trend = {
  shopId: string
  shopNm: string | null
  from: string
  to: string
  months: Month[]
  total: { qty: number; amt: number; prevQty: number; prevAmt: number; growth: number | null }
}

const ym = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
const mil = (v: number) => Math.round(v / 1_000_000)
export const fmtGrowth = (g: number | null) => (g === null ? '-' : `${g > 0 ? '+' : ''}${g.toFixed(1)}%`)
export const growthClass = (g: number | null) => (g === null ? 'muted' : g >= 0 ? 'up' : 'down')

/** 매장 최근 12개월 월별 판매 추이 (전년 같은 달 비교). url 은 화면 권한에 맞는 API. */
export default function ShopTrendModal({ url, title, onClose }: { url: string; title?: string; onClose: () => void }) {
  const [data, setData] = useState<Trend | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch(url)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(e.message))
  }, [url])

  const chart = (data?.months ?? []).map((m) => ({ ym: ym(m.ym).slice(2), 당해: mil(m.amt), 전년: mil(m.prevAmt) }))
  const tick = { fill: '#8b93a7', fontSize: 12 }

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card trend-modal">
        <div className="modal-head">
          <h3>
            <TrendingUp size={16} /> {data?.shopNm ?? title ?? ''} <span className="muted mono">{data?.shopId}</span> 판매 추이
          </h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        {error && <div className="alert error">{error}</div>}
        {!data && !error && <div className="trend-loading"><Loader2 size={22} className="spin" /> 판매 데이터를 불러오는 중…</div>}
        {data && (
          <>
            <div className="summary-pills">
              <div className="pill strong"><span>기간</span><b>{ym(data.from)} ~ {ym(data.to)}</b></div>
              <div className="pill"><span>실판금액</span><b>{fmtNum(data.total.amt)}원</b></div>
              <div className="pill"><span>전년 같은 기간</span><b>{fmtNum(data.total.prevAmt)}원</b></div>
              <div className="pill"><span>증감</span><b className={growthClass(data.total.growth)}>{fmtGrowth(data.total.growth)}</b></div>
              <div className="pill"><span>수량</span><b>{fmtNum(data.total.qty)}</b></div>
            </div>
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                <XAxis dataKey="ym" tick={tick} tickLine={false} axisLine={false} />
                <YAxis tick={tick} tickLine={false} axisLine={false} width={52} tickFormatter={(v) => fmtNum(v)} />
                <Tooltip formatter={(v) => `${fmtNum(Number(v))}백만원`} />
                <Legend />
                <Bar dataKey="당해" fill="#6366f1" radius={[5, 5, 0, 0]} maxBarSize={26} />
                <Line dataKey="전년" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3 }} />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="table-wrap trend-table">
              <table className="table">
                <thead>
                  <tr>
                    <th>판매년월</th>
                    <th className="num">수량</th>
                    <th className="num">실판금액(원)</th>
                    <th className="num">전년 같은 달(원)</th>
                    <th className="num">증감</th>
                  </tr>
                </thead>
                <tbody>
                  {data.months.map((m) => (
                    <tr key={m.ym}>
                      <td>{ym(m.ym)}</td>
                      <td className="num">{fmtNum(m.qty)}</td>
                      <td className="num strong">{fmtNum(m.amt)}</td>
                      <td className="num muted">{fmtNum(m.prevAmt)}</td>
                      <td className={`num ${growthClass(m.growth)}`}>{fmtGrowth(m.growth)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted small">지난달까지 마감된 판매(T_CLOSE_SALE_BASE) 기준 · 차트 단위 백만원</div>
          </>
        )}
      </div>
    </div>
  )
}
