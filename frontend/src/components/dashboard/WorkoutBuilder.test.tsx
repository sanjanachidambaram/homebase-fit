// Build Your Own: every muscle-group counter starts at 0, and the equipment chips are the live list from the API.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { MUSCLE_GROUP_LABELS } from '../../api'
import { resetEquipmentCache } from '../../equipment'
import { EQUIPMENT, mockFetch } from '../../test-utils'
import WorkoutBuilder from './WorkoutBuilder'

beforeEach(() => {
  resetEquipmentCache()
  mockFetch({ '/api/exercises/equipment': EQUIPMENT, '/api/favorites': [] })
})
afterEach(cleanup)

describe('Build Your Own', () => {
  it('starts every muscle-group counter at 0 on a fresh load', () => {
    render(<WorkoutBuilder token="t" />)
    const groups = Object.values(MUSCLE_GROUP_LABELS)
    expect(groups).toHaveLength(7)
    for (const label of groups) {
      const stepper = screen.getByText(label, { selector: '.stepper-label' }).closest('.stepper') as HTMLElement
      expect(within(stepper).getByRole('status').textContent, label).toBe('0')
      expect((within(stepper).getByRole('button', { name: `Fewer ${label}` }) as HTMLButtonElement).disabled).toBe(true)
    }
    expect(screen.getByText('(0 of 12 max)')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Build my workout' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('offers every equipment value the exercises use, from the live list', async () => {
    render(<WorkoutBuilder token="t" />)
    const picker = await screen.findByTestId('equipment-picker')
    await waitFor(() => expect(picker.querySelectorAll('input[type=checkbox]')).toHaveLength(EQUIPMENT.length))
    const boxes = [...picker.querySelectorAll<HTMLInputElement>('input[type=checkbox]')]
    expect(boxes.map((b) => b.value).sort()).toEqual(EQUIPMENT.map((e) => e.value).sort())
    for (const box of boxes) {
      if (box.value === 'none') {
        expect(box.checked && box.disabled).toBe(true) // bodyweight: always included, nothing to pick
      } else {
        expect(box.disabled).toBe(false) // every other value can be selected
        expect(box.checked).toBe(false) // and nothing is pre-selected
      }
    }
  })
})
