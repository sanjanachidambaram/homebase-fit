import { useEffect, useState, type JSX } from 'react'
import { fetchSources, type Source } from './api'
import { DisclaimerBar } from './components/Legal'
import Link from './components/Link'
import BuildPage from './pages/BuildPage'
import ContentPage from './pages/ContentPage'
import DashboardPage from './pages/DashboardPage'
import ExercisesPage from './pages/ExercisesPage'
import HowWeBuildPage from './pages/HowWeBuildPage'
import LegalPage from './pages/LegalPage'
import QuizPage from './pages/QuizPage'
import SettingsPage from './pages/SettingsPage'
import { usePath } from './router'
import './App.css'

const PAGES: Record<string, () => JSX.Element> = {
  '/': DashboardPage,
  '/content': ContentPage,
  '/build': BuildPage,
  '/faves': () => <ExercisesPage initialTab="faves" />,
  '/exercises': () => <ExercisesPage />,
  '/settings': SettingsPage,
  '/quiz': QuizPage, // reached from the dashboard and sign-up, not the nav
  '/legal': LegalPage, // linked from the footer on every page
  '/how-we-build': HowWeBuildPage, // public; linked from the plan on the Dashboard and Your Plan page
}

// Only pages that exist get a nav link (no Calendar yet).
const NAV: { path: string; label: string }[] = [
  { path: '/', label: 'Dashboard' },
  { path: '/content', label: 'Your Plan & Basics' },
  { path: '/build', label: 'Build Your Own' },
  { path: '/faves', label: 'My Faves' },
  { path: '/exercises', label: 'Exercise Library' },
  { path: '/settings', label: 'Settings' },
]

function SourcesFooter({ sources }: { sources: Source[] }) {
  return (
    <div className="sources">
      <h2>Data &amp; Sources</h2>
      <ul>
        {sources.map((s) => (
          <li key={s.id}>
            {s.url ? (
              <a href={s.url} target="_blank" rel="noopener noreferrer">
                {s.name}
              </a>
            ) : (
              <span className="source-name">{s.name}</span>
            )}{' '}
            <span className={`status status-${s.status}`}>{s.status}</span>
            <br />
            <span className="source-detail">
              License: {s.license} · Used for: {s.used_for}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function App() {
  const path = usePath()
  const [sources, setSources] = useState<Source[]>([])

  useEffect(() => {
    fetchSources()
      .then(setSources)
      .catch(() => setSources([]))
  }, [])

  const Page = PAGES[path]

  return (
    <div className="page">
      <header className="site-header">
        <div className="header-inner">
          <h1 className="brand">
            <Link to="/">
              <span className="brand-mark" aria-hidden="true">
                ♥
              </span>
              HomeBase Fit
            </Link>
          </h1>
          <nav aria-label="Main">
            {NAV.map((p) => (
              <Link key={p.path} to={p.path} className={p.path === path ? 'nav-link active' : 'nav-link'}>
                {p.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main key={path} className="page-enter">
        {Page ? (
          <Page />
        ) : (
          <p>
            Page not found. <Link to="/">Go to the dashboard</Link>
          </p>
        )}
      </main>

      <footer>
        <SourcesFooter sources={sources} />
        <DisclaimerBar />
      </footer>
    </div>
  )
}
