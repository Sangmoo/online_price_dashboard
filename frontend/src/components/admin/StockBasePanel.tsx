import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Database, Loader2, Play, RefreshCw } from 'lucide-react'
import { opsApi, type StockBaseStatus } from '../../opsApi'
import { fmtNum } from '../../format'

type Notify = (text: string, error?: boolean) => void

/** 스케줄 · 배치 > 매장 재고 기준 집계: 브랜드별 마지막 집계 · 지금 쓰는지 · [지금 재집계] (DB 스케줄 매일 06:30 과 같은 프로시저) */
export default function StockBasePanel({ notify, onDone }: { notify: Notify; onDone: () => void }) {
  const [d, setD] = useState<StockBaseStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const wasRunning = useRef(false)

  const load = useCallback(() => {
    opsApi.stockBase().then((x) => {
      setD(x)
      const running = x.run.status === 'running'
      if (wasRunning.current && !running) {
        if (x.run.status === 'error') notify(`재집계가 일부 실패했습니다: ${x.run.error ?? ''}`, true)
        else notify(`매장 재고 기준을 재집계했습니다 (${x.run.elapsedSec ?? 0}초). 장기 미판매 · 재고 회전 · 주간 브리핑이 새 기준을 씁니다.`)
        onDone()
      }
      wasRunning.current = running
    }).catch((e) => notify(e.message, true))
  }, [notify, onDone])
  useEffect(() => load(), [load])
  const running = d?.run.status === 'running'
  useEffect(() => {
    if (!running) return
    const t = window.setInterval(load, 3000)
    return () => window.clearInterval(t)
  }, [running, load])

  const start = (brand?: string, name?: string) => {
    if (!confirm(`${name ?? '전체 브랜드'} 매장 재고 기준을 지금 다시 집계합니다 (${brand ? '1분 안팎' : '2~3분'}). 진행하는 동안에도 화면은 이전 기준을 그대로 씁니다. 진행할까요?`)) return
    setBusy(true)
    opsApi.stockBaseRefresh(brand).then((r) => {
      wasRunning.current = r.run.status === 'running'
      load()
    }).catch((e) => notify(e.message, true)).finally(() => setBusy(false))
  }

  return (
    <section className="card panel" aria-label="매장 재고 기준 집계">
      <div className="panel-head row">
        <h3><Database size={15} /> 매장 재고 기준 집계</h3>
        <span className="panel-hint">장기 미판매 · 재고 회전 · 주간 브리핑 · 매장 평가 카드가 읽는 이번 달 매장 × 스타일 재고 · {d?.schedule ?? '매일 06:30'} DB 스케줄로 자동 집계</span>
        <div className="grow" />
        <button className="icon-btn bordered" onClick={load} title="새로고침"><RefreshCw size={15} /></button>
        <button className="btn primary" onClick={() => start()} disabled={!d?.ready || running || busy}>
          {running ? <Loader2 size={15} className="spin" /> : <Play size={15} />} {running ? `재집계 중… ${d?.run.elapsedSec ?? 0}초` : '지금 재집계'}
        </button>
      </div>
      {!d && <div className="trend-loading"><Loader2 size={16} className="spin" /> 집계 상태를 읽는 중…</div>}
      {d && !d.ready && (
        <div className="notice-box warn"><AlertTriangle size={15} /><div>{d.message}</div></div>
      )}
      {d?.ready && (
        <>
          <div className="table-wrap">
            <table className="table jobs-table">
              <thead><tr><th>브랜드</th><th>사용</th><th>마지막 집계</th><th>기준 월</th><th className="num">행 수</th><th className="num">걸린 시간</th><th>마지막 시도</th><th /></tr></thead>
              <tbody>
                {d.brands.map((b) => (
                  <tr key={b.brand}>
                    <td className="strong">{b.brandNm}</td>
                    <td>
                      <span className={`job-status tone-${b.status === 'RUNNING' ? 'warn' : b.inUse ? 'ok' : 'bad'}`}>
                        {b.status === 'RUNNING' ? '집계 중' : b.inUse ? '집계 사용' : '원장 직접 계산'}
                      </span>
                    </td>
                    <td className="nowrap mono">{b.baseDt ?? '-'}</td>
                    <td className="mono">{b.makeYymm ?? '-'}</td>
                    <td className="num">{b.rows != null ? fmtNum(b.rows) : '-'}</td>
                    <td className="num">{b.sec != null ? `${b.sec}초` : '-'}</td>
                    <td className="small">
                      {b.updDt ?? '-'}
                      {b.status === 'ERROR' && <div className="bad-text" title={b.msg ?? ''}>실패: {b.msg}</div>}
                    </td>
                    <td><button className="btn ghost small" onClick={() => start(b.brand, b.brandNm)} disabled={running || busy}>이 브랜드만</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="muted small">
            '집계 사용'은 기준 월이 이번 달이고 {d.maxAgeHours ?? 36}시간 안에 집계된 경우입니다. 아니면 그 브랜드는 원장(T_SHOP_STOCK)에서 바로 계산해 첫 조회가 1분 안팎 걸립니다.
            재고가 크게 바뀐 날(대량 출고 · 반품 뒤) 오전에 다시 집계하면 화면이 새 재고를 씁니다.
            {d.run.status !== 'idle' && d.run.finished && <> · 마지막 재집계 {d.run.finished}{d.run.by ? ` (${d.run.by})` : ''}{d.run.status === 'error' ? ` · 오류: ${d.run.error}` : ''}</>}
          </div>
        </>
      )}
    </section>
  )
}
