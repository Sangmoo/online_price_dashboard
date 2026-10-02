import { useEffect, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Globe, Loader2, Package, Store, X } from 'lucide-react'
import { apiFetch } from '../api'
import { fmtNum } from '../format'

type Insight = {
  prdtCd: string
  online?: {
    title: string | null
    lastDt: string | null
    daily: { dt: string; avgDcRate: number | null; maxDcRate: number | null; minDcPrice: number | null; price: number | null; malls: number; rows: number }[]
    malls: { mallNm: string; dcPrice: number | null; price: number | null; dcRate: number | null }[]
  }
  sales?: { itemNm: string | null; prdtGrpNm: string | null; source: string; months: { ym: string; amt: number; qty: number; dsctRate: number | null }[] }
  shops?: {
    from: string
    to: string
    shopCount: number
    qty: number
    amt: number
    topShare: number | null
    shops: { shopId: string; shopNm: string | null; team: string | null; qty: number; amt: number; share: number | null; dsctRate: number | null }[]
    teams: { team: string; brand: string; qty: number; amt: number; shops: number }[]
  }
  siblings?: {
    planYy: string
    season: string
    itemNm: string
    brand: string
    count: number
    rank: number | null
    topPct: number | null
    avgQty: number | null
    rows: { prdtCd: string; prdtGrpNm: string | null; qty: number; amt: number; dsctRate: number | null; from: string; to: string; rank: number }[]
  }
}

const dt = (v: string) => `${v.slice(4, 6)}-${v.slice(6, 8)}`
const ym = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${Number(v).toFixed(1)}%`)

/** 상품 팝업: 품번으로 온라인 가격(최근 31일)과 매장 판매(최근 12개월)를 나란히. 권한이 있는 쪽만 보인다. */
export default function ProductInsightModal({ prdtCd: initialCd, onClose }: { prdtCd: string; onClose: () => void }) {
  const [prdtCd, setPrdtCd] = useState(initialCd) // 같은 아이템 비교에서 다른 품번을 누르면 그 품번으로
  const [data, setData] = useState<Insight | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setData(null)
    setError(null)
    apiFetch(`/api/products/${encodeURIComponent(prdtCd)}/insight`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(e.message))
  }, [prdtCd])

  const tick = { fill: '#8b93a7', fontSize: 11 }
  const on = data?.online
  const sa = data?.sales
  const first = on?.daily[0]
  const last = on?.daily[on.daily.length - 1]
  const recent = sa ? sa.months.slice(-3).reduce((s, m) => s + m.qty, 0) : 0
  const before = sa ? sa.months.slice(-6, -3).reduce((s, m) => s + m.qty, 0) : 0

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card trend-modal product-modal">
        <div className="modal-head">
          <h3>
            <Package size={16} /> <span className="mono">{prdtCd}</span>
            <span className="muted small"> {[sa?.itemNm, sa?.prdtGrpNm].filter(Boolean).join(' · ')}</span>
          </h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        {on?.title && <div className="muted small ellipsis" title={on.title}>{on.title}</div>}
        {error && <div className="alert error">{error}</div>}
        {!data && !error && <div className="trend-loading"><Loader2 size={22} className="spin" /> 온라인 가격·매장 판매를 불러오는 중…</div>}

        {data && on && first && last && sa && (
          <div className="product-insight-note">
            온라인 평균 할인율 <b>{pct(first.avgDcRate)} → {pct(last.avgDcRate)}</b> ({dt(first.dt)} → {dt(last.dt)}) ·
            매장 판매 최근 3개월 <b>{fmtNum(recent)}개</b> (그 전 3개월 {fmtNum(before)}개)
          </div>
        )}

        {data && (
          <div className="product-insight-grid">
            {on && (
              <section>
                <div className="shop-invt-head"><Globe size={14} /> 온라인 가격 · 최근 31일</div>
                {on.daily.length === 0 ? (
                  <div className="muted small">최근 31일 수집 기록이 없습니다.</div>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={190}>
                      <LineChart data={on.daily.map((d) => ({ name: dt(d.dt), 평균할인율: d.avgDcRate, 최저가: d.minDcPrice }))}>
                        <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                        <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} minTickGap={16} />
                        <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={36} tickFormatter={(v) => `${v}%`} />
                        <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={52} tickFormatter={(v) => fmtNum(v)} />
                        <Tooltip formatter={(v, n) => (n === '평균할인율' ? `${v}%` : `${fmtNum(Number(v))}원`)} />
                        <Legend />
                        <Line yAxisId="l" dataKey="평균할인율" stroke="#ef4444" strokeWidth={2} dot={false} />
                        <Line yAxisId="r" dataKey="최저가" stroke="#6366f1" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                    <div className="table-wrap trend-table">
                      <table className="table">
                        <thead><tr><th>사이트 ({on.lastDt ? dt(on.lastDt) : '-'})</th><th className="num">할인가</th><th className="num">정상가</th><th className="num">할인율</th></tr></thead>
                        <tbody>
                          {on.malls.map((m) => (
                            <tr key={m.mallNm}><td>{m.mallNm}</td><td className="num strong">{fmtNum(m.dcPrice)}</td><td className="num muted">{fmtNum(m.price)}</td><td className="num">{pct(m.dcRate)}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </section>
            )}
            {sa && (
              <section>
                <div className="shop-invt-head"><Store size={14} /> 매장 판매 · 월별 <span className="muted small">({sa.source})</span></div>
                <ResponsiveContainer width="100%" height={190}>
                  <ComposedChart data={sa.months.map((m) => ({ name: ym(m.ym).slice(2), 수량: m.qty, 할인율: m.dsctRate }))}>
                    <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                    <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={false} />
                    <YAxis yAxisId="l" tick={tick} tickLine={false} axisLine={false} width={40} />
                    <YAxis yAxisId="r" orientation="right" tick={tick} tickLine={false} axisLine={false} width={36} tickFormatter={(v) => `${v}%`} />
                    <Tooltip formatter={(v, n) => (n === '할인율' ? `${v}%` : `${fmtNum(Number(v))}개`)} />
                    <Legend />
                    <Bar yAxisId="l" dataKey="수량" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={22} />
                    <Line yAxisId="r" dataKey="할인율" stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} />
                  </ComposedChart>
                </ResponsiveContainer>
                <div className="table-wrap trend-table">
                  <table className="table">
                    <thead><tr><th>판매년월</th><th className="num">수량</th><th className="num">실판금액</th><th className="num">할인율</th></tr></thead>
                    <tbody>
                      {sa.months.map((m) => (
                        <tr key={m.ym}><td>{ym(m.ym)}</td><td className="num">{fmtNum(m.qty)}</td><td className="num strong">{fmtNum(m.amt)}</td><td className="num">{pct(m.dsctRate)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        )}
        {data?.shops && data.shops.shopCount > 0 && (
          <section>
            <div className="shop-invt-head">
              <Store size={14} /> 많이 팔린 매장 · {ym(data.shops.from)}~{ym(data.shops.to)}
              <span className="muted small">
                판매 매장 {fmtNum(data.shops.shopCount)}개 · 수량 {fmtNum(data.shops.qty)}개 · 상위 {data.shops.shops.length}개 매장이 실판금액의 {pct(data.shops.topShare)}
              </span>
            </div>
            <div className="mini-grid">
              <div className="table-wrap trend-table">
                <table className="table">
                  <thead><tr><th>매장</th><th>팀</th><th className="num">수량</th><th className="num">실판금액</th><th className="num">비중</th><th className="num">할인율</th></tr></thead>
                  <tbody>
                    {data.shops.shops.map((s) => (
                      <tr key={s.shopId}>
                        <td title={s.shopId}>{s.shopNm ?? s.shopId} <span className="muted mono small">{s.shopId}</span></td>
                        <td className="small">{s.team ?? '-'}</td>
                        <td className="num strong">{fmtNum(s.qty)}</td>
                        <td className="num">{fmtNum(s.amt)}</td>
                        <td className="num">{pct(s.share)}</td>
                        <td className="num">{pct(s.dsctRate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="table-wrap trend-table">
                <table className="table">
                  <thead><tr><th>팀</th><th className="num">매장 수</th><th className="num">수량</th><th className="num">수량 비중</th></tr></thead>
                  <tbody>
                    {data.shops.teams.map((t) => (
                      <tr key={t.team}>
                        <td>{t.team} <span className="muted small">{t.brand}</span></td>
                        <td className="num">{fmtNum(t.shops)}</td>
                        <td className="num strong">{fmtNum(t.qty)}</td>
                        <td className="num">{data.shops && data.shops.qty ? pct((t.qty * 100) / data.shops.qty) : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}
        {data?.siblings && data.siblings.count > 1 && (
          <section>
            <div className="shop-invt-head">
              <Package size={14} /> 같은 아이템 비교 · {data.siblings.brand} {data.siblings.planYy} {data.siblings.season} {data.siblings.itemNm}
              <span className="muted small">
                {data.siblings.count}개 품번 중 수량 <b>{data.siblings.rank}위</b>
                {data.siblings.topPct !== null ? ` (상위 ${data.siblings.topPct}%)` : ''} · 품번 평균 {fmtNum(data.siblings.avgQty)}개 · 시즌 누적
              </span>
            </div>
            <div className="table-wrap trend-table">
              <table className="table">
                <thead><tr><th>순위</th><th>품번</th><th>품군</th><th className="num">수량</th><th className="num">실판금액</th><th className="num">할인율</th><th>판매 기간</th></tr></thead>
                <tbody>
                  {data.siblings.rows.map((r) => (
                    <tr key={r.prdtCd} className={r.prdtCd === prdtCd ? 'me-row' : ''}>
                      <td className="muted">{r.rank}</td>
                      <td>
                        {r.prdtCd === prdtCd ? <b className="mono">{r.prdtCd}</b> : (
                          <button className="btn-link mono" onClick={() => setPrdtCd(r.prdtCd)} title="이 품번으로 보기">{r.prdtCd}</button>
                        )}
                      </td>
                      <td className="small">{r.prdtGrpNm ?? '-'}</td>
                      <td className="num strong">{fmtNum(r.qty)}</td>
                      <td className="num">{fmtNum(r.amt)}</td>
                      <td className="num">{pct(r.dsctRate)}</td>
                      <td className="small muted">{ym(r.from)}~{ym(r.to)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <div className="muted small">온라인: 가격 수집(T_SELECT_ONLINE_MNG_R) · 매장: 마감 판매(T_CLOSE_SALE_BASE) · 할인율 = 할인금액 ÷ (실판금액 + 할인금액)</div>
      </div>
    </div>
  )
}
