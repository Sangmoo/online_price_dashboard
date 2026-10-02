import { useEffect, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ClipboardList, Loader2, PieChart, Store, UserRound, X } from 'lucide-react'
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
type Profile = {
  shop: {
    shopId: string
    shopNm: string | null
    status: string | null
    teamNm: string | null
    repId: string | null
    repNm: string | null
    openDt: string | null
    closeDt: string | null
    brands: { brdCd: string; brand: string }[]
    addr: string | null
    tel: string | null
    found: boolean
  }
  goals?: Record<string, number>
  invtPlans?: { planId: number; invtPlanDt: string | null; invtPlanNote: string | null; lastInvtDt: string | null; prevInvtType: string | null; shopRankNm: string | null; stockQty: number | null }[]
  managers?: { smasrNm: string; smasrHp: string | null; openDt: string | null }[]
  mix?: {
    from: string
    to: string
    brand: string | null
    amt: number
    brandAvg: boolean
    itemCount: number
    salesTypes: { name: string; amt: number; qty: number; share: number | null; dsctRate: number | null; brandShare?: number; shareDiff?: number | null }[]
    items: { name: string; amt: number; qty: number; share: number | null; dsctRate: number | null }[]
  }
}

const ym = (v: string) => `${v.slice(0, 4)}-${v.slice(4)}`
const d8 = (v: string | null | undefined) => (v && v.length >= 8 ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}` : '-')
const mil = (v: number) => Math.round(v / 1_000_000)
const achieve = (amt: number, goal: number | undefined) => (goal ? Math.round((amt * 1000) / goal) / 10 : null)
export const fmtGrowth = (g: number | null) => (g === null ? '-' : `${g > 0 ? '+' : ''}${g.toFixed(1)}%`)
export const growthClass = (g: number | null) => (g === null ? 'muted' : g >= 0 ? 'up' : 'down')
const achieveClass = (v: number | null) => (v === null ? 'muted' : v >= 100 ? 'up' : 'down')

/** 매장 정보 팝업: 기본 정보·담당 영업직원 + 최근 12개월 판매(전년 비교·목표 대비) + 실사 일정·매니저(실사계획 권한).
 *  url 은 화면 권한에 맞는 판매 추이 API, ctx='invt' 는 실사계획 화면에서 연 경우. */
export default function ShopTrendModal({ url, shopId, ctx, title, onClose }: {
  url: string
  shopId?: string
  ctx?: 'invt'
  title?: string
  onClose: () => void
}) {
  const [data, setData] = useState<Trend | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch(url)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(e.message))
  }, [url])
  useEffect(() => {
    if (!shopId) return
    apiFetch(`/api/shops/${encodeURIComponent(shopId)}/profile${ctx ? `?ctx=${ctx}` : ''}`)
      .then((r) => r.json())
      .then(setProfile)
      .catch((e) => setProfileError(e.message))
  }, [shopId, ctx])

  const goals = profile?.goals
  const hasGoals = !!goals && Object.keys(goals).length > 0
  const chart = (data?.months ?? []).map((m) => ({
    ym: ym(m.ym).slice(2), 당해: mil(m.amt), 전년: mil(m.prevAmt), ...(hasGoals ? { 목표: goals![m.ym] ? mil(goals![m.ym]) : null } : {}),
  }))
  const tick = { fill: '#8b93a7', fontSize: 12 }
  const goalTotal = hasGoals && data ? data.months.reduce((s, m) => s + (goals![m.ym] ?? 0), 0) : 0
  const goalSales = hasGoals && data ? data.months.reduce((s, m) => s + (goals![m.ym] ? m.amt : 0), 0) : 0
  const s = profile?.shop

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card trend-modal">
        <div className="modal-head">
          <h3>
            <Store size={16} /> {s?.shopNm ?? data?.shopNm ?? title ?? ''} <span className="muted mono">{shopId ?? data?.shopId}</span>
            {s?.status && <span className={`shop-status ${s.status === '정상' ? 'ok' : s.status === '폐점' ? 'closed' : 'warn'}`}>{s.status}</span>}
          </h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>

        {s && s.found && (
          <div className="shop-info-grid">
            <div><span>브랜드 · 팀</span><b>{s.brands.map((b) => b.brand).join(', ') || '-'} · {s.teamNm ?? '-'}</b></div>
            <div>
              <span><UserRound size={12} /> 담당 영업직원</span>
              <b>{s.repNm ?? '미지정'}{s.repId && <span className="muted mono small"> {s.repId}</span>}</b>
            </div>
            <div><span>오픈일{s.closeDt ? ' · 폐점일' : ''}</span><b>{s.openDt ?? '-'}{s.closeDt ? ` · ${s.closeDt}` : ''}</b></div>
            <div><span>매장 전화</span><b>{s.tel ?? '-'}</b></div>
            <div className="wide"><span>주소</span><b>{s.addr ?? '-'}</b></div>
          </div>
        )}
        {s && !s.found && <div className="muted small">매장 마스터(T_SHOP_BRD)에 이 매장 정보가 없습니다.</div>}
        {profileError && <div className="muted small">매장 정보: {profileError}</div>}

        {error && <div className="alert error">{error}</div>}
        {!data && !error && <div className="trend-loading"><Loader2 size={22} className="spin" /> 판매 데이터를 불러오는 중…</div>}
        {data && (
          <>
            <div className="summary-pills">
              <div className="pill strong"><span>기간</span><b>{ym(data.from)} ~ {ym(data.to)}</b></div>
              <div className="pill"><span>실판금액</span><b>{fmtNum(data.total.amt)}원</b></div>
              <div className="pill"><span>전년 같은 기간</span><b>{fmtNum(data.total.prevAmt)}원</b></div>
              <div className="pill"><span>증감</span><b className={growthClass(data.total.growth)}>{fmtGrowth(data.total.growth)}</b></div>
              {hasGoals && (
                <div className="pill" title="목표가 있는 달의 실판금액 ÷ 목표금액">
                  <span>목표 달성률</span><b className={achieveClass(achieve(goalSales, goalTotal))}>{achieve(goalSales, goalTotal) ?? '-'}%</b>
                </div>
              )}
              <div className="pill"><span>수량</span><b>{fmtNum(data.total.qty)}</b></div>
            </div>
            <ResponsiveContainer width="100%" height={230}>
              <ComposedChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="rgba(148,163,184,.18)" vertical={false} />
                <XAxis dataKey="ym" tick={tick} tickLine={false} axisLine={false} />
                <YAxis tick={tick} tickLine={false} axisLine={false} width={52} tickFormatter={(v) => fmtNum(v)} />
                <Tooltip formatter={(v) => `${fmtNum(Number(v))}백만원`} />
                <Legend />
                <Bar dataKey="당해" fill="#6366f1" radius={[5, 5, 0, 0]} maxBarSize={26} />
                <Line dataKey="전년" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 3 }} />
                {hasGoals && <Line dataKey="목표" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />}
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
                    {hasGoals && <><th className="num">목표(원)</th><th className="num">달성률</th></>}
                  </tr>
                </thead>
                <tbody>
                  {data.months.map((m) => {
                    const g = goals?.[m.ym]
                    const a = achieve(m.amt, g)
                    return (
                      <tr key={m.ym}>
                        <td>{ym(m.ym)}</td>
                        <td className="num">{fmtNum(m.qty)}</td>
                        <td className="num strong">{fmtNum(m.amt)}</td>
                        <td className="num muted">{fmtNum(m.prevAmt)}</td>
                        <td className={`num ${growthClass(m.growth)}`}>{fmtGrowth(m.growth)}</td>
                        {hasGoals && <><td className="num muted">{g ? fmtNum(g) : '-'}</td><td className={`num ${achieveClass(a)}`}>{a === null ? '-' : `${a}%`}</td></>}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}

        {profile?.mix && profile.mix.amt !== 0 && (
          <div className="mix-block">
            <div className="shop-invt-head">
              <PieChart size={14} /> 판매 구성 · {ym(profile.mix.from)}~{ym(profile.mix.to)}
              <span className="muted small">
                {profile.mix.brandAvg ? `주황 선: ${profile.mix.brand} 전체 비중` : '브랜드 평균은 상품 사전 집계 뷰가 있을 때 표시'}
              </span>
            </div>
            <div className="mini-grid">
              <div className="table-wrap trend-table">
                <table className="table">
                  <thead>
                    <tr><th>판매형태</th><th className="num">실판금액</th><th>비중</th><th className="num">비중</th>{profile.mix.brandAvg && <th className="num">브랜드 대비</th>}<th className="num">할인율</th></tr>
                  </thead>
                  <tbody>
                    {profile.mix.salesTypes.map((t) => (
                      <tr key={t.name}>
                        <td className="strong">{t.name}</td>
                        <td className="num">{fmtNum(t.amt)}</td>
                        <td>
                          <div className="share-bar">
                            <i style={{ width: `${Math.max(0, Math.min(100, t.share ?? 0))}%` }} />
                            {t.brandShare !== undefined && <s style={{ left: `${Math.max(0, Math.min(100, t.brandShare))}%` }} />}
                          </div>
                        </td>
                        <td className="num">{t.share === null ? '-' : `${t.share.toFixed(1)}%`}</td>
                        {profile.mix!.brandAvg && (
                          <td className={`num ${growthClass(t.shareDiff ?? null)}`}>
                            {t.shareDiff === null || t.shareDiff === undefined ? '-' : `${t.shareDiff > 0 ? '+' : ''}${t.shareDiff.toFixed(1)}%p`}
                          </td>
                        )}
                        <td className="num">{t.dsctRate === null ? '-' : `${t.dsctRate.toFixed(1)}%`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="table-wrap trend-table">
                <table className="table">
                  <thead><tr><th>주력 아이템 (상위 {profile.mix.items.length}/{profile.mix.itemCount})</th><th className="num">수량</th><th className="num">실판금액</th><th className="num">비중</th></tr></thead>
                  <tbody>
                    {profile.mix.items.map((t) => (
                      <tr key={t.name}>
                        <td className="strong">{t.name}</td>
                        <td className="num">{fmtNum(t.qty)}</td>
                        <td className="num">{fmtNum(t.amt)}</td>
                        <td className="num">{t.share === null ? '-' : `${t.share.toFixed(1)}%`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {profile && (profile.invtPlans || profile.managers) && (
          <div className="shop-invt">
            <div className="shop-invt-head"><ClipboardList size={14} /> 재고 실사 · 매니저</div>
            <div className="shop-info-grid">
              {(profile.invtPlans ?? []).slice(0, 2).map((p) => (
                <div key={p.planId} className="wide">
                  <span>실사계획 #{p.planId}</span>
                  <b>
                    예정일 {p.invtPlanDt ? d8(p.invtPlanDt) : '미정'} · 최종실사 {d8(p.lastInvtDt)}{p.prevInvtType ? `(${p.prevInvtType})` : ''}
                    {p.shopRankNm ? ` · 관리등급 ${p.shopRankNm}` : ''}{p.stockQty !== null ? ` · 재고 ${fmtNum(p.stockQty)}` : ''}
                  </b>
                </div>
              ))}
              {profile.invtPlans && profile.invtPlans.length === 0 && <div className="wide"><span>실사계획</span><b className="muted">등록된 계획 없음</b></div>}
              <div className="wide">
                <span>현재 매니저</span>
                <b>{profile.managers && profile.managers.length ? profile.managers.map((m) => `${m.smasrNm}${m.smasrHp ? ` (${m.smasrHp})` : ''}`).join(', ') : '-'}</b>
              </div>
            </div>
          </div>
        )}
        <div className="muted small">
          판매: 지난달까지 마감된 판매(T_CLOSE_SALE_BASE) · 목표: T_SHOP_SELL_MGOAL · 매장·담당 영업직원: T_SHOP_BRD · T_SHOP · 차트 단위 백만원
        </div>
      </div>
    </div>
  )
}
