// The public landing page (signed out "/"). The one page meant to feel the most alive: floating shapes, cards that
// rise in as you scroll, and previews built from LIVE data (a real generated week, the real filter funnel, the real
// library counts), never screenshots. Everything moves only when the visitor's system allows motion: the global
// prefers-reduced-motion rule (index.css) stills the CSS, and useReveal shows everything at once.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { fetchDataSummary, fetchPlanExample, type DataSummary, type PlanExample } from '../api'
import AccountForm from '../components/AccountForm'
import Link from '../components/Link'
import VideoSlot from '../components/VideoSlot'

const INTRO_VIDEO = ['/content/video/intro_podcast.mp4', '/content/video/intro_podcast.mov']
const DAY = { mon: 'M', tue: 'T', wed: 'W', thu: 'T', fri: 'F', sat: 'S', sun: 'S' } as const
const words = (s: string) => s.replace(/_/g, ' ')

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Adds .is-visible when the element scrolls into view (at once if motion is reduced or unsupported). */
function Reveal({ children, className = '', delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(() => reducedMotion() || typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    if (visible || !ref.current) return
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true)
          io.disconnect()
        }
      },
      { threshold: 0.15 },
    )
    io.observe(ref.current)
    return () => io.disconnect()
  }, [visible])
  return (
    <div ref={ref} className={`reveal ${visible ? 'is-visible' : ''} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------- live previews (HTML/CSS, no images)

function PlanPreview({ example }: { example: PlanExample | null }) {
  if (!example) return <div className="preview-skeleton" aria-hidden="true" />
  const { plan, profile } = example
  return (
    <>
      <ol className="mini-week" aria-label="A real generated week">
        {plan.days.map((d, i) => (
          <li key={d.day} className={d.kind === 'training' ? 'mini-train' : 'mini-rest'} style={{ animationDelay: `${i * 90}ms` }}>
            <span>{DAY[d.day]}</span>
            <small>{d.kind === 'training' ? `${d.exercises.length} moves` : 'rest'}</small>
          </li>
        ))}
      </ol>
      <p className="preview-caption">
        Built live just now for a {words(profile.experience_level)} whose goal is{' '}
        {profile.goal === 'feel_good' ? 'just feeling good' : words(profile.goal)}, with a{' '}
        {profile.injury_flags.map(words).join(' and ')} injury and {profile.equipment.map(words).join(', ')}.
      </p>
    </>
  )
}

function CalendarPreview() {
  return (
    <>
      <div className="mini-cal" aria-hidden="true">
        {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
          <div key={i} className="mini-cal-day">
            <span>{d}</span>
          </div>
        ))}
        <div className="mini-cal-card">Full body</div>
      </div>
      <p className="preview-caption">Life happens. Drag a workout to another day, jot notes, tick it off.</p>
    </>
  )
}

function FunnelPreview({ example }: { example: PlanExample | null }) {
  if (!example) return <div className="preview-skeleton" aria-hidden="true" />
  const top = example.funnel[0]?.exercises_left || 1
  return (
    <>
      <ol className="mini-funnel" aria-label="How the safety and equipment filters narrow the library">
        {example.funnel.map((s, i) => (
          <li key={s.step}>
            <span className="mini-funnel-bar" style={{ width: `${Math.max(4, (s.exercises_left / top) * 100)}%`, animationDelay: `${i * 150}ms` }} />
            <small>
              {s.exercises_left.toLocaleString()} · {s.step}
            </small>
          </li>
        ))}
      </ol>
      <p className="preview-caption">
        No AI guessing: clear rules, the same every time. <Link to="/how-we-build">See exactly how →</Link>
      </p>
    </>
  )
}

function SafetyPreview({ data }: { data: DataSummary | null }) {
  const ex = data?.exercises
  return (
    <>
      <div className="mini-stats">
        <div>
          <strong>{ex ? ex.total.toLocaleString() : '…'}</strong>
          <small>exercises</small>
        </div>
        <div>
          <strong>{ex ? ex.injury_checked : '…'}</strong>
          <small>checked for injuries</small>
        </div>
        <div>
          <strong>{ex ? ex.reasons_ai_drafted : '…'}</strong>
          <small>cautions explained</small>
        </div>
      </div>
      <p className="preview-caption">
        Flag an injury and you only get exercises checked for it. No exceptions.{' '}
        <Link to="/about/data">Where our data comes from →</Link>
      </p>
    </>
  )
}

// ---------------------------------------------------------------- the page

export default function WelcomePage() {
  const [example, setExample] = useState<PlanExample | null>(null)
  const [data, setData] = useState<DataSummary | null>(null)
  const [mode, setMode] = useState<'signup' | 'login'>('signup')
  const joinRef = useRef<HTMLElement>(null)

  useEffect(() => {
    fetchPlanExample().then(setExample).catch(() => setExample(null))
    fetchDataSummary().then(setData).catch(() => setData(null))
  }, [])

  function join(next: 'signup' | 'login') {
    setMode(next)
    joinRef.current?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }

  return (
    <div className="landing">
      <section className="landing-hero">
        <div className="landing-shapes" aria-hidden="true">
          <span className="shape shape-1" />
          <span className="shape shape-2" />
          <span className="shape shape-3" />
          <span className="shape shape-4" />
          <span className="sparkle sparkle-1">✦</span>
          <span className="sparkle sparkle-2">✦</span>
          <span className="sparkle sparkle-3">✦</span>
        </div>
        <p className="landing-kicker">Free · home workouts · built around you</p>
        <h2 className="landing-title">
          HomeBase <span className="landing-title-pop">Fit</span>
        </h2>
        <p className="landing-pitch">
          Your goals and your injuries, in <span className="hl">one</span> plan. Finally.
        </p>
        <div className="landing-cta">
          <button type="button" className="btn btn-big" onClick={() => join('signup')}>
            Create my free account
          </button>
          <button type="button" className="btn-secondary btn-big" onClick={() => join('login')}>
            Log in
          </button>
        </div>
      </section>

      <Reveal className="landing-video">
        <VideoSlot sources={INTRO_VIDEO} label="Intro video" />
      </Reveal>

      <section className="landing-highlights" aria-label="What HomeBase Fit does">
        <Reveal className="highlight" delay={0}>
          <h3>A plan built around you</h3>
          <PlanPreview example={example} />
        </Reveal>
        <Reveal className="highlight" delay={120}>
          <h3>A calendar you can drag</h3>
          <CalendarPreview />
        </Reveal>
        <Reveal className="highlight" delay={240}>
          <h3>See exactly how we build it</h3>
          <FunnelPreview example={example} />
        </Reveal>
        <Reveal className="highlight" delay={360}>
          <h3>Safety you can count</h3>
          <SafetyPreview data={data} />
        </Reveal>
      </section>

      <Reveal>
        <section className="landing-join" id="join" ref={joinRef} aria-label="Create an account or log in">
          <h3>{mode === 'signup' ? 'Ready? It takes two minutes.' : 'Welcome back!'}</h3>
          <AccountForm key={mode} initialMode={mode} />
          <p className="hint">
            A Yale SOM class project, not medical advice. <Link to="/about">About</Link> ·{' '}
            <Link to="/legal">Legal &amp; privacy</Link>
          </p>
        </section>
      </Reveal>
    </div>
  )
}
