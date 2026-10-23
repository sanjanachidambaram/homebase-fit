// Shared test helpers: a fake fetch that answers by URL, so components can be tested without a backend.
import { vi } from 'vitest'

export type Routes = Record<string, unknown>

/** Replace fetch with one that returns JSON for the first route whose key appears in the URL (404 otherwise). */
export function mockFetch(routes: Routes) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      calls.push(url)
      const key = Object.keys(routes).find((k) => url.includes(k))
      const body = key === undefined ? { detail: 'Not found' } : routes[key]
      return new Response(JSON.stringify(body), {
        status: key === undefined ? 404 : 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

/** What GET /api/exercises/equipment returns for the real library (all 14 values, bodyweight first). */
export const EQUIPMENT = [
  { value: 'none', label: 'Bodyweight', exercises: 197, always_included: true },
  { value: 'barbell', label: 'Barbell', exercises: 170, always_included: false },
  { value: 'dumbbells', label: 'Dumbbells', exercises: 129, always_included: false },
  { value: 'other', label: 'Other equipment', exercises: 122, always_included: false },
  { value: 'cable', label: 'Cable', exercises: 81, always_included: false },
  { value: 'machine', label: 'Machine', exercises: 67, always_included: false },
  { value: 'kettlebells', label: 'Kettlebell', exercises: 56, always_included: false },
  { value: 'resistance_band', label: 'Resistance band', exercises: 26, always_included: false },
  { value: 'medicine_ball', label: 'Medicine ball', exercises: 17, always_included: false },
  { value: 'mat', label: 'Mat', exercises: 20, always_included: false },
  { value: 'exercise_ball', label: 'Exercise ball', exercises: 12, always_included: false },
  { value: 'foam_roller', label: 'Foam roller', exercises: 11, always_included: false },
  { value: 'ez_curl_bar', label: 'EZ curl bar', exercises: 9, always_included: false },
  { value: 'chair', label: 'Sturdy chair', exercises: 3, always_included: false },
]
