import type { MouseEvent, ReactNode } from 'react'
import { navigate } from '../router'

/** In-app link: changes the page without a full reload. */
export default function Link({
  to,
  children,
  className,
  ariaLabel,
  current,
}: {
  to: string
  children: ReactNode
  className?: string
  ariaLabel?: string
  current?: boolean // the page being viewed (a nav tab): announced as the current page
}) {
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    navigate(to)
  }
  return (
    <a href={to} onClick={onClick} className={className} aria-label={ariaLabel} aria-current={current ? 'page' : undefined}>
      {children}
    </a>
  )
}
