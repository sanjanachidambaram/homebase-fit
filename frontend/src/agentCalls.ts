// Agent calls cost real tokens, so the same request is never sent twice at once.
// (React's StrictMode runs effects twice in development; without this the Coach would be asked twice.)
import { ApiError, isSignInGone } from './api'
import { navigate } from './router'
import { setSession } from './session'

const inflight = new Map<string, Promise<unknown>>()

export function once<T>(key: string, call: () => Promise<T>): Promise<T> {
  const existing = inflight.get(key)
  if (existing) return existing as Promise<T>
  const p = call().finally(() => inflight.delete(key))
  inflight.set(key, p)
  return p
}

/** A friendly message for a failed agent call; signs the user out if their sign-in is no longer valid. */
export function agentError(e: unknown): string {
  const message = (e as Error).message || 'Something went wrong.'
  if (isSignInGone(e)) setSession(null)
  if (e instanceof ApiError && e.code === 'needs_clinical_review' && e.page) navigate(e.page)   // pregnancy support
  if (/AI features are off/i.test(message)) return 'The AI features are switched off on this server right now.'
  return message
}
