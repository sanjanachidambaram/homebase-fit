import { useEffect, useRef, useState } from 'react'
import AccountForm from '../components/AccountForm'
import { takeReturnPath } from '../components/SignInWith'
import { setSession } from '../session'

/** Where the server sends you back after "Continue with Google / Microsoft" (backend app/oauth.py):
 *  /auth/callback#token=...&user_id=...&username=...&new=0|1, or #error=... . The values are in the fragment, which is
 *  never sent to a server; they're moved into the same session a password sign-in makes, and wiped from the address
 *  bar and history straight away. */
export function readCallback(hash: string):
  | {
      session: { userId: number; token: string; username: string }
      isNew: boolean
    }
  | { error: string } {
  const p = new URLSearchParams(hash.replace(/^#/, ''))
  const userId = Number(p.get('user_id'))
  const token = p.get('token')
  if (token && Number.isInteger(userId) && userId > 0) {
    return {
      session: { userId, token, username: p.get('username') ?? '' },
      isNew: p.get('new') === '1',
    }
  }
  return {
    error: p.get('error') || 'That sign-in did not finish. Please try again.',
  }
}

export default function AuthCallbackPage() {
  const [error, setError] = useState<string | null>(null)
  const handled = useRef(false)
  useEffect(() => {
    if (handled.current) return // once: a second run (React's dev double-run) would find the fragment already gone
    handled.current = true
    const result = readCallback(window.location.hash)
    window.history.replaceState({}, '', '/auth/callback') // the token never stays in the address bar or history
    const back = takeReturnPath()
    if ('error' in result) {
      setError(result.error)
      return
    }
    setSession(result.session)
    // A brand-new account has no plan yet: start with the quiz. Otherwise, back to where the button was.
    const to = result.isNew ? '/quiz' : back && back !== '/auth/callback' ? back : '/'
    window.history.replaceState({}, '', to) // replace, so Back doesn't return to this page
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, [])

  if (!error) return <p className="meta">Signing you in…</p>
  return (
    <>
      <h2 className="page-title">Sign in</h2>
      <p className="error" role="alert">
        {error}
      </p>
      <AccountForm initialMode="login" />
    </>
  )
}
