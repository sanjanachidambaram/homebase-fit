// Is the signed-in user pregnant / postpartum (quiz_profiles.needs_clinical_review)? Used to swap features for
// the support card. The server enforces the block on its own (403 needs_clinical_review); this is just the UI.
import { useEffect, useState } from 'react'
import { fetchAccount } from './api'
import type { Session } from './session'

/** null while loading; true if this user's quiz says pregnant or postpartum. */
export function useNeedsClinicalReview(session: Session | null): boolean | null {
  const [result, setResult] = useState<{ userId: number; value: boolean } | null>(null)
  useEffect(() => {
    if (!session) return
    let cancelled = false
    fetchAccount(session.userId, session.token)
      .then((a) => !cancelled && setResult({ userId: session.userId, value: !!a.quiz_profile?.needs_clinical_review }))
      .catch(() => !cancelled && setResult({ userId: session.userId, value: false }))   // the API still blocks
    return () => {
      cancelled = true
    }
  }, [session])
  return session && result?.userId === session.userId ? result.value : null
}
