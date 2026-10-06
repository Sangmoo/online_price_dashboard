export const OPEN_HELP_EVENT = 'erp:open-help'

/** 도움말 열기 (id 를 주면 그 지표로 이동). App 이 이 이벤트를 받아 도움말 창을 띄운다. */
export function openHelp(id?: string) {
  window.dispatchEvent(new CustomEvent<string | undefined>(OPEN_HELP_EVENT, { detail: id }))
}
