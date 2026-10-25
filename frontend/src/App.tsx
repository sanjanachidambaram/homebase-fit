import { useLayoutEffect, type JSX } from 'react'
import BeeLogo from './components/BeeLogo'
import { DisclaimerBar } from './components/Legal'
import Link from './components/Link'
import AboutDataPage from './pages/AboutDataPage'
import AboutPage from './pages/AboutPage'
import AuthCallbackPage from './pages/AuthCallbackPage'
import BuildPage from './pages/BuildPage'
import CalendarPage from './pages/CalendarPage'
import DashboardPage from './pages/DashboardPage'
import ExercisesPage from './pages/ExercisesPage'
import HowWeBuildPage from './pages/HowWeBuildPage'
import LegalPage from './pages/LegalPage'
import PlanPage from './pages/PlanPage'
import PlanReviewPage from './pages/PlanReviewPage'
import PregnancySupportPage from './pages/PregnancySupportPage'
import QuizPage from './pages/QuizPage'
import SettingsPage from './pages/SettingsPage'
import { usePath, useRouteKey, useScrollToTopOnRouteChange } from './router'
import './App.css'

/** An old address that moved: swap it in the address bar, so Back doesn't bounce. */
function Moved({ to }: { to: string }) {
  useLayoutEffect(() => {
    window.history.replaceState({}, '', to)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, [to])
  return <></>
}

const PAGES: Record<string, () => JSX.Element> = {
  '/': DashboardPage,
  '/plan': PlanPage, // "Your Personalized Plan": the generated week only
  '/content': () => <Moved to="/plan" />, // the old combined "Your Plan & Basics" page (2026-10-23)
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
  '/how-we-build': HowWeBuildPage, // public; linked from the plan on the Dashboard and Your Personalized Plan
  '/pregnancy-support': PregnancySupportPage, // pregnant / postpartum users are sent here (quiz, Dashboard, blocks)
  '/auth/callback': AuthCallbackPage, // where Google / Microsoft sign-in lands (app/oauth.py); not in the nav
}

// Only pages that exist get a nav link. The order (2026-10-25): Dashboard, About, Personalized Plan, Calendar, Build
// Your Own, Exercise Library, Settings. My Faves lives inside the Exercise Library (a subtab), not in the nav.
const NAV: { path: string; label: string; also?: (path: string) => boolean }[] = [
  { path: '/', label: 'Dashboard' },
  { path: '/about', label: 'About', also: (p) => p.startsWith('/about/') },
  { path: '/plan', label: 'Personalized Plan', also: (p) => p === '/plan/review' },
  { path: '/calendar', label: 'Calendar' },
  { path: '/build', label: 'Build Your Own' },
  { path: '/exercises', label: 'Exercise Library', also: (p) => p === '/faves' },
  { path: '/settings', label: 'Settings' },
]


export default function App() {
  const path = usePath()
  const routeKey = useRouteKey(path)
  useScrollToTopOnRouteChange(path)

  const Page = PAGES[path]

  return (
    <div className="page">
      <header className="site-header">
        <div className="header-inner">
          {/* The logo goes home: the Dashboard when signed in, the landing page when signed out (both live at /).
              From the home page itself it starts the page over at the top (router.ts navigate). */}
          <h1 className="brand">
            <Link to="/" ariaLabel="Bee Fit home">
              <span className="brand-mark" aria-hidden="true">
                <BeeLogo size={40} />
              </span>
              Bee Fit
            </Link>
          </h1>
          <nav aria-label="Main">
            {NAV.map((p) => {
              // Whichever tab matches the page being viewed (or one of its sub-pages) is highlighted (orange).
              // Dashboard also always carries a green underline, whatever page is active: a fixed marker, not a state.
              const active = p.path === path || !!p.also?.(path)
              const className = ['nav-link', p.path === '/' && 'nav-home', active && 'active'].filter(Boolean).join(' ')
              return (
                <Link key={p.path} to={p.path} className={className} current={active}>
                  {p.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>

      <main key={routeKey} className="page-enter">
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
