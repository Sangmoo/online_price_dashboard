import { CircleHelp } from 'lucide-react'
import { openHelp } from './openHelp'

/** 지표 이름 옆 (?) 아이콘: 누르면 도움말의 그 지표 설명이 열린다 */
export function HelpTip({ id, label }: { id: string; label?: string }) {
  return (
    <button
      type="button"
      className="help-tip"
      title={`${label ?? '이 지표'} 계산 방법 보기`}
      aria-label={`${label ?? '지표'} 도움말`}
      onClick={(e) => {
        e.preventDefault() // label 안에 있어도 입력칸으로 초점이 옮겨가지 않게
        e.stopPropagation() // 행 클릭(상세 이동) 등 부모 동작 막기
        openHelp(id)
      }}
    >
      <CircleHelp size={13} />
    </button>
  )
}
