/** 클립보드 복사. HTTP(사내 주소)에서는 navigator.clipboard 를 쓸 수 없어 숨긴 입력칸 + execCommand 로 복사한다. */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* 아래 방식으로 */
    }
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.top = '-1000px'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  const active = document.activeElement as HTMLElement | null
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  ta.remove()
  active?.focus?.()
  return ok
}
