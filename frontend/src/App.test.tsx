// The logo goes home (the Dashboard when signed in, the landing page when signed out), the Dashboard's cards, and the
// nav: an orange highlight on the current tab (no underline) and a permanent green underline on Dashboard.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

  it('goes to the Dashboard when signed in, which shows the plan for today, the streak and this week', async () => {
    window.localStorage.setItem('homebase.session', JSON.stringify({ userId: 1, token: 't', username: 'sarah_k' }))
    mockFetch({ '/api/users/1': { id: 1, username: 'sarah_k', first_name: 'Sarah', created_at: '', quiz_profile: null } })
    window.history.replaceState({}, '', '/settings')
    render(<App />)
    fireEvent.click(logo())
    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
    const cards = await screen.findAllByRole('heading', { level: 3 })
    expect(cards.map((h) => h.textContent)).toEqual(['Plan for today', 'Your streak', 'This week'])
    for (const gone of [/build your own workout/i, /Ask Workout Basics/, /Your coach/, /Recommended for you/]) {
      expect(screen.queryByRole('heading', { name: gone })).toBeNull()
    }
    expect(screen.getByRole('link', { name: 'Build Your Own' }).getAttribute('href')).toBe('/build')   // still in the nav
  })

  it('on the home page already, it starts the home page over at the top instead of doing nothing', async () => {
    mockFetch({})
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    window.history.replaceState({}, '', '/')
    render(<App />)
    const before = window.history.length
    scrollTo.mockClear()
    // Partway down the landing page with the sign-in form open: the logo brings back the page as it first loads.
    Element.prototype.scrollIntoView = vi.fn()                               // jsdom has no scrolling
    fireEvent.click(await screen.findByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Welcome back!' })).toBeTruthy()
    fireEvent.click(logo())
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    expect(window.history.length).toBe(before)   // no extra history entry
    expect(await screen.findByRole('heading', { name: 'Ready? It takes two minutes.' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Welcome back!' })).toBeNull()
  })

  it('goes home from every page in the nav', async () => {
    mockFetch({ '/api/exercises/equipment': EQUIPMENT })
    for (const from of ['/about', '/plan', '/calendar', '/build', '/exercises', '/settings', '/legal', '/quiz']) {
      window.history.replaceState({}, '', from)
      render(<App />)
      fireEvent.click(logo())
      await waitFor(() => expect(window.location.pathname).toBe('/'))
      cleanup()
    }
  })
})

describe('the nav', () => {
  const nav = () => screen.getByRole('navigation', { name: 'Main' })
  const tab = (name: string) => within(nav()).getByRole('link', { name })

  it('highlights only the current tab, and Dashboard always has its green underline', () => {
    mockFetch({ '/api/exercises/equipment': EQUIPMENT })
    window.history.replaceState({}, '', '/calendar')
    render(<App />)
    expect(tab('Calendar').className).toBe('nav-link active')
    expect(tab('Calendar').getAttribute('aria-current')).toBe('page')
    expect(tab('Dashboard').className).toBe('nav-link nav-home')            // not active, still marked
    expect(tab('About').className).toBe('nav-link')
    fireEvent.click(tab('Dashboard'))
    expect(tab('Dashboard').className).toBe('nav-link nav-home active')
    expect(tab('Calendar').className).toBe('nav-link')
  })
})
