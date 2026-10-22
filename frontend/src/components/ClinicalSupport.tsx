// Shown in place of the plan, the workout builder, and the AI cards for pregnant / postpartum users.
// The server blocks those features too (403 needs_clinical_review); this just points people to the right page.
import Link from './Link'

export default function ClinicalSupportCard() {
  return (
    <section className="dash-card clinical-card" aria-labelledby="clinical-card-title">
      <h3 id="clinical-card-title">
        <span className="card-icon" aria-hidden="true">💜</span> Your plan and workouts are paused for now
      </h3>
      <p>
        Because you told us you're pregnant or recently gave birth, we don't build plans or workouts for you. Exercise
        in this period needs individual advice from your OB-GYN or midwife.
      </p>
      <Link to="/pregnancy-support" className="btn btn-big">
        Read the message from our OB-GYN
      </Link>
    </section>
  )
}
