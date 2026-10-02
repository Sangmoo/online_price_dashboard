import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Loader2, Save, Search, Wand2 } from 'lucide-react'
import { api, type MallShopList, type MallShopRow } from '../api'
import { fmtNum } from '../format'

type Edit = { shopId: string; useYn: 'Y' | 'N'; rmk: string }
type Filter = 'all' | 'unmapped' | 'mapped'
type Cond = { days: number; filter: Filter; q: string }
const DEFAULT_COND: Cond = { days: 7, filter: 'all', q: '' }
const PERIODS = [7, 31, 90]
const keyOf = (r: { mallNm: string; sellNo: string; brdCd: string }) => `${r.mallNm}\u0001${r.sellNo}\u0001${r.brdCd}`
const d8 = (v: string | null) => (v ? `${v.slice(4, 6)}-${v.slice(6, 8)}` : '-')

/** 온라인 가격 > 판매처 매장 연결: 사이트·판매자번호·브랜드별 매장코드 매핑 (수집 프로그램이 T_SELECT_ONLINE_MNG_R.SHOP_ID 를 채운다) */
export default function MallShopView() {
  // 조회 조건: 화면에서 고르는 값(draft)과 [조회]로 적용한 값(applied)을 나눈다 — 메뉴를 열면 최근 7일로 한 번 조회
  const [draft, setDraft] = useState<Cond>(DEFAULT_COND)
  const [applied, setApplied] = useState<Cond>(DEFAULT_COND)
  const { days, filter, q } = applied
  const [data, setData] = useState<MallShopList | null>(null)
  const [shops, setShops] = useState<{ shopId: string; shopNm: string | null; brands: string[] }[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [edits, setEdits] = useState<Record<string, Edit>>({})
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api.mallShops
      .list(days)
      .then((d) => {
        setData(d)
        setEdits({})
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [days])
  useEffect(load, [load])
  useEffect(() => {
    api.mallShops.shops().then((d) => setShops(d.shops)).catch(() => undefined)
  }, [])

  const shopName = useMemo(() => new Map(shops.map((s) => [s.shopId, s.shopNm ?? ''])), [shops])
  const current = (r: MallShopRow): Edit =>
    edits[keyOf(r)] ?? { shopId: r.shopId ?? '', useYn: r.useYn === 'N' ? 'N' : 'Y', rmk: r.mapRmk ?? '' }
  const changed = (r: MallShopRow) => {
    const e = edits[keyOf(r)]
    return !!e && (e.shopId !== (r.shopId ?? '') || e.useYn !== (r.useYn === 'N' ? 'N' : 'Y') || e.rmk !== (r.mapRmk ?? ''))
  }
  const setEdit = (r: MallShopRow, patch: Partial<Edit>) => setEdits((cur) => ({ ...cur, [keyOf(r)]: { ...current(r), ...patch } }))

  const rows = useMemo(() => {
    if (!data) return []
    const s = q.trim().toUpperCase()
    return data.rows.filter((r) => {
      const mapped = !!(current(r).shopId || r.starShopId)
      if (filter === 'unmapped' && mapped) return false
      if (filter === 'mapped' && !mapped) return false
      if (!s) return true
      return [r.mallNm, r.sellNo, r.rmk, r.shopId, r.shopNm, current(r).shopId].some((v) => (v ?? '').toUpperCase().includes(s))
    })
  }, [data, q, filter, edits])
  const pending = data ? data.rows.filter(changed) : []
  const search = () => {
    if (pending.length && !confirm(`저장하지 않은 변경 ${pending.length}건이 있습니다. 조회하면 사라집니다. 계속할까요?`)) return
    setNotice(null)
    if (draft.days === applied.days) {
      setApplied({ ...draft })
      load() // 기간이 같아도 [조회]는 최신 수집을 다시 읽는다
    } else setApplied({ ...draft }) // 기간이 바뀌면 load 가 다시 만들어져 자동으로 읽는다
  }
  const set = (patch: Partial<Cond>) => setDraft((d) => ({ ...d, ...patch }))
  const dirtyCond = draft.days !== applied.days || draft.filter !== applied.filter || draft.q !== applied.q
  // 사이트 · 판매자번호 묶음 (표에서 같은 사이트·판매자번호는 한 칸으로 합친다)
  const spans = useMemo(() => {
    // 각 행에서 시작하는 묶음의 행 수 (이어지는 행은 0 → 칸을 그리지 않음)
    const site = rows.map(() => 0), seller = rows.map(() => 0)
    let si = 0, se = 0
    rows.forEach((r, i) => {
      if (i === 0 || rows[i - 1].mallNm !== r.mallNm) si = i
      if (i === 0 || rows[i - 1].mallNm !== r.mallNm || rows[i - 1].sellNo !== r.sellNo) se = i
      site[si] += 1
      seller[se] += 1
    })
    return { site, seller }
  }, [rows])
  const badCodes = pending.filter((r) => {
    const id = current(r).shopId.trim().toUpperCase()
    return id && shops.length > 0 && !shopName.has(id)
  })

  const save = async () => {
    setSaving(true)
    setNotice(null)
    try {
      const items = pending.map((r) => {
        const e = current(r)
        return { mallNm: r.mallNm, sellNo: r.sellNo, brdCd: r.brdCd, shopId: e.shopId.trim().toUpperCase(), useYn: e.useYn, rmk: e.rmk.trim() }
      })
      const res = await api.mallShops.save(items)
      setNotice(`저장했습니다 · 등록·수정 ${res.saved}건 · 해제 ${res.deleted}건`)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const applyAllSuggestions = () => {
    if (!data) return
    const next = { ...edits }
    for (const r of rows) {
      if (!current(r).shopId && r.suggestions.length === 1) next[keyOf(r)] = { ...current(r), shopId: r.suggestions[0].shopId }
    }
    setEdits(next)
  }
  const suggestible = rows.filter((r) => !current(r).shopId && r.suggestions.length === 1).length
  const sm = data?.summary

  return (
    <div className="stack mall-shop">
      <section className="card toolbar">
        <div className="seg" role="group" aria-label="기간">
          {PERIODS.map((p) => <button key={p} className={draft.days === p ? 'on' : ''} onClick={() => set({ days: p })}>최근 {p}일</button>)}
        </div>
        <div className="seg" role="group" aria-label="연결 상태">
          {([['all', '전체'], ['unmapped', '미연결'], ['mapped', '연결됨']] as [Filter, string][]).map(([k, l]) => (
            <button key={k} className={draft.filter === k ? 'on' : ''} onClick={() => set({ filter: k })}>{l}</button>
          ))}
        </div>
        <label className="search-box">
          <Search size={15} />
          <input className="input" placeholder="사이트 · 판매자번호 · 매장정보 · 매장코드" value={draft.q} aria-label="검색"
            onChange={(e) => set({ q: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && search()} />
        </label>
        <button className={`btn ${dirtyCond ? 'primary' : 'ghost'}`} onClick={search} disabled={loading}>
          {loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} 조회
        </button>
        <div className="grow" />
        {suggestible > 0 && data?.ready && (
          <button className="btn ghost" onClick={applyAllSuggestions} title="후보가 하나뿐인 미연결 행에 그 매장을 넣습니다 (저장 전 확인)">
            <Wand2 size={15} /> 후보 {suggestible}건 채우기
          </button>
        )}
        <button className="btn primary" disabled={!pending.length || saving || badCodes.length > 0 || !data?.ready} onClick={save}>
          {saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} 변경 {pending.length}건 저장
        </button>
      </section>

      {data && !data.ready && (
        <div className="alert warn-inline">
          <AlertTriangle size={14} /> 매핑 테이블(T_SELECT_ONLINE_MALL_SHOP)이 아직 없습니다. 관리자가 <span className="mono">db/create_online_mall_shop.sql</span> 을 실행하면 저장할 수 있습니다.
          지금은 수집 현황만 볼 수 있습니다.
        </div>
      )}
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert ok-inline">{notice}</div>}
      {badCodes.length > 0 && <div className="alert error">매장 목록에 없는 매장코드: {badCodes.map((r) => current(r).shopId).join(', ')}</div>}

      {sm && (
        <div className="summary-pills">
          <div className="pill strong" title="판매자번호가 있는 수집 행만 (판매자번호가 없는 오픈마켓 행은 매장 하나로 이을 수 없어 제외)">
            <span>최근 {data!.days}일 판매처</span><b>{fmtNum(sm.sellers)}</b><span className="muted">사이트 {fmtNum(sm.malls)} · 브랜드별 {fmtNum(sm.combos)}</span></div>
          <div className="pill"><span>연결</span><b>{fmtNum(sm.mapped)}</b><span className="muted">미연결 {fmtNum(sm.unmapped)}</span></div>
          <div className="pill" title="연결된 판매처의 수집 행 비중 (수집 시 매장코드가 들어갈 행)"><span>수집 행 연결률</span><b>{sm.rowsMappedPct ?? 0}%</b>
            <span className="muted">{fmtNum(sm.rowsMapped)} / {fmtNum(sm.rowsTotal)}</span></div>
          <div className="pill" title="수집 테이블 T_SELECT_ONLINE_MNG_R.SHOP_ID 에 실제로 값이 들어간 행"><span>수집 테이블 반영</span><b>{fmtNum(sm.shopFilled)}행</b></div>
        </div>
      )}

      <section className="card panel">
        {!data && loading && <div className="trend-loading"><Loader2 size={18} className="spin" /> 수집 현황을 읽는 중… (최근 {days}일)</div>}
        {data && (
          <div className="table-wrap mall-table">
            <table className="table">
              <thead>
                <tr>
                  <th>사이트</th><th>판매자번호</th><th>브랜드</th><th className="num">수집 행</th><th className="num">상품</th><th>마지막</th>
                  <th>매장정보 예시</th><th>매장코드</th><th>사용</th><th>비고</th><th className="num">반영</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const e = current(r)
                  const id = e.shopId.trim().toUpperCase()
                  const nm = id ? shopName.get(id) ?? (id === r.shopId ? r.shopNm : null) : null
                  return (
                    <tr key={keyOf(r)} className={`${changed(r) ? 'changed-row' : ''} ${spans.site[i] ? 'group-start' : ''}`}>
                      {spans.site[i] > 0 && <td className="strong group-cell" rowSpan={spans.site[i]} title={r.mallNm}>{r.mallNm}</td>}
                      {spans.seller[i] > 0 && (
                        <td className="mono small group-cell" rowSpan={spans.seller[i]}>{r.sellNo === '-' ? <span className="muted">(없음)</span> : r.sellNo}</td>
                      )}
                      <td className="small">{r.brand}</td>
                      <td className="num">{fmtNum(r.rows)}</td>
                      <td className="num">{fmtNum(r.products)}</td>
                      <td className="small muted">{r.seen ? d8(r.lastDt) : '수집 없음'}</td>
                      <td className="small ellipsis rmk-cell" title={r.rmk ? `${r.rmk} (이 조합 수집 행의 ${r.rmkShare}%)` : '대표할 매장정보 없음'}>{r.rmk ?? '-'}</td>
                      <td className="shop-cell">
                        <input className="input small mono" list="mall-shop-options" maxLength={6} value={e.shopId} disabled={!data.ready}
                          placeholder={r.starShopId ? `${r.starShopId}(공통)` : '매장코드'} aria-label={`${r.mallNm} ${r.brand} 매장코드`}
                          onChange={(ev) => setEdit(r, { shopId: ev.target.value.toUpperCase() })} />
                        <span className="small">
                          {nm ? <span className="shop-nm">{nm}</span>
                            : id ? <span className="up">매장 없음</span>
                              : r.starShopId ? <span className="muted">공통 {r.starShopNm ?? r.starShopId}</span>
                                : r.suggestions.map((s) => (
                                  <button key={s.shopId} className="chip suggest" disabled={!data.ready} onClick={() => setEdit(r, { shopId: s.shopId })}
                                    title={`${s.shopNm} (${s.brand}) 로 연결`}>{s.shopId} {s.shopNm}</button>
                                ))}
                        </span>
                      </td>
                      <td>
                        <input type="checkbox" checked={e.useYn === 'Y'} disabled={!data.ready || !e.shopId} aria-label="사용"
                          onChange={(ev) => setEdit(r, { useYn: ev.target.checked ? 'Y' : 'N' })} />
                      </td>
                      <td><input className="input small" value={e.rmk} maxLength={150} disabled={!data.ready || !e.shopId} aria-label="비고"
                        onChange={(ev) => setEdit(r, { rmk: ev.target.value })} /></td>
                      <td className="num small" title="수집 테이블 SHOP_ID 가 채워진 행 / 수집 행">{r.rows ? `${Math.round((r.shopFilled * 100) / r.rows)}%` : '-'}</td>
                    </tr>
                  )
                })}
                {rows.length === 0 && <tr><td colSpan={11} className="empty">해당하는 판매처가 없습니다.</td></tr>}
              </tbody>
            </table>
            <datalist id="mall-shop-options">
              {shops.map((s) => <option key={s.shopId} value={s.shopId}>{`${s.shopNm ?? ''} · ${s.brands.join('/')}`}</option>)}
            </datalist>
          </div>
        )}
        <div className="muted small">
          브랜드 = 품번 첫 글자(S 쉬즈미스 · T 리스트 · A 시스티나). 매장코드를 비우고 저장하면 연결이 해제됩니다. 수집 프로그램은 브랜드 행을 먼저, 없으면
          '모든 브랜드' 행을 씁니다. 판매자번호가 있는 수집 행만 보여 줍니다. 매장정보 예시는 판매자번호마다 조회 기간(최대 31일) RMK 중
          같은 값이 그 판매자 수집 행의 절반 이상일 때만 표시합니다(모델번호 부분은 뗌). 매장 후보는 매장정보 예시에서 먼저, 없으면 사이트명에서
          같은 브랜드 매장을 찾습니다(체인·지역 순서 무관, 예: 광주신세계 → 신세계광주).
        </div>
      </section>
    </div>
  )
}
