// Usernames and first names: the Dashboard greets you by name, sign-up sends a username (not an email), and a
// session saved before usernames still works.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AccountForm from '../components/AccountForm'
import { getSession } from '../session'
import { mockFetch } from '../test-utils'
import { localToday } from '../components/dashboard/TodayCard'
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

describe('Dashboard contents', () => {
  it('shows only the plan for today and the streak, with no AI calls', async () => {
    signIn()
    const today = localToday()
    const calls = mockFetch({
      '/api/users/1': { ...account('Sarah'), quiz_profile: { needs_clinical_review: false } },
      '/api/calendar': {
        start: today, end: today, today, needs_quiz: false, needs_clinical_review: false, cardio: [],
        calendar_mode: 'generated', needs_review: false,
        entries: [{
          id: 9, date: today, weekday: 'mon', day_type: 'workout', completed: false, notes: null, can_complete: true,
          source: 'generated', can_override: true, planned: null, choice: 'plan', calories: null,
          weights: { glute_bridge: { weighted: false } },
          workout: { focus: 'Lower body', est_minutes: 22, exercises: [
            { exercise_id: 'glute_bridge', name: 'Glute Bridge', muscle_group: 'legs', sets: '3', reps: '12-15' }] },
        }],
      },
      '/api/progress/streak': {
        found: true, current_streak_days: 4, longest_streak_days: 9, active_days_last_30: 12, last_workout_date: today,
        rest_day_suggested: false, next_badge: { days: 7, to_go: 3 }, definition: 'x',
        badges: [{ days: 3, earned: true }, { days: 7, earned: true }, { days: 14, earned: false }, { days: 30, earned: false }],
      },
    })
    render(<DashboardPage />)
    expect(await screen.findByText('Glute Bridge')).toBeTruthy()
    expect(screen.getByText(/Lower body/)).toBeTruthy()
    expect(await screen.findByText('4')).toBeTruthy()                                     // the current streak
    expect(screen.getByText('9 days')).toBeTruthy()                                      // the longest
    expect(screen.getByText(/3 days to go until your 7 days badge/)).toBeTruthy()
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(headings).toEqual(['Plan for today', 'Your streak'])
    expect(calls.some((u) => /coach|programs|basics/.test(u))).toBe(false)              // nothing reaches an agent
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
