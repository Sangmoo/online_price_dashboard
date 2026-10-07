import { useEffect, useState } from 'react'

// AI 대화의 [화면에서 열기] → 재고 재배치 추천 화면을 그 조건으로 열고 계산한다.
// 화면이 아직 한 번도 열리지 않았을 수 있어, 요청을 여기 잡아 두었다가 화면이 꺼내 쓴다(한 번만).

export type StockOpenRequest = {
  tab: 'rt' | 'alloc'
  brand: string
  view?: string | null
  run?: boolean
  cond: Record<string, unknown>
  /** AI 가 고른 추천 행 (품번 · 칼라 · 사이즈 · 보내는 매장 · 받는 매장) — 계산 뒤 화면에서 체크 */
  select?: { keys: string[][]; label: string }
  nonce: number
}

export const OPEN_VIEW_EVENT = 'erp:open-view'
let pending: StockOpenRequest | null = null
const listeners = new Set<(r: StockOpenRequest | null) => void>()

export function requestStockOpen(r: Omit<StockOpenRequest, 'nonce'>) {
  pending = { ...r, nonce: Date.now() }
  listeners.forEach((l) => l(pending))
  window.dispatchEvent(new CustomEvent(OPEN_VIEW_EVENT, { detail: 'stock_rt' }))
}

/** 요청을 적용했으면 지워 다시 적용되지 않게 한다 */
export function consumeStockOpen(nonce: number) {
  if (pending?.nonce === nonce) {
    pending = null
    listeners.forEach((l) => l(null))
  }
}

export function useStockOpen(): StockOpenRequest | null {
  const [r, setR] = useState(pending)
  useEffect(() => {
    listeners.add(setR)
    setR(pending)
    return () => { listeners.delete(setR) }
  }, [])
  return r
}
