import { useEffect, useState } from 'react'
import { ArrowRightLeft, Award, Gauge, Loader2, PackageCheck, TrendingUp } from 'lucide-react'
import { apiFetch, ApiError } from '../api'
import { fmtNum } from '../format'

// 매장 평가 카드 (매장 정보 팝업 안): 판매 추세 · 재고 회전 · RT 응답 · 초도 판매율을 브랜드 평균과 비교

type Grade = 'good' | 'ok' | 'bad' | 'none'
type Num = number | null | undefined
export type Scorecard = {
  shopId: string; shopNm: string | null; brand: string; brandNm: string; virtual?: boolean; virtualWhy?: string | null; asOf: string; errors: string[]
  summary: { good: number; ok: number; bad: number }
  sales?: { from: string; to: string; curAmt?: number; curQty: number; prevAmt?: number; prevQty: number; lyAmt?: number; vsPrev: Num; vsLy: Num
    brandVsPrev: Num; brandVsLy: Num; grade: Grade; note: string }
  stock?: { stock: number; amt: number; sales28: number; cover: Num; sellThru: Num; agedQty: number; agedRate: Num; brandCover: Num; brandAgedRate: Num
    grade: Grade; note: string }
  rt?: { requests: number; accepted: number; denied: number; autoDenied: number; pending: number; acceptRate: Num; avgHours: Num
    brandAcceptRate: Num; brandAvgHours: Num; grade: Grade; note: string }
  initial?: { period: string; window: number; alloc: number; sold: number; sellThru: Num; products: number; zero: number; soldOut: number
    brandSellThru: Num; brandOverlap: Num; grade: Grade; note: string }
}

const GRADE: Record<Grade, string> = { good: '좋음', ok: '보통', bad: '주의', none: '판단 보류' }
const growth = (v: Num) => (v == null ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)
const pct = (v: Num) => (v == null ? '-' : `${v.toFixed(1)}%`)
const days = (v: Num) => (v == null ? '판매 없음' : `${fmtNum(Math.round(v))}일`)
const eok = (v: number) => (Math.abs(v) >= 1e8 ? `${(v / 1e8).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억` : `${Math.round(v / 1e4).toLocaleString('ko-KR')}만`)

function Tile({ icon, title, grade, main, sub, compare, note }: {
  icon: React.ReactNode; title: string; grade: Grade; main: string; sub: string; compare: string; note: string
}) {
  return (
    <div className={`sc-tile ${grade}`} title={note}>
      <div className="sc-tile-head">{icon}<span>{title}</span><b className={`sc-grade ${grade}`}>{GRADE[grade]}</b></div>
      <div className="sc-main">{main}</div>
      <div className="sc-sub">{sub}</div>
      <div className="sc-compare">{compare}</div>
    </div>
  )
}

export default function ShopScorecard({ shopId }: { shopId: string }) {
  const [d, setD] = useState<Scorecard | null>(null)
  const [error, setError] = useState('')
  const [hidden, setHidden] = useState(false)
  useEffect(() => {
    setD(null)
    apiFetch(`/api/shops/${encodeURIComponent(shopId)}/scorecard`).then((r) => r.json()).then(setD).catch((e) => {
      if (e instanceof ApiError && (e.status === 403 || e.status === 404)) setHidden(true)   // 권한 없는 메뉴 · 브랜드면 카드를 숨긴다
      else setError((e as Error).message)
    })
  }, [shopId])
  if (hidden) return null
  if (error) return <div className="muted small">매장 평가 카드: {error}</div>
  if (!d) return <div className="sc-block sc-loading"><Loader2 size={15} className="spin" /> 매장 평가 카드를 계산하는 중… (판매 · 재고 · RT · 초도)</div>
  const s = d.sales
  const st = d.stock
  const rt = d.rt
  const ini = d.initial
  return (
    <div className="sc-block" aria-label="매장 평가 카드">
      <div className="sc-title">
        <Award size={15} /> 매장 평가 카드 <span className="muted small">브랜드({d.brandNm}) 평균과 비교 · {d.asOf}</span>
        <span className="sc-sum">
          {d.summary.good > 0 && <span className="sc-grade good">좋음 {d.summary.good}</span>}
          {d.summary.ok > 0 && <span className="sc-grade ok">보통 {d.summary.ok}</span>}
          {d.summary.bad > 0 && <span className="sc-grade bad">주의 {d.summary.bad}</span>}
        </span>
      </div>
      {d.virtual && <div className="muted small">행사 · 가상 매장({d.virtualWhy}) — 재고 재배치 통계에서는 빠지는 매장입니다.</div>}
      <div className="sc-tiles">
        {s && (
          <Tile icon={<TrendingUp size={14} />} title={`판매 추세 (최근 4주 ${s.from.slice(5)}~${s.to.slice(5)})`} grade={s.grade}
            main={`전 4주 대비 ${growth(s.vsPrev)}`}
            sub={`${s.curAmt != null ? `실판 ${eok(s.curAmt)} · ` : ''}${fmtNum(s.curQty)}장 · 전년 같은 4주 ${growth(s.vsLy)}`}
            compare={`브랜드 전 4주 대비 ${growth(s.brandVsPrev)} · 전년 ${growth(s.brandVsLy)}`} note={s.note} />
        )}
        {st && (
          <Tile icon={<Gauge size={14} />} title="재고 회전 (최근 28일 판매)" grade={st.grade}
            main={`재고일수 ${days(st.cover)}`}
            sub={`재고 ${fmtNum(st.stock)}장 · 판매율 ${pct(st.sellThru)} · 90일 넘게 안 팔림 ${pct(st.agedRate)}`}
            compare={st.brandCover != null ? `브랜드 재고일수 ${days(st.brandCover)} · 장기 비중 ${pct(st.brandAgedRate)}` : '브랜드 평균은 재고 기준 계산 후(매일 아침) 표시'} note={st.note} />
        )}
        {rt && (
          <Tile icon={<ArrowRightLeft size={14} />} title="RT 응답 (최근 30일 · 보내는 쪽)" grade={rt.grade}
            main={`수락률 ${pct(rt.acceptRate)}`}
            sub={`요청 ${fmtNum(rt.requests)} · 거부 ${fmtNum(rt.denied)} · 자동거부 ${fmtNum(rt.autoDenied)} · 미처리 ${fmtNum(rt.pending)} · 평균 처리 ${rt.avgHours != null ? `${rt.avgHours}시간` : '-'}`}
            compare={`브랜드 수락률 ${pct(rt.brandAcceptRate)} · 평균 처리 ${rt.brandAvgHours != null ? `${rt.brandAvgHours}시간` : '-'}`} note={rt.note} />
        )}
        {ini && (
          <Tile icon={<PackageCheck size={14} />} title={`초도 판매율 (${ini.window}일)`} grade={ini.grade}
            main={ini.alloc ? `판매율 ${pct(ini.sellThru)}` : '초도 배분 없음'}
            sub={ini.alloc ? `배분 ${fmtNum(ini.alloc)} · 판매 ${fmtNum(ini.sold)}장 · 상품 ${fmtNum(ini.products)} (무판매 ${fmtNum(ini.zero)} · 소진 ${fmtNum(ini.soldOut)})` : ini.period}
            compare={`브랜드 판매율 ${pct(ini.brandSellThru)} · 초도 배분 ${ini.period}`} note={ini.note} />
        )}
      </div>
      {d.errors.length > 0 && <div className="muted small">일부 항목을 계산하지 못했습니다: {d.errors.join(' · ')}</div>}
    </div>
  )
}
