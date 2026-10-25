// The quiz: one goal, weight and goal weight only on the losing-weight path, bodyweight always included, a review
// screen before submitting, and every step starting at the top (the steps share one route, so the route-change scroll
// reset never fires).
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import QuizPage from './QuizPage'

const LOSE = { question: 'goal', equals: 'lose_weight' }
const QUESTIONS = [
  { id: 'goal', prompt: "What's your main fitness goal?", type: 'single_select', required: true,
    options: [{ value: 'stronger', label: 'Getting stronger', description: '3 strength days and 1 cardio day.' },
              { value: 'lose_weight', label: 'Losing weight', description: '2 strength days and 2 cardio days.' }] },
  { id: 'equipment', prompt: 'What equipment do you have?', type: 'multi_select', required: true,
    always_included: 'bodyweight',
    options: [{ value: 'bodyweight', label: 'Bodyweight (always included)' }, { value: 'dumbbells', label: 'Dumbbells' }] },
  { id: 'weight', prompt: 'What is your current weight?', type: 'number', unit: 'lb', min: 60, max: 700,
    required: true, health: true, ask_if: LOSE, options: [] },
  { id: 'goal_weight', prompt: "What's your goal weight?", type: 'number', unit: 'lb', min: 60, max: 700,
    required: false, health: true, ask_if: LOSE, options: [],
    pace_note: { lbs_per_week: [1, 2], text: 'Gradual is more likely to last.', source: 'CDC, Losing Weight: https://www.cdc.gov/x' } },
]
const PROFILE = { needs_clinical_review: false, calendar_mode: 'generated', consent_accepted_at: '2026-10-25T12:00:00Z' }

let sent: { answers: Record<string, unknown> } | null = null
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

/** Past Summer's intro card, straight to the questions (without playing the audio). */
function skipIntro() {
  const button = screen.queryByRole('button', { name: 'Continue to quiz' })
  if (button) fireEvent.click(button)                                            // (already past it: nothing to do)
}

async function toHealth(goal: string) {
  skipIntro()
  fireEvent.click(await screen.findByLabelText(new RegExp(`^${goal}`)))
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  fireEvent.click(screen.getByRole('checkbox'))                                  // the disclaimer
  fireEvent.click(screen.getByRole('button', { name: 'I agree, continue' }))
}

describe('the quiz', () => {
  it('starts with a skippable audio message from Summer, before any question', async () => {
    const play = vi.fn(async () => {})
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(play)
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    render(<QuizPage />)
    expect(
      screen.getByRole('heading', { name: 'Before you take the quiz, a quick word from your personal trainer, Summer...' }),
    ).toBeTruthy()
    expect(screen.queryByRole('list')).toBeNull()                                 // the quiz's step list comes after
    expect(screen.queryByLabelText(/^Losing weight/)).toBeNull()                  // no question yet
    const audio = document.querySelector('audio')!
    expect(audio.getAttribute('src')).toBe('/audio/summer-quiz-intro.mp3')
    expect(audio.controls).toBe(true)                                             // play / pause / progress
    fireEvent.click(screen.getByRole('button', { name: "Play Summer's message" }))   // the mic bee plays it
    expect(play).toHaveBeenCalledTimes(1)
    fireEvent.play(audio)
    expect(screen.getByRole('button', { name: "Pause Summer's message" }).getAttribute('aria-pressed')).toBe('true')
    skipIntro()                                                                   // continue (or skip) any time
    expect(await screen.findByLabelText(/^Losing weight/)).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /a quick word from your personal trainer/ })).toBeNull()
    vi.restoreAllMocks()
  })

  it('can be skipped without playing anything', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play')
    render(<QuizPage />)
    skipIntro()
    expect(await screen.findByLabelText(/^Losing weight/)).toBeTruthy()
    expect(play).not.toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('asks weight only for losing weight, shows a review screen, and starts every step at the top', async () => {
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    render(<QuizPage />)
    skipIntro()
    const bodyweight = (await screen.findByLabelText('Bodyweight (always included)')) as HTMLInputElement
    expect(bodyweight.checked && bodyweight.disabled).toBe(true)                  // always on
    scrollTo.mockClear()
    await toHealth('Losing weight')
    expect(scrollTo).toHaveBeenCalledTimes(2)                                    // disclaimer, then health
    fireEvent.change(screen.getByRole('spinbutton', { name: /current weight/i }), { target: { value: '180' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: /goal weight/i }), { target: { value: '165' } })
    expect(screen.getByText(/That's 15 lb: at a gradual 1 to 2 lb a week, roughly 8 to 15 weeks/)).toBeTruthy()

    scrollTo.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Review my answers' }))
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)
    const review = screen.getByRole('heading', { name: 'Review your answers' }).parentElement!
    expect(review.textContent).toContain('Losing weight')
    expect(review.textContent).toContain('Bodyweight (always included)')
    expect(review.textContent).toContain('180 lb')
    fireEvent.click(screen.getAllByRole('button', { name: 'Change' })[1])          // back to the health answers
    expect(screen.getByRole('spinbutton', { name: /current weight/i })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Review my answers' }))

    scrollTo.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Submit quiz' }))
    await screen.findByText(/Your answers are saved/)
    expect(scrollTo).toHaveBeenLastCalledWith(0, 0)
    expect(sent?.answers).toEqual({ goal: 'lose_weight', equipment: ['bodyweight'], weight: 180, goal_weight: 165 })
  })

  it('never asks for or sends a weight for another goal', async () => {
    render(<QuizPage />)
    await toHealth('Getting stronger')
    expect(screen.queryByRole('spinbutton', { name: /weight/i })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Review my answers' }))
    expect(screen.queryByText(/current weight/i)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Submit quiz' }))
    await screen.findByText(/Your answers are saved/)
    expect(sent?.answers).toEqual({ goal: 'stronger', equipment: ['bodyweight'] })
  })

  it('needs a current weight on the losing-weight path', async () => {
    render(<QuizPage />)
    await toHealth('Losing weight')
    fireEvent.click(screen.getByRole('button', { name: 'Review my answers' }))
    expect(screen.getByText('Please answer: What is your current weight?')).toBeTruthy()
    expect(sent).toBeNull()
  })
})

describe('the nav', () => {
  it('lists the tabs in order, with About right after Dashboard and Settings last', async () => {
    window.history.replaceState({}, '', '/about')
    render(<App />)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    const labels = Array.from(nav.querySelectorAll('a')).map((a) => a.textContent)
    expect(labels).toEqual(['Dashboard', 'About', 'Personalized Plan', 'Calendar', 'Build Your Own',
      'Exercise Library', 'Settings'])
    // the tab for the page you're on is highlighted and announced as the current page (here: About)
    const current = Array.from(nav.querySelectorAll('a[aria-current="page"]')).map((a) => a.textContent)
    expect(current).toEqual(['About'])
    expect(nav.querySelector('a[aria-current="page"]')?.className).toContain('active')
  })

  it('sends the old combined page to the plan', async () => {
    window.history.replaceState({}, '', '/content')
    render(<App />)
    await waitFor(() => expect(window.location.pathname).toBe('/plan'))
    expect(await screen.findByRole('heading', { name: 'Your Personalized Plan' })).toBeTruthy()
  })
})
