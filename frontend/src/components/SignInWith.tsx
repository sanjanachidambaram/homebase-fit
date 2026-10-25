import { useEffect, useState, type JSX } from 'react'
import { fetchSignInProviders, oauthStartUrl, type SignInProvider, type SignInProviders } from '../api'

const RETURN_KEY = 'beefit.oauth.returnTo'

/** Where to land after a Google / Microsoft sign-in: the page the button was on (kept for the round trip). */
export function takeReturnPath(): string | null {
  const to = sessionStorage.getItem(RETURN_KEY)
  sessionStorage.removeItem(RETURN_KEY)
  return to && to.startsWith('/') && !to.startsWith('//') ? to : null
}

// The providers' marks, drawn as inline SVG (no image files).
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true" focusable="false">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  )
}

function MicrosoftMark() {
  return (
    <svg viewBox="0 0 21 21" width="20" height="20" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  )
}

const BUTTONS: {
  provider: SignInProvider
  label: string
  Mark: () => JSX.Element
}[] = [
  { provider: 'google', label: 'Continue with Google', Mark: GoogleMark },
  {
    provider: 'microsoft',
    label: 'Continue with Microsoft',
    Mark: MicrosoftMark,
  },
]

/** "Continue with Google" / "Continue with Microsoft". Only the providers the server has set up are shown (none in a
 *  local setup without OAuth keys, so then this renders nothing). A full-page redirect: the server does the OAuth
 *  round trip (PKCE + state) and comes back to /auth/callback with the same kind of session a password sign-in gets. */
export default function SignInWith() {
  const [providers, setProviders] = useState<SignInProviders | null>(null)
  useEffect(() => {
    let cancelled = false
    fetchSignInProviders()
      .then((p) => !cancelled && setProviders(p))
      .catch(() => !cancelled && setProviders(null))
    return () => {
      cancelled = true
    }
  }, [])
  const shown = BUTTONS.filter((b) => providers?.[b.provider])
  if (shown.length === 0) return null
  return (
    <div className="sign-in-with" aria-label="Sign in with another account">
      <div className="sign-in-with-or">
        <span>or</span>
      </div>
      {shown.map(({ provider, label, Mark }) => (
        <a
          key={provider}
          className="btn-oauth"
          href={oauthStartUrl(provider)}
          onClick={() => sessionStorage.setItem(RETURN_KEY, window.location.pathname)}
        >
          <Mark />
          <span>{label}</span>
        </a>
      ))}
    </div>
  )
}
