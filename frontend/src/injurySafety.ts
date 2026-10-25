// Injury-safety wording shared by the library, the exercise detail view, and the plan.
// Honesty rule: an exercise with no cautions is only "safe" if someone actually checked it, and every
// AI-drafted reason says so.
import type { Exercise, InjuryRationale } from './api'

export const words = (values: string[]) => values.map((v) => v.replace(/_/g, ' ')).join(', ')

/** One line per exercise, as shown on library cards and in the detail view. */
export function injuryStatusLabel(ex: Pick<Exercise, 'contraindication_status' | 'injury_contraindications'>): string {
  const tags = ex.injury_contraindications
  switch (ex.contraindication_status) {
    case 'untagged':
      return 'No injury cautions drafted — not yet reviewed by a physical therapist'
    case 'draft':
      return tags.length
        ? `Caution drafted for: ${words(tags)} — not yet PT-reviewed`
        : 'Drafted with no injury cautions — not yet PT-reviewed'
    case 'pt_reviewed':
      return tags.length ? `PT-reviewed — caution for: ${words(tags)}` : 'PT-reviewed — no injury cautions'
  }
}

/** "AI-drafted, not yet reviewed · Pending review by a licensed physical therapist" or "Reviewed by <PT>". */
export function rationaleCredit(r: Pick<InjuryRationale, 'tier' | 'source'>): string {
  return r.tier === 'pt_reviewed' ? `Reviewed by ${r.source}` : `AI-drafted, not yet reviewed · ${r.source}`
}
