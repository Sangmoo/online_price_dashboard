// 공지 '오늘 하루 보지 않기': 사용자 · 브라우저별로 '오늘 날짜 + 숨긴 공지 ID' 를 기억한다 (날짜가 바뀌면 다시 보임)
const hideKey = (userId: string) => `notice.hide.${userId}`
const today = () => new Date().toLocaleDateString('sv-SE') // YYYY-MM-DD (로컬 날짜)

export function hiddenToday(userId: string): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(hideKey(userId)) || 'null') as { day: string; ids: string[] } | null
    return v && v.day === today() ? v.ids : []
  } catch {
    return []
  }
}

export function hideForToday(userId: string, ids: string[]) {
  try {
    localStorage.setItem(hideKey(userId), JSON.stringify({ day: today(), ids: [...new Set([...hiddenToday(userId), ...ids])] }))
  } catch {
    /* 저장할 수 없는 브라우저(사생활 보호 모드 등): 이번 접속에서만 닫힌다 */
  }
}

/** 마이페이지: 오늘 숨긴 공지 다시 보기 */
export function clearHidden(userId: string) {
  try {
    localStorage.removeItem(hideKey(userId))
  } catch {
    /* 무시 */
  }
}
