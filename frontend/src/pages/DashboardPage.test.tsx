// Usernames and first names: the Dashboard greets you by name, sign-up sends a username (not an email), and a
// session saved before usernames still works.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AccountForm from '../components/AccountForm'
import { getSession } from '../session'
import { mockFetch } from '../test-utils'
import DashboardPage from './DashboardPage'

// A pregnant user's dashboard shows only the support card, so no AI card fetches get in the way of this test.
const profile = { needs_clinical_review: true }
const account = (first_name: string | null) => ({ id: 1, username: 'sarah_k', first_name, created_at: '', quiz_profile: profile })

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

function signIn(session: object = { userId: 1, token: 't', username: 'sarah_k' }) {
  window.localStorage.setItem('homebase.session', JSON.stringify(session))
}

describe('Dashboard greeting', () => {
  it('uses the first name from the account', async () => {
    signIn()
    mockFetch({ '/api/users/1': account('Sarah') })
    render(<DashboardPage />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi Sarah' })).toBeTruthy()
    expect(screen.queryByText(/Hey you/)).toBeNull()
  })

  it('falls back to "Hi there" for an account made before names were asked for', async () => {
    signIn()
    mockFetch({ '/api/users/1': account(null) })
    render(<DashboardPage />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Hi there' })).toBeTruthy()
  })
})

describe('Usernames', () => {
  it('a session saved before usernames keeps working (its email is now the username)', () => {
    signIn({ userId: 7, token: 't', email: 'old@example.com' })
    expect(getSession()).toEqual({ userId: 7, token: 't', username: 'old@example.com' })
  })

  it('sign-up sends a username and first name, not an email', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ user_id: 3, token: 'tok' }), { status: 201 }))
    vi.stubGlobal('fetch', fetch)
    const done = vi.fn()
    render(<AccountForm onDone={done} />)
    expect(screen.queryByLabelText(/email/i)).toBeNull()
    fireEvent.change(screen.getByLabelText(/First name/), { target: { value: 'Sarah' } })
    fireEvent.change(screen.getByLabelText(/Username/), { target: { value: 'sarah_k' } })
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'correct horse 1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(done).toHaveBeenCalled())
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/users')
    expect(JSON.parse(init.body as string)).toEqual({ username: 'sarah_k', first_name: 'Sarah', password: 'correct horse 1' })
    expect(getSession()).toEqual({ userId: 3, token: 'tok', username: 'sarah_k' })
  })
})
