import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, Gauge, Info, Loader2, PackageCheck, RefreshCw, Search, X } from 'lucide-react'
import { fmtNum } from '../format'
import {
  initQuery, stockApi, turnQuery,
  type InitCond, type InitProduct, type InitProductShop, type InitReport, type StockOptions, type TurnCond, type TurnReport,
} from '../stockApi'
import { Busy, errText, Pager, toggle, useElapsed, usePaged, won } from './stockUi'

// 재고 재배치 추천 > 재고 분석: 재고 회전 · 초도 배분 적중률 (조회만)

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
const days = (v: number | null) => (v == null ? '판매 없음' : `${fmtNum(Math.round(v))}일`)
const pctv = (v: number | null) => (v == null ? '-' : `${v}%`)
const CLS_TAG: Record<string, string> = { out: 'miss', c7: 'miss', c30: 'auto', c90: '', c180: 'warn', c999: 'warn', nosale: 'warn' }

/** 같은 조건으로 다시 부르기 · 취소 · 경과 초 */
function useRun<C, R>(fetcher: (c: C, refresh: boolean, signal: AbortSignal) => Promise<R>) {
  const [data, setData] = useState<R | null>(null)
  const [applied, setApplied] = useState<C | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const abort = useRef<AbortController | null>(null)
  const sec = useElapsed(loading)
  const run = (c: C, refresh = false) => {
    abort.current?.abort()
    const ac = new AbortController()
    abort.current = ac
    setLoading(true)
    setError('')
    fetcher(c, refresh, ac.signal).then((x) => { setData(x); setApplied(c) })
      .catch((e) => { if (!ac.signal.aborted) setError(errText(e)) }).finally(() => { if (abort.current === ac) setLoading(false) })
  }
  useEffect(() => () => abort.current?.abort(), [])
  return { data, applied, loading, error, sec, run, setError }
}

// ---------------------------------------------------------------- 재고 회전
export function TurnoverTab({ opts }: { opts: StockOptions }) {
  const init: TurnCond = { brand: opts.brand, days: 28, planYy: [], seasons: [], teams: [], prdt: '', includeVirtual: false }
  const [cond, setCond] = useState<TurnCond>(init)
  const r = useRun<TurnCond, TurnReport>((c, refresh, signal) => stockApi.turnover(c, refresh, signal))
  const [view, setView] = useState<'shops' | 'teams' | 'styles' | 'short' | 'over'>('shops')
  const [q, setQ] = useState('')
  const [shop, setShop] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => r.run(init), []) // eslint-disable-line react-hooks/exhaustive-deps
  const d = r.data
  const dirty = !!r.applied && turnQuery(r.applied) !== turnQuery(cond)
  const shops = useMemo(() => (d?.shops ?? []).filter((g) => hit(q, [g.shopId, g.shopNm, g.team])), [d, q])
  const styles = useMemo(() => (d?.styles ?? []).filter((g) => hit(q, [g.prdtCd, g.styleNm])), [d, q])
  const short = useMemo(() => (d?.detail ?? []).filter((x) => (x.cls === 'out' || x.cls === 'c7') && (!shop || x.shopId === shop)
    && hit(q, [x.prdtCd, x.shopId, x.shopNm])), [d, q, shop])
  const over = useMemo(() => (d?.detail ?? []).filter((x) => x.cls !== 'out' && x.cls !== 'c7' && (!shop || x.shopId === shop)
    && hit(q, [x.prdtCd, x.shopId, x.shopNm])), [d, q, shop])
  const pgShops = usePaged(shops)
  const pgStyles = usePaged(styles)
  const pgShort = usePaged(short)
  const pgOver = usePaged(over)
  const s = d?.summary
  const clsNm = useMemo(() => Object.fromEntries((d?.classes ?? []).map((c) => [c.key, c.name])), [d])
  const exportXlsx = async () => {
    if (!r.applied) return
    setBusy(true)
    try { await stockApi.turnoverExport(r.applied) } catch (e) { r.setError(errText(e)) } finally { setBusy(false) }
  }
  const cmax = Math.max(1, ...(d?.classes ?? []).map((c) => c.rows))
  const detailTable = (pg: typeof pgShort, label: string, empty: string) => (
    <>
      <div className="table-wrap tall">
        <table className="table stock-table" aria-label={label}>
          <thead><tr><th>매장</th><th>품번</th><th>기획 · 시즌</th><th className="num">재고</th><th className="num">기간 판매</th><th className="num">일평균</th>
            <th className="num">재고일수</th><th className="num">판매율</th><th>구분</th></tr></thead>
          <tbody>
            {pg.slice.map((x) => (
              <tr key={`${x.shopId}-${x.prdtCd}`}>
                <td><span className="mono">{x.shopId}</span> {x.shopNm}<div className="muted small">{x.team}</div></td>
                <td><b className="mono">{x.prdtCd}</b></td><td className="muted">{x.planYy} {x.sesnNm}</td>
                <td className="num">{fmtNum(x.stock)}</td><td className="num">{fmtNum(x.sales)}</td><td className="num">{x.daily}</td>
                <td className="num"><b>{x.cls === 'out' ? '품절' : days(x.cover)}</b></td><td className="num">{pctv(x.sellThru)}</td>
                <td><span className={`tag ${CLS_TAG[x.cls]}`}>{clsNm[x.cls]}</span></td>
              </tr>
            ))}
            {!pg.total && <tr><td colSpan={9} className="empty">{empty}</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager pg={pg}>{d && d.detailTotal > d.detail.length && <span className="muted small">앞쪽 {fmtNum(d.detail.length)}건 · 전체는 엑셀</span>}</Pager>
    </>
  )
  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><Gauge size={17} /> 재고 회전 <span className="muted small">(매장 × 스타일 재고 ÷ 일평균 판매)</span></div>
          <div className="seg" role="group" aria-label="판매 기간">
            {[7, 14, 28, 56, 91].map((n) => <button key={n} className={cond.days === n ? 'on' : ''} onClick={() => setCond({ ...cond, days: n })}>최근 {n}일 판매</button>)}
          </div>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => r.run(cond)} disabled={r.loading}>{r.loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 조회{dirty ? ' *' : ''}</button>
            <button className="btn ghost" onClick={() => r.run(cond, true)} disabled={r.loading} title="지금 매장 재고 · 판매로 다시 읽습니다 (1~2분)"><RefreshCw size={15} /> 새로 계산</button>
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
          <input className="input sm stock-prdt" value={cond.prdt} placeholder="앞부분만 입력 가능" onChange={(e) => setCond({ ...cond, prdt: e.target.value.toUpperCase() })} aria-label="재고 회전 품번" />
          <label className="check-label"><input type="checkbox" checked={cond.includeVirtual} onChange={(e) => setCond({ ...cond, includeVirtual: e.target.checked })} /> 행사 · 가상 매장 포함</label>
        </div>
      </section>
      {r.error && <div className="alert error">{r.error}</div>}
      {r.loading && <section className="card"><Busy sec={r.sec} text="매장 재고와 판매를 읽는 중… (재고 기준이 없으면 처음 1~2분)" /></section>}
      {d && s && (
        <>
          <section className="summary-pills">
            <div className="pill strong"><span>재고일수</span><b>{days(s.cover)}</b><span className="muted">재고 {fmtNum(s.stock)}장 ÷ 일평균 {fmtNum(s.daily)}장</span></div>
            <div className="pill"><span>판매율 ({d.days}일)</span><b>{pctv(s.sellThru)}</b><span className="muted">판매 {fmtNum(s.sales)}장</span></div>
            <div className={`pill ${s.shortRows ? 'warn-pill' : ''}`}><span>품절 · 품절 위험</span><b>{fmtNum(s.shortRows)}</b><span className="muted">매장 × 스타일</span></div>
            <div className="pill warn-pill"><span>과다 (90일 넘음 · 판매 없음)</span><b>{fmtNum(s.overRows)}</b><span className="muted">재고 {fmtNum(s.overStock)}장</span></div>
            <div className="pill hint-pill">{d.brandNm} · 재고 기준 {d.stockAsOf} · {fmtNum(s.shops)}개 매장 · {fmtNum(s.styles)}개 스타일{!r.applied?.includeVirtual && d.virtualRows ? ` · 행사 · 가상 매장 ${fmtNum(d.virtualRows)}건 제외` : ''}</div>
          </section>
          <section className="card stock-aging-buckets">
            <div className="stock-bars">
              <b>재고일수 구간 (매장 × 스타일 수)</b>
              {d.classes.map((c) => (
                <div key={c.key} className="stock-bar-row">
                  <span className="stock-bar-name">{c.name}</span>
                  <span className="stock-bar"><i className={c.key === 'out' || c.key === 'c7' ? 'fail' : c.key === 'c30' || c.key === 'c90' ? 'done' : 'etc'} style={{ width: `${(c.rows / cmax) * 100}%` }} /></span>
                  <b className="num">{fmtNum(c.rows)} · 재고 {fmtNum(c.stock)}</b>
                </div>
              ))}
              <div className="stock-legend"><i className="fail" /> 품절 위험 <i className="done" /> 적정 <i className="etc" /> 과다</div>
            </div>
          </section>
          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="재고 회전 보기">
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>매장별 ({fmtNum(d.shops.length)})</button>
                <button className={view === 'teams' ? 'on' : ''} onClick={() => setView('teams')}>팀별</button>
                <button className={view === 'styles' ? 'on' : ''} onClick={() => setView('styles')}>스타일별 ({fmtNum(d.stylesTotal)})</button>
                <button className={view === 'short' ? 'on' : ''} onClick={() => setView('short')}>품절 위험 ({fmtNum(s.shortRows)})</button>
                <button className={view === 'over' ? 'on' : ''} onClick={() => setView('over')}>과다 ({fmtNum(s.overRows)})</button>
              </div>
              {view !== 'teams' && <SearchBox q={q} setQ={setQ} placeholder="매장 · 품번" label="재고 회전 검색" />}
              {(view === 'short' || view === 'over') && shop && <button className="chip active" onClick={() => setShop(null)}>{shop} <X size={12} /></button>}
              {view === 'shops' && <span className="muted small">매장을 누르면 그 매장 과다 재고</span>}
            </div>
            {view === 'shops' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="재고 회전 매장별">
                    <thead><tr><th>매장</th><th className="num">재고</th><th className="num">재고 금액</th><th className="num">기간 판매</th><th className="num">일평균</th>
                      <th className="num">재고일수</th><th className="num">판매율</th><th className="num">품절 위험</th><th className="num">과다</th><th className="num">과다 재고</th></tr></thead>
                    <tbody>
                      {pgShops.slice.map((g) => (
                        <tr key={g.shopId} className={`clickable ${g.cover == null || g.cover >= 180 ? 'row-short' : ''}`} onClick={() => { setShop(g.shopId); setView('over') }}>
                          <td><span className="mono">{g.shopId}</span> {g.shopNm}<div className="muted small">{g.team}</div></td>
                          <td className="num">{fmtNum(g.stock)}</td><td className="num">{won(g.amt)}</td><td className="num">{fmtNum(g.sales)}</td><td className="num">{g.daily}</td>
                          <td className="num"><b>{days(g.cover)}</b></td><td className="num">{pctv(g.sellThru)}</td><td className="num">{g.short || '-'}</td>
                          <td className="num">{g.over || '-'}</td><td className="num">{fmtNum(g.overStock)}</td>
                        </tr>
                      ))}
                      {!shops.length && <tr><td colSpan={10} className="empty">매장이 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgShops} label="곳" />
              </>
            )}
            {view === 'teams' && (
              <div className="table-wrap">
                <table className="table stock-table" aria-label="재고 회전 팀별">
                  <thead><tr><th>팀</th><th className="num">매장</th><th className="num">재고</th><th className="num">기간 판매</th><th className="num">재고일수</th><th className="num">판매율</th>
                    <th className="num">품절 위험</th><th className="num">과다</th><th className="num">과다 재고</th></tr></thead>
                  <tbody>
                    {d.teams.map((t) => (
                      <tr key={t.team}><td>{t.team}</td><td className="num">{t.shops}</td><td className="num">{fmtNum(t.stock)}</td><td className="num">{fmtNum(t.sales)}</td>
                        <td className="num"><b>{days(t.cover)}</b></td><td className="num">{pctv(t.sellThru)}</td><td className="num">{fmtNum(t.short)}</td>
                        <td className="num">{fmtNum(t.over)}</td><td className="num">{fmtNum(t.overStock)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {view === 'styles' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="재고 회전 스타일별">
                    <thead><tr><th>품번</th><th>기획 · 시즌</th><th className="num">매장 재고</th><th className="num">기간 판매</th><th className="num">일평균</th><th className="num">재고일수</th>
                      <th className="num">판매율</th><th className="num">매장 수</th><th className="num">품절 위험 매장</th><th className="num">과다 매장</th></tr></thead>
                    <tbody>
                      {pgStyles.slice.map((g) => (
                        <tr key={g.prdtCd} className={g.short >= 3 ? 'row-short' : ''}>
                          <td><b className="mono">{g.prdtCd}</b></td><td className="muted">{g.planYy} {g.sesnNm}</td><td className="num">{fmtNum(g.stock)}</td>
                          <td className="num">{fmtNum(g.sales)}</td><td className="num">{g.daily}</td><td className="num"><b>{days(g.cover)}</b></td><td className="num">{pctv(g.sellThru)}</td>
                          <td className="num">{g.shops}</td><td className="num">{g.short || '-'}</td><td className="num">{g.over || '-'}</td>
                        </tr>
                      ))}
                      {!styles.length && <tr><td colSpan={10} className="empty">스타일이 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgStyles} label="개" />
              </>
            )}
            {view === 'short' && detailTable(pgShort, '재고 회전 품절 위험', '품절 위험 매장 × 스타일이 없습니다.')}
            {view === 'over' && detailTable(pgOver, '재고 회전 과다', '과다 재고가 없습니다.')}
          </section>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 초도 배분 적중률
export function InitialTab({ opts }: { opts: StockOptions }) {
  const init: InitCond = { brand: opts.brand, dateFrom: '', dateTo: '', window: 14, planYy: [], seasons: [], includeVirtual: false, maturedOnly: true }
  const [cond, setCond] = useState<InitCond>(init)
  const r = useRun<InitCond, InitReport>((c, refresh, signal) => stockApi.initial(c, refresh, signal))
  const [view, setView] = useState<'products' | 'shops' | 'types'>('products')
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [prod, setProd] = useState<InitProduct | null>(null)
  useEffect(() => r.run(init), []) // eslint-disable-line react-hooks/exhaustive-deps
  const d = r.data
  const dirty = !!r.applied && initQuery(r.applied) !== initQuery(cond)
  const prods = useMemo(() => (d?.products ?? []).filter((p) => hit(q, [p.prdtCd, p.styleNm])), [d, q])
  const shops = useMemo(() => (d?.shops ?? []).filter((g) => hit(q, [g.shopId, g.shopNm, g.team])), [d, q])
  const pgProds = usePaged(prods)
  const pgShops = usePaged(shops)
  const s = d?.summary
  const exportXlsx = async () => {
    if (!r.applied) return
    setBusy(true)
    try { await stockApi.initialExport(r.applied) } catch (e) { r.setError(errText(e)) } finally { setBusy(false) }
  }
  const dateFrom = cond.dateFrom || d?.from || ''
  const dateTo = cond.dateTo || d?.to || ''
  return (
    <div className="stack">
      <section className="card sale-filter">
        <div className="sale-filter-row">
          <div className="toolbar-title"><PackageCheck size={17} /> 초도 배분 적중률 <span className="muted small">(초도 배분 대비 출고예정일부터 판매)</span></div>
          <div className="date-range" title="초도 배분 의뢰일 (최대 92일)">
            <span className="date-range-label">초도 배분</span>
            <input type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => setCond({ ...cond, dateFrom: e.target.value, dateTo: dateTo })} aria-label="초도 배분 시작" />
            <span className="muted">~</span>
            <input type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => setCond({ ...cond, dateTo: e.target.value, dateFrom: dateFrom })} aria-label="초도 배분 끝" />
          </div>
          <div className="seg" role="group" aria-label="판매 확인 기간">
            {[7, 14, 28].map((n) => <button key={n} className={cond.window === n ? 'on' : ''} onClick={() => setCond({ ...cond, window: n })}>{n}일 판매</button>)}
          </div>
          <div className="toolbar-actions">
            <button className="btn primary" onClick={() => r.run(cond)} disabled={r.loading}>{r.loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 조회{dirty ? ' *' : ''}</button>
            <button className="btn ghost" onClick={() => r.run(cond, true)} disabled={r.loading}><RefreshCw size={15} /> 새로 계산</button>
            <button className="btn success" onClick={exportXlsx} disabled={!d || busy || dirty}>{busy ? <Loader2 size={15} className="spin" /> : <Download size={15} />} 엑셀</button>
          </div>
        </div>
        <div className="sale-filter-row">
          <span className="filter-label">기획년도</span>
          <Chips items={opts.planYears.map((y) => ({ code: y, name: y }))} value={cond.planYy} onChange={(planYy) => setCond({ ...cond, planYy })} empty="비우면 전체" />
          <span className="filter-label">시즌</span>
          <Chips items={opts.seasons} value={cond.seasons} onChange={(seasons) => setCond({ ...cond, seasons })} empty="비우면 전체" />
          <label className="check-label" title="출고예정일부터 판매 확인 기간이 아직 다 지나지 않은 배분은 판매가 덜 쌓여 낮게 나옵니다">
            <input type="checkbox" checked={cond.maturedOnly} onChange={(e) => setCond({ ...cond, maturedOnly: e.target.checked })} /> 판매 기간이 다 지난 배분만</label>
          <label className="check-label"><input type="checkbox" checked={cond.includeVirtual} onChange={(e) => setCond({ ...cond, includeVirtual: e.target.checked })} /> 행사 · 가상 매장 포함</label>
        </div>
      </section>
      {r.error && <div className="alert error">{r.error}</div>}
      {r.loading && <section className="card"><Busy sec={r.sec} text="초도 배분과 판매를 읽는 중…" /></section>}
      {d && s && (
        <>
          <section className="summary-pills">
            <div className="pill strong"><span>적중률</span><b>{pctv(s.overlap)}</b><span className="muted">판단 {fmtNum(s.judged)}개 상품 (판매 {s.minSold}장 이상)</span></div>
            <div className="pill"><span>판매율 ({d.window}일)</span><b>{pctv(s.sellThru)}</b><span className="muted">배분 {fmtNum(s.alloc)} · 판매 {fmtNum(s.sold)}장</span></div>
            <div className="pill warn-pill"><span>무판매</span><b>{pct2(s.zero, s.rows)}</b><span className="muted">{fmtNum(s.zero)} / {fmtNum(s.rows)} 상품 × 매장</span></div>
            <div className="pill"><span>소진 (더 받았어야)</span><b>{fmtNum(s.soldOut)}</b><span className="muted">상품 × 매장</span></div>
            <div className="pill"><span>적중률 50% 미만</span><b>{fmtNum(s.lowOverlap)}개 상품</b></div>
            <div className="pill hint-pill">{d.brandNm} · 초도 배분 {d.from} ~ {d.to} · {fmtNum(s.products)}개 상품 · {fmtNum(s.shops)}개 매장 · {d.asOf} 기준
              {d.maturedOnly && d.immature ? ` · 진행 중 ${fmtNum(d.immature)}건 제외` : ''}</div>
          </section>
          <div className="alert info"><Info size={14} /> <span><b>적중률</b> = 매장별 (배분 비중, 판매 비중) 중 작은 값의 합 — 판매가 많이 난 매장에 그만큼 배분했으면 100%. 판매율은 시즌 초 · 날씨 영향을 받으니 적중률과 함께 보세요. 상품을 누르면 매장별 배분 · 판매 비중.</span></div>
          <section className="card grid-card">
            <div className="stock-subbar">
              <div className="seg" role="tablist" aria-label="초도 배분 보기">
                <button className={view === 'products' ? 'on' : ''} onClick={() => setView('products')}>상품별 ({fmtNum(d.products.length)})</button>
                <button className={view === 'shops' ? 'on' : ''} onClick={() => setView('shops')}>매장별 ({fmtNum(d.shops.length)})</button>
                <button className={view === 'types' ? 'on' : ''} onClick={() => setView('types')}>유통형태별</button>
              </div>
              {view !== 'types' && <SearchBox q={q} setQ={setQ} placeholder={view === 'shops' ? '매장' : '품번'} label="초도 배분 검색" />}
            </div>
            {view === 'products' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="초도 배분 상품별">
                    <thead><tr><th>품번 · 칼라</th><th>기획 · 시즌</th><th>첫 출고예정</th><th className="num">매장</th><th className="num">초도 배분</th><th className="num">판매</th>
                      <th className="num">판매율</th><th className="num">무판매 매장</th><th className="num">소진 매장</th><th className="num">적중률</th></tr></thead>
                    <tbody>
                      {pgProds.slice.map((p) => (
                        <tr key={`${p.prdtCd}-${p.colorCd}`} className={`clickable ${p.overlap != null && p.overlap < 30 ? 'row-short' : ''}`} onClick={() => setProd(p)}>
                          <td><b className="mono">{p.prdtCd}</b> <span className="muted">{p.colorCd}</span></td><td className="muted">{p.planYy} {p.sesnNm}</td>
                          <td className="muted">{p.start}</td><td className="num">{p.shops}</td><td className="num">{fmtNum(p.alloc)}</td><td className="num">{fmtNum(p.sold)}</td>
                          <td className="num">{pctv(p.sellThru)}</td><td className="num">{p.zero}</td><td className="num">{p.soldOut || '-'}</td>
                          <td className="num"><b>{p.overlap != null ? `${p.overlap}%` : <span className="muted small">판매 적음</span>}</b></td>
                        </tr>
                      ))}
                      {!prods.length && <tr><td colSpan={10} className="empty">초도 배분이 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgProds} label="개" />
              </>
            )}
            {view === 'shops' && (
              <>
                <div className="table-wrap tall">
                  <table className="table stock-table" aria-label="초도 배분 매장별">
                    <thead><tr><th>매장</th><th>유통형태</th><th className="num">상품</th><th className="num">초도 배분</th><th className="num">판매</th><th className="num">판매율</th>
                      <th className="num">무판매 상품</th><th className="num">소진 상품</th></tr></thead>
                    <tbody>
                      {pgShops.slice.map((g) => (
                        <tr key={g.shopId} className={g.sellThru != null && g.sellThru < (s.sellThru ?? 0) / 2 ? 'row-short' : ''}>
                          <td><span className="mono">{g.shopId}</span> {g.shopNm}<div className="muted small">{g.team}</div></td><td>{g.shopType}</td>
                          <td className="num">{g.products}</td><td className="num">{fmtNum(g.alloc)}</td><td className="num">{fmtNum(g.sold)}</td><td className="num"><b>{pctv(g.sellThru)}</b></td>
                          <td className="num">{g.zero}</td><td className="num">{g.soldOut || '-'}</td>
                        </tr>
                      ))}
                      {!shops.length && <tr><td colSpan={8} className="empty">매장이 없습니다.</td></tr>}
                    </tbody>
                  </table>
                </div>
                <Pager pg={pgShops} label="곳" />
              </>
            )}
            {view === 'types' && (
              <div className="table-wrap">
                <table className="table stock-table" aria-label="초도 배분 유통형태별">
                  <thead><tr><th>유통형태</th><th className="num">초도 배분</th><th className="num">판매</th><th className="num">판매율</th><th className="num">무판매</th><th className="num">소진</th></tr></thead>
                  <tbody>{d.types.map((t) => <tr key={t.shopType}><td>{t.shopType}</td><td className="num">{fmtNum(t.alloc)}</td><td className="num">{fmtNum(t.sold)}</td>
                    <td className="num"><b>{pctv(t.sellThru)}</b></td><td className="num">{fmtNum(t.zero)}</td><td className="num">{fmtNum(t.soldOut)}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
      {prod && r.applied && <InitialShopsModal cond={r.applied} prod={prod} onClose={() => setProd(null)} />}
    </div>
  )
}

const pct2 = (a: number, b: number) => (b ? `${Math.round((a * 1000) / b) / 10}%` : '-')

function InitialShopsModal({ cond, prod, onClose }: { cond: InitCond; prod: InitProduct; onClose: () => void }) {
  const [rows, setRows] = useState<InitProductShop[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { stockApi.initialShops(cond, prod.prdtCd, prod.colorCd).then((x) => setRows(x.rows)).catch((e) => setError(errText(e))) }, [cond, prod])
  const pg = usePaged(rows ?? [])
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card help-modal stock-write-modal wide" role="dialog" aria-label="초도 배분 매장별">
        <div className="modal-head">
          <h3><PackageCheck size={17} /> {prod.prdtCd} {prod.colorCd} · 매장별 초도 배분 · 판매</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        <div className="muted small">배분 {fmtNum(prod.alloc)}장 · 판매 {fmtNum(prod.sold)}장 · 판매율 {pctv(prod.sellThru)} · 적중률 {prod.overlap != null ? `${prod.overlap}%` : '판매 적어 판단 보류'} — 판매 비중이 배분 비중보다 큰 매장은 더 받았어야 한 매장입니다.</div>
        {error && <div className="alert error">{error}</div>}
        {!rows && !error && <Busy sec={0} text="불러오는 중…" />}
        {rows && (
          <>
            <div className="table-wrap tall">
              <table className="table stock-table" aria-label="초도 배분 매장별 비중">
                <thead><tr><th>매장</th><th>유통형태</th><th className="num">배분</th><th className="num">판매</th><th className="num">판매율</th><th className="num">배분 비중</th><th className="num">판매 비중</th><th>출고예정</th></tr></thead>
                <tbody>
                  {pg.slice.map((x) => (
                    <tr key={x.shopId} className={x.soldShare > x.allocShare * 1.5 && x.sold > 0 ? 'row-short' : ''}>
                      <td><span className="mono">{x.shopId}</span> {x.shopNm}<div className="muted small">{x.team}</div></td><td>{x.shopType}</td>
                      <td className="num">{x.alloc}</td><td className="num">{x.sold}</td><td className="num">{pctv(x.sellThru)}</td>
                      <td className="num">{x.allocShare}%</td><td className="num"><b>{x.soldShare}%</b></td><td className="muted">{x.start}{x.matured ? '' : ' (진행 중)'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager pg={pg} label="곳" />
          </>
        )}
      </div>
    </div>
  )
}
