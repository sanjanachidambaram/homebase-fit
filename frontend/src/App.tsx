import { type JSX } from 'react'
import { DisclaimerBar } from './components/Legal'
import Link from './components/Link'
import AboutDataPage from './pages/AboutDataPage'
import AboutPage from './pages/AboutPage'
import BuildPage from './pages/BuildPage'
import CalendarPage from './pages/CalendarPage'
import ContentPage from './pages/ContentPage'
import DashboardPage from './pages/DashboardPage'
import ExercisesPage from './pages/ExercisesPage'
import HowWeBuildPage from './pages/HowWeBuildPage'
import LegalPage from './pages/LegalPage'
import PlanReviewPage from './pages/PlanReviewPage'
import PregnancySupportPage from './pages/PregnancySupportPage'
import QuizPage from './pages/QuizPage'
import SettingsPage from './pages/SettingsPage'
import { usePath, useScrollToTopOnRouteChange } from './router'
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
  '/about': AboutPage, // public; Sanjana's essay (verbatim), her class-project disclaimer, the team
  '/about/data': AboutDataPage, // public; live data figures and every source (linked from About and the footer)
  '/plan/review': PlanReviewPage, // review mode: swap exercises before the plan goes on the calendar
  '/how-we-build': HowWeBuildPage, // public; linked from the plan on the Dashboard and Your Plan page
  '/pregnancy-support': PregnancySupportPage, // pregnant / postpartum users are sent here (quiz, Dashboard, blocks)
}

// Only pages that exist get a nav link.
// About sits right after Dashboard. My Faves lives inside the Exercise Library (a subtab), not in the nav.
const NAV: { path: string; label: string; also?: (path: string) => boolean }[] = [
  { path: '/', label: 'Dashboard' },
  { path: '/about', label: 'About', also: (p) => p.startsWith('/about/') },
  { path: '/content', label: 'Your Plan & Basics' },
  { path: '/calendar', label: 'Calendar' },
  { path: '/build', label: 'Build Your Own' },
  { path: '/exercises', label: 'Exercise Library', also: (p) => p === '/faves' },
  { path: '/settings', label: 'Settings' },
]


export default function App() {
  const path = usePath()
  useScrollToTopOnRouteChange(path)

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
              <Link
                key={p.path}
                to={p.path}
                className={p.path === path || p.also?.(path) ? 'nav-link active' : 'nav-link'}
              >
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
