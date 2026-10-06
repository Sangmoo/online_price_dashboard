import { api } from './api'

// 강조 색 팔레트 (마이페이지). 데이터 의미 색(증감 빨강·파랑, 주의, 위험, 정상)은 바뀌지 않는다.
// 서버 사용자 설정 'ui.accent' 에 저장하고(다른 PC 에서도 유지), 로그인 전 화면용으로 브라우저에도 기억한다.
// 키는 backend/app/main.py ACCENTS, 색 값은 index.css [data-accent] 와 같게 유지한다.
export type AccentKey = 'indigo' | 'teal' | 'graphite' | 'ocean' | 'forest' | 'wine'

export const ACCENTS: { key: AccentKey; label: string; desc: string; light: string; dark: string; note?: string }[] = [
  { key: 'indigo', label: '인디고', desc: '기본', light: '#4f46e5', dark: '#818cf8' },
  { key: 'teal', label: '틸', desc: '차분 · 데이터 화면에 잘 어울림', light: '#0f766e', dark: '#2dd4bf' },
  { key: 'graphite', label: '그래파이트', desc: '무채색 · 눈이 가장 편함', light: '#334155', dark: '#cbd5e1' },
  { key: 'ocean', label: '오션 블루', desc: '깔끔', light: '#1d4ed8', dark: '#60a5fa', note: '감소(파랑) 표시와 비슷해 보일 수 있음' },
  { key: 'forest', label: '포레스트', desc: '안정감', light: '#15803d', dark: '#4ade80', note: '정상(초록) 배지와 비슷함' },
  { key: 'wine', label: '와인', desc: '개성', light: '#9d174d', dark: '#f472b6' },
]
const KEY = 'accent'

export const isAccent = (v: unknown): v is AccentKey => ACCENTS.some((a) => a.key === v)

export function applyAccent(key: AccentKey, remember = true) {
  if (key === 'indigo') delete document.documentElement.dataset.accent
  else document.documentElement.dataset.accent = key
  if (remember) {
    try {
      localStorage.setItem(KEY, key)
    } catch {
      /* 저장할 수 없는 브라우저: 이번 접속에만 적용 */
    }
  }
}

export function storedAccent(): AccentKey {
  try {
    const v = localStorage.getItem(KEY)
    return isAccent(v) ? v : 'indigo'
  } catch {
    return 'indigo'
  }
}

/** 로그인 직후: 서버에 저장된 강조 색 적용 (없으면 브라우저 기억값 유지) */
export async function loadAccent() {
  try {
    const { value } = await api.getPref<string>('ui.accent')
    if (isAccent(value)) applyAccent(value)
  } catch {
    /* 무시 */
  }
}
