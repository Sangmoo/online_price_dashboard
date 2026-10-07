import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ArrowRight, ArrowRightLeft, BarChart3, Bot, CheckCircle2, Clock, Gauge, Hourglass, PackageCheck, Undo2, ClipboardList, Download, Info, ListOrdered, Loader2, RefreshCw, Search, Send, Settings2, Store, Warehouse, X } from 'lucide-react'
import { ApiError } from '../api'
import { fmtNum } from '../format'
import {
  stockApi,
  type AllocCond, type AllocResult, type AllocRow, type AllocSku, type RecentRun, type RtCond, type RtPerformance, type RtResult, type RtStats, type SettingCheck,
  type ShortRt,
  type StockOptions,
} from '../stockApi'
import { AllocRegisterModal, RegisteredModal, RtRegisterModal } from './StockWrite'
import { consumeStockOpen, useStockOpen, type StockOpenRequest } from '../stockNav'
import { Pager, SelectAllFiltered, usePaged } from './stockUi'
import { AgingTab, PendingTab, ReturnTab } from './StockMoreTabs'
import { InitialTab, TurnoverTab } from './StockAnalysisTabs'

type Tab = 'rt' | 'alloc' | 'return' | 'pending' | 'aging' | 'turnover' | 'initial'
const iso = (d8: string) => `${d8.slice(0, 4)}-${d8.slice(4, 6)}-${d8.slice(6, 8)}`
const addDaysIso = (isoDate: string, n: number) => {
  const d = new Date(`${isoDate}T00:00:00`)
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const spanDays = (a: string, b: string) => Math.round((new Date(`${b}T00:00:00`).getTime() - new Date(`${a}T00:00:00`).getTime()) / 86400000) + 1
const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))
const pct = (a: number, b: number) => (b ? `${Math.round((a * 1000) / b) / 10}%` : '-')
const rtKey = (r: RtResult['rows'][number]) => [r.prdtCd, r.colorCd, r.sizeCd, r.fromShopId, r.toShopId]
const alKey = (r: AllocRow) => [r.shopId, r.prdtCd, r.colorCd, r.sizeCd]

/** 표에서 고른 행 (키 문자열 집합) */
function useSelection() {
  const [sel, setSel] = useState<Set<string>>(new Set())
  const flip = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const setMany = (keys: string[], on: boolean) => setSel((s) => { const n = new Set(s); keys.forEach((k) => (on ? n.add(k) : n.delete(k))); return n })
  return { sel, flip, setMany, clear: () => setSel(new Set()) }
}

/** 계산 중 경과 초 */
function useElapsed(on: boolean) {
  const [sec, setSec] = useState(0)
  useEffect(() => {
    if (!on) return
    setSec(0)
    const t = window.setInterval(() => setSec((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [on])
  return sec
}

function Chips({ items, value, onChange, empty }: { items: { code: string; name: string }[]; value: string[]; onChange: (v: string[]) => void; empty?: string }) {
  return (
    <div className="chips wrap">
      {items.map((it) => (
        <button key={it.code} className={`chip ${value.includes(it.code) ? 'active' : ''}`} onClick={() => onChange(toggle(value, it.code))} title={it.code}>{it.name}</button>
      ))}
      {empty && <span className="muted small">{empty}</span>}
    </div>
  )
}

function Computing({ sec, what }: { sec: number; what: string }) {
  return (
    <section className="card stock-computing" role="status">
      <Loader2 size={18} className="spin" />
      <div>
        <b>{what} 계산 중… {sec}초</b>
        <div className="muted small">판매 · 재고 · 수불제어를 ERP 규칙대로 확인합니다. 보통 10~30초, 기간이 길거나 시즌을 비우면 더 걸립니다. 같은 조건은 30분 동안 바로 열립니다.</div>
      </div>
    </section>
  )
}

/**
 * 재고 재배치 추천: 매장 간 RT(자동 RT 규칙) · 창고 → 매장 배분(판매분 자동보충 규칙).
 * 관리자(canWrite)는 고른 추천을 ERP 에 본사지시 RT 지시 · 배분의뢰(둘 다 미확정)로 넣고, 이 화면에서 넣은 미확정 행을 지울 수 있다.
 */
export default function StockRtView({ onContextChange }: { onContextChange?: (ctx: Record<string, string>) => void }) {
  const [tab, setTab] = useState<Tab>('rt')
  const [brand, setBrand] = useState('')
  const [opts, setOpts] = useState<StockOptions | null>(null)
  const [error, setError] = useState('')
  const req = useStockOpen()          // AI 대화 [화면에서 열기]
  const [seen, setSeen] = useState<Set<Tab>>(new Set(['rt']))      // 연 탭만 그린다 (미처리 · 장기 미판매는 열 때 불러온다)
  const [returnSeed, setReturnSeed] = useState<{ cond: AllocCond; nonce: number } | null>(null)
  useEffect(() => setSeen((v) => (v.has(tab) ? v : new Set(v).add(tab))), [tab])

  useEffect(() => {
    if (!req) return
    setTab(req.tab)
    if (req.brand !== brand) setBrand(req.brand)
  }, [req?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let stale = false                 // 브랜드를 빠르게 바꾸면(AI 화면 열기 등) 늦게 온 이전 브랜드 응답은 버린다
    stockApi.options(brand || undefined).then((o) => {
      if (stale) return
      setOpts(o)
      setBrand((b) => b || o.brand)
    }).catch((e) => { if (!stale) setError(errText(e)) })
    return () => { stale = true }
  }, [brand])

  return (
    <div className="stack">
      <section className="card stock-head">
        <div className="toolbar-title"><ArrowRightLeft size={18} /> 재고 재배치 추천</div>
        <div className="stock-tab-groups">
          <div className="stock-tab-group">
            <span className="stock-tab-label">재배치</span>
            <div className="seg big" role="tablist" aria-label="재배치">
              <button role="tab" aria-selected={tab === 'rt'} className={tab === 'rt' ? 'on' : ''} onClick={() => setTab('rt')}><Store size={14} /> 매장 간 RT</button>
              <button role="tab" aria-selected={tab === 'alloc'} className={tab === 'alloc' ? 'on' : ''} onClick={() => setTab('alloc')}><Warehouse size={14} /> 창고 → 매장 배분</button>
              <button role="tab" aria-selected={tab === 'return'} className={tab === 'return' ? 'on' : ''} onClick={() => setTab('return')}><Undo2 size={14} /> 창고 회수</button>
              <button role="tab" aria-selected={tab === 'pending'} className={tab === 'pending' ? 'on' : ''} onClick={() => setTab('pending')}><Clock size={14} /> 미처리 RT 현황</button>
            </div>
          </div>
          <div className="stock-tab-group">
            <span className="stock-tab-label">재고 분석</span>
            <div className="seg big" role="tablist" aria-label="재고 분석">
              <button role="tab" aria-selected={tab === 'turnover'} className={tab === 'turnover' ? 'on' : ''} onClick={() => setTab('turnover')}><Gauge size={14} /> 재고 회전</button>
              <button role="tab" aria-selected={tab === 'aging'} className={tab === 'aging' ? 'on' : ''} onClick={() => setTab('aging')}><Hourglass size={14} /> 장기 미판매 재고</button>
              <button role="tab" aria-selected={tab === 'initial'} className={tab === 'initial' ? 'on' : ''} onClick={() => setTab('initial')}><PackageCheck size={14} /> 초도 배분 적중률</button>
            </div>
          </div>
        </div>
        <div className="chips" role="group" aria-label="브랜드">
          {(opts?.brands ?? []).map((b) => (
            <button key={b.code} className={`chip ${brand === b.code ? 'active' : ''}`} onClick={() => setBrand(b.code)}>{b.name}</button>
          ))}
        </div>
        <span className="pill hint-pill"><Info size={13} /> {opts?.canWrite
          ? '관리자: 고른 추천을 ERP 본사지시 RT 지시 · 확정(로그인 사번) · 배분의뢰(미확정)로 등록할 수 있습니다'
          : '조회 · 추천만 합니다 — ERP 에 RT · 배분의뢰가 등록되지 않습니다'}</span>
      </section>
      {error && <div className="alert error">{error}</div>}
      {opts && opts.brand === brand && (
        <>
          <div hidden={tab !== 'rt'}><RtTab key={`rt-${brand}`} opts={opts} request={req?.tab === 'rt' && req.brand === opts.brand ? req : null} onContext={(c) => tab === 'rt' && onContextChange?.({ view: 'stock_rt', tab: 'rt', ...c })} /></div>
          <div hidden={tab !== 'alloc'}><AllocTab key={`al-${brand}`} opts={opts} request={req?.tab === 'alloc' && req.brand === opts.brand ? req : null} onContext={(c) => tab === 'alloc' && onContextChange?.({ view: 'stock_rt', tab: 'alloc', ...c })}
            onReturn={(cond) => { setReturnSeed({ cond, nonce: Date.now() }); setTab('return') }} /></div>
          {(seen.has('return') || returnSeed) && <div hidden={tab !== 'return'}><ReturnTab key={`ret-${brand}`} opts={opts} seed={returnSeed?.cond.brand === opts.brand ? returnSeed : null} /></div>}
          {seen.has('pending') && <div hidden={tab !== 'pending'}><PendingTab key={`pd-${brand}`} opts={opts} /></div>}
          {seen.has('aging') && <div hidden={tab !== 'aging'}><AgingTab key={`ag-${brand}`} opts={opts} /></div>}
          {seen.has('turnover') && <div hidden={tab !== 'turnover'}><TurnoverTab key={`tv-${brand}`} opts={opts} /></div>}
          {seen.has('initial') && <div hidden={tab !== 'initial'}><InitialTab key={`in-${brand}`} opts={opts} /></div>}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 매장 간 RT
function RtTab({ opts, request, onContext }: { opts: StockOptions; request: StockOpenRequest | null; onContext: (c: Record<string, string>) => void }) {
  const today = iso(opts.today)
  const init: RtCond = {
    brand: opts.brand, dateFrom: addDaysIso(today, -6), dateTo: today, planYy: opts.defaultPlanYy, seasons: opts.defaultSeasons, prdt: '', teams: [],
    per: 1, order: 'slow', senderMax: 0, limits: false,
  }
  const [cond, setCond] = useState<RtCond>(init)
  const [applied, setApplied] = useState<RtCond | null>(null)
  const [data, setData] = useState<RtResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'rows' | 'unfilled' | 'shops' | 'stats' | 'check' | 'perf'>('rows')
  const [perfOnly, setPerfOnly] = useState(false)          // 추천 계산 없이 RT 성과만 보기
  // AI 대화에서 고른 행 (계산이 끝나면 화면에서 체크)
  const pendingPick = useRef<{ keys: string[][]; label: string } | null>(null)
  const [aiPick, setAiPick] = useState<{ label: string; keys: Set<string>; found: number; total: number; qty: number } | null>(null)
  const [onlyPick, setOnlyPick] = useState(false)
  const [q, setQ] = useState('')
  const [exporting, setExporting] = useState(false)
  const [writing, setWriting] = useState<'register' | 'list' | null>(null)
  const [done, setDone] = useState('')
  const { sel, flip, setMany, clear } = useSelection()
  const abort = useRef<AbortController | null>(null)
  const sec = useElapsed(loading)
  const days = spanDays(cond.dateFrom, cond.dateTo)
  const bad = !cond.dateFrom || !cond.dateTo || days < 1 ? '기간을 고르세요.' : days > opts.maxDays ? `기간은 최대 ${opts.maxDays}일입니다.` : ''
  const seasonNm = useMemo(() => Object.fromEntries(opts.seasons.map((s) => [s.code, s.name])), [opts])

  const run = (refresh = false, override?: RtCond) => {
    if (bad && !override) return
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    setLoading(true)
    setError('')
    const c = { ...(override ?? cond) }
    stockApi.rt(c, refresh, ac.signal).then((d) => {
      setData(d)
      setApplied(c)
      clear()
      const pick = pendingPick.current
      pendingPick.current = null
      if (pick) {
        const want = new Set(pick.keys.map((k) => k.join('|')))
        const hit = d.rows.filter((r) => want.has(rtKey(r).join('|')))
        const keys = hit.map((r) => rtKey(r).join('|'))
        setAiPick({ label: pick.label, keys: new Set(keys), found: hit.length, total: want.size, qty: hit.reduce((a, r) => a + r.qty, 0) })
        setOnlyPick(true)
        if (opts.canWrite) setMany(keys, true)
      } else {
        setAiPick(null)
        setOnlyPick(false)
      }
      onContext({ brand: d.brandNm, period: `${d.from}~${d.to}`, seasons: c.seasons.map((s) => seasonNm[s] ?? s).join(','), prdt: c.prdt })
    }).catch((e) => { if (!ac.signal.aborted) setError(errText(e)) }).finally(() => { if (abort.current === ac) setLoading(false) })
  }
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {                   // AI 대화에서 정한 조건으로 열고 계산
    if (!request) return
    consumeStockOpen(request.nonce)
    const c = { ...init, ...request.cond } as RtCond
    setCond(c)
    pendingPick.current = request.select ?? null
    if (request.view) setView(request.view as typeof view)
    if (request.run !== false) run(false, c)
  }, [request?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = applied !== null && JSON.stringify(applied) !== JSON.stringify(cond)
  const rtSrc = useMemo(() => (applied ? stockApi.rtSource(applied) : null), [applied])
  const rows = useMemo(() => {
    const k = q.trim().toUpperCase()
    if (!data) return []
    const base = onlyPick && aiPick ? data.rows.filter((r) => aiPick.keys.has(rtKey(r).join('|'))) : data.rows
    if (!k) return base
    return base.filter((r) => [r.prdtCd, r.fromShopId, r.toShopId, r.fromShopNm, r.toShopNm, r.styleNm].some((v) => v?.toUpperCase().includes(k)))
  }, [data, q, onlyPick, aiPick])
  const unfilled = useMemo(() => {
    const k = q.trim().toUpperCase()
    if (!data) return []
    return k ? data.unfilled.filter((r) => [r.prdtCd, r.shopId, r.shopNm].some((v) => v?.toUpperCase().includes(k))) : data.unfilled
  }, [data, q])
  const s = data?.summary
  const selRows = useMemo(() => (data?.rows ?? []).filter((r) => sel.has(rtKey(r).join('|'))), [data, sel])
  const selQty = selRows.reduce((a, r) => a + r.qty, 0)
  const selKeys = useMemo(() => selRows.map(rtKey), [selRows])

  const exportXlsx = async () => {
    if (!applied) return
    setExporting(true)
    try { await stockApi.rtExport(applied) } catch (e) { setError(errText(e)) } finally { setExporting(false) }
  }

  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><Store size={17} /> 매장 간 RT 추천</div>
          <div className="date-range" title="판매 기간 (최대 31일)">
            <span className="date-range-label">판매 기간</span>
            <input type="date" value={cond.dateFrom} max={cond.dateTo || today} onChange={(e) => setCond({ ...cond, dateFrom: e.target.value })} aria-label="판매 기간 시작" />
            <span className="muted">~</span>
            <input type="date" value={cond.dateTo} min={cond.dateFrom} max={today} onChange={(e) => setCond({ ...cond, dateTo: e.target.value })} aria-label="판매 기간 끝" />
            <span className={`muted small ${days > opts.maxDays ? 'danger-text' : ''}`}>{days > 0 ? `${days}일` : ''}</span>
          </div>
          <div className="chips">
            {[7, 14, 31].map((n) => (
              <button key={n} className="chip" onClick={() => setCond({ ...cond, dateFrom: addDaysIso(today, -(n - 1)), dateTo: today })}>최근 {n}일</button>
            ))}
          </div>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => run(false)} disabled={loading || !!bad} title={bad || undefined}>
              {loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 추천 계산{dirty ? ' *' : ''}
            </button>
            <button className="btn ghost" onClick={() => run(true)} disabled={loading || !applied || !!bad} title="30분 캐시를 무시하고 지금 재고로 다시 계산">
              <RefreshCw size={15} /> 새로 계산
            </button>
            <button className="btn success" onClick={exportXlsx} disabled={!data || exporting || dirty}>
              {exporting ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀
            </button>
          </div>
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">기획년도</span>
          <Chips items={opts.planYears.map((y) => ({ code: y, name: y }))} value={cond.planYy} onChange={(planYy) => setCond({ ...cond, planYy })} />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">시즌</span>
          <Chips items={opts.seasons} value={cond.seasons} onChange={(seasons) => setCond({ ...cond, seasons })} empty="비우면 전체 (느림)" />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">받는 팀</span>
          <Chips items={opts.teams} value={cond.teams} onChange={(teams) => setCond({ ...cond, teams })} empty="비우면 전체" />
          <span className="filter-label">품번</span>
          <input className="input sm stock-prdt" value={cond.prdt} placeholder="앞부분만 입력 가능" onChange={(e) => setCond({ ...cond, prdt: e.target.value.toUpperCase() })} aria-label="품번" />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">방식</span>
          <div className="seg" role="group" aria-label="보내는 매장 순서">
            <button className={cond.order === 'slow' ? 'on' : ''} onClick={() => setCond({ ...cond, order: 'slow' })} title="기간 판매가 적은 매장부터 (재고 재배치)">안 팔리는 매장 우선</button>
            <button className={cond.order === 'auto' ? 'on' : ''} onClick={() => setCond({ ...cond, order: 'auto' })} title="ERP 자동 RT 와 같은 순서 (요청가능 재고 많은 순 · 판매율 · 최종판매일)">자동 RT 순서</button>
          </div>
          <label className="field-label">받는 상품당
            <select className="input sm" value={cond.per} onChange={(e) => setCond({ ...cond, per: Number(e.target.value) })} aria-label="받는 상품당 수량">
              {[1, 2, 3].map((n) => <option key={n} value={n}>{n}장</option>)}
            </select>
          </label>
          <label className="field-label">보내는 매장당 최대
            <select className="input sm" value={cond.senderMax} onChange={(e) => setCond({ ...cond, senderMax: Number(e.target.value) })} aria-label="보내는 매장당 최대 수량">
              {[0, 10, 20, 50, 100].map((n) => <option key={n} value={n}>{n ? `${n}장` : '제한 없음'}</option>)}
            </select>
          </label>
          <label className="check-label" title="ERP 자동 RT 의 하루 지정가능수 · 요청가능수까지 지킴 (지정가능수 0 매장이 많아 추천이 크게 줄어듭니다)">
            <input type="checkbox" checked={cond.limits} onChange={(e) => setCond({ ...cond, limits: e.target.checked })} /> 자동 RT 하루 한도 적용
          </label>
        </div>
      </section>

      {bad && <div className="alert warn">{bad}</div>}
      {error && <div className="alert error">{error}</div>}
      {loading && <Computing sec={sec} what="매장 간 RT 추천" />}
      {!data && !loading && (
        <section className="card stock-empty">
          <ArrowRightLeft size={26} />
          <div>
            <b>판매됐는데 재고가 없는 매장에, 같은 RT 그룹의 안 팔리는 재고를 짝지어 드립니다.</b>
            <div className="muted small">ERP 자동 RT 규칙(같은 RT 그룹 · 이동중/요청중 · 최소보유재고 · 출고 경과일 · 매장등급 · 수불제어)을 그대로 적용합니다. [추천 계산]을 누르세요.</div>
          </div>
          <button className="btn ghost sm stock-write-bar" onClick={() => setPerfOnly((v) => !v)}><BarChart3 size={14} /> {perfOnly ? 'RT 성과 닫기' : 'RT 성과 보기'}</button>
        </section>
      )}
      {!data && !loading && perfOnly && <section className="card grid-card"><RtPerformancePanel brand={opts.brand} today={opts.today} /></section>}

      {data && s && (
        <>
          <section className="summary-pills">
            <div className="pill strong"><span>받을 상품</span><b>{fmtNum(s.receivers)}건</b><span className="muted">필요 {fmtNum(s.needQty)}장</span></div>
            <div className="pill strong"><span>추천</span><b>{fmtNum(s.recRows)}건 · {fmtNum(s.recQty)}장</b><span className="muted">채움 {pct(s.filledReceivers, s.receivers)}</span></div>
            <div className="pill"><span>보내는 매장</span><b>{fmtNum(s.senders)}곳</b></div>
            <div className="pill"><span>받는 매장</span><b>{fmtNum(s.receivingShops)}곳</b></div>
            <div className="pill" title="기간 중 자동 RT 가 '지시가능매장없음'으로 취소된 요청 중 이번 추천으로 보낼 매장을 찾은 건"><span>자동 RT 취소 요청</span><b>{fmtNum(s.failFilled)} / {fmtNum(s.failRequests)}</b></div>
            <div className="pill"><span>못 채움</span><b>{fmtNum(s.unfilled)}건</b></div>
            <div className="pill hint-pill">{data.brandNm} · {data.from} ~ {data.to} · {data.orderNm}{data.limits ? ' · 하루 한도' : ''} · {data.asOf} 기준 · {data.timing.total}초</div>
            {dirty && <div className="pill hint-pill warn-pill">조건을 바꿨습니다 · [추천 계산]을 누르면 적용됩니다</div>}
          </section>

          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="결과 보기">
                <button className={view === 'rows' ? 'on' : ''} onClick={() => setView('rows')}>추천 목록 ({fmtNum(data.rowsTotal)})</button>
                <button className={view === 'unfilled' ? 'on' : ''} onClick={() => setView('unfilled')}>못 채운 수요 ({fmtNum(data.unfilledTotal)})</button>
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>매장별 합계</button>
                <button className={view === 'stats' ? 'on' : ''} onClick={() => setView('stats')}><BarChart3 size={13} /> 자동 RT 현황</button>
                <button className={view === 'check' ? 'on' : ''} onClick={() => setView('check')} title="보낼 수 있는데 자동 RT 지정가능수가 0 · 부족한 매장"><Settings2 size={13} /> 자동 RT 설정 점검</button>
                <button className={view === 'perf' ? 'on' : ''} onClick={() => setView('perf')} title="지시한 RT 의 매장 수락 · 거부 · 판매 전환"><BarChart3 size={13} /> RT 성과</button>
              </div>
              {(view === 'rows' || view === 'unfilled') && (
                <div className="search sm">
                  <Search size={14} />
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="품번 · 매장코드 · 매장명" aria-label="결과 검색" />
                  {q && <button className="clear" onClick={() => setQ('')}><X size={13} /></button>}
                </div>
              )}
              {opts.canWrite && (
                <div className="stock-write-bar">
                  {view === 'rows' && (
                    <button className="btn primary sm" disabled={!selRows.length || dirty} onClick={() => setWriting('register')}
                      title={dirty ? '조건을 바꿨습니다 — 다시 계산한 뒤 등록하세요' : '고른 추천을 ERP 본사지시 RT 지시(미확정)로 등록'}>
                      <Send size={14} /> 본사지시 RT 지시{selRows.length ? ` (${fmtNum(selRows.length)}건 · ${fmtNum(selQty)}장)` : ''}
                    </button>
                  )}
                  <button className="btn ghost sm" onClick={() => setWriting('list')}><ClipboardList size={14} /> 등록 내역</button>
                </div>
              )}
            </div>
            {done && <div className="alert info stock-done"><CheckCircle2 size={14} /> <span>{done}</span></div>}
            {aiPick && view === 'rows' && (
              <div className="alert info stock-done stock-ai-pick">
                <Bot size={14} /> <span>AI 가 고른 행: <b>{aiPick.label}</b> · {fmtNum(aiPick.found)}건 · {fmtNum(aiPick.qty)}장
                  {aiPick.found < aiPick.total ? ` (화면에 없는 ${fmtNum(aiPick.total - aiPick.found)}건 — 그사이 추천이 바뀜)` : ''}
                  {opts.canWrite ? ' — 체크해 두었습니다. 확인 후 [본사지시 RT 지시]를 누르세요.' : ''}</span>
                <label className="check-label"><input type="checkbox" checked={onlyPick} onChange={(e) => setOnlyPick(e.target.checked)} /> 고른 것만 보기</label>
                <button className="btn ghost sm" onClick={() => { setAiPick(null); setOnlyPick(false) }}>닫기</button>
              </div>
            )}
            {view === 'rows' && <RtTable rows={rows} select={opts.canWrite ? { sel, flip, setMany } : undefined} />}
            {view === 'unfilled' && <UnfilledTable data={data} rows={unfilled} />}
            {view === 'shops' && <ShopTotals data={data} />}
            {view === 'stats' && applied && <RtStatsPanel brand={applied.brand} from={applied.dateFrom} to={applied.dateTo} data={data} />}
            {view === 'check' && applied && <SettingCheckPanel cond={applied} />}
            {view === 'perf' && <RtPerformancePanel brand={opts.brand} today={opts.today} />}
          </section>
        </>
      )}
      {writing === 'register' && rtSrc && (
        <RtRegisterModal source={rtSrc} keys={selKeys} today={opts.today} onClose={() => setWriting(null)}
          onDone={(m) => { setWriting(null); setDone(m); run(true) }} />
      )}
      {writing === 'list' && (
        <RegisteredModal kind="rt" brand={opts.brand} brandNm={opts.brands.find((b) => b.code === opts.brand)?.name ?? opts.brand} today={opts.today}
          onClose={() => setWriting(null)} onChanged={() => { if (applied) setDone('지시를 삭제했습니다 — [새로 계산]을 누르면 지금 재고로 다시 추천합니다.') }} />
      )}
    </div>
  )
}

type Select = { sel: Set<string>; flip: (k: string) => void; setMany: (keys: string[], on: boolean) => void }

function SelectAll({ keys, select, label }: { keys: string[]; select: Select; label: string }) {
  const on = keys.length > 0 && keys.every((k) => select.sel.has(k))
  return <th className="check"><input type="checkbox" checked={on} disabled={!keys.length} onChange={() => select.setMany(keys, !on)} aria-label={label} title={`화면의 ${keys.length}건 모두`} /></th>
}

function RtTable({ rows, select }: { rows: RtResult['rows']; select?: Select }) {
  const allKeys = useMemo(() => rows.map((r) => rtKey(r).join('|')), [rows])
  const pg = usePaged(rows)
  const keys = useMemo(() => pg.slice.map((r) => rtKey(r).join('|')), [pg.slice])
  return (
    <>
    <div className="table-wrap tall">
      <table className="table stock-table" aria-label="매장 간 RT 추천 목록">
        <thead>
          <tr>
            {select && <SelectAll keys={keys} select={select} label="이 페이지 추천 모두 선택" />}
            <th>품번 · 칼라 · 사이즈</th><th className="num">수량</th>
            <th>보내는 매장</th><th className="num" title="현재고 / 보낼 수 있는 수량">재고</th><th className="num">기간 판매</th><th>최종판매일</th>
            <th aria-label="방향" />
            <th>받는 매장</th><th className="num">재고</th><th className="num">기간 판매</th><th>사유</th>
          </tr>
        </thead>
        <tbody>
          {pg.slice.map((r, i) => (
            <tr key={r.no} className={select?.sel.has(keys[i]) ? 'selected' : ''}>
              {select && <td className="check"><input type="checkbox" checked={select.sel.has(keys[i])} onChange={() => select.flip(keys[i])} aria-label={`${r.prdtCd} ${r.fromShopId}→${r.toShopId} 선택`} /></td>}
              <td><b className="mono">{r.prdtCd}</b> <span className="muted">{r.colorCd} · {r.sizeCd}</span>{r.styleNm && r.styleNm !== r.prdtCd && <div className="muted small">{r.styleNm}</div>}</td>
              <td className="num"><b>{r.qty}</b></td>
              <td><span className="mono">{r.fromShopId}</span> {r.fromShopNm}<div className="muted small">{r.fromTeam}</div></td>
              <td className="num">{r.fromStock}<span className="muted"> / {r.fromSendable}</span></td>
              <td className="num">{r.fromSales}</td>
              <td className="muted">{r.fromLastSale ?? '-'}</td>
              <td className="center muted"><ArrowRight size={14} /></td>
              <td><span className="mono">{r.toShopId}</span> {r.toShopNm}<div className="muted small">{r.toTeam}</div></td>
              <td className={`num ${r.toStock < 0 ? 'danger-text' : ''}`}>{r.toStock}</td>
              <td className="num">{r.toSales}</td>
              <td><span className={`tag ${r.toFailCnt ? 'miss' : r.toStock < 0 ? 'warn' : 'auto'}`}>{r.why}{r.toFailCnt > 1 ? ` ${r.toFailCnt}회` : ''}</span></td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={12} className="empty">추천할 RT 가 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
    <Pager pg={pg}>{select && <SelectAllFiltered keys={allKeys} sel={select.sel} setMany={select.setMany} />}</Pager>
    </>
  )
}

function UnfilledTable({ data, rows }: { data: RtResult; rows: RtResult['unfilled'] }) {
  const pg = usePaged(rows)
  const s = data.summary
  const ex = Object.entries(s.senderExcluded).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  return (
    <>
      <div className="stock-reasons">
        <div>
          <b>못 채운 이유</b>
          {Object.entries(s.unfilledBy).filter(([, v]) => v > 0).map(([k, v]) => <span key={k} className="chip small">{data.reasonNames[k]} {fmtNum(v)}</span>)}
        </div>
        <div title="재고는 있지만 자동 RT 규칙으로 보내는 후보에서 빠진 매장 × 상품 (확인한 후보 기준)">
          <b>보내는 후보에서 빠진 이유</b>
          {ex.map(([k, v]) => <span key={k} className="chip small">{data.ruleNames[k]} {fmtNum(v)}</span>)}
        </div>
        {(s.skipped.noGroup > 0 || s.skipped.recvCtl > 0 || !!s.skipped.incoming || !!s.skipped.virtual) && (
          <div className="muted small">받는 매장에서 뺀 것: RT 그룹 없음 · 정상 매장 아님 {fmtNum(s.skipped.noGroup)}건 · 자동RT 반입 수불제어 {fmtNum(s.skipped.recvCtl)}건{s.skipped.incoming ? ` · 이미 지시 · 요청받아 들어올 예정 ${fmtNum(s.skipped.incoming)}건` : ''}{s.skipped.virtual ? ` · 행사 · 가상 매장 ${fmtNum(s.skipped.virtual)}건` : ''}</div>
        )}
      </div>
      <div className="table-wrap tall">
        <table className="table stock-table" aria-label="못 채운 수요">
          <thead><tr><th>매장</th><th>품번 · 칼라 · 사이즈</th><th className="num">재고</th><th className="num">기간 판매</th><th className="num">자동RT 취소</th><th className="num">못 채운 수량</th><th>이유</th></tr></thead>
          <tbody>
            {pg.slice.map((u, i) => (
              <tr key={`${u.shopId}-${u.prdtCd}-${u.colorCd}-${u.sizeCd}-${i}`}>
                <td><span className="mono">{u.shopId}</span> {u.shopNm}<div className="muted small">{u.team}</div></td>
                <td><b className="mono">{u.prdtCd}</b> <span className="muted">{u.colorCd} · {u.sizeCd}</span></td>
                <td className="num">{u.stock}</td><td className="num">{u.sales}</td><td className="num">{u.failCnt || '-'}</td><td className="num">{u.left}</td>
                <td>{u.reasonNm}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={7} className="empty">못 채운 수요가 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager pg={pg} />
    </>
  )
}

function ShopTotals({ data }: { data: RtResult }) {
  const box = (title: string, list: RtResult['topSenders']) => {
    const max = Math.max(1, ...list.map((x) => x.qty))
    return (
      <div className="stock-bars">
        <b>{title}</b>
        {list.map((x) => (
          <div key={x.shopId} className="stock-bar-row">
            <span className="stock-bar-name"><span className="mono">{x.shopId}</span> {x.shopNm}</span>
            <span className="stock-bar"><i style={{ width: `${(x.qty / max) * 100}%` }} /></span>
            <b className="num">{fmtNum(x.qty)}장</b>
          </div>
        ))}
        {!list.length && <span className="muted">없음</span>}
      </div>
    )
  }
  return <div className="stock-two">{box('많이 보내는 매장 (상위 15)', data.topSenders)}{box('많이 받는 매장 (상위 15)', data.topReceivers)}</div>
}

function RtStatsPanel({ brand, from, to, data }: { brand: string; from: string; to: string; data: RtResult }) {
  const [st, setSt] = useState<RtStats | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setSt(null)
    stockApi.rtStats(brand, from, to).then(setSt).catch((e) => setError(errText(e)))
  }, [brand, from, to])
  if (error) return <div className="alert error">{error}</div>
  if (!st) return <div className="stock-loading"><Loader2 size={16} className="spin" /> 자동 RT 현황을 불러오는 중…</div>
  const max = Math.max(1, ...st.days.map((d) => d.total))
  return (
    <div className="stock-stats">
      <div className="summary-pills">
        <div className="pill strong"><span>자동 RT 요청</span><b>{fmtNum(st.total)}건</b></div>
        {st.results.map((r) => <div key={r.code} className="pill"><span>{r.name}</span><b>{fmtNum(r.count)}</b></div>)}
        <div className="pill warn-pill"><span>'지시가능매장없음' 취소</span><b>{fmtNum(st.noShopCancel)}건 ({st.noShopRate ?? '-'}%)</b></div>
      </div>
      <div className="alert info">
        <AlertTriangle size={14} /> 이번 조건의 추천은 취소된 요청 {fmtNum(data.summary.failRequests)}건 중 {fmtNum(data.summary.failFilled)}건에 보낼 매장을 찾았습니다.
        자동 RT 가 못 찾은 주된 이유는 보내는 매장의 <b>자동 RT 지정가능수(ASIGN_ABLE_QTY)</b>입니다 — 0 인 매장이 많아 재고가 있어도 지정되지 않습니다
        ([자동 RT 하루 한도 적용]을 켜서 비교해 보세요).
      </div>
      <div className="stock-two">
        <div className="stock-bars">
          <b>일별 요청 · 완료 · 취소</b>
          {st.days.map((d) => (
            <div key={d.day} className="stock-bar-row">
              <span className="stock-bar-name">{d.day}</span>
              <span className="stock-bar stack3" title={`요청 ${d.total} · 완료 ${d.done} · 지시가능매장없음 ${d.fail}`}>
                <i className="done" style={{ width: `${(d.done / max) * 100}%` }} />
                <i className="fail" style={{ width: `${(d.fail / max) * 100}%` }} />
                <i className="etc" style={{ width: `${((d.total - d.done - d.fail) / max) * 100}%` }} />
              </span>
              <b className="num">{fmtNum(d.total)}</b>
            </div>
          ))}
          <div className="stock-legend"><i className="done" /> 완료 <i className="fail" /> 지시가능매장없음 <i className="etc" /> 그 외</div>
        </div>
        <div className="stock-bars">
          <b>취소가 많은 매장</b>
          {st.failShops.map((x) => <div key={x.shopId} className="stock-bar-row"><span className="stock-bar-name"><span className="mono">{x.shopId}</span> {x.shopNm}</span><b className="num">{fmtNum(x.count)}건</b></div>)}
          <b className="stock-gap">취소가 많은 품번</b>
          {st.failProducts.map((x) => <div key={x.prdtCd} className="stock-bar-row"><span className="stock-bar-name"><span className="mono">{x.prdtCd}</span> {x.styleNm !== x.prdtCd ? x.styleNm : ''}</span><b className="num">{fmtNum(x.count)}건</b></div>)}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 창고 → 매장 배분
function fromRun(opts: StockOptions, r: RecentRun | undefined, today: string): AllocCond {
  const yday = addDaysIso(today, -1)
  return {
    brand: opts.brand, wh: r?.wh ?? opts.warehouses[0]?.code ?? 'IN', dateFrom: yday, dateTo: yday,
    base: r?.base ?? opts.bases[0]?.id ?? '', grdGrp: r?.grdGrp ?? opts.gradeGroups.find((g) => g.base)?.id ?? '',
    planYy: r?.planYy ?? opts.defaultPlanYy, seasons: r?.seasons ?? opts.defaultSeasons, prdtGrps: r?.prdtGrps ?? [], items: r?.items ?? [],
    prdt: r?.prdt ?? '', teams: r?.teams ?? [], rate: r?.rate ?? 1,
  }
}

function AllocTab({ opts, request, onContext, onReturn }: {
  opts: StockOptions; request: StockOpenRequest | null; onContext: (c: Record<string, string>) => void; onReturn: (cond: AllocCond) => void
}) {
  const today = iso(opts.today)
  const [runSeq, setRunSeq] = useState(opts.recentRuns[0]?.seq ?? '')
  const [cond, setCond] = useState<AllocCond>(() => fromRun(opts, opts.recentRuns[0], today))
  const [applied, setApplied] = useState<AllocCond | null>(null)
  const [data, setData] = useState<AllocResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'rows' | 'short' | 'skus' | 'shops'>('rows')
  const [q, setQ] = useState('')
  const [onlyShort, setOnlyShort] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [cand, setCand] = useState<AllocSku | null>(null)
  const [writing, setWriting] = useState<'register' | 'list' | null>(null)
  const [shortRt, setShortRt] = useState(false)
  const [done, setDone] = useState('')
  const { sel, flip, setMany, clear } = useSelection()
  const abort = useRef<AbortController | null>(null)
  const sec = useElapsed(loading)
  const run0 = opts.recentRuns.find((r) => r.seq === runSeq)
  const days = spanDays(cond.dateFrom, cond.dateTo)
  const bad = !cond.dateFrom || !cond.dateTo || days < 1 ? '기간을 고르세요.' : days > opts.maxDays ? `기간은 최대 ${opts.maxDays}일입니다.`
    : !cond.base ? '판매보충기준을 고르세요.' : ''

  const pickRun = (seq: string) => {
    setRunSeq(seq)
    const r = opts.recentRuns.find((x) => x.seq === seq)
    if (r) setCond({ ...fromRun(opts, r, today), dateFrom: cond.dateFrom, dateTo: cond.dateTo })
  }
  const run = (refresh = false, override?: AllocCond) => {
    if (bad && !override) return
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    setLoading(true)
    setError('')
    const c = { ...(override ?? cond) }
    stockApi.alloc(c, refresh, ac.signal).then((d) => {
      setData(d)
      setApplied(c)
      clear()
      onContext({ brand: d.brandNm, period: `${d.from}~${d.to}`, prdt: c.prdt })
    }).catch((e) => { if (!ac.signal.aborted) setError(errText(e)) }).finally(() => { if (abort.current === ac) setLoading(false) })
  }
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {                   // AI 대화에서 정한 조건으로 열고 계산 (최근 자동보충 실행 조건에서 시작)
    if (!request) return
    consumeStockOpen(request.nonce)
    const r = opts.recentRuns[0]
    setRunSeq(r?.seq ?? '')
    const c = { ...fromRun(opts, r, today), ...request.cond } as AllocCond
    setCond(c)
    if (request.view) setView(request.view as typeof view)
    if (request.run !== false) run(false, c)
  }, [request?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = applied !== null && JSON.stringify(applied) !== JSON.stringify(cond)
  const match = (vals: (string | null)[]) => {
    const k = q.trim().toUpperCase()
    return !k || vals.some((v) => v?.toUpperCase().includes(k))
  }
  const rows = useMemo(() => (data?.rows ?? []).filter((r) => match([r.prdtCd, r.shopId, r.shopNm, r.styleNm])), [data, q]) // eslint-disable-line react-hooks/exhaustive-deps
  const shortRows = useMemo(() => (data?.shortRows ?? []).filter((r) => match([r.prdtCd, r.shopId, r.shopNm, r.styleNm])), [data, q]) // eslint-disable-line react-hooks/exhaustive-deps
  const selRows = useMemo(() => (data?.rows ?? []).filter((r) => sel.has(alKey(r).join('|'))), [data, sel])
  const selQty = selRows.reduce((a, r) => a + r.ask, 0)
  const selKeys = useMemo(() => selRows.map(alKey), [selRows])
  const skus = useMemo(() => (data?.skus ?? []).filter((r) => (!onlyShort || r.short > 0) && match([r.prdtCd, r.styleNm])), [data, q, onlyShort]) // eslint-disable-line react-hooks/exhaustive-deps
  const s = data?.summary
  const baseNm = (id: string) => opts.bases.find((b) => b.id === id)?.rmk ?? ''

  const exportXlsx = async () => {
    if (!applied) return
    setExporting(true)
    try { await stockApi.allocExport(applied) } catch (e) { setError(errText(e)) } finally { setExporting(false) }
  }

  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><Warehouse size={17} /> 창고 → 매장 배분 추천 <span className="muted small">(판매분 자동보충 규칙)</span></div>
          <div className="date-range" title="판매 기간 (최대 31일)">
            <span className="date-range-label">판매 기간</span>
            <input type="date" value={cond.dateFrom} max={cond.dateTo || today} onChange={(e) => setCond({ ...cond, dateFrom: e.target.value })} aria-label="배분 판매 기간 시작" />
            <span className="muted">~</span>
            <input type="date" value={cond.dateTo} min={cond.dateFrom} max={today} onChange={(e) => setCond({ ...cond, dateTo: e.target.value })} aria-label="배분 판매 기간 끝" />
          </div>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => run(false)} disabled={loading || !!bad} title={bad || undefined}>
              {loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 배분 계산{dirty ? ' *' : ''}
            </button>
            <button className="btn ghost" onClick={() => run(true)} disabled={loading || !applied || !!bad} title="캐시를 무시하고 지금 재고로 다시 계산"><RefreshCw size={15} /> 새로 계산</button>
            <button className="btn success" onClick={exportXlsx} disabled={!data || exporting || dirty}>
              {exporting ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀
            </button>
          </div>
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">최근 실행</span>
          <select className="input sm stock-run" value={runSeq} onChange={(e) => pickRun(e.target.value)} aria-label="최근 판매분 자동보충 실행 조건">
            {opts.recentRuns.map((r) => (
              <option key={r.seq} value={r.seq}>
                {r.seq} · {r.at} · {r.from === r.to ? r.from : `${r.from}~${r.to}`} · {baseNm(r.base) || r.base} · {r.seasons.map((x) => opts.seasons.find((s) => s.code === x)?.name ?? x).join(',')}
              </option>
            ))}
            {!opts.recentRuns.length && <option value="">최근 실행 기록 없음</option>}
          </select>
          {run0?.ignored.length ? <span className="muted small"><Info size={12} /> 이 화면에서 쓰지 않는 조건: {run0.ignored.join(', ')}</span> : null}
        </div>
        <div className="sale-filter-row">
          <label className="field-label">창고
            <select className="input sm" value={cond.wh} onChange={(e) => setCond({ ...cond, wh: e.target.value })} aria-label="창고">
              {opts.warehouses.map((w) => <option key={w.code} value={w.code}>{w.name}</option>)}
              {!opts.warehouses.some((w) => w.code === cond.wh) && <option value={cond.wh}>{cond.wh}</option>}
            </select>
          </label>
          <label className="field-label">판매보충기준
            <select className="input sm stock-base" value={cond.base} onChange={(e) => setCond({ ...cond, base: e.target.value })} aria-label="판매보충기준">
              {opts.bases.map((b) => <option key={b.id} value={b.id}>{b.id} · {b.rmk ?? ''} ({b.aplyDt})</option>)}
            </select>
          </label>
          <label className="field-label">등급 그룹
            <select className="input sm" value={cond.grdGrp} onChange={(e) => setCond({ ...cond, grdGrp: e.target.value })} aria-label="등급 그룹">
              {opts.gradeGroups.map((g) => <option key={g.id} value={g.id}>{g.name}{g.base ? ' (기본)' : ''}</option>)}
            </select>
          </label>
          <label className="field-label">배수
            <input className="input sm stock-rate" type="number" min={0.1} max={10} step={0.1} value={cond.rate} onChange={(e) => setCond({ ...cond, rate: Number(e.target.value) })} aria-label="배수" />
          </label>
          <span className="filter-label">품번</span>
          <input className="input sm stock-prdt" value={cond.prdt} placeholder="앞부분만 입력 가능" onChange={(e) => setCond({ ...cond, prdt: e.target.value.toUpperCase() })} aria-label="배분 품번" />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">기획년도</span>
          <Chips items={opts.planYears.map((y) => ({ code: y, name: y }))} value={cond.planYy} onChange={(planYy) => setCond({ ...cond, planYy })} />
          <span className="filter-label">시즌</span>
          <Chips items={opts.seasons} value={cond.seasons} onChange={(seasons) => setCond({ ...cond, seasons })} />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">팀</span>
          <Chips items={opts.teams} value={cond.teams} onChange={(teams) => setCond({ ...cond, teams })} empty="비우면 전체" />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">품군</span>
          <Chips items={opts.prdtGrps} value={cond.prdtGrps} onChange={(prdtGrps) => setCond({ ...cond, prdtGrps })} empty="비우면 전체" />
        </div>
      </section>

      {bad && <div className="alert warn">{bad}</div>}
      {error && <div className="alert error">{error}</div>}
      {loading && <Computing sec={sec} what="창고 → 매장 배분" />}
      {!data && !loading && (
        <section className="card stock-empty">
          <Warehouse size={26} />
          <div>
            <b>판매분 자동보충을 돌리기 전에, 어느 매장에 몇 장이 가는지 미리 봅니다.</b>
            <div className="muted small">최근 실행 조건을 불러왔습니다. 오늘 이미 실행했다면 그 미확정 의뢰가 창고 가용에서 빠져 '추가로 더 보낼 수 있는 양'이 계산됩니다.</div>
          </div>
        </section>
      )}

      {data && s && (
        <>
          <section className="summary-pills">
            <div className="pill strong"><span>배분</span><b>{fmtNum(s.allocQty)}장</b><span className="muted">완불 {fmtNum(s.allocFp)}</span></div>
            <div className="pill"><span>상품</span><b>{fmtNum(s.allocSkus)} / {fmtNum(s.skus)}</b></div>
            <div className="pill"><span>받는 매장</span><b>{fmtNum(s.shops)}곳</b></div>
            <div className="pill"><span>필요 수량</span><b>{fmtNum(s.demand)}장</b></div>
            <div className={`pill ${s.short ? 'warn-pill' : ''}`}><span>창고 부족</span><b>{fmtNum(s.short)}장</b><span className="muted">재고 없는 상품 {fmtNum(s.noStockSkus)}</span></div>
            {s.ctlRows > 0 && <div className="pill"><span>수불제어로 건너뜀</span><b>{fmtNum(s.ctlRows)}</b></div>}
            <div className="pill hint-pill">{data.brandNm} · {data.wh} · {data.from === data.to ? data.from : `${data.from} ~ ${data.to}`} · 기준 {data.base} · {data.asOf} 기준 · {data.timing.total}초</div>
            {dirty && <div className="pill hint-pill warn-pill">조건을 바꿨습니다 · [배분 계산]을 누르면 적용됩니다</div>}
          </section>
          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="배분 결과 보기">
                <button className={view === 'rows' ? 'on' : ''} onClick={() => setView('rows')}>매장별 배분 ({fmtNum(data.rowsTotal)})</button>
                <button className={view === 'short' ? 'on' : ''} onClick={() => setView('short')} title="창고 수량이 모자라 필요만큼 못 받은 매장 (일부만 · 전혀 못 받음)">
                  <AlertTriangle size={13} /> 창고 부족 ({fmtNum(data.shortRowsTotal)})
                </button>
                <button className={view === 'skus' ? 'on' : ''} onClick={() => setView('skus')}>상품별 ({fmtNum(data.skusTotal)})</button>
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>많이 받는 매장</button>
              </div>
              {view !== 'shops' && (
                <div className="search sm">
                  <Search size={14} />
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={view === 'skus' ? '품번' : '품번 · 매장'} aria-label="배분 결과 검색" />
                  {q && <button className="clear" onClick={() => setQ('')}><X size={13} /></button>}
                </div>
              )}
              {view === 'skus' && <label className="check-label"><input type="checkbox" checked={onlyShort} onChange={(e) => setOnlyShort(e.target.checked)} /> 부족한 상품만</label>}
              {view === 'skus' && <span className="muted small">상품을 누르면 후보 매장 순서</span>}
              {view === 'rows' && s.shortRows > 0 && <span className="muted small"><span className="stock-short-swatch" /> 노란 행 = 창고 부족으로 필요보다 적게 받음</span>}
              {opts.canWrite && (
                <div className="stock-write-bar">
                  {view === 'rows' && (
                    <button className="btn primary sm" disabled={!selRows.length || dirty} onClick={() => setWriting('register')}
                      title={dirty ? '조건을 바꿨습니다 — 다시 계산한 뒤 등록하세요' : '고른 배분을 ERP 출고의뢰(미확정)로 등록'}>
                      <Send size={14} /> 배분의뢰 등록{selRows.length ? ` (${fmtNum(selRows.length)}건 · ${fmtNum(selQty)}장)` : ''}
                    </button>
                  )}
                  <button className="btn ghost sm" onClick={() => setWriting('list')}><ClipboardList size={14} /> 등록 내역</button>
                </div>
              )}
            </div>
            {done && <div className="alert info stock-done"><CheckCircle2 size={14} /> <span>{done}</span></div>}
            {view === 'rows' && <AllocTable rows={rows} select={opts.canWrite ? { sel, flip, setMany } : undefined} />}
            {view === 'short' && (
              <>
                <div className="alert warn stock-short-note">
                  <AlertTriangle size={14} /> <span>창고 가용(창고 재고 − 출고지시 · 미확정 의뢰 − 창고하한)이 모자라 필요 수량만큼 못 받은 매장입니다 —
                  일부만 받음 {fmtNum(s.shortRows - s.shortZero)}건 · 전혀 못 받음 {fmtNum(s.shortZero)}건 · 부족 합계 {fmtNum(s.short)}장.</span>
                  {s.shortRows > 0 && (
                    <button className="btn primary sm" disabled={dirty} onClick={() => setShortRt(true)} title={dirty ? '조건을 바꿨습니다 — 다시 계산하세요' : '같은 RT 그룹의 다른 매장 재고로 채우는 매장 간 RT 추천'}>
                      <ArrowRightLeft size={14} /> 매장 간 RT 로 채우기
                    </button>
                  )}
                  {s.shortRows > 0 && applied && (
                    <button className="btn ghost sm" disabled={dirty} onClick={() => onReturn(applied)} title="창고 부족 상품을 판매 없는 매장 재고에서 창고로 회수 (추천)">
                      <Undo2 size={14} /> 창고로 회수 추천
                    </button>
                  )}
                </div>
                <AllocTable rows={shortRows} showShort />
              </>
            )}
            {view === 'skus' && <SkuTable skus={skus} onPick={setCand} />}
            {view === 'shops' && (
              <div className="stock-two"><div className="stock-bars"><b>많이 받는 매장 (상위 15)</b>
                {data.topShops.map((x) => {
                  const max = Math.max(1, ...data.topShops.map((y) => y.qty))
                  return <div key={x.shopId} className="stock-bar-row"><span className="stock-bar-name"><span className="mono">{x.shopId}</span> {x.shopNm}</span><span className="stock-bar"><i style={{ width: `${(x.qty / max) * 100}%` }} /></span><b className="num">{fmtNum(x.qty)}장</b></div>
                })}
              </div></div>
            )}
          </section>
        </>
      )}
      {cand && applied && <CandidatesModal cond={applied} sku={cand} onClose={() => setCand(null)} />}
      {shortRt && applied && <ShortRtModal cond={applied} canWrite={opts.canWrite} today={opts.today} onClose={() => setShortRt(false)} />}
      {writing === 'register' && applied && (
        <AllocRegisterModal cond={applied} keys={selKeys} today={opts.today} onClose={() => setWriting(null)}
          onDone={(m) => { setWriting(null); setDone(m); run(true) }} />
      )}
      {writing === 'list' && (
        <RegisteredModal kind="alloc" brand={opts.brand} brandNm={opts.brands.find((b) => b.code === opts.brand)?.name ?? opts.brand} today={opts.today}
          onClose={() => setWriting(null)} onChanged={() => { if (applied) setDone('의뢰를 삭제했습니다 — [새로 계산]을 누르면 지금 창고 재고로 다시 배분합니다.') }} />
      )}
    </div>
  )
}

function AllocTable({ rows, select, showShort }: { rows: AllocRow[]; select?: Select; showShort?: boolean }) {
  const pg = usePaged(rows)
  const keys = useMemo(() => pg.slice.map((r) => alKey(r).join('|')), [pg.slice])
  const allKeys = useMemo(() => rows.filter((r) => r.ask).map((r) => alKey(r).join('|')), [rows])
  return (
    <>
    <div className="table-wrap tall">
      <table className="table stock-table" aria-label="매장별 배분">
        <thead>
          <tr>
            {select && <SelectAll keys={keys} select={select} label="이 페이지 배분 모두 선택" />}
            <th>품번 · 칼라 · 사이즈</th><th className="num">순위</th><th>매장</th><th>유통 · 등급</th><th className="num">판매율</th><th className="num">완불 · 판매</th><th className="num">현재고</th>
            <th className="num">배분(완불)</th><th className="num">배분(판매)</th><th className="num">합계</th>
            <th className="num" title="매장재고상한까지 받을 수 있는 완불 + 판매 수량">필요</th><th className="num" title="창고 수량이 모자라 못 받은 수량">창고 부족</th>
          </tr>
        </thead>
        <tbody>
          {pg.slice.map((r, i) => (
            <tr key={`${r.prdtCd}-${r.colorCd}-${r.sizeCd}-${r.shopId}`}
              className={`${r.short > 0 ? 'row-short' : ''} ${select?.sel.has(keys[i]) ? 'selected' : ''}`}>
              {select && <td className="check"><input type="checkbox" checked={select.sel.has(keys[i])} disabled={!r.ask} onChange={() => select.flip(keys[i])} aria-label={`${r.shopId} ${r.prdtCd} 선택`} /></td>}
              <td><b className="mono">{r.prdtCd}</b> <span className="muted">{r.colorCd} · {r.sizeCd}</span></td>
              <td className="num">{r.rank}</td>
              <td><span className="mono">{r.shopId}</span> {r.shopNm}<div className="muted small">{r.team}</div></td>
              <td>{r.shopType} <span className="muted">{r.grade}{r.gradeRank != null ? ` · ${r.gradeRank}` : ''}</span></td>
              <td className="num">{r.srate}%</td><td className="num">{r.fq} · {r.sq}</td><td className="num">{r.stock}</td>
              <td className="num">{r.askFp || '-'}</td><td className="num">{r.askSale || '-'}</td><td className="num"><b>{r.ask}</b></td>
              <td className="num">{r.ctl ? '-' : r.need}</td>
              <td className="num">{r.short > 0 ? <span className="tag warn">{r.ask ? '' : '미배분 '}부족 {r.short}</span> : '-'}</td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={13} className="empty">{showShort ? '창고 부족으로 못 받은 매장이 없습니다.' : '배분할 매장이 없습니다.'}</td></tr>}
        </tbody>
      </table>
    </div>
    <Pager pg={pg}>{select && <SelectAllFiltered keys={allKeys} sel={select.sel} setMany={select.setMany} />}</Pager>
    </>
  )
}

function SkuTable({ skus, onPick }: { skus: AllocSku[]; onPick: (k: AllocSku) => void }) {
  const pg = usePaged(skus)
  return (
    <>
      <div className="table-wrap tall">
        <table className="table stock-table" aria-label="상품별 배분">
          <thead><tr><th>품번 · 칼라 · 사이즈</th><th className="num">창고 재고</th><th className="num" title="오늘 이후 출고지시 미명세 + 미확정 배분의뢰">지시 · 의뢰</th><th className="num">창고하한</th><th className="num">배분 가능</th><th className="num">후보 매장</th><th className="num">필요</th><th className="num">배분</th><th className="num">부족</th><th className="num">매장상한</th></tr></thead>
          <tbody>
            {pg.slice.map((k) => (
              <tr key={`${k.prdtCd}-${k.colorCd}-${k.sizeCd}`} className="clickable" onClick={() => onPick(k)}>
                <td><b className="mono">{k.prdtCd}</b> <span className="muted">{k.colorCd} · {k.sizeCd}</span></td>
                <td className="num">{fmtNum(k.whStock)}</td><td className="num">{fmtNum(k.reserved)}</td><td className="num">{k.minWh}</td>
                <td className="num"><b>{fmtNum(k.avail)}</b></td><td className="num">{k.shops}</td><td className="num">{k.demand}</td>
                <td className="num"><b>{k.alloc}</b></td><td className={`num ${k.short ? 'danger-text' : ''}`}>{k.short || '-'}</td><td className="num">{k.maxStock === 9999 ? '없음' : k.maxStock}</td>
              </tr>
            ))}
            {!skus.length && <tr><td colSpan={10} className="empty">상품이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager pg={pg} />
    </>
  )
}

function CandidatesModal({ cond, sku, onClose }: { cond: AllocCond; sku: AllocSku; onClose: () => void }) {
  const [rows, setRows] = useState<AllocRow[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    stockApi.allocCandidates(cond, sku).then((d) => setRows(d.rows)).catch((e) => setError(errText(e)))
  }, [cond, sku])
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal stock-cand-modal" role="dialog" aria-label="후보 매장 순서">
        <div className="modal-head">
          <h3><ListOrdered size={17} /> {sku.prdtCd} {sku.colorCd} · {sku.sizeCd} 후보 매장 순서</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        <div className="muted small">창고 배분 가능 {fmtNum(sku.avail)}장 (창고 {fmtNum(sku.whStock)} − 지시 · 의뢰 {fmtNum(sku.reserved)} − 하한 {sku.minWh}) · 매장재고상한 {sku.maxStock === 9999 ? '없음' : sku.maxStock} · 순서 = 유통형태 · 판매율 · 등급 · 등급 내 순위 · 최초판매일</div>
        {error && <div className="alert error">{error}</div>}
        {!rows && !error && <div className="stock-loading"><Loader2 size={16} className="spin" /> 불러오는 중…</div>}
        {rows && <AllocTable rows={rows.map((r) => ({ ...r, shopNm: r.ctl ? `${r.shopNm ?? ''} (수불제어 · 건너뜀)` : r.shopNm }))} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 자동 RT 설정 점검 (지정가능수)
function SettingCheckPanel({ cond }: { cond: RtCond }) {
  const [d, setD] = useState<SettingCheck | null>(null)
  const [error, setError] = useState('')
  const [all, setAll] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setD(null)
    setError('')
    stockApi.settingCheck(cond).then(setD).catch((e) => setError(errText(e)))
  }, [cond])
  if (error) return <div className="alert error">{error}</div>
  if (!d) return <div className="stock-loading"><Loader2 size={16} className="spin" /> 보낼 수 있는 매장의 지정가능수를 점검하는 중… (하루 한도 없이 계산한 추천 기준)</div>
  const s = d.summary
  const rows = all ? d.rows : d.rows.filter((r) => r.status !== '적정')
  const exportXlsx = async () => {
    setBusy(true)
    try { await stockApi.settingExport(cond) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  return (
    <div className="stock-stats">
      <div className="summary-pills">
        <div className="pill strong"><span>보낼 수 있는 매장</span><b>{fmtNum(s.senders)}곳</b><span className="muted">추천 {fmtNum(s.recQty)}장</span></div>
        <div className="pill warn-pill"><span>지정가능수 0</span><b>{fmtNum(s.blockedShops)}곳</b><span className="muted">{fmtNum(s.blockedQty)}장 · {pct(s.blockedQty, s.recQty)}</span></div>
        <div className="pill"><span>지정가능수 부족</span><b>{fmtNum(s.lowShops)}곳</b></div>
        <div className="pill" title="기간 중 '지시가능매장없음'으로 취소된 요청 중 이 매장들이 채울 수 있었던 수량"><span>취소 요청 채울 수 있던 수량</span>
          <b>0 매장 {fmtNum(s.blockedFailQty)} · 부족 매장 {fmtNum(s.lowFailQty)}</b></div>
        <div className="pill hint-pill">{d.brandNm} · {d.from} ~ {d.to} ({d.days}일) · {d.asOf} 기준</div>
      </div>
      <div className="alert info">
        <Info size={14} /> <span>자동 RT 는 보내는 매장의 <b>하루 지정가능수(ASIGN_ABLE_QTY)</b>가 남아 있어야 지정합니다. 0 인 매장은 재고가 있어도 보내는 매장이 될 수 없어
        '지시가능매장없음'으로 취소됩니다. 권장 지정가능수 = 올림((기간 실제 지정 수 + 취소 요청 채움 수량) ÷ 기간 일수). 설정 변경은 ERP 매장 RT 그룹 설정에서 합니다.</span>
      </div>
      <div className="stock-subbar flat">
        <label className="check-label"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> 적정 매장도 보기</label>
        <span className="muted small">{fmtNum(rows.length)}곳</span>
        <button className="btn success sm stock-write-bar" onClick={exportXlsx} disabled={busy}>{busy ? <Loader2 size={14} className="spin" /> : <Download size={14} />} 엑셀</button>
      </div>
      <div className="table-wrap tall">
        <table className="table stock-table" aria-label="자동 RT 설정 점검">
          <thead>
            <tr><th>매장</th><th>RT 그룹</th><th className="num">지정가능수</th><th className="num">권장</th><th className="num" title="기간 중 실제 자동 RT 지정 수 (하루 평균)">실제 지정</th>
              <th className="num">추천 보낼 수량</th><th className="num" title="'지시가능매장없음' 취소 요청을 채울 수 있던 수량">취소 채움</th><th className="num">받는 매장</th><th>판단</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.shopId} className={r.blocked ? 'row-short' : ''}>
                <td><span className="mono">{r.shopId}</span> {r.shopNm}<div className="muted small">{r.team}</div></td>
                <td className="mono muted">{r.rtGrp}</td>
                <td className={`num ${r.blocked ? 'danger-text' : ''}`}><b>{r.asign}</b></td>
                <td className="num"><b>{r.suggest}</b></td>
                <td className="num">{fmtNum(r.assigned)} <span className="muted">({r.assignedPerDay}/일)</span></td>
                <td className="num">{fmtNum(r.recQty)}</td><td className="num">{fmtNum(r.failQty)}</td><td className="num">{r.receivers}</td>
                <td><span className={`tag ${r.blocked ? 'warn' : r.status === '적정' ? 'auto' : 'miss'}`}>{r.status}</span></td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={9} className="empty">점검할 매장이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 창고 부족 → 매장 간 RT 로 채우기
function ShortRtModal({ cond, canWrite, today, onClose }: { cond: AllocCond; canWrite: boolean; today: string; onClose: () => void }) {
  const [d, setD] = useState<ShortRt | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reg, setReg] = useState(false)
  const [done, setDone] = useState('')
  const [tab, setTab] = useState<'rows' | 'unfilled'>('rows')
  const { sel, flip, setMany, clear } = useSelection()
  const sec = useElapsed(loading)
  const load = (refresh = false) => {
    setLoading(true)
    setError('')
    stockApi.shortRt(cond, refresh).then((x) => { setD(x); clear() }).catch((e) => setError(errText(e))).finally(() => setLoading(false))
  }
  useEffect(() => load(), [cond]) // eslint-disable-line react-hooks/exhaustive-deps
  const src = useMemo(() => stockApi.shortRtSource(cond), [cond])
  const selRows = useMemo(() => (d?.rows ?? []).filter((r) => sel.has(rtKey(r).join('|'))), [d, sel])
  const selKeys = useMemo(() => selRows.map(rtKey), [selRows])
  const s = d?.summary
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal stock-write-modal wide" role="dialog" aria-label="창고 부족을 매장 간 RT 로 채우기">
        <div className="modal-head">
          <h3><ArrowRightLeft size={17} /> 창고 부족 → 매장 간 RT 로 채우기</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        <div className="muted small">창고 수량이 모자라 못 받은 매장(창고 부족 행)에 같은 RT 그룹 매장의 재고를 자동 RT 규칙 · 자동 RT 순서로 짝지었습니다. 받는 수량 = 창고 부족 − 이미 들어올 지시 · 요청.</div>
        {loading && <div className="stock-loading"><Loader2 size={16} className="spin" /> 보낼 매장을 찾는 중… {sec}초</div>}
        {error && <div className="alert error">{error}</div>}
        {d && s && !loading && (
          <>
            <div className="summary-pills">
              <div className="pill"><span>창고 부족</span><b>{fmtNum(s.shortRows)}건 · {fmtNum(s.shortQty)}장</b></div>
              <div className="pill strong"><span>RT 로 채움</span><b>{fmtNum(s.recRows)}건 · {fmtNum(s.recQty)}장</b><span className="muted">{pct(s.filledReceivers, s.receivers)}</span></div>
              <div className="pill"><span>보내는 매장</span><b>{fmtNum(s.senders)}곳</b></div>
              <div className="pill"><span>못 채움</span><b>{fmtNum(s.unfilled)}건</b></div>
              {s.skipped.incoming > 0 && <div className="pill"><span>이미 지시 · 요청 들어옴</span><b>{fmtNum(s.skipped.incoming)}건</b></div>}
              <div className="pill hint-pill">{d.brandNm} · 배분 {d.allocAsOf} · RT {d.asOf} 기준 · {d.timing.total}초</div>
            </div>
            {done && <div className="alert info"><CheckCircle2 size={14} /> <span>{done}</span></div>}
            <div className="stock-subbar flat">
              <div className="seg" role="tablist" aria-label="채우기 결과 보기">
                <button className={tab === 'rows' ? 'on' : ''} onClick={() => setTab('rows')}>RT 추천 ({fmtNum(s.recRows)})</button>
                <button className={tab === 'unfilled' ? 'on' : ''} onClick={() => setTab('unfilled')}>못 채움 ({fmtNum(s.unfilled)})</button>
              </div>
              <button className="btn ghost sm" onClick={() => load(true)}><RefreshCw size={14} /> 새로 계산</button>
              {canWrite && tab === 'rows' && (
                <div className="stock-write-bar">
                  <button className="btn primary sm" disabled={!selRows.length} onClick={() => setReg(true)}>
                    <Send size={14} /> 본사지시 RT 지시{selRows.length ? ` (${fmtNum(selRows.length)}건 · ${fmtNum(selRows.reduce((a, r) => a + r.qty, 0))}장)` : ''}
                  </button>
                </div>
              )}
            </div>
            {tab === 'rows' && <RtTable rows={d.rows} select={canWrite ? { sel, flip, setMany } : undefined} />}
            {tab === 'unfilled' && <UnfilledTable data={{ ...d, summary: { ...d.summary, skipped: { ...d.summary.skipped } } } as unknown as RtResult} rows={d.unfilled} />}
          </>
        )}
        {reg && (
          <RtRegisterModal source={src} keys={selKeys} today={today} onClose={() => setReg(false)}
            onDone={(m) => { setReg(false); setDone(m); load(true) }} />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- RT 성과 (본사지시 RT 처리 · 판매 전환)
function RtPerformancePanel({ brand, today }: { brand: string; today: string }) {
  const t = iso(today)
  const [from, setFrom] = useState(addDaysIso(t, -13))
  const [to, setTo] = useState(t)
  const [scope, setScope] = useState<'web' | 'all'>('web')
  const [virt, setVirt] = useState(false)
  const [d, setD] = useState<RtPerformance | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<'senders' | 'receivers' | 'reasons' | 'days'>('senders')
  const [busy, setBusy] = useState(false)
  const load = (refresh = false) => {
    setLoading(true)
    setError('')
    stockApi.rtPerformance(brand, from, to, scope, refresh, virt).then(setD).catch((e) => setError(errText(e))).finally(() => setLoading(false))
  }
  useEffect(() => load(), [brand, from, to, scope, virt]) // eslint-disable-line react-hooks/exhaustive-deps
  const s = d?.summary
  const exportXlsx = async () => {
    setBusy(true)
    try { await stockApi.rtPerformanceExport(brand, from, to, scope, virt) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  const shopTable = (list: RtPerformance['senders'], label: string) => (
    <div className="table-wrap tall">
      <table className="table stock-table" aria-label={label}>
        <thead><tr><th>매장</th><th className="num">지시</th><th className="num">수락</th><th className="num">거부</th><th className="num">자동거부</th><th className="num">미처리</th>
          <th className="num">취소</th><th className="num">수락률</th><th className="num" title="확정 → 매장 수락 · 거부까지">평균 처리</th><th className="num" title={`수락 후 ${d?.soldDays ?? 7}일 안에 받은 매장에서 판매`}>판매 전환</th></tr></thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.shopId} className={r.acceptRate != null && r.acceptRate < 50 ? 'row-short' : ''}>
              <td><span className="mono">{r.shopId}</span> {r.shopNm}<div className="muted small">{r.team}</div></td>
              <td className="num"><b>{fmtNum(r.total)}</b></td><td className="num">{fmtNum(r.accepted)}</td><td className="num">{fmtNum(r.denied)}</td>
              <td className="num">{fmtNum(r.autoDenied)}</td><td className="num">{fmtNum(r.pending)}</td><td className="num">{fmtNum(r.canceled)}</td>
              <td className="num">{r.acceptRate != null ? `${r.acceptRate}%` : '-'}</td><td className="num">{r.avgHours != null ? `${r.avgHours}시간` : '-'}</td>
              <td className="num">{r.soldRate != null ? `${r.soldRate}% (${fmtNum(r.sold)})` : '-'}</td>
            </tr>
          ))}
          {!list.length && <tr><td colSpan={10} className="empty">이 기간에 지시한 RT 가 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  )
  return (
    <div className="stock-stats stock-perf">
      <div className="stock-write-fields">
        <div className="date-range">
          <span className="date-range-label">지시일</span>
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} aria-label="RT 성과 시작" />
          <span className="muted">~</span>
          <input type="date" value={to} min={from} max={t} onChange={(e) => setTo(e.target.value)} aria-label="RT 성과 끝" />
        </div>
        <div className="seg" role="group" aria-label="RT 성과 범위">
          <button className={scope === 'web' ? 'on' : ''} onClick={() => setScope('web')}>이 화면에서 지시</button>
          <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>본사지시 전체</button>
        </div>
        <label className="check-label" title="오픈매장 · 사내 · 온라인 · 행사 매장이 낀 지시까지"><input type="checkbox" checked={virt} onChange={(e) => setVirt(e.target.checked)} /> 행사 · 가상 매장 포함</label>
        <button className="btn ghost sm" onClick={() => load(true)} disabled={loading}><RefreshCw size={14} /> 새로 계산</button>
        <button className="btn success sm stock-write-bar" onClick={exportXlsx} disabled={busy || !d}>{busy ? <Loader2 size={14} className="spin" /> : <Download size={14} />} 엑셀</button>
      </div>
      {error && <div className="alert error">{error}</div>}
      {loading && <div className="stock-loading"><Loader2 size={16} className="spin" /> RT 성과를 계산하는 중…</div>}
      {d && s && !loading && (
        <>
          <div className="summary-pills">
            <div className="pill strong"><span>지시</span><b>{fmtNum(s.total)}장</b></div>
            <div className="pill"><span>수락률</span><b>{s.acceptRate != null ? `${s.acceptRate}%` : '-'}</b><span className="muted">수락 {fmtNum(s.accepted)} · 거부 {fmtNum(s.denied)} · 자동거부 {fmtNum(s.autoDenied)}</span></div>
            <div className={`pill ${s.pending ? 'warn-pill' : ''}`}><span>매장 미처리</span><b>{fmtNum(s.pending)}장</b></div>
            {s.canceled > 0 && <div className="pill"><span>지시 취소</span><b>{fmtNum(s.canceled)}장</b></div>}
            <div className="pill"><span>평균 처리</span><b>{s.avgHours != null ? `${s.avgHours}시간` : '-'}</b></div>
            <div className="pill" title={`수락 건 중 받은 매장이 ${d.soldDays}일 안에 같은 상품을 판매한 비율 (괄호는 ${d.soldDays}일이 지난 건만)`}>
              <span>판매 전환 ({d.soldDays}일)</span><b>{s.soldRate != null ? `${s.soldRate}%` : '-'}</b>
              <span className="muted">{s.maturedAccepted ? `${d.soldDays}일 지난 건 ${pct(s.maturedSold, s.maturedAccepted)}` : ''}</span></div>
            <div className="pill hint-pill">{d.brandNm} · {d.scope === 'web' ? '이 화면에서 지시' : '본사지시 전체'} · {d.asOf} 기준{!d.includeVirtual && d.virtualQty ? ` · 행사 · 가상 매장 ${fmtNum(d.virtualQty)}장 제외` : ''}</div>
          </div>
          {s.total === 0 && scope === 'web' && <div className="alert info"><Info size={14} /> <span>이 기간에 이 화면에서 지시한 RT 가 없습니다. [본사지시 전체]로 ERP 에서 지시한 것까지 볼 수 있습니다.</span></div>}
          <div className="seg" role="tablist" aria-label="RT 성과 보기">
            <button className={tab === 'senders' ? 'on' : ''} onClick={() => setTab('senders')}>보내는 매장</button>
            <button className={tab === 'receivers' ? 'on' : ''} onClick={() => setTab('receivers')}>받는 매장</button>
            <button className={tab === 'reasons' ? 'on' : ''} onClick={() => setTab('reasons')}>거부 사유</button>
            <button className={tab === 'days' ? 'on' : ''} onClick={() => setTab('days')}>일별</button>
          </div>
          {tab === 'senders' && shopTable(d.senders, 'RT 성과 보내는 매장')}
          {tab === 'receivers' && shopTable(d.receivers, 'RT 성과 받는 매장')}
          {tab === 'reasons' && (
            <div className="stock-bars">
              {d.reasons.map((r) => {
                const max = Math.max(1, ...d.reasons.map((x) => x.qty))
                return <div key={r.reason} className="stock-bar-row"><span className="stock-bar-name">{r.reason}</span><span className="stock-bar"><i className="fail" style={{ width: `${(r.qty / max) * 100}%` }} /></span><b className="num">{fmtNum(r.qty)}장</b></div>
              })}
              {!d.reasons.length && <span className="muted">거부된 RT 가 없습니다.</span>}
            </div>
          )}
          {tab === 'days' && (
            <div className="stock-bars">
              {d.days.map((x) => {
                const max = Math.max(1, ...d.days.map((y) => y.total))
                return (
                  <div key={x.day} className="stock-bar-row">
                    <span className="stock-bar-name">{x.day}</span>
                    <span className="stock-bar stack3" title={`지시 ${x.total} · 수락 ${x.accepted} · 거부 ${x.denied} · 미처리 ${x.pending}`}>
                      <i className="done" style={{ width: `${(x.accepted / max) * 100}%` }} /><i className="fail" style={{ width: `${(x.denied / max) * 100}%` }} />
                      <i className="etc" style={{ width: `${(x.pending / max) * 100}%` }} />
                    </span>
                    <b className="num">{fmtNum(x.total)}</b>
                  </div>
                )
              })}
              <div className="stock-legend"><i className="done" /> 수락 <i className="fail" /> 거부 <i className="etc" /> 미처리</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
