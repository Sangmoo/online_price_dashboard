import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardList, Loader2, Send, Trash2, X } from 'lucide-react'
import { ApiError } from '../api'
import { fmtNum } from '../format'
import {
  stockApi,
  type AllocCond, type AllocRegistered, type AskSeqns, type RtRegistered, type RtWriteSource, type Skipped, type WritePreview,
} from '../stockApi'

// 재고 재배치 추천 > ERP 등록 · 삭제 (관리자). 본사지시 RT 는 지시(미확정)만, 배분은 출고의뢰(미확정)만 넣는다.

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))
const iso = (d8: string) => `${d8.slice(0, 4)}-${d8.slice(4, 6)}-${d8.slice(6, 8)}`
const addDaysIso = (isoDate: string, n: number) => {
  const d = new Date(`${isoDate}T00:00:00`)
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const fmt14 = (v: string | null | undefined) => (v && v.length >= 12 ? `${v.slice(4, 6)}-${v.slice(6, 8)} ${v.slice(8, 10)}:${v.slice(10, 12)}` : v ?? '')

function Modal({ title, icon, onClose, children, wide }: { title: string; icon: React.ReactNode; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal card help-modal stock-write-modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h3>{icon} {title}</h3>
          <button className="icon-btn" onClick={onClose} title="닫기"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

function SkippedList({ list, label }: { list: Skipped[]; label: (k: string[]) => string }) {
  if (!list.length) return null
  const by: Record<string, number> = {}
  list.forEach((s) => { by[s.reason] = (by[s.reason] ?? 0) + 1 })
  return (
    <details className="stock-skipped">
      <summary><AlertTriangle size={13} /> 제외 {fmtNum(list.length)}건 — {Object.entries(by).map(([r, n]) => `${r} ${n}`).join(' · ')}</summary>
      <ul>{list.slice(0, 200).map((s, i) => <li key={i}><span className="mono">{label(s.key)}</span> · {s.reason}</li>)}</ul>
    </details>
  )
}

// ---------------------------------------------------------------- 매장 간 RT → 본사지시 RT 지시
type RtPlanRow = { fromShopId: string; fromShopNm?: string | null; toShopId: string; toShopNm?: string | null; qty: number }

/** 지시 전 한눈에: 보내는 매장 · 받는 매장별 건수 · 장수 (많은 순) */
function RtShopSummary({ rows }: { rows?: RtPlanRow[] }) {
  const [side, setSide] = useState<'from' | 'to'>('from')
  if (!rows?.length) return null
  const m = new Map<string, { id: string; nm: string; rows: number; qty: number; other: Set<string> }>()
  for (const r of rows) {
    const id = side === 'from' ? r.fromShopId : r.toShopId
    const x = m.get(id) ?? { id, nm: (side === 'from' ? r.fromShopNm : r.toShopNm) ?? '', rows: 0, qty: 0, other: new Set<string>() }
    x.rows += 1
    x.qty += r.qty
    x.other.add(side === 'from' ? r.toShopId : r.fromShopId)
    m.set(id, x)
  }
  const list = [...m.values()].sort((a, b) => b.qty - a.qty)
  return (
    <div className="stock-reg-shops">
      <div className="seg">
        <button className={side === 'from' ? 'on' : ''} onClick={() => setSide('from')}>보내는 매장별</button>
        <button className={side === 'to' ? 'on' : ''} onClick={() => setSide('to')}>받는 매장별</button>
      </div>
      <div className="table-wrap">
        <table className="table stock-table" aria-label="매장별 지시 요약">
          <thead><tr><th>{side === 'from' ? '보내는 매장' : '받는 매장'}</th><th className="num">건수</th><th className="num">장수</th><th className="num">{side === 'from' ? '받는 매장 수' : '보내는 매장 수'}</th></tr></thead>
          <tbody>
            {list.map((x) => (
              <tr key={x.id}><td><span className="mono">{x.id}</span> {x.nm}</td><td className="num">{fmtNum(x.rows)}</td><td className="num"><b>{fmtNum(x.qty)}</b></td><td className="num">{fmtNum(x.other.size)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function RtRegisterModal({ source, keys, today, onClose, onDone }: {
  source: RtWriteSource; keys: string[][]; today: string; onClose: () => void; onDone: (msg: string) => void
}) {
  const [pv, setPv] = useState<WritePreview | null>(null)
  const [indcDt, setIndcDt] = useState(iso(today))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { source.preview(keys).then(setPv).catch((e) => setError(errText(e))) }, [source, keys])
  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const r = await source.register(keys, indcDt)
      onDone(`본사지시 RT ${fmtNum(r.qty)}장(${fmtNum(r.count)}건)을 지시 · 확정했습니다 · 지시번호 ${r.firstId} ~ ${r.lastId}${r.skipped.length ? ` · 제외 ${r.skipped.length}건` : ''} — 매장이 수락 · 거부합니다.`)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title="본사지시 RT 지시 등록" icon={<Send size={17} />} onClose={onClose}>
      <div className="alert info">
        <span>ERP <b>본사지시 RT</b> 를 지시하고 <b>로그인한 사번으로 확정</b>합니다 (T_INDC_RT 1장에 1행 → 매장 이동요청 T_SHOP_REQ <b>매장 미처리</b>).
        매장이 수락 · 거부합니다. 보내는 매장 재고는 지금 기준으로 다시 확인해 모자라면 뺍니다.</span>
      </div>
      {!pv && !error && <div className="stock-loading"><Loader2 size={16} className="spin" /> 지금 재고로 확인하는 중…</div>}
      {pv && (
        <>
          <div className="summary-pills">
            <div className="pill strong"><span>지시</span><b>{fmtNum(pv.count)}건 · {fmtNum(pv.qty)}장</b></div>
            <div className="pill"><span>보내는 매장</span><b>{fmtNum(Number(pv.senders))}곳</b></div>
            <div className="pill"><span>받는 매장</span><b>{fmtNum(Number(pv.receivers))}곳</b></div>
            <div className="pill hint-pill">{pv.brandNm} · 추천 {pv.asOf} 기준</div>
          </div>
          <RtShopSummary rows={pv.rows as RtPlanRow[] | undefined} />
          <SkippedList list={pv.skipped} label={(k) => (k.length === 5 ? `${k[0]} ${k[1]}·${k[2]} ${k[3]}→${k[4]}` : k.join(' '))} />
          <label className="field-label">지시일자
            <input type="date" className="input sm" value={indcDt} min={iso(today)} max={addDaysIso(iso(today), 7)} onChange={(e) => setIndcDt(e.target.value)} />
          </label>
        </>
      )}
      {error && <div className="alert error">{error}</div>}
      <div className="modal-foot">
        <button className="btn ghost" onClick={onClose}>취소</button>
        <button className="btn primary" disabled={!pv || !pv.count || busy} onClick={submit}>
          {busy ? <Loader2 size={15} className="spin" /> : <Send size={15} />} {pv ? `${fmtNum(pv.qty)}장 지시` : '지시'}
        </button>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------- 창고 → 매장 배분 → 출고의뢰
export function AllocRegisterModal({ cond, keys, today, onClose, onDone }: {
  cond: AllocCond; keys: string[][]; today: string; onClose: () => void; onDone: (msg: string) => void
}) {
  const [pv, setPv] = useState<WritePreview | null>(null)
  const [askDt, setAskDt] = useState(iso(today))
  const [seqns, setSeqns] = useState<AskSeqns | null>(null)
  const [askSeqn, setAskSeqn] = useState(0)
  const [delvPreDt, setDelvPreDt] = useState(iso(today))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { stockApi.allocPreview(cond, keys).then(setPv).catch((e) => setError(errText(e))) }, [cond, keys])
  useEffect(() => {
    setSeqns(null)
    stockApi.askSeqns(cond.brand, askDt).then((s) => { setSeqns(s); setAskSeqn(s.next) }).catch((e) => setError(errText(e)))
    if (delvPreDt < askDt) setDelvPreDt(askDt)
  }, [cond.brand, askDt]) // eslint-disable-line react-hooks/exhaustive-deps
  const used = seqns?.used.filter((u) => u.seqn === askSeqn) ?? []
  const confirmed = used.some((u) => u.confirmed)
  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const r = await stockApi.allocRegister(cond, keys, askDt, askSeqn, delvPreDt)
      onDone(`배분의뢰 ${r.askDt} ${r.askSeqn}차에 ${fmtNum(r.qty)}장(${fmtNum(r.count)}건 · 매장 ${r.shops}곳)을 넣었습니다${r.skipped.length ? ` · 제외 ${r.skipped.length}건` : ''} — 확정 · 출고지시는 ERP 에서 합니다.`)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title="배분의뢰 등록" icon={<Send size={17} />} onClose={onClose}>
      <div className="alert info">
        <span>ERP <b>출고의뢰</b>(T_DELV_ASK)에 판매분 자동보충과 같은 값(판매분의뢰(자동) · <b>미확정</b>)으로 넣습니다. 의뢰 확정 · 출고지시는 ERP 에서 합니다.
        창고 가용은 지금 기준으로 다시 확인해 모자라면 순위 뒤쪽 매장부터 뺍니다.</span>
      </div>
      {!pv && !error && <div className="stock-loading"><Loader2 size={16} className="spin" /> 지금 창고 재고로 확인하는 중…</div>}
      {pv && (
        <>
          <div className="summary-pills">
            <div className="pill strong"><span>의뢰</span><b>{fmtNum(pv.count)}건 · {fmtNum(pv.qty)}장</b></div>
            <div className="pill"><span>받는 매장</span><b>{fmtNum(Number(pv.shops))}곳</b></div>
            <div className="pill hint-pill">{pv.brandNm} · 창고 {String(pv.wh)} · 추천 {pv.asOf} 기준</div>
          </div>
          <SkippedList list={pv.skipped} label={(k) => (k.length === 4 ? `${k[0]} ${k[1]} ${k[2]}·${k[3]}` : k.join(' '))} />
          <div className="stock-write-fields">
            <label className="field-label">의뢰일자
              <input type="date" className="input sm" value={askDt} min={iso(today)} max={addDaysIso(iso(today), 7)} onChange={(e) => setAskDt(e.target.value)} />
            </label>
            <label className="field-label">의뢰차수
              <input type="number" className="input sm stock-rate" min={1} max={9999} value={askSeqn || ''} onChange={(e) => setAskSeqn(Number(e.target.value))} />
            </label>
            <label className="field-label">출고예정일
              <input type="date" className="input sm" value={delvPreDt} min={askDt} onChange={(e) => setDelvPreDt(e.target.value)} />
            </label>
          </div>
          {seqns && (
            <div className="muted small">
              {askDt} 사용 중인 차수: {seqns.used.length ? seqns.used.map((u) => `${u.seqn}(${u.brandNm}${u.confirmed ? '·확정' : ''})`).join(', ') : '없음'} · 제안 {seqns.next}차
            </div>
          )}
          {confirmed && <div className="alert warn">{askSeqn}차는 이미 확정된 차수라 넣을 수 없습니다.</div>}
          {!confirmed && used.length > 0 && <div className="alert warn">{askSeqn}차는 이미 쓰는 차수입니다 ({used.map((u) => `${u.brandNm} ${u.rows}건`).join(', ')}). 같은 매장 · 상품이 있으면 그 행은 뺍니다.</div>}
        </>
      )}
      {error && <div className="alert error">{error}</div>}
      <div className="modal-foot">
        <button className="btn ghost" onClick={onClose}>취소</button>
        <button className="btn primary" disabled={!pv || !pv.count || busy || !askSeqn || confirmed} onClick={submit}>
          {busy ? <Loader2 size={15} className="spin" /> : <Send size={15} />} {pv ? `${fmtNum(pv.qty)}장 의뢰` : '의뢰'}
        </button>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------- 등록 내역 · 삭제
export function RegisteredModal({ kind, brand, brandNm, today, onClose, onChanged }: {
  kind: 'rt' | 'alloc'; brand: string; brandNm: string; today: string; onClose: () => void; onChanged: () => void
}) {
  const [from, setFrom] = useState(addDaysIso(iso(today), -7))
  const [to, setTo] = useState(addDaysIso(iso(today), 7))
  const [rt, setRt] = useState<RtRegistered | null>(null)
  const [al, setAl] = useState<AllocRegistered | null>(null)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [ask, setAsk] = useState(false)

  const load = () => {
    setLoading(true)
    setError('')
    setSel(new Set())
    const p = kind === 'rt' ? stockApi.rtRegistered(brand, from, to).then(setRt) : stockApi.allocRegistered(brand, from, to).then(setAl)
    p.catch((e) => setError(errText(e))).finally(() => setLoading(false))
  }
  useEffect(load, [kind, brand, from, to]) // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => (kind === 'rt'
    ? (rt?.rows ?? []).map((r) => ({ key: r.id, deletable: r.deletable, cells: r }))
    : (al?.rows ?? []).map((r) => ({ key: `${r.askDt}|${r.askSeqn}|${r.seq}`, deletable: r.deletable, cells: r }))), [kind, rt, al])
  const deletable = rows.filter((r) => r.deletable)
  const allOn = deletable.length > 0 && deletable.every((r) => sel.has(r.key))
  const flip = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })

  const remove = async () => {
    setBusy(true)
    setError('')
    try {
      const keys = [...sel]
      const r = kind === 'rt' ? await stockApi.rtDelete(brand, keys) : await stockApi.allocDelete(brand, keys.map((k) => k.split('|')))
      setMsg(kind === 'rt'
        ? `${fmtNum(r.deleted)}건을 취소했습니다${r.notDeleted ? ` · ${r.notDeleted}건은 그사이 매장이 처리해 취소하지 않았습니다` : ''}.`
        : `${fmtNum(r.deleted)}건을 삭제했습니다${r.notDeleted ? ` · ${r.notDeleted}건은 그사이 확정 · 처리돼 삭제하지 않았습니다` : ''}.`)
      setAsk(false)
      onChanged()
      load()
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title={`${kind === 'rt' ? '본사지시 RT 지시' : '배분의뢰'} 등록 내역 · ${brandNm}`} icon={<ClipboardList size={17} />} onClose={onClose} wide>
      <div className="stock-write-fields">
        <div className="date-range">
          <span className="date-range-label">{kind === 'rt' ? '지시일자' : '의뢰일자'}</span>
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} aria-label="등록 내역 시작" />
          <span className="muted">~</span>
          <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} aria-label="등록 내역 끝" />
        </div>
        <span className="muted small">이 화면에서 등록한 것만 보입니다 · {kind === 'rt' ? '매장이 아직 처리(수락 · 거부)하지 않은 지시' : '확정 · 출고지시 전 의뢰'}만 {kind === 'rt' ? '취소' : '삭제'}할 수 있습니다</span>
        <button className="btn danger" disabled={!sel.size || busy} onClick={() => setAsk(true)}><Trash2 size={15} /> 선택 {kind === 'rt' ? '취소' : '삭제'} ({fmtNum(sel.size)})</button>
      </div>
      {kind === 'rt' && rt && (
        <div className="summary-pills">
          <div className="pill strong"><span>지시</span><b>{fmtNum(rt.total)}장</b></div>
          {rt.byStatus.map((s) => <div key={s.code} className="pill"><span>{s.name}</span><b>{fmtNum(s.qty)}</b></div>)}
        </div>
      )}
      {kind === 'alloc' && al && (
        <div className="summary-pills">
          {al.runs.map((r) => (
            <div key={`${r.askDt}-${r.askSeqn}`} className="pill"><span>{r.askDt} {r.askSeqn}차</span><b>{fmtNum(r.rows)}건 · {fmtNum(r.qty)}장</b>
              <span className="muted">{r.confirmed ? `확정 ${r.confirmed}` : '미확정'} · {r.insUser}</span></div>
          ))}
          {!al.runs.length && <span className="muted small">등록한 의뢰가 없습니다.</span>}
        </div>
      )}
      {msg && <div className="alert info"><CheckCircle2 size={14} /> {msg}</div>}
      {error && <div className="alert error">{error}</div>}
      {ask && (
        <div className="alert warn stock-confirm">
          <AlertTriangle size={15} /> <span>{kind === 'rt'
            ? `선택한 ${fmtNum(sel.size)}건의 매장 이동요청을 ERP 본사지시 취소와 같이 취소합니다(본사지시취소 · 삭제일 표시). 되돌릴 수 없습니다.`
            : `선택한 ${fmtNum(sel.size)}건을 ERP 에서 삭제합니다. 되돌릴 수 없습니다.`} (관리자 변경 이력에는 남습니다)</span>
          <button className="btn danger sm" disabled={busy} onClick={remove}>{busy ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />} {kind === 'rt' ? '취소' : '삭제'}</button>
          <button className="btn ghost sm" onClick={() => setAsk(false)}>그만두기</button>
        </div>
      )}
      {loading && <div className="stock-loading"><Loader2 size={16} className="spin" /> 불러오는 중…</div>}
      {!loading && (
        <div className="table-wrap tall">
          <table className="table stock-table" aria-label="등록 내역">
            <thead>
              <tr>
                <th className="check"><input type="checkbox" checked={allOn} disabled={!deletable.length} aria-label="삭제 가능한 행 모두 선택"
                  onChange={() => setSel(allOn ? new Set() : new Set(deletable.map((r) => r.key)))} /></th>
                {kind === 'rt'
                  ? <><th>지시번호</th><th>품번 · 칼라 · 사이즈</th><th>보내는 매장</th><th>받는 매장</th><th>상태</th><th>등록</th></>
                  : <><th>의뢰</th><th>매장</th><th>품번 · 칼라 · 사이즈</th><th className="num">수량</th><th>출고예정</th><th>상태</th><th>등록</th></>}
              </tr>
            </thead>
            <tbody>
              {kind === 'rt' && (rt?.rows ?? []).map((r) => (
                <tr key={r.id} className={sel.has(r.id) ? 'selected' : ''}>
                  <td className="check"><input type="checkbox" disabled={!r.deletable} checked={sel.has(r.id)} onChange={() => flip(r.id)} aria-label={`${r.id} 선택`} /></td>
                  <td className="mono">{r.id}</td>
                  <td><b className="mono">{r.prdtCd}</b> <span className="muted">{r.colorCd} · {r.sizeCd}</span></td>
                  <td><span className="mono">{r.fromShopId}</span> {r.fromShopNm}</td>
                  <td><span className="mono">{r.toShopId}</span> {r.toShopNm}</td>
                  <td><span className={`tag ${r.status === 'C2954' || r.status === 'N' ? 'warn' : r.status === 'C2951' ? 'auto' : r.status === 'C2952' ? 'miss' : ''}`}>{r.statusNm}</span>
                    {r.resn && <div className="muted small">{r.resn}</div>}</td>
                  <td className="muted small">{fmt14(r.insDay)} · {r.insUser}{r.cnfmUser ? ` · 확정 ${r.cnfmUser}` : ''}</td>
                </tr>
              ))}
              {kind === 'alloc' && (al?.rows ?? []).map((r) => {
                const k = `${r.askDt}|${r.askSeqn}|${r.seq}`
                return (
                  <tr key={k} className={sel.has(k) ? 'selected' : ''}>
                    <td className="check"><input type="checkbox" disabled={!r.deletable} checked={sel.has(k)} onChange={() => flip(k)} aria-label={`${k} 선택`} /></td>
                    <td className="mono">{r.askDt} {r.askSeqn}차 #{r.seq}</td>
                    <td><span className="mono">{r.shopId}</span> {r.shopNm}</td>
                    <td><b className="mono">{r.prdtCd}</b> <span className="muted">{r.colorCd} · {r.sizeCd}</span></td>
                    <td className="num"><b>{r.qty}</b></td>
                    <td className="muted">{r.delvPreDt}</td>
                    <td><span className={`tag ${r.confirmed ? 'auto' : 'warn'}`}>{r.statusNm}</span></td>
                    <td className="muted small">{fmt14(r.insDay)} · {r.insUser}</td>
                  </tr>
                )
              })}
              {!rows.length && <tr><td colSpan={8} className="empty">이 기간에 이 화면에서 등록한 내역이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
