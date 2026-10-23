// The quiz: every step starts at the top (the steps share one route, so the route-change reset never fires), and
// height is asked in feet + inches but sent as total inches.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import QuizPage from './QuizPage'

const QUESTIONS = [
  { id: 'goals', prompt: 'What do you want?', type: 'multi_select', required: true,
    options: [{ value: 'strength', label: 'Get stronger' }] },
  { id: 'height', prompt: 'How tall are you?', type: 'number', unit: 'in', input: 'feet_inches', min: 48, max: 90,
    required: true, health: true, options: [] },
]
const PROFILE = { needs_clinical_review: false, calendar_mode: 'generated', consent_accepted_at: '2026-10-23T12:00:00Z' }

let sent: Record<string, unknown> | null = null
beforeEach(() => {
  sent = null
  window.localStorage.setItem('homebase.session', JSON.stringify({ userId: 1, token: 't', username: 'tester' }))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/quiz/questions')) return new Response(JSON.stringify(QUESTIONS))
    if (url.includes('/quiz-profile')) {
      sent = JSON.parse(String(init?.body))
      return new Response(JSON.stringify(PROFILE))
    }
    return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
  }))
})
afterEach(() => {
  cleanup()
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

describe('the quiz', () => {
  it('scrolls to the top on every step, and sends height in inches from feet + inches', async () => {
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    render(<QuizPage />)
    fireEvent.click(await screen.findByLabelText('Get stronger'))
    scrollTo.mockClear()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))                         // -> disclaimer
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)
    scrollTo.mockClear()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'I agree, continue' }))            // -> health
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)
    scrollTo.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))                          // back to the disclaimer
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)
    fireEvent.click(screen.getByRole('button', { name: 'I agree, continue' }))

    expect(screen.queryByRole('spinbutton', { name: /how tall/i })).toBeNull()             // no single inches box
    fireEvent.change(screen.getByLabelText('Feet'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Inches'), { target: { value: '10' } })
    scrollTo.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Submit quiz' }))                   // -> thank-you screen
    await screen.findByText(/Your answers are saved/)
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)
    expect((sent as { answers: Record<string, unknown> } | null)?.answers.height).toBe(70)
  })

  it('explains the height range in feet and inches', async () => {
    render(<QuizPage />)
    fireEvent.click(await screen.findByLabelText('Get stronger'))
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'I agree, continue' }))
    fireEvent.change(screen.getByLabelText('Feet'), { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit quiz' }))
    expect(await screen.findByText('"How tall are you?" must be between 4 ft 0 in and 7 ft 6 in.')).toBeTruthy()
    expect(sent).toBeNull()
  })
})

describe('the nav', () => {
  it('has the plan and Basics as separate pages, with Calendar right after Build Your Own', async () => {
    window.history.replaceState({}, '', '/about')
    render(<App />)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    const labels = Array.from(nav.querySelectorAll('a')).map((a) => a.textContent)
    expect(labels).toEqual(['Dashboard', 'About', 'Your Personalized Plan', 'Basics', 'Build Your Own', 'Calendar',
      'Exercise Library', 'Settings'])
  })

  it('sends the old combined page to the plan', async () => {
    window.history.replaceState({}, '', '/content')
    render(<App />)
    await waitFor(() => expect(window.location.pathname).toBe('/plan'))
    expect(await screen.findByRole('heading', { name: 'Your Personalized Plan' })).toBeTruthy()
  })
})
