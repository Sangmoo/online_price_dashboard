import { useEffect, useState } from 'react'
import { BadgeCheck, Check, Download, EyeOff, Loader2, Moon, Palette, ShieldCheck, Sun, UserRound } from 'lucide-react'
import { api, type User } from '../api'
import { opsApi, type MyOverview } from '../opsApi'
import { ACCENTS, applyAccent, storedAccent, type AccentKey } from '../palette'
import { clearHidden, hiddenToday } from '../noticeHide'
import { fmtNum } from '../format'

/** 마이페이지: 내 정보 · 화면 설정(다크 모드 · 강조 색) · 내 권한 · 오늘 AI 사용 · 숨긴 공지 · 최근 내 다운로드 */
export default function MyPage({ me, theme, onTheme, onShowNotices }: {
  me: User; theme: 'light' | 'dark'; onTheme: () => void; onShowNotices: () => void
}) {
  const [data, setData] = useState<MyOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [accent, setAccent] = useState<AccentKey>(storedAccent)
  const [saved, setSaved] = useState(false)
  const [hidden, setHidden] = useState(() => hiddenToday(me.id).length)
  const preview = !!me.viewAs

  useEffect(() => {
    opsApi.myOverview().then(setData).catch((e) => setError(e.message))
  }, [])

  const pick = (key: AccentKey) => {
    setAccent(key)
    if (preview) return   // 미리보기 중에는 관리자 본인 설정을 바꾸지 않는다
    applyAccent(key)
    api.setPref('ui.accent', key).then(() => {
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    }).catch(() => undefined)
  }

  return (
    <div className="stack mypage">
      {error && <div className="alert error">{error}</div>}
      <section className="card panel my-profile">
        <div className={`avatar lg ${me.role === 'ADMIN' ? 'admin' : ''}`}>{me.name.slice(0, 1)}</div>
        <div className="my-profile-text">
          <h2>{me.name} <span className={`role-badge ${me.role === 'ADMIN' ? 'admin' : ''}`}>{me.role === 'ADMIN' ? '관리자' : '일반'}</span></h2>
          <div className="muted small mono">{me.id}</div>
          <div className="muted small">
            최근 로그인 {data?.lastLoginAt ?? '-'}{data?.createdAt ? ` · 등록 ${data.createdAt.slice(0, 10)}` : ''}
            {data?.role && <> · 권한 묶음 <b>{data.role.name}</b></>}
          </div>
        </div>
      </section>

      <section className="card panel">
        <div className="panel-head"><h3><Palette size={16} /> 화면 설정</h3>
          <span className="panel-hint">강조 색은 버튼 · 선택한 메뉴 · 차트 기본색에 쓰입니다. 증감(빨강 · 파랑) · 주의 · 위험 · 정상 색은 바뀌지 않습니다.{saved && ' · 저장했습니다'}</span>
        </div>
        <div className="my-theme">
          <span className="field-label">화면 모드</span>
          <div className="seg">
            <button className={theme === 'light' ? 'on' : ''} onClick={() => theme !== 'light' && onTheme()}><Sun size={13} /> 라이트</button>
            <button className={theme === 'dark' ? 'on' : ''} onClick={() => theme !== 'dark' && onTheme()}><Moon size={13} /> 다크</button>
          </div>
        </div>
        <div className="accent-grid" role="radiogroup" aria-label="강조 색">
          {ACCENTS.map((a) => (
            <button key={a.key} role="radio" aria-checked={accent === a.key} className={`accent-card ${accent === a.key ? 'on' : ''}`} onClick={() => pick(a.key)}>
              <span className="accent-swatches">
                <span style={{ background: a.light }} title="라이트 모드" />
                <span style={{ background: a.dark }} title="다크 모드" />
              </span>
              <span className="accent-name">{a.label}{accent === a.key && <Check size={14} />}</span>
              <span className="muted small">{a.desc}</span>
              {a.note && <span className="accent-note">{a.note}</span>}
            </button>
          ))}
        </div>
        {preview && <div className="muted small">미리보기 중에는 화면 설정이 저장되지 않습니다.</div>}
      </section>

      <div className="grid-2">
        <section className="card panel">
          <div className="panel-head"><h3><ShieldCheck size={16} /> 내 권한</h3></div>
          <dl className="my-dl">
            <dt>메뉴</dt>
            <dd className="chip-row">{(data?.pages ?? []).map((p) => <span key={p.key} className="chip">{p.label}</span>)}</dd>
            <dt>브랜드</dt>
            <dd>{me.brands?.length ? me.brands.join(', ') : '모든 브랜드'}</dd>
            <dt>AI</dt>
            <dd>
              {data ? (data.usage.enabled
                ? `오늘 질문 ${fmtNum(data.usage.questions)} / ${fmtNum(data.usage.questionLimit)}회 · 비용 $${data.usage.costUsd.toFixed(2)} / $${data.usage.costLimitUsd}`
                : '사용 안 함') : <Loader2 size={13} className="spin" />}
            </dd>
          </dl>
          <div className="muted small">권한이 더 필요하면 상단 [문의·신고] 로 요청하세요.</div>
        </section>

        <section className="card panel">
          <div className="panel-head"><h3><EyeOff size={16} /> 공지</h3></div>
          <p className="small">오늘 '하루 보지 않기' 로 숨긴 공지 <b>{hidden}건</b></p>
          <button className="btn ghost" disabled={!hidden || preview} onClick={() => { clearHidden(me.id); setHidden(0); onShowNotices() }}>
            <BadgeCheck size={14} /> 숨긴 공지 다시 보기
          </button>
        </section>
      </div>

      <section className="card panel">
        <div className="panel-head"><h3><Download size={16} /> 최근 30일 내 다운로드</h3>
          <span className="panel-hint">엑셀 다운로드 · 매장 매니저 연락처 조회 기록 (관리자도 볼 수 있습니다)</span>
        </div>
        {data && !data.downloads && <div className="muted small">다운로드 이력 기능이 아직 준비되지 않았습니다.</div>}
        {data?.downloads && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>일시</th><th>종류</th><th>파일 · 대상</th><th className="num">행</th></tr></thead>
              <tbody>
                {data.downloads.rows.map((r) => (
                  <tr key={r.id}><td className="mono nowrap">{r.at}</td><td className="nowrap">{r.kindLabel}</td><td className="ellipsis" title={r.title ?? ''}>{r.title}</td>
                    <td className="num">{r.rows != null ? fmtNum(r.rows) : ''}</td></tr>
                ))}
                {!data.downloads.rows.length && <tr><td colSpan={4} className="empty">최근 30일 기록이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="muted small my-foot"><UserRound size={12} /> 계정 정보(이름 · 비밀번호)는 사내 계정 시스템에서 관리됩니다.</div>
    </div>
  )
}
