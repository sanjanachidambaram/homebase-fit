import type { MouseEvent, ReactNode } from 'react'
import { navigate } from '../router'

/** In-app link: changes the page without a full reload. */
export default function Link({ to, children, className }: { to: string; children: ReactNode; className?: string }) {
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    navigate(to)
  }
  return (
    <a href={to} onClick={onClick} className={className}>
      {children}
    </a>
  )
}
