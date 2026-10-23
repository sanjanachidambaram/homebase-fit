// Minimal client-side routing (a handful of pages doesn't need a router library).
import { useEffect, useLayoutEffect, useState } from 'react'

export function navigate(to: string) {
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

/** Every route change starts the new page at the top (links, back/forward, and code that navigates). */
export function useScrollToTopOnRouteChange(path: string) {
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [path])
}

if (typeof window !== 'undefined' && 'scrollRestoration' in window.history) {
  window.history.scrollRestoration = 'manual' // the browser would otherwise put back/forward pages mid-scroll
}
