// "Continue with Google / Microsoft": the buttons appear only for providers the server has set up, start the server's
// OAuth flow, and the callback page turns the server's answer into the same session a password sign-in makes.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import AuthCallbackPage, { readCallback } from '../pages/AuthCallbackPage'
import { getSession } from '../session'
import { mockFetch } from '../test-utils'
import AccountForm from './AccountForm'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  window.sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('Continue with Google / Microsoft', () => {
  it('shows a button for each provider the server has set up, linking to its start route', async () => {
    mockFetch({ '/api/auth/providers': { google: true, microsoft: true } })
    render(<AccountForm initialMode="login" />)
    const google = await screen.findByRole('link', { name: 'Continue with Google' })
    const microsoft = screen.getByRole('link', { name: 'Continue with Microsoft' })
    expect(google.getAttribute('href')).toBe('/api/auth/google/start')
    expect(microsoft.getAttribute('href')).toBe('/api/auth/microsoft/start')
    expect(screen.getByLabelText(/Username/)).toBeTruthy() // username / password sign-in is still there
  })

  it('shows only the providers that are configured, and none when the server has no OAuth keys', async () => {
    const calls = mockFetch({ '/api/auth/providers': { google: false, microsoft: true } })
    render(<AccountForm initialMode="login" />)
    expect(await screen.findByRole('link', { name: 'Continue with Microsoft' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Continue with Google' })).toBeNull()
    expect(calls).toContain('/api/auth/providers')
    cleanup()
    mockFetch({ '/api/auth/providers': { google: false, microsoft: false } })
    render(<AccountForm initialMode="login" />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy())
    expect(screen.queryByText('or')).toBeNull()
    expect(screen.queryByRole('link', { name: /Continue with/ })).toBeNull()
  })

  it('remembers the page the button was on, to come back to it', async () => {
    mockFetch({ '/api/auth/providers': { google: true, microsoft: false } })
    window.history.replaceState({}, '', '/calendar')
    render(<AccountForm initialMode="login" />)
    const google = await screen.findByRole('link', { name: 'Continue with Google' })
    google.addEventListener('click', (e) => e.preventDefault()) // jsdom can't leave the page
    fireEvent.click(google)
    expect(window.sessionStorage.getItem('beefit.oauth.returnTo')).toBe('/calendar')
  })
})

describe('the /auth/callback page', () => {
  it('reads the session or the error from the URL fragment', () => {
    expect(readCallback('#token=1.abc&user_id=1&username=sarah&new=0')).toEqual({
      session: { userId: 1, token: '1.abc', username: 'sarah' },
      isNew: false,
    })
    expect(readCallback('#error=Google+sign-in+was+cancelled.')).toEqual({ error: 'Google sign-in was cancelled.' })
    expect(readCallback('#token=x&user_id=nope')).toHaveProperty('error')
    expect(readCallback('')).toHaveProperty('error')
  })

  it('signs you in, wipes the token from the address bar, and goes back to where you were', async () => {
    mockFetch({ '/api/users/5': { id: 5, username: 'sam', first_name: 'Sam', created_at: '', quiz_profile: null } })
    window.sessionStorage.setItem('beefit.oauth.returnTo', '/calendar')
    window.history.replaceState({}, '', '/auth/callback#token=5.sig&user_id=5&username=sam&new=0')
    render(<App />)
    await waitFor(() => expect(window.location.pathname).toBe('/calendar'))
    expect(window.location.hash).toBe('')
    expect(getSession()).toEqual({ userId: 5, token: '5.sig', username: 'sam' })
  })

  it('works under StrictMode too (its double run must not undo the sign-in)', async () => {
    window.sessionStorage.setItem('beefit.oauth.returnTo', '/settings')
    window.history.replaceState({}, '', '/auth/callback#token=7.sig&user_id=7&username=strict&new=0')
    render(
      <StrictMode>
        <AuthCallbackPage />
      </StrictMode>,
    )
    await waitFor(() => expect(window.location.pathname).toBe('/settings'))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(getSession()?.userId).toBe(7)
  })

  it('sends a brand-new account to the quiz', async () => {
    mockFetch({})
    window.history.replaceState({}, '', '/auth/callback#token=6.sig&user_id=6&username=new.person&new=1')
    render(<AuthCallbackPage />)
    await waitFor(() => expect(window.location.pathname).toBe('/quiz'))
    expect(getSession()?.userId).toBe(6)
  })

  it('shows the error and the sign-in form when it did not work, without signing anyone in', async () => {
    mockFetch({ '/api/auth/providers': { google: true, microsoft: true } })
    window.history.replaceState({}, '', '/auth/callback#error=Microsoft%20sign-in%20was%20cancelled.')
    render(<AuthCallbackPage />)
    expect((await screen.findByRole('alert')).textContent).toBe('Microsoft sign-in was cancelled.')
    expect(window.location.hash).toBe('')
    expect(getSession()).toBeNull()
    expect(await screen.findByRole('link', { name: 'Continue with Google' })).toBeTruthy()
  })
})
