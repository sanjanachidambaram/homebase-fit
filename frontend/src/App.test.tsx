// Home and the logo: "/" is the Landing Page for signed-out visitors and the Dashboard for signed-in users (always
// their default); the Bee Fit logo always opens the Landing Page (/welcome), which has "Go to my Dashboard" when signed
// in. Also the Dashboard's cards, and the nav: an orange highlight on the current tab (no underline) and a permanent
// green underline on Dashboard.
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
const signIn = () =>
  window.localStorage.setItem('homebase.session', JSON.stringify({ userId: 1, token: 't', username: 'sarah_k' }))
const ACCOUNT = { id: 1, username: 'sarah_k', first_name: 'Sarah', created_at: '', quiz_profile: null }

describe('the front door', () => {
  it('signed out, the root URL is the Landing Page (not the Dashboard) with sign-up and log-in', async () => {
    mockFetch({})
    window.history.replaceState({}, '', '/')
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Create my free account' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Log in' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Ready? It takes two minutes.' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /^Hi / })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Go to my Dashboard' })).toBeNull()
    const dashboardTab = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Dashboard' })
    expect(dashboardTab.className).toBe('nav-link nav-home')                 // not highlighted: this isn't the Dashboard
  })

  it('signed in, the root URL is the Dashboard (plan for today, streak, this week), never the Landing Page', async () => {
    signIn()
    mockFetch({ '/api/users/1': ACCOUNT })
    window.history.replaceState({}, '', '/')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
    const cards = await screen.findAllByRole('heading', { level: 3 })
    expect(cards.map((h) => h.textContent)).toEqual(['Plan for today', 'Your streak', 'This week'])
    for (const gone of [/build your own workout/i, /Ask Workout Basics/, /Your coach/, /Recommended for you/]) {
      expect(screen.queryByRole('heading', { name: gone })).toBeNull()
    }
    expect(screen.queryByRole('button', { name: 'Create my free account' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Build Your Own' }).getAttribute('href')).toBe('/build')   // still in the nav
  })

  it('logging in on the Landing Page goes to the Dashboard', async () => {
    Element.prototype.scrollIntoView = vi.fn()                               // jsdom has no scrolling
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body = url === '/api/login' ? { user_id: 1, token: 't' } : url.startsWith('/api/users/1') ? ACCOUNT : null
      return new Response(JSON.stringify(body ?? { detail: 'Not found' }), { status: body ? 200 : 404 })
    })
    vi.stubGlobal('fetch', fetch)
    window.history.replaceState({}, '', '/welcome')                         // e.g. after following the logo
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Log in' }))
    fireEvent.change(screen.getByLabelText(/Username/), { target: { value: 'sarah_k' } })
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse 1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
  })
})

describe('the logo', () => {
  it('signed out, opens the Landing Page from every page', async () => {
    mockFetch({ '/api/exercises/equipment': EQUIPMENT })
    for (const from of ['/', '/about', '/plan', '/calendar', '/build', '/exercises', '/settings', '/legal', '/quiz']) {
      window.history.replaceState({}, '', from)
      render(<App />)
      expect(logo().getAttribute('href')).toBe('/welcome')
      fireEvent.click(logo())
      await waitFor(() => expect(window.location.pathname).toBe('/welcome'))
      expect(await screen.findByRole('button', { name: 'Create my free account' })).toBeTruthy()
      cleanup()
    }
  })

  it('signed in, opens the Landing Page too, with an obvious way back to the Dashboard', async () => {
    signIn()
    mockFetch({ '/api/users/1': ACCOUNT, '/api/exercises/equipment': EQUIPMENT })
    window.history.replaceState({}, '', '/')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
    fireEvent.click(logo())
    await waitFor(() => expect(window.location.pathname).toBe('/welcome'))
    const back = await screen.findAllByRole('link', { name: 'Go to my Dashboard' })
    expect(back.length).toBe(2)                                             // the hero and the bottom of the page
    expect(screen.getByText('Signed in as sarah_k')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Create my free account' })).toBeNull()   // no sign-up when signed in
    fireEvent.click(back[0])
    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
  })

  it('on the Landing Page already, it starts the page over at the top instead of doing nothing', async () => {
    mockFetch({})
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    window.history.replaceState({}, '', '/welcome')
    render(<App />)
    const before = window.history.length
    scrollTo.mockClear()
    // Partway down the Landing Page with the sign-in form open: the logo brings back the page as it first loads.
    Element.prototype.scrollIntoView = vi.fn()                               // jsdom has no scrolling
    fireEvent.click(await screen.findByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Welcome back!' })).toBeTruthy()
    fireEvent.click(logo())
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    expect(window.history.length).toBe(before)   // no extra history entry
    expect(await screen.findByRole('heading', { name: 'Ready? It takes two minutes.' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Welcome back!' })).toBeNull()
  })
})

describe('the nav', () => {
  const nav = () => screen.getByRole('navigation', { name: 'Main' })
  const tab = (name: string) => within(nav()).getByRole('link', { name })

  it('highlights only the current tab, and Dashboard always has its green underline', () => {
    signIn()
    mockFetch({ '/api/exercises/equipment': EQUIPMENT, '/api/users/1': ACCOUNT })
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
