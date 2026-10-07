import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Clock, Download, Hourglass, Info, Loader2, RefreshCw, Search, Undo2, X } from 'lucide-react'
import { fmtNum } from '../format'
import {
  agingQuery, stockApi,
  type AgingCond, type AgingReport, type AgingRow, type AgingSku, type AllocCond, type PendingBoard, type PendingGroup, type RecentRun, type ReturnResult,
  type StockOptions,
} from '../stockApi'
import { addDaysIso, Busy, errText, iso, Pager, pct, toggle, useElapsed, usePaged, won } from './stockUi'

// 재고 재배치 추천 > 창고 회수 추천 · 미처리 RT 현황 · 장기 미판매 재고 (조회 · 추천만)

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

function SearchBox({ q, setQ, placeholder, label }: { q: string; setQ: (v: string) => void; placeholder: string; label: string }) {
  return (
    <div className="search sm">
      <Search size={14} />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label={label} />
      {q && <button className="clear" onClick={() => setQ('')}><X size={13} /></button>}
    </div>
  )
}

const hit = (q: string, vals: (string | null | undefined)[]) => {
  const k = q.trim().toUpperCase()
  return !k || vals.some((v) => v?.toUpperCase().includes(k))
}

export function allocCondFromRun(opts: StockOptions, r: RecentRun | undefined): AllocCond {
  const yday = addDaysIso(iso(opts.today), -1)
  return {
    brand: opts.brand, wh: r?.wh ?? opts.warehouses[0]?.code ?? 'IN', dateFrom: yday, dateTo: yday,
    base: r?.base ?? opts.bases[0]?.id ?? '', grdGrp: r?.grdGrp ?? opts.gradeGroups.find((g) => g.base)?.id ?? '',
    planYy: r?.planYy ?? opts.defaultPlanYy, seasons: r?.seasons ?? opts.defaultSeasons, prdtGrps: r?.prdtGrps ?? [], items: r?.items ?? [],
    prdt: r?.prdt ?? '', teams: r?.teams ?? [], rate: r?.rate ?? 1,
  }
}

// ---------------------------------------------------------------- 창고 회수 추천
export function ReturnTab({ opts, seed }: { opts: StockOptions; seed: { cond: AllocCond; nonce: number } | null }) {
  const [runSeq, setRunSeq] = useState(opts.recentRuns[0]?.seq ?? '')
  const [cond, setCond] = useState<AllocCond>(() => allocCondFromRun(opts, opts.recentRuns[0]))
  const [lookback, setLookback] = useState(14)
  const [mode, setMode] = useState<'need' | 'all'>('need')
  const [applied, setApplied] = useState<{ cond: AllocCond; lookback: number; mode: string } | null>(null)
  const [d, setD] = useState<ReturnResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'rows' | 'skus' | 'shops'>('rows')
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const sec = useElapsed(loading)
  const today = iso(opts.today)

  const run = (refresh = false, override?: AllocCond) => {
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    setLoading(true)
    setError('')
    const c = { ...(override ?? cond) }
    stockApi.returnRec(c, lookback, mode, refresh, ac.signal).then((x) => { setD(x); setApplied({ cond: c, lookback, mode }) })
      .catch((e) => { if (!ac.signal.aborted) setError(errText(e)) }).finally(() => { if (abort.current === ac) setLoading(false) })
  }
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {                         // 창고 → 매장 배분의 [창고로 회수 추천]에서 같은 조건으로
    if (!seed) return
    setCond(seed.cond)
    setRunSeq('')
    run(false, seed.cond)
  }, [seed?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => (d?.rows ?? []).filter((r) => hit(q, [r.prdtCd, r.shopId, r.shopNm, r.styleNm])), [d, q])
  const skus = useMemo(() => (d?.skus ?? []).filter((r) => hit(q, [r.prdtCd, r.styleNm])), [d, q])
  const pgRows = usePaged(rows)
  const pgSkus = usePaged(skus)
  const s = d?.summary
  const dirty = !!applied && JSON.stringify(applied) !== JSON.stringify({ cond, lookback, mode })
  const exportXlsx = async () => {
    if (!applied) return
    setBusy(true)
    try { await stockApi.returnExport(applied.cond, applied.lookback, applied.mode) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><Undo2 size={17} /> 창고 회수 추천 <span className="muted small">(창고 부족 상품 → 판매 없는 매장 재고)</span></div>
          <div className="date-range" title="창고 → 매장 배분 판매 기간 (창고 부족 계산)">
            <span className="date-range-label">배분 판매 기간</span>
            <input type="date" value={cond.dateFrom} max={cond.dateTo || today} onChange={(e) => setCond({ ...cond, dateFrom: e.target.value })} aria-label="회수 배분 기간 시작" />
            <span className="muted">~</span>
            <input type="date" value={cond.dateTo} min={cond.dateFrom} max={today} onChange={(e) => setCond({ ...cond, dateTo: e.target.value })} aria-label="회수 배분 기간 끝" />
          </div>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => run(false)} disabled={loading}>{loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 회수 추천{dirty ? ' *' : ''}</button>
            <button className="btn ghost" onClick={() => run(true)} disabled={loading || !applied}><RefreshCw size={15} /> 새로 계산</button>
            <button className="btn success" onClick={exportXlsx} disabled={!d || busy || dirty}>{busy ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀</button>
          </div>
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">배분 조건</span>
          <select className="input sm stock-run" value={runSeq} onChange={(e) => {
            setRunSeq(e.target.value)
            const r = opts.recentRuns.find((x) => x.seq === e.target.value)
            if (r) setCond({ ...allocCondFromRun(opts, r), dateFrom: cond.dateFrom, dateTo: cond.dateTo })
          }} aria-label="회수 배분 조건 (최근 판매분 자동보충 실행)">
            {!runSeq && <option value="">창고 → 매장 배분 탭 조건</option>}
            {opts.recentRuns.map((r) => <option key={r.seq} value={r.seq}>최근 실행 {r.seq} · {r.at} · 창고 {r.wh}</option>)}
          </select>
          <label className="field-label">판매 없음 기준
            <select className="input sm" value={lookback} onChange={(e) => setLookback(Number(e.target.value))} aria-label="판매 없음 기준 기간">
              {[7, 14, 30, 60].map((n) => <option key={n} value={n}>최근 {n}일</option>)}
            </select>
          </label>
          <div className="seg" role="group" aria-label="회수 방식">
            <button className={mode === 'need' ? 'on' : ''} onClick={() => setMode('need')}>창고 부족 수량만큼</button>
            <button className={mode === 'all' ? 'on' : ''} onClick={() => setMode('all')}>판매 없는 재고 전부</button>
          </div>
        </div>
      </section>
      {error && <div className="alert error">{error}</div>}
      {loading && <section className="card"><Busy sec={sec} text="창고 부족 상품과 매장 재고 · 판매를 확인하는 중…" /></section>}
      {!d && !loading && (
        <section className="card stock-empty">
          <Undo2 size={26} />
          <div>
            <b>창고가 모자라 판매분 보충을 못 하는 상품을, 그 상품이 안 팔리는 매장에서 창고로 회수하도록 추천합니다.</b>
            <div className="muted small">받아야 하는 매장 · 최근 판매가 있는 매장 · 행사 · 가상 매장은 빼고, 폐점 · 비정상 매장 → 판매 이력 없는/오래된 매장 순으로 고릅니다. 추천만 하며 ERP 에 반품 지시를 넣지 않습니다.</div>
          </div>
        </section>
      )}
      {d && s && (
        <>
          <section className="summary-pills">
            <div className="pill"><span>창고 부족</span><b>{fmtNum(s.shortSkus)}개 · {fmtNum(s.shortQty)}장</b></div>
            <div className="pill strong"><span>회수 추천</span><b>{fmtNum(s.returnQty)}장</b><span className="muted">{fmtNum(s.shops)}개 매장 · 부족 채움 {pct(s.coveredQty, s.shortQty)}</span></div>
            <div className="pill"><span>다 채운 상품</span><b>{fmtNum(s.coveredSkus)}</b><span className="muted">일부 {fmtNum(s.partialSkus)} · 회수할 곳 없음 {fmtNum(s.noSourceSkus)}</span></div>
            <div className="pill" title="회수 후보에서 뺀 매장 × 상품"><span>후보에서 뺌</span><b>최근 판매 {fmtNum(s.excluded.sold ?? 0)} · 받을 매장 {fmtNum(s.excluded.needs ?? 0)}</b>
              <span className="muted">이동 · 지시 중 {fmtNum(s.excluded.reserved ?? 0)} · 행사 · 가상 {fmtNum(s.excluded.virtual ?? 0)}</span></div>
            <div className="pill hint-pill">{d.brandNm} · 창고 {d.wh} · 배분 {d.from === d.to ? d.from : `${d.from}~${d.to}`} · {d.salesFrom}부터 판매 없음 · {d.modeNm} · {d.asOf} 기준</div>
          </section>
          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="회수 결과 보기">
                <button className={view === 'rows' ? 'on' : ''} onClick={() => setView('rows')}>회수 추천 ({fmtNum(s.rows)})</button>
                <button className={view === 'skus' ? 'on' : ''} onClick={() => setView('skus')}>상품별 ({fmtNum(d.skus.length)})</button>
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>많이 회수할 매장</button>
              </div>
              {view !== 'shops' && <SearchBox q={q} setQ={setQ} placeholder="품번 · 매장" label="회수 결과 검색" />}
              <span className="pill hint-pill"><Info size={13} /> 추천만 — ERP 반품 지시는 등록하지 않습니다</span>
            </div>
            {view === 'rows' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="창고 회수 추천">
                    <thead><tr><th>품번 · 칼라 · 사이즈</th><th>회수할 매장</th><th className="num">현재고</th><th className="num" title="현재고 − 이동중 · 요청중 · 미처리 지시">회수 가능</th>
                      <th className="num">회수 추천</th><th>최종판매일</th><th>최종출고일</th><th className="num">상품 창고 부족</th></tr></thead>
                    <tbody>
                      {pgRows.slice.map((r) => (
                        <tr key={`${r.prdtCd}-${r.colorCd}-${r.sizeCd}-${r.shopId}`} className={r.closed ? 'row-short' : ''}>
                          <td><b className="mono">{r.prdtCd}</b> <span className="muted">{r.colorCd} · {r.sizeCd}</span></td>
                          <td><span className="mono">{r.shopId}</span> {r.shopNm}{r.closed && <span className="tag warn"> 폐점 · 비정상</span>}<div className="muted small">{r.team}</div></td>
                          <td className="num">{r.stock}</td><td className="num">{r.avail}</td><td className="num"><b>{r.qty}</b></td>
                          <td className="muted">{r.lastSale ? `${r.lastSale} (${fmtNum(r.daysNoSale ?? 0)}일)` : '판매 이력 없음'}</td>
                          <td className="muted">{r.lastDelv ?? '-'}</td><td className="num">{r.skuShort}</td>
                        </tr>
                      ))}
                      {!rows.length && <tr><td colSpan={8} className="empty">회수할 재고가 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgRows} />
              </>
            )}
            {view === 'skus' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="창고 회수 상품별">
                    <thead><tr><th>품번 · 칼라 · 사이즈</th><th className="num">창고 재고</th><th className="num">배분 가능</th><th className="num">필요</th><th className="num">창고 부족</th>
                      <th className="num">회수 후보 매장</th><th className="num">후보 재고</th><th className="num">회수 추천</th><th className="num">남는 부족</th></tr></thead>
                    <tbody>
                      {pgSkus.slice.map((k) => (
                        <tr key={`${k.prdtCd}-${k.colorCd}-${k.sizeCd}`} className={k.left ? 'row-short' : ''}>
                          <td><b className="mono">{k.prdtCd}</b> <span className="muted">{k.colorCd} · {k.sizeCd}</span></td>
                          <td className="num">{fmtNum(k.whStock)}</td><td className="num">{fmtNum(k.avail)}</td><td className="num">{k.demand}</td><td className="num danger-text">{k.short}</td>
                          <td className="num">{k.candidates}</td><td className="num">{k.candQty}</td><td className="num"><b>{k.returnQty}</b></td><td className="num">{k.left || '-'}</td>
                        </tr>
                      ))}
                      {!skus.length && <tr><td colSpan={9} className="empty">창고 부족 상품이 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgSkus} />
              </>
            )}
            {view === 'shops' && (
              <div className="stock-two"><div className="stock-bars"><b>많이 회수할 매장 (상위 15)</b>
                {d.topShops.map((x) => {
                  const max = Math.max(1, ...d.topShops.map((y) => y.qty))
                  return <div key={x.shopId} className="stock-bar-row"><span className="stock-bar-name"><span className="mono">{x.shopId}</span> {x.shopNm}</span><span className="stock-bar"><i style={{ width: `${(x.qty / max) * 100}%` }} /></span><b className="num">{fmtNum(x.qty)}장</b></div>
                })}
                {!d.topShops.length && <span className="muted">없음</span>}
              </div></div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 미처리 RT 현황판
const AGE_CLS: Record<string, string> = { d0: '', d1: '', d2: 'warn', d3: 'miss' }

export function PendingTab({ opts }: { opts: StockOptions }) {
  const [days, setDays] = useState(14)
  const [types, setTypes] = useState<string[]>(['C6811', 'C6812', 'C6813'])
  const [virt, setVirt] = useState(false)
  const [d, setD] = useState<PendingBoard | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'shops' | 'teams' | 'rows'>('shops')
  const [q, setQ] = useState('')
  const [shop, setShop] = useState<string | null>(null)
  const [onlyUrgent, setOnlyUrgent] = useState(false)
  const [busy, setBusy] = useState(false)
  const load = (refresh = false) => {
    if (!types.length) return
    setLoading(true)
    setError('')
    stockApi.pending(opts.brand, days, types, virt, refresh).then(setD).catch((e) => setError(errText(e))).finally(() => setLoading(false))
  }
  useEffect(() => load(), [opts.brand, days, types, virt]) // eslint-disable-line react-hooks/exhaustive-deps
  const shops = useMemo(() => (d?.shops ?? []).filter((g) => hit(q, [g.key, g.name, g.team])), [d, q])
  const rows = useMemo(() => (d?.rows ?? []).filter((r) => (!shop || r.fromShopId === shop) && (!onlyUrgent || r.urgent)
    && hit(q, [r.prdtCd, r.fromShopId, r.fromShopNm, r.toShopId, r.toShopNm])), [d, q, shop, onlyUrgent])
  const pgShops = usePaged(shops)
  const pgRows = usePaged(rows)
  const s = d?.summary
  const typeItems = Object.entries(d?.typeNames ?? { C6811: '본사지시', C6812: '자동 RT', C6813: '매장간' }).map(([code, name]) => ({ code, name }))
  const exportXlsx = async () => {
    setBusy(true)
    try { await stockApi.pendingExport(opts.brand, days, types, virt) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  const groupTable = (list: PendingGroup[], label: string, isShop: boolean) => (
    <div className="table-wrap tall">
      <table className="table stock-table" aria-label={label}>
        <thead><tr><th>{isShop ? '처리할 매장 (보내는 매장)' : '팀'}</th><th className="num">미처리</th><th className="num">수량</th>
          <th className="num" title={`본사지시 ${d?.urgentHours ?? 48}시간 넘음 — 3일 무응답이면 자동거부`}>자동거부 임박</th><th className="num">가장 오래된</th>
          {(d?.ages ?? []).map((a) => <th key={a.key} className="num">{a.name}</th>)}
          <th className="num">본사지시</th><th className="num">자동 RT</th><th className="num">매장간</th></tr></thead>
        <tbody>
          {list.map((g) => (
            <tr key={g.key} className={`${g.urgent ? 'row-short' : ''} ${isShop ? 'clickable' : ''}`} onClick={isShop ? () => { setShop(g.key); setView('rows') } : undefined}>
              <td>{isShop ? <><span className="mono">{g.key}</span> {g.name}<div className="muted small">{g.team}</div></> : g.name}</td>
              <td className="num"><b>{fmtNum(g.rows)}</b></td><td className="num">{fmtNum(g.qty)}</td>
              <td className={`num ${g.urgent ? 'danger-text' : ''}`}>{g.urgent || '-'}</td><td className="num">{Math.floor(g.oldestHours / 24)}일 {Math.round(g.oldestHours % 24)}시간</td>
              <td className="num">{g.d0 || '-'}</td><td className="num">{g.d1 || '-'}</td><td className="num">{g.d2 || '-'}</td><td className="num">{g.d3 || '-'}</td>
              <td className="num">{g.C6811 || '-'}</td><td className="num">{g.C6812 || '-'}</td><td className="num">{g.C6813 || '-'}</td>
            </tr>
          ))}
          {!list.length && <tr><td colSpan={12} className="empty">미처리 RT 가 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  )
  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><Clock size={17} /> 미처리 RT 현황 <span className="muted small">(매장이 아직 수락 · 거부하지 않은 요청)</span></div>
          <div className="seg" role="group" aria-label="요청일 기간">
            {[3, 7, 14, 31].map((n) => <button key={n} className={days === n ? 'on' : ''} onClick={() => setDays(n)}>최근 {n}일</button>)}
          </div>
          <div className="toolbar-actions">
            <button className="btn ghost" onClick={() => load(true)} disabled={loading}>{loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} 새로 고침</button>
            <button className="btn success" onClick={exportXlsx} disabled={!d || busy}>{busy ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀</button>
          </div>
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">종류</span>
          <Chips items={typeItems} value={types} onChange={setTypes} empty={types.length ? undefined : '하나 이상 고르세요'} />
          <label className="check-label"><input type="checkbox" checked={virt} onChange={(e) => setVirt(e.target.checked)} /> 행사 · 가상 매장 포함</label>
        </div>
      </section>
      {error && <div className="alert error">{error}</div>}
      {loading && !d && <section className="card"><Busy sec={0} text="미처리 RT 를 불러오는 중…" /></section>}
      {d && s && (
        <>
          <section className="summary-pills">
            <div className="pill strong"><span>미처리</span><b>{fmtNum(s.rows)}건 · {fmtNum(s.qty)}장</b></div>
            <div className="pill"><span>처리할 매장</span><b>{fmtNum(s.shops)}곳</b></div>
            <div className={`pill ${s.urgent ? 'warn-pill' : ''}`} title="본사지시 RT 는 3일 동안 응답이 없으면 새벽 배치가 자동거부합니다"><span>자동거부 임박 ({d.urgentHours}시간 넘은 본사지시)</span><b>{fmtNum(s.urgent)}건</b></div>
            {d.ages.map((a) => <div key={a.key} className="pill"><span>{a.name}</span><b>{fmtNum(s.byAge[a.key] ?? 0)}</b></div>)}
            <div className="pill hint-pill">{d.brandNm} · 요청일 {d.from} ~ {d.to} · {Object.entries(s.byType).map(([k, v]) => `${d.typeNames[k]} ${fmtNum(v)}`).join(' · ')} · {d.asOf} 기준
              {!d.includeVirtual && d.virtualRows ? ` · 행사 · 가상 매장 ${fmtNum(d.virtualRows)}건 제외` : ''}</div>
          </section>
          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="미처리 RT 보기">
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>매장별 ({fmtNum(d.shops.length)})</button>
                <button className={view === 'teams' ? 'on' : ''} onClick={() => setView('teams')}>팀별</button>
                <button className={view === 'rows' ? 'on' : ''} onClick={() => setView('rows')}>요청 목록 ({fmtNum(s.rows)})</button>
              </div>
              {view !== 'teams' && <SearchBox q={q} setQ={setQ} placeholder="매장 · 품번" label="미처리 RT 검색" />}
              {view === 'rows' && <label className="check-label"><input type="checkbox" checked={onlyUrgent} onChange={(e) => setOnlyUrgent(e.target.checked)} /> 자동거부 임박만</label>}
              {view === 'rows' && shop && <button className="chip active" onClick={() => setShop(null)}>{shop} <X size={12} /></button>}
              {view === 'shops' && <span className="muted small">매장을 누르면 그 매장 요청 목록</span>}
            </div>
            {view === 'shops' && <>{groupTable(pgShops.slice, '미처리 RT 매장별', true)}<Pager pg={pgShops} label="곳" /></>}
            {view === 'teams' && groupTable(d.teams, '미처리 RT 팀별', false)}
            {view === 'rows' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="미처리 RT 요청 목록">
                    <thead><tr><th>처리할 매장</th><th>종류</th><th>요청</th><th className="num">경과</th><th>품번 · 칼라 · 사이즈</th><th className="num">수량</th><th>받는 매장</th><th>요청자 · 번호</th></tr></thead>
                    <tbody>
                      {pgRows.slice.map((r) => (
                        <tr key={`${r.makeDt}-${r.seq}`} className={r.urgent ? 'row-short' : ''}>
                          <td><span className="mono">{r.fromShopId}</span> {r.fromShopNm}<div className="muted small">{r.fromTeam}</div></td>
                          <td>{r.typeNm}</td><td className="muted">{r.requestedAt ?? r.makeDt}</td>
                          <td className="num"><span className={`tag ${AGE_CLS[r.age]}`}>{Math.floor(r.hours / 24)}일 {Math.round(r.hours % 24)}시간</span>{r.urgent && <div className="danger-text small">자동거부 임박</div>}</td>
                          <td><b className="mono">{r.prdtCd}</b> <span className="muted">{r.colorCd} · {r.sizeCd}</span></td>
                          <td className="num">{r.qty}</td>
                          <td><span className="mono">{r.toShopId}</span> {r.toShopNm}</td>
                          <td className="muted small">{r.requestedBy}{r.ref ? ` · ${r.ref}` : ''}</td>
                        </tr>
                      ))}
                      {!rows.length && <tr><td colSpan={8} className="empty">미처리 RT 가 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgRows} />
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 장기 미판매 재고
export function AgingTab({ opts }: { opts: StockOptions }) {
  const init: AgingCond = { brand: opts.brand, minDays: 90, planYy: [], seasons: [], teams: [], prdt: '', includeVirtual: false }
  const [cond, setCond] = useState<AgingCond>(init)
  const [applied, setApplied] = useState<AgingCond | null>(null)
  const [d, setD] = useState<AgingReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<'shops' | 'styles' | 'detail'>('shops')
  const [q, setQ] = useState('')
  const [shop, setShop] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [skuOf, setSkuOf] = useState<AgingRow | null>(null)
  const abort = useRef<AbortController | null>(null)
  const sec = useElapsed(loading)
  const run = (refresh = false, c: AgingCond = cond) => {
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    setLoading(true)
    setError('')
    stockApi.aging(c, refresh, ac.signal).then((x) => { setD(x); setApplied(c) })
      .catch((e) => { if (!ac.signal.aborted) setError(errText(e)) }).finally(() => { if (abort.current === ac) setLoading(false) })
  }
  useEffect(() => { run(false, init); return () => abort.current?.abort() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = !!applied && agingQuery(applied) !== agingQuery(cond)
  const shops = useMemo(() => (d?.shops ?? []).filter((g) => g.agedQty && hit(q, [g.shopId, g.shopNm, g.team])), [d, q])
  const styles = useMemo(() => (d?.styles ?? []).filter((g) => hit(q, [g.prdtCd, g.styleNm])), [d, q])
  const detail = useMemo(() => (d?.detail ?? []).filter((r) => (!shop || r.shopId === shop) && hit(q, [r.prdtCd, r.shopId, r.shopNm, r.styleNm])), [d, q, shop])
  const pgShops = usePaged(shops)
  const pgStyles = usePaged(styles)
  const pgDetail = usePaged(detail)
  const s = d?.summary
  const exportXlsx = async () => {
    if (!applied) return
    setBusy(true)
    try { await stockApi.agingExport(applied) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  const bmax = Math.max(1, ...(d?.buckets ?? []).map((b) => b.qty))
  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><Hourglass size={17} /> 장기 미판매 재고 <span className="muted small">(매장 × 스타일, 그 매장 최종판매일 기준)</span></div>
          <div className="seg" role="group" aria-label="장기 미판매 기준">
            {[30, 60, 90, 180, 365].map((n) => <button key={n} className={cond.minDays === n ? 'on' : ''} onClick={() => setCond({ ...cond, minDays: n })}>{n}일 이상</button>)}
          </div>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => run(false)} disabled={loading}>{loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 조회{dirty ? ' *' : ''}</button>
            <button className="btn ghost" onClick={() => run(true)} disabled={loading} title="지금 매장 재고를 다시 읽습니다 (1~2분)"><RefreshCw size={15} /> 새로 계산</button>
            <button className="btn success" onClick={exportXlsx} disabled={!d || busy || dirty}>{busy ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀</button>
          </div>
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">기획년도</span>
          <Chips items={opts.planYears.map((y) => ({ code: y, name: y }))} value={cond.planYy} onChange={(planYy) => setCond({ ...cond, planYy })} empty="비우면 전체" />
          <span className="filter-label">시즌</span>
          <Chips items={opts.seasons} value={cond.seasons} onChange={(seasons) => setCond({ ...cond, seasons })} empty="비우면 전체" />
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">팀</span>
          <Chips items={opts.teams} value={cond.teams} onChange={(teams) => setCond({ ...cond, teams })} empty="비우면 전체" />
          <span className="filter-label">품번</span>
          <input className="input sm stock-prdt" value={cond.prdt} placeholder="앞부분만 입력 가능" onChange={(e) => setCond({ ...cond, prdt: e.target.value.toUpperCase() })} aria-label="장기 미판매 품번" />
          <label className="check-label"><input type="checkbox" checked={cond.includeVirtual} onChange={(e) => setCond({ ...cond, includeVirtual: e.target.checked })} /> 행사 · 가상 매장 포함</label>
        </div>
      </section>
      {error && <div className="alert error">{error}</div>}
      {loading && <section className="card"><Busy sec={sec} text="매장 재고와 최종판매일을 읽는 중… (처음은 1~2분, 이후 12시간은 바로)" /></section>}
      {d && s && (
        <>
          <section className="summary-pills">
            <div className="pill"><span>매장 재고</span><b>{fmtNum(s.qty)}장</b><span className="muted">{won(s.amt)}원 · {fmtNum(s.shops)}개 매장</span></div>
            <div className="pill strong warn-pill"><span>{d.minDays}일 넘게 안 팔림</span><b>{fmtNum(s.agedQty)}장 · {won(s.agedAmt)}원</b><span className="muted">재고의 {s.agedRate ?? 0}%</span></div>
            <div className="pill"><span>해당 매장</span><b>{fmtNum(s.agedShops)}곳</b></div>
            <div className="pill"><span>해당 스타일</span><b>{fmtNum(s.agedStyles)}개</b></div>
            <div className="pill hint-pill">{d.brandNm} · 재고 기준 {d.asOf}{!d.cond.includeVirtual && d.virtualQty ? ` · 행사 · 가상 매장 ${fmtNum(d.virtualQty)}장 제외` : ''}</div>
          </section>
          <section className="card stock-aging-buckets">
            <div className="stock-bars">
              <b>미판매 일수별 매장 재고 (수량 · 금액)</b>
              {d.buckets.filter((b) => b.qty || b.key !== 'none').map((b) => (
                <div key={b.key} className="stock-bar-row">
                  <span className="stock-bar-name">{b.name}</span>
                  <span className="stock-bar"><i className={b.key === 'b30' || b.key === 'b60' ? 'done' : b.key === 'none' ? 'etc' : 'fail'} style={{ width: `${(b.qty / bmax) * 100}%` }} /></span>
                  <b className="num">{fmtNum(b.qty)}장 · {won(b.amt)}</b>
                </div>
              ))}
            </div>
          </section>
          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="장기 미판매 보기">
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>매장별 ({fmtNum(s.agedShops)})</button>
                <button className={view === 'styles' ? 'on' : ''} onClick={() => setView('styles')}>스타일별 ({fmtNum(d.stylesTotal)})</button>
                <button className={view === 'detail' ? 'on' : ''} onClick={() => setView('detail')}>매장 × 스타일 ({fmtNum(d.detailTotal)})</button>
              </div>
              <SearchBox q={q} setQ={setQ} placeholder="매장 · 품번" label="장기 미판매 검색" />
              {view === 'detail' && shop && <button className="chip active" onClick={() => setShop(null)}>{shop} <X size={12} /></button>}
              {view === 'shops' && <span className="muted small">매장을 누르면 그 매장 스타일 목록</span>}
              {view === 'detail' && <span className="muted small">행을 누르면 칼라 · 사이즈별 재고</span>}
            </div>
            {view === 'shops' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="장기 미판매 매장별">
                    <thead><tr><th>매장</th><th className="num">매장 재고</th><th className="num">재고 금액</th><th className="num">장기 미판매</th><th className="num">금액</th><th className="num">비중</th><th className="num">스타일 수</th></tr></thead>
                    <tbody>
                      {pgShops.slice.map((g) => (
                        <tr key={g.shopId} className={`clickable ${g.agedRate != null && g.agedRate >= 30 ? 'row-short' : ''}`} onClick={() => { setShop(g.shopId); setView('detail') }}>
                          <td><span className="mono">{g.shopId}</span> {g.shopNm}{g.closed && <span className="tag warn"> 폐점 · 비정상</span>}<div className="muted small">{g.team}</div></td>
                          <td className="num">{fmtNum(g.qty)}</td><td className="num">{won(g.amt)}</td><td className="num"><b>{fmtNum(g.agedQty)}</b></td><td className="num">{won(g.agedAmt)}</td>
                          <td className="num">{g.agedRate != null ? `${g.agedRate}%` : '-'}</td><td className="num">{fmtNum(g.agedStyles)}</td>
                        </tr>
                      ))}
                      {!shops.length && <tr><td colSpan={7} className="empty">장기 미판매 재고가 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgShops} label="곳" />
              </>
            )}
            {view === 'styles' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="장기 미판매 스타일별">
                    <thead><tr><th>품번</th><th>기획 · 시즌</th><th className="num">매장 재고</th><th className="num">장기 미판매</th><th className="num">금액</th><th className="num">매장 수</th><th className="num">최장 미판매</th></tr></thead>
                    <tbody>
                      {pgStyles.slice.map((g) => (
                        <tr key={g.prdtCd}>
                          <td><b className="mono">{g.prdtCd}</b>{g.styleNm && g.styleNm !== g.prdtCd && <div className="muted small">{g.styleNm}</div>}</td>
                          <td className="muted">{g.planYy} {g.sesnNm}</td><td className="num">{fmtNum(g.qty)}</td><td className="num"><b>{fmtNum(g.agedQty)}</b></td>
                          <td className="num">{won(g.agedAmt)}</td><td className="num">{g.agedShops}</td><td className="num">{g.maxDays != null ? `${fmtNum(g.maxDays)}일` : '-'}</td>
                        </tr>
                      ))}
                      {!styles.length && <tr><td colSpan={7} className="empty">장기 미판매 스타일이 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgStyles} label="개" />
              </>
            )}
            {view === 'detail' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="장기 미판매 매장 × 스타일">
                    <thead><tr><th>매장</th><th>품번</th><th>기획 · 시즌</th><th className="num">재고</th><th className="num">금액</th><th className="num">미판매</th><th>최종판매일</th><th>최종출고일</th></tr></thead>
                    <tbody>
                      {pgDetail.slice.map((r) => (
                        <tr key={`${r.shopId}-${r.prdtCd}`} className={`clickable ${r.days != null && r.days >= 365 ? 'row-short' : ''}`} onClick={() => setSkuOf(r)}>
                          <td><span className="mono">{r.shopId}</span> {r.shopNm}<div className="muted small">{r.team}</div></td>
                          <td><b className="mono">{r.prdtCd}</b> <span className="muted small">{r.skus}개 칼라 · 사이즈</span></td>
                          <td className="muted">{r.planYy} {r.sesnNm}</td><td className="num"><b>{fmtNum(r.qty)}</b></td><td className="num">{won(r.amt)}</td>
                          <td className="num">{r.days != null ? `${fmtNum(r.days)}일` : '-'}</td>
                          <td className="muted">{r.neverSold ? '판매 이력 없음' : r.lastSale}</td><td className="muted">{r.lastDelv ?? '-'}</td>
                        </tr>
                      ))}
                      {!detail.length && <tr><td colSpan={8} className="empty">장기 미판매 재고가 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgDetail}>{d.detailTotal > d.detail.length && <span className="muted small">금액 큰 순 앞쪽 {fmtNum(d.detail.length)}건 · 전체는 엑셀</span>}</Pager>
              </>
            )}
          </section>
        </>
      )}
      {skuOf && <AgingSkuModal brand={opts.brand} row={skuOf} onClose={() => setSkuOf(null)} />}
    </div>
  )
}

function AgingSkuModal({ brand, row, onClose }: { brand: string; row: AgingRow; onClose: () => void }) {
  const [rows, setRows] = useState<AgingSku[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { stockApi.agingSkus(brand, row.shopId, row.prdtCd).then((x) => setRows(x.rows)).catch((e) => setError(errText(e))) }, [brand, row])
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal stock-write-modal" role="dialog" aria-label="칼라 · 사이즈별 재고">
        <div className="modal-head">
          <h3><Hourglass size={17} /> {row.shopNm} · {row.prdtCd}</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        {error && <div className="alert error">{error}</div>}
        {!rows && !error && <Busy sec={0} text="불러오는 중…" />}
        {rows && (
          <div className="table-wrap">
            <table className="table stock-table" aria-label="칼라 · 사이즈별 재고">
              <thead><tr><th>칼라 · 사이즈</th><th className="num">재고</th><th className="num">금액</th><th className="num">미판매</th><th>최종판매일</th><th>최종출고일</th><th>최초출고일</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.colorCd}-${r.sizeCd}`}>
                    <td className="mono">{r.colorCd} · {r.sizeCd}</td><td className="num">{r.qty}</td><td className="num">{won(r.amt)}</td>
                    <td className="num">{r.days != null ? `${fmtNum(r.days)}일` : '-'}</td><td className="muted">{r.lastSale ?? '판매 이력 없음'}</td>
                    <td className="muted">{r.lastDelv ?? '-'}</td><td className="muted">{r.firstDelv ?? '-'}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={7} className="empty">재고가 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <div className="muted small"><AlertTriangle size={12} /> 미판매 일수 = 오늘 − 그 매장 최종판매일 (판매 이력이 없으면 최초출고일부터)</div>
      </div>
    </div>
  )
}
