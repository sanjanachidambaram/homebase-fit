import { PrivacyNote } from '../components/Legal'
import { CLASS_PROJECT_NOTE, DISCLAIMER, DISCLAIMER_FULL_POINTS } from '../legal'

export default function LegalPage() {
  return (
    <article className="prose">
      <h2 className="page-title">Legal &amp; privacy</h2>

      <h3>Medical disclaimer</h3>
      <p>
        <strong>{DISCLAIMER}</strong>
      </p>
      <ul>
        {DISCLAIMER_FULL_POINTS.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>

      <h3>About this project</h3>
      <p>{CLASS_PROJECT_NOTE}</p>

      <PrivacyNote title="Data practices" />
    </article>
  )
}
