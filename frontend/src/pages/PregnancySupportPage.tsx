// Where pregnant and postpartum users land (from the quiz, the Dashboard, and any blocked feature).
// No AI runs for them anywhere; this page is static text plus the OB-GYN's recorded message.
import { useEffect, useState } from 'react'
import Link from '../components/Link'
import { OBGYN_NAME } from '../legal'

const VIDEO = '/content/video/obgyn_pregnancy_message.mp4'
const ACOG_URL =
  'https://www.acog.org/clinical/clinical-guidance/committee-opinion/articles/2020/04/physical-activity-and-exercise-during-pregnancy-and-the-postpartum-period'

function OBGYNVideo() {
  const [available, setAvailable] = useState<boolean | null>(null)
  useEffect(() => {
    fetch(VIDEO, { method: 'HEAD' })
      // Some hosts answer a missing file with the app's index.html (200), so also require a video content type.
      .then((r) => setAvailable(r.ok && (r.headers.get('content-type') ?? '').startsWith('video/')))
      .catch(() => setAvailable(false))
  }, [])
  if (available) {
    return (
      <video className="support-video" src={VIDEO} controls playsInline preload="metadata">
        A video message from {OBGYN_NAME}, OB-GYN.
      </video>
    )
  }
  return (
    <div className="support-video video-placeholder" role="img" aria-label="Video coming soon">
      <span aria-hidden="true">▶</span>
      <p>{available === null ? 'Loading the video…' : 'Video message coming soon'}</p>
    </div>
  )
}

export default function PregnancySupportPage() {
  return (
    <article className="support-page">
      <OBGYNVideo />

      <h2 className="page-title">A message from {OBGYN_NAME}, OB-GYN</h2>

      <div className="support-body">
        <p>
          Thank you for telling us. Being active during pregnancy and after giving birth can be really good for you,
          and many people keep moving through both. But what's safe varies a lot from person to person during these
          months, depending on your health, your pregnancy, and your recovery.
        </p>
        <p>
          Bee Fit's generated plans and workout builder aren't built for pregnancy or postpartum exercise. They
          can't check the things that matter most right now, so we've switched them off for you rather than guess.
        </p>
        <p>
          The American College of Obstetricians and Gynecologists says physical activity in pregnancy is safe and
          desirable when there are no medical or obstetric complications or reasons to avoid it. Knowing whether that
          applies to you takes an individual check with your own clinician, which an app can't give.
        </p>
        <p className="support-citation">
          Source:{' '}
          <a href={ACOG_URL} target="_blank" rel="noopener noreferrer">
            ACOG Committee Opinion No. 804, Physical Activity and Exercise During Pregnancy and the Postpartum
            Period (2020)
          </a>
          , Obstetrics &amp; Gynecology 2020;135:e178–e188.
        </p>
      </div>

      <section className="support-next">
        <h3>Your next step</h3>
        <p>
          <strong>Talk with your OB-GYN or midwife</strong> about what kind of activity is right for you now, and bring
          any questions you have. If you notice bleeding, dizziness, chest pain, or pain anywhere, stop and contact
          them right away.
        </p>
      </section>

      <section className="support-more">
        <h3>Want some general reading?</h3>
        <p>
          Our <Link to="/basics">Workout Basics articles</Link> are general background (like how rest between sets
          works), not a plan or advice for pregnancy. They're also still pending expert review.
        </p>
      </section>
    </article>
  )
}
