import { useEffect, useState } from 'react'
import { fetchSources, type Source } from './api'
import { DisclaimerBar } from './components/Legal'
import ContentPage from './pages/ContentPage'
import ExercisesPage from './pages/ExercisesPage'
import LegalPage from './pages/LegalPage'
import QuizPage from './pages/QuizPage'
import SettingsPage from './pages/SettingsPage'
import Link from './components/Link'
import { usePath } from './router'
import './App.css'

const PAGES: { path: string; label: string; element: () => React.JSX.Element }[] = [
  { path: '/', label: 'Exercises', element: ExercisesPage },
  { path: '/quiz', label: 'Quiz', element: QuizPage },
  { path: '/content', label: 'Programs & Basics', element: ContentPage },
  { path: '/settings', label: 'Settings', element: SettingsPage },
  { path: '/legal', label: 'Legal', element: LegalPage },
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

  const page = PAGES.find((p) => p.path === path)
  const Page = page?.element

  return (
    <div className="page">
      <header className="site-header">
        <h1>
          <Link to="/">HomeBase Fit</Link>
        </h1>
        <nav>
          {PAGES.map((p) => (
            <Link key={p.path} to={p.path} className={p.path === path ? 'active' : ''}>
              {p.label}
            </Link>
          ))}
        </nav>
      </header>

      <main>
        {Page ? (
          <Page />
        ) : (
          <p>
            Page not found. <Link to="/">Go home</Link>
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
