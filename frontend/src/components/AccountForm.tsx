import { useState, type FormEvent } from 'react'
import { logIn, signUp } from '../api'
import { setSession, type Session } from '../session'
import { PrivacyNote } from './Legal'
import SignInWith from './SignInWith'

/** Sign up (with the privacy note) or sign in. */
export default function AccountForm({
  initialMode = 'signup',
  onDone,
}: {
  initialMode?: 'signup' | 'login'
  onDone?: (s: Session) => void
}) {
  const [mode, setMode] = useState(initialMode)
  const [username, setUsername] = useState('')
  const [firstName, setFirstName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result =
        mode === 'signup' ? await signUp(username, firstName, password) : await logIn(username, password)
      const session = { userId: result.user_id, token: result.token, username: username.trim() }
      setSession(session)
      onDone?.(session)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="account-form">
      {mode === 'signup' && <PrivacyNote title="Before you sign up: your data and privacy" />}
      <form onSubmit={submit}>
        <h3>{mode === 'signup' ? 'Create your account' : 'Sign in'}</h3>
        {mode === 'signup' && (
          <label>
            First name <span className="hint">(just for your greeting; never sent to the AI)</span>
            <input
              required
              maxLength={50}
              autoComplete="given-name"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
            />
          </label>
        )}
        <label>
          Username {mode === 'signup' && <span className="hint">(3 to 30 letters, numbers, dots, dashes or underscores)</span>}
          <input
            required
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            {...(mode === 'signup' ? { minLength: 3, maxLength: 30, pattern: '[A-Za-z0-9._\\-]+' } : {})}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Password {mode === 'signup' && <span className="hint">(at least 8 characters)</span>}
          <input
            type="password"
            required
            minLength={8}
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" className="btn" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'signup' ? 'Create account' : 'Sign in'}
        </button>
        <button
          type="button"
          className="btn-link"
          onClick={() => {
            setMode(mode === 'signup' ? 'login' : 'signup')
            setError(null)
          }}
        >
          {mode === 'signup' ? 'I already have an account' : 'Create a new account instead'}
        </button>
        <SignInWith />
      </form>
    </div>
  )
}
