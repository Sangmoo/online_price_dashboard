import { useState } from 'react'
import { Loader2, LogIn, RefreshCw, Wrench } from 'lucide-react'

/** 점검 모드(관리자 외 접속 차단) 안내 화면. [다시 확인] 은 점검이 끝났는지 서버에 다시 묻는다. */
export default function MaintenanceScreen({ message, onRetry, onLogin }: {
  message: string
  onRetry: () => Promise<void>
  onLogin: () => void
}) {
  const [checking, setChecking] = useState(false)
  const retry = async () => {
    setChecking(true)
    try {
      await onRetry()
    } finally {
      setChecking(false)
    }
  }
  return (
    <div className="login-page maintenance-page">
      <div className="card maintenance-card">
        <div className="maintenance-icon"><Wrench size={28} /></div>
        <h2>시스템 점검 중</h2>
        <p>{message}</p>
        <div className="maintenance-actions">
          <button className="btn primary" onClick={retry} disabled={checking}>
            {checking ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} 다시 확인
          </button>
          <button className="btn ghost" onClick={onLogin}><LogIn size={15} /> 관리자 로그인</button>
        </div>
      </div>
    </div>
  )
}
