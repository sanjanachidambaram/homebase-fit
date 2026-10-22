// About the Data: where every exercise, number and claim in HomeBase Fit comes from. Every figure is counted live
// (GET /api/data-summary and /api/sources, tested in tests/test_about_data.py), never typed in by hand, so it can't go
// stale when content is added or reviewed. Moved here from the About page unchanged.
import { useEffect, useState, type ReactNode } from 'react'
import { fetchDataSummary, fetchSources, type DataSummary, type Source } from '../api'
import Link from '../components/Link'

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

export default function AboutDataPage() {
  return (
    <article className="about">
      <p className="hint">
        <Link to="/about">← About HomeBase Fit</Link>
      </p>
      <h2 className="page-title">About the data</h2>
      <p className="page-sub">Where every exercise, number and claim in the app comes from, and how much has been reviewed.</p>
      <section className="about-section about-data">
        <AboutTheData />
      </section>
    </article>
  )
}
