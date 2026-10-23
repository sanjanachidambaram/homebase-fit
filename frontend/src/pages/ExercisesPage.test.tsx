// My Faves is a subtab of the Exercise Library (not a separate page), using the same favorites API as before.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resetEquipmentCache } from '../equipment'
import { EQUIPMENT, mockFetch } from '../test-utils'
import ExercisesPage from './ExercisesPage'

const GLUTE_BRIDGE = {
  id: 'glute_bridge', name: 'Glute Bridge', muscle_group: 'legs', equipment_needed: ['mat'], difficulty: 'beginner',
  force: 'push', category: null, primary_muscles: [], secondary_muscles: [], injury_contraindications: [],
  contraindication_status: 'draft', injury_rationale: {}, est_time_seconds: 45, instructions: 'x',
  demo_media_url: null, media_type: null, source_dataset: 'placeholder-authored',
  source: { name: 's', url: null, license: 'l', status: 'placeholder' }, status: 'placeholder',
  review_notice: 'Content pending expert review', citations: [],
}

beforeEach(() => {
  resetEquipmentCache()
  window.localStorage.setItem('homebase.session', JSON.stringify({ userId: 1, token: 't', username: 'tester' }))
  mockFetch({ '/api/exercises/equipment': EQUIPMENT, '/api/favorites': [GLUTE_BRIDGE], '/api/exercises': [] })
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

  it('filters equipment from the same live list', async () => {
    render(<ExercisesPage />)
    for (const e of EQUIPMENT) expect(await screen.findByText(e.label)).toBeTruthy()
  })
})
