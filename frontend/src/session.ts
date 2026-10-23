// The signed-in user, kept in localStorage so a refresh doesn't sign you out.
import { useEffect, useState } from 'react'

export interface Session {
  userId: number
  token: string
  username: string
}

const KEY = 'homebase.session'
const EVENT = 'homebase-session'

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    // Sessions saved before usernames (2026-10-23) have `email`; that email is now the account's username.
    const s = JSON.parse(raw) as Session & { email?: string }
    return { userId: s.userId, token: s.token, username: s.username ?? s.email ?? '' }
  } catch {
    return null
  }
}

export function setSession(session: Session | null) {
  if (session) localStorage.setItem(KEY, JSON.stringify(session))
  else localStorage.removeItem(KEY)
  window.dispatchEvent(new Event(EVENT))
}

export function useSession(): Session | null {
  const [session, set] = useState(getSession)
  useEffect(() => {
    const update = () => set(getSession())
    window.addEventListener(EVENT, update)
    window.addEventListener('storage', update)
    return () => {
      window.removeEventListener(EVENT, update)
      window.removeEventListener('storage', update)
    }
  }, [])
  return session
}
