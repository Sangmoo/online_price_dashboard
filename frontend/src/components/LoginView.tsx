import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, Loader2, Lock, LogIn, TrendingDown, User as UserIcon } from 'lucide-react'
import { api, ApiError, type User } from '../api'

type Props = { notice?: string | null; onLogin: (u: User) => void }

export default function LoginView({ notice, onLogin }: Props) {
  const [id, setId] = useState('')
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lockUntil, setLockUntil] = useState(0)
  const [now, setNow] = useState(Date.now())
  const idRef = useRef<HTMLInputElement>(null)

  useEffect(() => idRef.current?.focus(), [])

  // 잠금 카운트다운
  useEffect(() => {
    if (lockUntil <= Date.now()) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [lockUntil])

  const remain = Math.max(0, Math.ceil((lockUntil - now) / 1000))
  const locked = remain > 0

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!id.trim() || !pw || busy || locked) return
    setBusy(true)
    setError(null)
    try {
      const { user } = await api.login(id.trim(), pw)
      onLogin(user)
    } catch (err) {
      const ex = err as ApiError
      setError(ex.message)
      if (ex.code === 'LOCKED') {
        const sec = Number(ex.extra?.retryAfter ?? 60)
        setLockUntil(Date.now() + sec * 1000)
        setNow(Date.now())
      }
      setPw('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-glow" />
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="brand-mark lg">
            <TrendingDown size={24} strokeWidth={2.6} />
          </div>
          <h1>ERP 영업 관리</h1>
          <p>사내 계정으로 로그인하세요</p>
        </div>

        {notice && !error && <div className="login-notice">{notice}</div>}

        <label className="login-field">
          <span>아이디</span>
          <div className="login-input">
            <UserIcon size={16} />
            <input ref={idRef} value={id} onChange={(e) => setId(e.target.value)} autoComplete="username" placeholder="사번 ID" maxLength={20} />
          </div>
        </label>
        <label className="login-field">
          <span>비밀번호</span>
          <div className="login-input">
            <Lock size={16} />
            <input
              type={show ? 'text' : 'password'}
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              autoComplete="current-password"
              placeholder="비밀번호"
              maxLength={100}
            />
            <button type="button" className="pw-toggle" onClick={() => setShow((s) => !s)} tabIndex={-1} title={show ? '숨기기' : '표시'}>
              {show ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </label>

        {error && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}

        <button className="btn primary login-btn" disabled={busy || locked || !id.trim() || !pw}>
          {busy ? <Loader2 size={16} className="spin" /> : <LogIn size={16} />}
          {locked ? `${remain}초 후 다시 시도` : '로그인'}
        </button>
        <div className="login-foot">로그인 후 1시간 동안 사용하지 않으면 자동으로 로그아웃됩니다.</div>
      </form>
    </div>
  )
}
