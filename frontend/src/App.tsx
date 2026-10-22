import { type JSX } from 'react'
import { DisclaimerBar } from './components/Legal'
import Link from './components/Link'
import AboutPage from './pages/AboutPage'
import BuildPage from './pages/BuildPage'
import CalendarPage from './pages/CalendarPage'
import ContentPage from './pages/ContentPage'
import DashboardPage from './pages/DashboardPage'
import ExercisesPage from './pages/ExercisesPage'
import HowWeBuildPage from './pages/HowWeBuildPage'
import LegalPage from './pages/LegalPage'
import PregnancySupportPage from './pages/PregnancySupportPage'
import QuizPage from './pages/QuizPage'
import SettingsPage from './pages/SettingsPage'
import { usePath } from './router'
import './App.css'

const PAGES: Record<string, () => JSX.Element> = {
  '/': DashboardPage,
  '/content': ContentPage,
  '/build': BuildPage,
  '/calendar': CalendarPage,
  '/faves': () => <ExercisesPage initialTab="faves" />,
  '/exercises': () => <ExercisesPage />,
  '/settings': SettingsPage,
  '/quiz': QuizPage, // reached from the dashboard and sign-up, not the nav
  '/legal': LegalPage, // linked from the footer on every page
  '/about': AboutPage, // public; the class-project disclaimer, the data and its sources, the team
  '/how-we-build': HowWeBuildPage, // public; linked from the plan on the Dashboard and Your Plan page
  '/pregnancy-support': PregnancySupportPage, // pregnant / postpartum users are sent here (quiz, Dashboard, blocks)
}

// Only pages that exist get a nav link.
const NAV: { path: string; label: string }[] = [
  { path: '/', label: 'Dashboard' },
  { path: '/content', label: 'Your Plan & Basics' },
  { path: '/calendar', label: 'Calendar' },
  { path: '/build', label: 'Build Your Own' },
  { path: '/faves', label: 'My Faves' },
  { path: '/exercises', label: 'Exercise Library' },
  { path: '/settings', label: 'Settings' },
  { path: '/about', label: 'About' },
]

export default function App() {
  const path = usePath()

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

      {/* Sources and data credits live on the About page now; contextual review tags stay where they apply. */}
      <footer>
        <DisclaimerBar />
      </footer>
    </div>
  )
}
