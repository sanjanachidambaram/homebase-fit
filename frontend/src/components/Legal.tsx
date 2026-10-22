// Reusable legal/privacy blocks so every page shows the exact same text.
import { CONSENT_LABEL, DISCLAIMER, DISCLAIMER_FULL_POINTS, PRIVACY_POINTS } from '../legal'
import Link from './Link'

/** Always rendered in the site footer on every page; there is no way to dismiss it. */
export function DisclaimerBar() {
  return (
    <div className="disclaimer-bar" role="note" aria-label="Medical disclaimer">
      <strong>Medical disclaimer:</strong> {DISCLAIMER} <Link to="/legal">Legal &amp; privacy</Link>
    </div>
  )
}

export function PrivacyNote({ title = 'Your data and privacy' }: { title?: string }) {
  return (
    <section className="privacy-note">
      <h3>{title}</h3>
      <ul>
        {PRIVACY_POINTS.map((p) => (
          <li key={p.heading}>
            <strong>{p.heading}:</strong> {p.text}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The full disclaimer + required checkbox shown in the quiz before health questions. */
export function ConsentStep({ accepted, onChange }: { accepted: boolean; onChange: (v: boolean) => void }) {
  return (
    <section className="consent-box">
      <h3>Before we ask about your health</h3>
      <p>
        <strong>{DISCLAIMER}</strong>
      </p>
      <ul>
        {DISCLAIMER_FULL_POINTS.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <label className="consent-check">
        <input type="checkbox" checked={accepted} onChange={(e) => onChange(e.target.checked)} />
        <span>{CONSENT_LABEL}</span>
      </label>
    </section>
  )
}
