// The logo goes home (the Dashboard when signed in, the landing page when signed out), and the Dashboard no longer
// repeats Build Your Own (it has its own page in the nav).
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { EQUIPMENT, mockFetch } from './test-utils'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

const logo = () => screen.getByRole('link', { name: 'Bee Fit home' })

describe('the logo', () => {
  it('goes to the landing page when signed out', async () => {
    mockFetch({ '/api/exercises/equipment': EQUIPMENT })
    window.history.replaceState({}, '', '/about')
    render(<App />)
    fireEvent.click(logo())
    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('button', { name: 'Create my free account' })).toBeTruthy()
  })

  it('goes to the Dashboard when signed in, without the Build Your Own section', async () => {
    window.localStorage.setItem('homebase.session', JSON.stringify({ userId: 1, token: 't', username: 'sarah_k' }))
    mockFetch({ '/api/users/1': { id: 1, username: 'sarah_k', first_name: 'Sarah', created_at: '', quiz_profile: null } })
    window.history.replaceState({}, '', '/settings')
    render(<App />)
    fireEvent.click(logo())
    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Ask Workout Basics' })).toBeTruthy())
    expect(screen.queryByRole('heading', { name: /build your own workout/i })).toBeNull()
    expect(screen.getByRole('link', { name: 'Build Your Own' }).getAttribute('href')).toBe('/build')   // still in the nav
  })

  it('on the home page already, it scrolls back to the top instead of doing nothing', () => {
    mockFetch({})
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    window.history.replaceState({}, '', '/')
    render(<App />)
    const before = window.history.length
    scrollTo.mockClear()
    fireEvent.click(logo())
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    expect(window.history.length).toBe(before)   // no extra history entry
  })
})
