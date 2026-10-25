// The Dashboard's "This week" card (workouts logged + a fun fact) and "View my quiz answers".
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { QuizProfile, QuizQuestion } from '../../api'
import { mockFetch } from '../../test-utils'
import QuizAnswers, { answerText } from './QuizAnswers'
import ThisWeekCard from './ThisWeekCard'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const week = (over: object = {}) => ({
  week_start: '2026-10-19', week_end: '2026-10-25', workouts_logged: 3, weight_lifted_lbs: 1500,
  cardio_miles: 0, cardio_minutes: 0, note: 'Just for fun: ballpark comparisons, not measurements.',
  fun_fact: { kind: 'lifted', text: "This week you've lifted about 6 golden retrievers!", basis: 'A golden retriever' },
  ...over,
})

describe('This week', () => {
  it('shows how many workouts were logged this week and the fun fact', async () => {
    const calls = mockFetch({ '/api/progress/this-week': week() })
    render(<ThisWeekCard token="t" />)
    expect(await screen.findByText('workouts logged this week')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByRole('note', { name: 'Fun fact' }).textContent).toContain('about 6 golden retrievers')
    expect(calls).toEqual(['/api/progress/this-week'])
  })

  it('says "1 workout", and nudges when there is nothing to make a fact from', async () => {
    mockFetch({ '/api/progress/this-week': week({ workouts_logged: 1, fun_fact: null, note: 'Log a workout or some cardio this week to unlock a fun fact.' }) })
    render(<ThisWeekCard token="t" />)
    expect(await screen.findByText('workout logged this week')).toBeTruthy()
    expect(screen.queryByRole('note', { name: 'Fun fact' })).toBeNull()
    expect(screen.getByText(/unlock a fun fact/)).toBeTruthy()
  })
})

const QUESTIONS: QuizQuestion[] = [
  { id: 'goal', prompt: "What's your main fitness goal?", type: 'single_select', required: true,
    options: [{ value: 'lose_weight', label: 'Lose weight' }, { value: 'stronger', label: 'Get stronger' }] },
  { id: 'experience_level', prompt: 'How much strength training have you done?', type: 'single_select', required: true,
    options: [{ value: 'beginner', label: 'New to it' }] },
  { id: 'equipment', prompt: 'What equipment do you have?', type: 'multi_select', required: true,
    options: [{ value: 'bodyweight', label: 'Just my body' }, { value: 'dumbbells', label: 'Dumbbells' }] },
  { id: 'injuries', prompt: 'Any injuries or areas that need extra care?', type: 'multi_select', required: true,
    options: [{ value: 'knee', label: 'Knee' }, { value: 'lower_back', label: 'Lower back' }, { value: 'none', label: 'None' }] },
  { id: 'weight', prompt: 'What is your current weight?', type: 'number', required: false, unit: 'lb', options: [] },
  { id: 'goal_weight', prompt: "What's your goal weight?", type: 'number', required: false, unit: 'lb', options: [] },
]

const PROFILE = {
  goal: 'lose_weight', experience_level: 'beginner', equipment: ['bodyweight', 'dumbbells'],
  injury_flags: ['knee', 'lower_back'], weight: 165, goal_weight: null, pregnancy_status: null,
  updated_at: '2026-10-20T12:00:00Z',
} as unknown as QuizProfile

describe('View my quiz answers', () => {
  it('opens to show each saved answer with the labels the quiz used', async () => {
    const calls = mockFetch({ '/api/quiz/questions': QUESTIONS })
    render(<QuizAnswers profile={PROFILE} />)
    const toggle = screen.getByText('View my quiz answers')
    expect(calls).toEqual([])                                   // nothing is loaded until it's opened
    const details = toggle.closest('details')!
    details.open = true
    fireEvent(details, new Event('toggle'))
    await waitFor(() => expect(screen.getByText('Lose weight')).toBeTruthy())
    const answers = Object.fromEntries(
      [...details.querySelectorAll('.answer-list div')].map((d) => [d.querySelector('dt')!.textContent, d.querySelector('dd')!.textContent]),
    )
    expect(answers).toEqual({
      "What's your main fitness goal?": 'Lose weight',
      'How much strength training have you done?': 'New to it',
      'What equipment do you have?': 'Just my body, Dumbbells',
      'Any injuries or areas that need extra care?': 'Knee, Lower back',
      'What is your current weight?': '165 lb',                 // goal weight was left blank: not listed
    })
    expect(screen.getByRole('link', { name: 'Retake the quiz' }).getAttribute('href')).toBe('/quiz')
  })

  it('shows "None" for no injuries, and skips questions that were not asked', () => {
    const injuries = QUESTIONS[3]
    expect(answerText(injuries, [])).toBe('None')
    expect(answerText(QUESTIONS[5], null)).toBeNull()
    expect(answerText(QUESTIONS[2], [])).toBeNull()
  })
})
