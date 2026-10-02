import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './features.css'
import './invt.css'
import './sale.css'
import App from './App.tsx'
import { ApiError, recordClientError } from './api'

// 화면 오류를 기억해 두었다가 문의·오류 신고에 자동으로 붙인다
window.addEventListener('error', (e) => recordClientError({ kind: 'js', message: e.message || String(e.error) }))
window.addEventListener('unhandledrejection', (e) => {
  const r = e.reason as { name?: string; message?: string } | undefined
  if (e.reason instanceof ApiError || r?.name === 'AbortError') return
  recordClientError({ kind: 'js', message: r?.message ?? String(e.reason) })
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
