// Minimal client-side routing (a handful of pages doesn't need a router library).
import { useEffect, useLayoutEffect, useState } from 'react'

// Bumped when a link points at the page you're already on, so App can start that page over (useRouteKey).
let visit = 0
const REVISIT = 'beefit-revisit'

export function navigate(to: string) {
  if (to === window.location.pathname) {
    // Already there (e.g. the logo while on the home page, partway down the sign-up form or a scrolled Dashboard):
    // no new history entry, but the page starts over fresh and back at the top, so the link visibly goes home.
    visit += 1
    window.dispatchEvent(new Event(REVISIT))
    window.scrollTo(0, 0)
    return
  }
  window.history.pushState({}, '', to)
  window.dispatchEvent(new PopStateEvent('popstate'))
  // Scrolling to the top happens in App (useScrollToTopOnRouteChange), after the new page renders.
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const onChange = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onChange)
    onChange() // catch a change made before this listener existed (a child's effect, like the /content redirect)
    return () => window.removeEventListener('popstate', onChange)
  }, [])
  return path
}

/** A key for the page being shown: changes on every route change AND when a link to the current page is followed,
 *  so keying the page on it remounts the page fresh. */
export function useRouteKey(path: string): string {
  const [n, setN] = useState(visit)
  useEffect(() => {
    const onRevisit = () => setN(visit)
    window.addEventListener(REVISIT, onRevisit)
    return () => window.removeEventListener(REVISIT, onRevisit)
  }, [])
  return `${path}#${n}`
}

/** Every route change starts the new page at the top (links, back/forward, and code that navigates). */
export function useScrollToTopOnRouteChange(path: string) {
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [path])
}

if (typeof window !== 'undefined' && 'scrollRestoration' in window.history) {
  window.history.scrollRestoration = 'manual' // the browser would otherwise put back/forward pages mid-scroll
}
