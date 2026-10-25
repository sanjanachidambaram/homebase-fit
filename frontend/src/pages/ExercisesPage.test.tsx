// My Faves is a subtab of the Exercise Library (not a separate page), using the same favorites API as before. The
// filters read like the quiz: a workout group to focus on, and body areas to avoid (the quiz's own injury list).
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resetEquipmentCache } from '../equipment'
import { EQUIPMENT, mockFetch } from '../test-utils'
import ExercisesPage from './ExercisesPage'

const GLUTE_BRIDGE = {
  id: 'glute_bridge', name: 'Glute Bridge', muscle_group: 'legs', equipment_needed: ['mat'], difficulty: 'beginner',
  force: 'push', category: null, workout_groups: ['lower'], primary_muscles: [], secondary_muscles: [], injury_contraindications: [],
  contraindication_status: 'draft', injury_rationale: {}, est_time_seconds: 45, instructions: 'x',
  demo_media_url: null, media_type: null, source_dataset: 'placeholder-authored',
  source: { name: 's', url: null, license: 'l', status: 'placeholder' }, status: 'placeholder',
  review_notice: 'Content pending expert review', citations: [],
}

const INJURIES = {
  id: 'injuries', prompt: 'Any injuries or areas that need extra care?', type: 'multi_select', required: true,
  health: true, exclusive: 'none',
  options: [{ value: 'shoulder', label: 'Shoulder' }, { value: 'knee', label: 'Knee' }, { value: 'none', label: 'None' }],
}

let calls: string[] = []
beforeEach(() => {
  resetEquipmentCache()
  window.localStorage.setItem('homebase.session', JSON.stringify({ userId: 1, token: 't', username: 'tester' }))
  calls = mockFetch({ '/api/exercises/equipment': EQUIPMENT, '/api/favorites': [GLUTE_BRIDGE],
                      '/api/quiz/questions': [INJURIES], '/api/exercises': [] })
})
afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

describe('Exercise Library with a My Faves subtab', () => {
  it('opens on My Faves from /faves, switches tabs in place, and keeps the address in step', async () => {
    window.history.replaceState({}, '', '/faves')
    render(<ExercisesPage initialTab="faves" />)
    expect(screen.getByRole('heading', { name: 'Exercise Library' })).toBeTruthy()
    const faves = await screen.findByRole('button', { name: /My Faves \(1\)/ })
    expect(faves.getAttribute('aria-pressed')).toBe('true')
    await waitFor(() => expect(screen.getByText('Glute Bridge')).toBeTruthy())   // the faved exercise, same API

    fireEvent.click(screen.getByRole('button', { name: 'All Exercises' }))
    expect(screen.getByRole('button', { name: 'All Exercises' }).getAttribute('aria-pressed')).toBe('true')
    expect(window.location.pathname).toBe('/exercises')
    fireEvent.click(faves)
    expect(window.location.pathname).toBe('/faves')
  })

  it('asks what to work on and what to avoid, like the quiz, and the API does the filtering', async () => {
    render(<ExercisesPage />)
    expect(await screen.findByRole('group', { name: 'What do you want to work on?' })).toBeTruthy()
    for (const label of ['Everything', 'Upper body', 'Lower body', 'Core / mobility']) {
      expect(screen.getByRole('radio', { name: new RegExp(`^${label}`) })).toBeTruthy()
    }
    const avoid = await screen.findByRole('group', { name: 'Any areas to avoid because of an injury?' })
    expect(avoid.querySelectorAll('input[type=checkbox]').length).toBe(2)            // the quiz's areas, minus "None"
    expect(screen.queryByText('Level')).toBeNull()
    expect(screen.queryByText('Injury safety')).toBeNull()
    expect(screen.queryByRole('combobox', { name: /muscle group/i })).toBeNull()

    fireEvent.click(screen.getByRole('radio', { name: /^Upper body/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Shoulder' }))
    await waitFor(() => expect(calls.some((u) => u.includes('/api/exercises?group=upper&avoid=shoulder'))).toBe(true))
  })

  it('filters equipment from the same live list', async () => {
    render(<ExercisesPage />)
    for (const e of EQUIPMENT) expect(await screen.findByText(e.label)).toBeTruthy()
  })
})
