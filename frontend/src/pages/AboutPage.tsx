// About: the class-project disclaimer, why the app exists, what's different, an honest "About the Data" section,
// and the team. Every number in "About the Data" comes live from the API (GET /api/data-summary, /api/sources),
// never typed in by hand, so it can't go stale when content is added or reviewed.
// The section copy is placeholder text for the creator to edit.
import { useEffect, useState, type ReactNode } from 'react'
import { fetchDataSummary, fetchSources, type DataSummary, type Source } from '../api'
import Link from '../components/Link'
import { OBGYN_NAME } from '../legal'

const TEAM_PHOTOS = '/content/images/team'
const PHOTO_EXTS = ['jpg', 'png', 'webp']

const TEAM: { file: string; name: string; role: string; bio: string }[] = [
  {
    file: 'creator',
    name: '[Your name]',
    role: 'Creator · Yale student',
    bio: '[Bio placeholder: who you are, what you study, and why you wanted to build this.]',
  },
  {
    file: 'pt-friend',
    name: '[Name], PT',
    role: 'Physical therapist · reviewing the protocols and injury tags',
    bio: '[Bio placeholder: her background and what she is reviewing for HomeBase Fit.]',
  },
  {
    file: 'pt-mom',
    name: '[Name], PT',
    role: 'Physical therapist · reviewing the protocols and injury tags',
    bio: '[Bio placeholder: her background and what she is reviewing for HomeBase Fit.]',
  },
  {
    file: 'obgyn-sister',
    name: OBGYN_NAME,
    role: 'OB-GYN · the pregnancy and postpartum message',
    bio: '[Bio placeholder: her background, and the message she recorded for pregnant and postpartum users.]',
  },
]

/** Tries name.jpg, .png, .webp; shows a drawn placeholder avatar until one exists (never a broken image). */
function TeamPhoto({ file, name }: { file: string; name: string }) {
  const [attempt, setAttempt] = useState(0)
  if (attempt >= PHOTO_EXTS.length) {
    return (
      <div className="team-avatar team-avatar-empty" role="img" aria-label={`Photo of ${name} coming soon`}>
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <circle cx="32" cy="24" r="12" />
          <path d="M10 58c2-13 11-20 22-20s20 7 22 20z" />
        </svg>
      </div>
    )
  }
  return (
    <img
      className="team-avatar"
      src={`${TEAM_PHOTOS}/${file}.${PHOTO_EXTS[attempt]}`}
      alt={`Photo of ${name}`}
      onError={() => setAttempt((a) => a + 1)}
    />
  )
}

function SourceLink({ source, children }: { source?: Source; children: ReactNode }) {
  return source?.url ? (
    <a href={source.url} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ) : (
    <>{children}</>
  )
}

const n = (x: number) => x.toLocaleString()

function AboutTheData() {
  const [data, setData] = useState<DataSummary | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchDataSummary(), fetchSources()])
      .then(([d, s]) => {
        setData(d)
        setSources(s)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="error">Couldn't load the live numbers: {error}</p>
  if (!data) return <p className="hint">Counting the library…</p>

  const ex = data.exercises
  const bySource = Object.fromEntries(ex.by_source.map((s) => [s.id, s]))
  const fedb = bySource['free-exercise-db']
  const authored = ex.total - (fedb?.count ?? 0)
  const src = Object.fromEntries(sources.map((s) => [s.id, s]))
  const checkedNoCaution = ex.injury_checked - ex.with_cautions
  const licenseName = (fedb?.license ?? 'The Unlicense').replace(/\s*\(.*\)\s*$/, '')   // "The Unlicense"
  const p = data.protocols

  return (
    <>
      <div className="stat-row" aria-label="The library today, counted live">
        <div className="stat-tile">
          <strong>{n(ex.total)}</strong>
          <span>exercises in the library</span>
        </div>
        <div className="stat-tile stat-tile-key">
          <strong>
            {n(ex.injury_checked)} <small>of {n(ex.total)}</small>
          </strong>
          <span>have any injury-safety information</span>
        </div>
        <div className="stat-tile">
          <strong>{n(ex.reasons_ai_drafted)}</strong>
          <span>injury cautions with an AI-drafted reason</span>
        </div>
        <div className="stat-tile">
          <strong>{n(ex.injury_pt_reviewed)}</strong>
          <span>reviewed by a physical therapist so far</span>
        </div>
      </div>
      <p className="hint">Counted live from the app's database every time this page loads.</p>

      <p>
        Most of HomeBase Fit's exercise library, <strong>{n(fedb?.count ?? 0)} of its {n(ex.total)} exercises</strong>,
        comes from <SourceLink source={src['free-exercise-db']}>free-exercise-db</SourceLink>, a public-domain dataset
        (released under {licenseName}, meaning anyone can use it freely, with no legal restrictions) of exercise
        names, muscles targeted, equipment needed, step-by-step instructions, and demo images. The other{' '}
        {n(authored)} are starter exercises written for this project. We chose free-exercise-db over paid alternatives
        (several commercial exercise-database APIs exist, but cost money and restrict reuse) and over wger (a full
        open-source workout-manager app with its own API, but more setup overhead than we needed for a one-day build)
        because it was free, legally unencumbered, and already structured almost exactly how our database needed it.
      </p>
      <p>
        What's good about this data: it's large, well-organized, and free of licensing risk. What's <em>not</em> good
        about it, and important to be honest about: it was not written or reviewed by medical or fitness
        professionals. It's crowdsourced, so quality and consistency vary from exercise to exercise, and critically, it
        contains no information at all about which exercises are unsafe for which injuries. That part, the
        safety-critical part, had to come from somewhere else: we hand-authored and drafted injury-safety reasoning for
        a starting set of exercises ourselves, clearly labeled everywhere as "AI-drafted, not yet reviewed by a physical
        therapist" until a real PT confirms or corrects it. As of today,{' '}
        <strong>
          {n(ex.injury_checked)} of {n(ex.total)} exercises
        </strong>{' '}
        have any injury-safety information at all: {n(ex.with_cautions)} carry drafted cautions ({n(ex.cautions)} in
        all, each with its own AI-drafted reason)
        {checkedNoCaution > 0 && <>, and {n(checkedNoCaution)} were checked and given none</>}. The other{' '}
        {n(ex.injury_unchecked)} are honestly labeled "not yet checked" rather than assumed safe.
      </p>
      <p>
        The same honesty applies to the science behind the workout protocols themselves (sessions per week, and sets,
        reps and rest for each goal): {p.placeholder === p.total ? `all ${n(p.total)}` : `${n(p.placeholder)} of the ${n(p.total)}`}{' '}
        are starting values still pending review by a physical therapist, and{' '}
        {p.with_citations === 0
          ? 'none is backed by cited research yet.'
          : `${n(p.with_citations)} are backed by cited research so far.`} Two pieces of outside guidance <em>are</em> real, cited sources: the{' '}
        <SourceLink source={src['cdc-losing-weight']}>CDC's guidance</SourceLink> that safe, sustainable weight loss is
        roughly 1 to 2 pounds a week, and{' '}
        <SourceLink source={src['acog-co-804']}>ACOG Committee Opinion No. 804 (2020)</SourceLink> on physical activity
        during pregnancy and postpartum recovery.
      </p>
      <p>
        We built the app to never blur these lines: anywhere you see a claim presented as scientific fact, it's backed
        by an actual citation; anywhere it isn't yet, the app says so outright instead of pretending otherwise.
      </p>

      <h3 className="about-subhead">Every source we use</h3>
      <ul className="source-list">
        {sources.map((s) => (
          <li key={s.id}>
            <div>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.name}
                </a>
              ) : (
                <strong>{s.name}</strong>
              )}{' '}
              <span className={`status status-${s.status}`}>{s.status}</span>
            </div>
            <span className="source-detail">
              Used for: {s.used_for}
              <br />
              License: {s.license}
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}

export default function AboutPage() {
  return (
    <article className="about">
      <section className="class-disclaimer" role="note" aria-labelledby="class-disclaimer-title">
        <h2 id="class-disclaimer-title">A student project</h2>
        <p>
          HomeBase Fit was built as a final project for an AI agent-building class at Yale University. It's a student
          project, not a commercial product or a medical device.
        </p>
        <Link to="/legal">Read the full disclaimer, privacy and legal page</Link>
      </section>

      <h2 className="page-title">About HomeBase Fit</h2>

      <section className="about-section">
        <h3>Why I built it</h3>
        <p>
          Most workout apps assume you either have a full gym or a flawless, injury-free body. I wanted something
          different: an app for people working out at home with limited equipment, who are also dealing with something
          real, like a cranky lower back, a packed schedule, or a weight goal they've tried before. I wanted an app that
          could hold "I want to lose weight" and "my back needs to heal" at the same time, instead of forcing a choice.
        </p>
      </section>

      <section className="about-section">
        <h3>What's different</h3>
        <p>
          Most fitness apps either hand you a generic program or use AI to pick exercises without real safety logic
          behind it. HomeBase Fit runs every plan through a strict, code-enforced safety filter: if you've flagged an
          injury, you only get exercises checked for it, no exceptions. The plan isn't AI-guessed. It's built from
          protocols my PT friend and her mom (also a PT) are reviewing, matched to your goals by clear rules, and the
          AI's only job is explaining the plan, not inventing it. See exactly how on the{' '}
          <Link to="/how-we-build">How We Build Your Plan</Link> page.
        </p>
      </section>

      <section className="about-section">
        <h3>What's cool about it</h3>
        <p>
          A plan that explains its own reasoning, down to why specific exercises were left out for your injuries. A
          calendar you can actually drag around your week. Favorite your go-to exercises. Fun non-scale-victory stats.
          And a genuinely pregnancy- and postpartum-aware design: if that's you, the app steps aside for real guidance
          instead of guessing.
        </p>
      </section>

      <section className="about-section about-data">
        <h3>About the data</h3>
        <AboutTheData />
      </section>

      <section className="about-section">
        <h3>Meet the team</h3>
        <ul className="team-grid">
          {TEAM.map((t) => (
            <li key={t.file} className="team-card">
              <TeamPhoto file={t.file} name={t.name} />
              <strong className="team-name">{t.name}</strong>
              <span className="team-role">{t.role}</span>
              <p>{t.bio}</p>
            </li>
          ))}
        </ul>
      </section>
    </article>
  )
}
