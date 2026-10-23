// Every route change starts the new page at the top: in-app links, and the browser's back/forward buttons.
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { navigate, usePath, useScrollToTopOnRouteChange } from './router'

function Probe() {
  const path = usePath()
  useScrollToTopOnRouteChange(path)
  return <p>{path}</p>
}

afterEach(cleanup)

describe('scroll position on navigation', () => {
  it('resets to the top after every route change, including back/forward', () => {
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    const { getByText } = render(<Probe />)
    scrollTo.mockClear()

    act(() => navigate('/calendar'))
    expect(getByText('/calendar')).toBeTruthy()
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)

    scrollTo.mockClear()
    act(() => {
      window.history.pushState({}, '', '/about')
      window.dispatchEvent(new PopStateEvent('popstate')) // what the back/forward buttons fire
    })
    expect(getByText('/about')).toBeTruthy()
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
  })
  // history.scrollRestoration = 'manual' is set too, but jsdom doesn't implement it; it's checked in a real browser.
})
