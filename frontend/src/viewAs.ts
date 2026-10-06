// 사용자 화면 미리보기 (관리자 · 읽기 전용): 이 브라우저 탭에서만 유지 (sessionStorage). 서버 요청에 X-View-As 헤더로 보낸다.
const KEY = 'erp.viewAs'

export function viewAsId(): string | null {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function startViewAs(id: string) {
  sessionStorage.setItem(KEY, id)
  window.location.assign('/')
}

export function endViewAs() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* 무시 */
  }
  window.location.assign('/?view=admin')
}
