import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AlertTriangle, Check, Loader2, Search, Store, UserRound, X } from 'lucide-react'
import {
  byteLength,
  invtApi,
  isoToYmd,
  ymdToIso,
  type InvtOptions,
  type InvtPlan,
  type Manager,
  type PlanForm,
  type ShopRow,
} from '../invtApi'
import { fmtNum } from '../format'

type Props = {
  plan: InvtPlan | null
  options: InvtOptions
  onClose: () => void
  onSaved: (plan: InvtPlan, isNew: boolean) => void
}

// 저장 대상 필드 (자동 조회 값도 수기로 수정 가능)
const EDITABLE: (keyof InvtPlan)[] = [
  'shopId', 'moBrdCd', 'brdNm', 'shopFormNm', 'shopNm', 'prevSaleAmt', 'currSaleAmt', 'addr', 'areaNm', 'regionNm',
  'lastInvtDt', 'prevInvtType', 'prevInvtResult', 'stockQty', 'stockBaseDt', 'invtPlanNote', 'baseFee', 'expectAmt',
  'invtPlanDt', 'rmk', 'twiceYearYn', 'shopRankNm', 'stlmTeam', 'smasrNm', 'smasrHp', 'shopTel',
]

// 업체 예상 비용 자동 계산 규칙
const BASE_FEE_CAPITAL = 150000 // 권역 '수도권' 기본료
const BASE_FEE_OTHER = 200000 // 그 외 권역 기본료
const EXPECT_PER_QTY = 85 // 실사예상액 = 재고 수량 × 85

const str = (v: unknown) => (v == null ? '' : String(v))
const numOrNull = (v: unknown) => {
  const s = str(v).replaceAll(',', '').trim()
  return s === '' || isNaN(Number(s)) ? null : Number(s)
}

export default function InvtPlanEditor({ plan, options, onClose, onSaved }: Props) {
  const isNew = !plan
  const [form, setForm] = useState<PlanForm>(() => (plan ? { ...plan } : { twiceYearYn: 'N' }))
  const [missing, setMissing] = useState<string[]>([])
  const [loadErrors, setLoadErrors] = useState<Record<string, string>>({})
  const [existing, setExisting] = useState(0)
  const [notes, setNotes] = useState<string[]>([])
  const [shopPicker, setShopPicker] = useState(false)
  const [mgrPicker, setMgrPicker] = useState(false)
  const [loadingShop, setLoadingShop] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = (k: keyof InvtPlan, v: string | number | boolean | null) => {
    setForm((f) => derive({ ...f, [k]: v }, k))
    if (missing.includes(k as string) && v !== '' && v != null) setMissing((m) => m.filter((x) => x !== k))
  }

  // Esc 로 닫기
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && !shopPicker && !mgrPicker && onClose()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose, shopPicker, mgrPicker])

  const pickShop = async (shop: ShopRow) => {
    setShopPicker(false)
    setLoadingShop(true)
    setError(null)
    try {
      const d = await invtApi.shop(shop.shopId)
      setForm((f) => derive({ ...f, ...d.values }, 'stockQty'))
      setMissing(d.missing)
      setNotes(d.notes ?? [])
      setLoadErrors(d.errors)
      setExisting(isNew ? d.existingPlans : Math.max(0, d.existingPlans - 1))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoadingShop(false)
    }
  }

  const rmkBytes = byteLength(str(form.rmk), options.encoding)
  const rmkOver = rmkBytes > options.rmkMaxBytes

  const saleRate = useMemo(() => {
    const p = numOrNull(form.prevSaleAmt)
    const c = numOrNull(form.currSaleAmt)
    return p && c != null ? ((c / p - 1) * 100).toFixed(1) : null
  }, [form.prevSaleAmt, form.currSaleAmt])

  const elapsed = useMemo(() => {
    const d = str(form.lastInvtDt)
    if (d.length !== 8) return null
    const t = new Date(ymdToIso(d)).getTime()
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return Math.round((today.getTime() - t) / 86400000)
  }, [form.lastInvtDt])

  const save = async () => {
    if (!form.shopId) {
      setError('매장코드를 먼저 선택하세요.')
      return
    }
    if (rmkOver) {
      setError(`비고는 ${options.rmkMaxBytes}바이트 이내로 입력하세요.`)
      return
    }
    const body: PlanForm = {}
    for (const k of EDITABLE) {
      if (k in form) body[k] = form[k] ?? null
    }
    body.twiceYearYn = form.twiceYearYn === 'Y' || form.twiceYearYn === true ? 'Y' : 'N'
    setSaving(true)
    setError(null)
    try {
      const r = isNew ? await invtApi.create(body) : await invtApi.update(plan!.planId, body)
      onSaved(r.plan, isNew)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const miss = (k: string) => missing.includes(k)
  const input = (k: keyof InvtPlan, placeholder = '', type: 'text' | 'number' = 'text') => (
    <input
      className={`input ${miss(k) ? 'missing' : ''}`}
      type={type}
      value={str(form[k])}
      placeholder={miss(k) ? '데이터 없음 · 직접 입력' : placeholder}
      onChange={(e) => set(k, e.target.value)}
    />
  )
  const dateInput = (k: keyof InvtPlan) => (
    <input
      className={`input ${miss(k) ? 'missing' : ''}`}
      type="date"
      value={ymdToIso(form[k])}
      onChange={(e) => set(k, e.target.value ? isoToYmd(e.target.value) : null)}
    />
  )
  const select = (k: keyof InvtPlan, list: string[], emptyLabel = '선택 안 함') => (
    <select className="input select" value={str(form[k])} onChange={(e) => set(k, e.target.value || null)}>
      <option value="">{emptyLabel}</option>
      {list.map((v) => <option key={v} value={v}>{v}</option>)}
    </select>
  )

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card editor-modal">
        <div className="modal-head">
          <h3>{isNew ? '실사계획 신규 등록' : `실사계획 수정 · ${plan!.shopNm ?? plan!.shopId}`}</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="editor-body">
          {/* 매장 */}
          <section className="form-section">
            <div className="form-section-title">매장 정보 <span className="muted">매장을 선택하면 자동으로 채워집니다</span></div>
            <div className="shop-select-row">
              <div className="shop-code-box">
                <span className="mono strong">{str(form.shopId) || '매장 미선택'}</span>
                {form.shopNm && <span>{str(form.shopNm)}</span>}
              </div>
              <button className="btn primary" onClick={() => setShopPicker(true)} disabled={loadingShop}>
                {loadingShop ? <Loader2 size={15} className="spin" /> : <Store size={15} />}
                {form.shopId ? '매장 다시 선택' : '매장코드 선택'}
              </button>
            </div>
            {missing.length > 0 && (
              <div className="notice-box warn">
                <AlertTriangle size={15} />
                <div>
                  다음 항목은 조회된 데이터가 없습니다. 직접 입력해 주세요: <b>{missing.map(labelOf).join(', ')}</b>
                  {notes.map((n) => <div key={n}>{n}</div>)}
                  {Object.keys(loadErrors).length > 0 && <div className="muted small">일부 항목은 조회 중 오류가 발생했습니다.</div>}
                </div>
              </div>
            )}
            {missing.length === 0 && notes.length > 0 && (
              <div className="notice-box warn">
                <AlertTriangle size={15} />
                <div>{notes.map((n) => <div key={n}>{n}</div>)}</div>
              </div>
            )}
            {existing > 0 && (
              <div className="notice-box info">
                <AlertTriangle size={15} /> 이 매장에는 이미 등록된 실사계획이 {existing}건 있습니다. 저장하면 별도의 계획으로 추가됩니다.
              </div>
            )}
            <div className="form-grid">
              <Field label="브랜드" auto missing={miss('brdNm')}>{input('brdNm')}</Field>
              <Field label="유통" auto missing={miss('shopFormNm')}>{input('shopFormNm')}</Field>
              <Field label="매장명" auto missing={miss('shopNm')}>{input('shopNm')}</Field>
              <Field label="관리등급" auto missing={miss('shopRankNm')} hint="최종실사일 기준">{input('shopRankNm')}</Field>
              <Field label="전년 매출(원)" auto missing={miss('prevSaleAmt')} hint={fmtMil(form.prevSaleAmt)}>{input('prevSaleAmt', '', 'number')}</Field>
              <Field label="당년 매출(원)" auto missing={miss('currSaleAmt')} hint={fmtMil(form.currSaleAmt)}>{input('currSaleAmt', '', 'number')}</Field>
              <Field label="증감율">
                <div className={`readonly ${saleRate && Number(saleRate) > 0 ? 'up' : saleRate && Number(saleRate) < 0 ? 'down' : ''}`}>
                  {saleRate ? `${Number(saleRate) > 0 ? '+' : ''}${saleRate}%` : '-'}
                </div>
              </Field>
              <Field label="매장번호" auto missing={miss('shopTel')}>{input('shopTel', '02-000-0000')}</Field>
            </div>
          </section>

          {/* 위치 */}
          <section className="form-section">
            <div className="form-section-title">위치</div>
            <div className="form-grid">
              <Field label="주소" wide>{input('addr', '주소를 입력하세요')}</Field>
              <Field label="지역">
                <select
                  className="input select"
                  value={str(form.areaNm)}
                  onChange={(e) => {
                    const v = e.target.value || null
                    set('areaNm', v)
                    if (v && options.areaRegion[v]) set('regionNm', options.areaRegion[v])
                  }}
                >
                  <option value="">선택 안 함</option>
                  {options.areas.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </Field>
              <Field label="권역" hint="지역 선택 시 자동">{select('regionNm', options.regions)}</Field>
            </div>
          </section>

          {/* 직전 실사 / 재고 */}
          <section className="form-section">
            <div className="form-section-title">직전 실사 · 재고</div>
            <div className="form-grid">
              <Field label="최종실사일" auto missing={miss('lastInvtDt')}>{dateInput('lastInvtDt')}</Field>
              <Field label="경과일"><div className="readonly">{elapsed != null ? `${fmtNum(elapsed)}일` : '-'}</div></Field>
              <Field label="전실사유형" auto missing={miss('prevInvtType')}>{select('prevInvtType', options.invtTypes)}</Field>
              <Field label="전실사결과" auto missing={miss('prevInvtResult')} hint={fmtWonHint(form.prevInvtResult)}>
                {input('prevInvtResult', '숫자', 'number')}
              </Field>
              <Field label="재고 수량" auto missing={miss('stockQty')} hint={form.stockBaseDt ? `${ymdToIso(form.stockBaseDt)} 기준` : '당일 기준'}>
                {input('stockQty', '', 'number')}
              </Field>
            </div>
          </section>

          {/* 실사 계획 */}
          <section className="form-section">
            <div className="form-section-title">실사 계획 · 업체 예상 비용</div>
            <div className="form-grid">
              <Field label="실사예정" wide>
                <textarea className="input textarea" rows={2} value={str(form.invtPlanNote)} placeholder="자유롭게 작성" onChange={(e) => set('invtPlanNote', e.target.value)} />
              </Field>
              <Field label="기본료(원)" hint="수도권 15만 · 그 외 20만">{input('baseFee', '권역 선택 시 자동', 'number')}</Field>
              <Field label="실사예상액(원)" hint="재고 수량 × 85">{input('expectAmt', '재고 입력 시 자동', 'number')}</Field>
              <Field label="실사예정일" hint="비우면 미정">
                <div className="date-with-clear">
                  {dateInput('invtPlanDt')}
                  {form.invtPlanDt ? (
                    <button className="btn ghost sm" onClick={() => set('invtPlanDt', null)}>미정</button>
                  ) : (
                    <span className="undecided">미정</span>
                  )}
                </div>
              </Field>
              <Field label="정산 팀구분">{select('stlmTeam', options.stlmTeams, '공백')}</Field>
              <Field label="연2회 실사 매장">
                <label className="check-label big">
                  <input
                    type="checkbox"
                    checked={form.twiceYearYn === 'Y' || form.twiceYearYn === true}
                    onChange={(e) => set('twiceYearYn', e.target.checked ? 'Y' : 'N')}
                  />
                  연 2회 실사
                </label>
              </Field>
              <Field label="비고" wide hint={`${rmkBytes}/${options.rmkMaxBytes} 바이트`} error={rmkOver}>
                <textarea className={`input textarea ${rmkOver ? 'missing' : ''}`} rows={2} value={str(form.rmk)} onChange={(e) => set('rmk', e.target.value)} />
              </Field>
            </div>
          </section>

          {/* 매니저 */}
          <section className="form-section">
            <div className="form-section-title">
              매니저
              <button className="btn ghost sm" disabled={!form.shopId} onClick={() => setMgrPicker(true)}>
                <UserRound size={13} /> 매니저 불러오기
              </button>
            </div>
            <div className="form-grid">
              <Field label="성함">{input('smasrNm')}</Field>
              <Field label="전화번호">{input('smasrHp', '010-0000-0000')}</Field>
            </div>
          </section>
        </div>

        {error && <div className="alert error">{error}</div>}
        <div className="modal-foot">
          {!isNew && plan && (
            <span className="muted small">
              등록 {plan.insUserId} {fmtDay(plan.insDay)}
              {plan.uptDay && ` · 수정 ${plan.uptUserId} ${fmtDay(plan.uptDay)}`}
            </span>
          )}
          <div className="grow" />
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn primary" onClick={save} disabled={saving || !form.shopId || rmkOver}>
            {saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} {isNew ? '등록' : '저장'}
          </button>
        </div>
      </div>

      {shopPicker && <ShopPicker onClose={() => setShopPicker(false)} onPick={pickShop} />}
      {mgrPicker && form.shopId && (
        <ManagerPicker
          shopId={String(form.shopId)}
          onClose={() => setMgrPicker(false)}
          onPick={(m) => {
            set('smasrNm', m.smasrNm)
            set('smasrHp', m.smasrHp)
            setMgrPicker(false)
          }}
        />
      )}
    </div>
  )
}

const LABELS: Record<string, string> = {
  brdNm: '브랜드', shopFormNm: '유통', shopNm: '매장명', prevSaleAmt: '전년 매출', currSaleAmt: '당년 매출',
  lastInvtDt: '최종실사일', prevInvtType: '전실사유형', prevInvtResult: '전실사결과', stockQty: '재고 수량',
  shopRankNm: '관리등급', shopTel: '매장번호',
}

/** 입력값 변경에 따른 자동 계산: 권역 → 기본료, 재고 수량 → 실사예상액 (계산 후 사용자가 직접 수정 가능) */
function derive(f: PlanForm, changed: keyof InvtPlan): PlanForm {
  if (changed === 'regionNm' && f.regionNm) {
    return { ...f, baseFee: f.regionNm === '수도권' ? BASE_FEE_CAPITAL : BASE_FEE_OTHER }
  }
  if (changed === 'stockQty') {
    const qty = numOrNull(f.stockQty)
    return { ...f, expectAmt: qty == null ? null : Math.round(qty * EXPECT_PER_QTY) }
  }
  return f
}
const fmtWonHint = (v: unknown) => {
  const n = numOrNull(v)
  return n == null ? undefined : `${n > 0 ? '+' : ''}${fmtNum(n)}원`
}
const labelOf = (k: string) => LABELS[k] ?? k
const fmtMil = (v: unknown) => {
  const n = numOrNull(v)
  return n == null ? undefined : `${fmtNum(Math.round(n / 1_000_000))}백만원`
}
const fmtDay = (v: string | null) => (v && v.length >= 12 ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)} ${v.slice(8, 10)}:${v.slice(10, 12)}` : '')

function Field({
  label,
  children,
  auto,
  missing,
  hint,
  wide,
  error,
}: {
  label: string
  children: ReactNode
  auto?: boolean
  missing?: boolean
  hint?: string
  wide?: boolean
  error?: boolean
}) {
  return (
    <label className={`field ${wide ? 'wide' : ''}`}>
      <span className="field-label">
        {label}
        {auto && !missing && <span className="tag auto">자동</span>}
        {missing && <span className="tag miss">데이터 없음</span>}
        {hint && <span className={`field-hint ${error ? 'err' : ''}`}>{hint}</span>}
      </span>
      {children}
    </label>
  )
}

// ----------------------------------------------------------------------------
// 매장코드 선택 팝업
// ----------------------------------------------------------------------------
function ShopPicker({ onClose, onPick }: { onClose: () => void; onPick: (s: ShopRow) => void }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<ShopRow[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const kw = q.trim()
    if (!kw) {
      setRows([])
      setSearched(false)
      return
    }
    const t = setTimeout(() => {
      setLoading(true)
      setError(null)
      invtApi
        .shops(kw)
        .then((r) => {
          setRows(r.shops)
          setSearched(true)
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card picker-modal">
        <div className="modal-head">
          <h3><Store size={16} /> 매장코드 선택</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="search">
          <Search size={16} />
          <input autoFocus placeholder="매장코드 또는 매장명 (예: S31019, 가산)" value={q} onChange={(e) => setQ(e.target.value)} />
          {loading && <Loader2 size={15} className="spin" />}
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="picker-list">
          <table className="table">
            <thead>
              <tr><th>매장코드</th><th>매장명</th><th>유통</th><th>유통보고형태</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.shopId} className="clickable" onClick={() => onPick(r)}>
                  <td className="mono strong">{r.shopId}</td>
                  <td>{r.shopNm}</td>
                  <td className="muted">{r.shopFormNm ?? '-'}</td>
                  <td className="muted">{r.shopForm2Nm ?? '-'}</td>
                </tr>
              ))}
              {searched && !loading && rows.length === 0 && (
                <tr><td colSpan={4} className="empty">검색 결과가 없습니다.</td></tr>
              )}
              {!searched && !loading && (
                <tr><td colSpan={4} className="empty">매장코드나 매장명을 입력하세요.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {rows.length >= 100 && <div className="muted small">검색 결과가 많아 100건까지 표시합니다. 검색어를 더 구체적으로 입력하세요.</div>}
      </div>
    </div>
  )
}

// ----------------------------------------------------------------------------
// 매니저 선택 팝업
// ----------------------------------------------------------------------------
function ManagerPicker({ shopId, onClose, onPick }: { shopId: string; onClose: () => void; onPick: (m: Manager) => void }) {
  const [rows, setRows] = useState<Manager[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    invtApi.managers(shopId).then((r) => setRows(r.managers)).catch((e) => setError(e.message))
  }, [shopId])

  return (
    <div className="modal-backdrop top" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card picker-modal">
        <div className="modal-head">
          <h3><UserRound size={16} /> 매니저 선택 · {shopId}</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        {error && <div className="alert error">{error}</div>}
        {!rows && !error && <div className="center pad"><Loader2 size={20} className="spin" /></div>}
        {rows && rows.length === 0 && (
          <div className="notice-box warn">
            <AlertTriangle size={15} /> 이 매장에 등록된 매니저 데이터가 없습니다. 성함과 전화번호를 직접 입력하세요.
          </div>
        )}
        {rows && rows.length > 0 && (
          <div className="picker-list">
            <table className="table">
              <thead><tr><th>매니저명</th><th>매니저번호</th><th>오픈일</th><th>종료일</th></tr></thead>
              <tbody>
                {rows.map((m, i) => (
                  <tr key={i} className={`clickable ${m.current ? 'current-mgr' : ''}`} onClick={() => onPick(m)}>
                    <td className="strong">
                      {m.smasrNm ?? '-'} {m.current && <span className="tag auto">현재</span>}
                    </td>
                    <td className="mono">{m.smasrHp ?? <span className="muted">번호 없음</span>}</td>
                    <td className="muted">{ymdToIso(m.openDt) || '-'}</td>
                    <td className="muted">{m.closeDt === '99991231' ? '근무 중' : ymdToIso(m.closeDt) || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
