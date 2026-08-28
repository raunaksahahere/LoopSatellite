import { NavLink, Route, Routes, useLocation } from 'react-router-dom'

import { RequireSession } from './components/auth/RequireSession'
import { SignOutButton } from './components/auth/SignOutButton'
import { DashboardPage } from './pages/DashboardPage'
import { DataSourcesPage } from './pages/DataSourcesPage'
import { PondDetailPage } from './pages/PondDetailPage'
import { QueuePage } from './pages/QueuePage'
import { WelcomePage } from './pages/WelcomePage'
import { EmptyState, Note } from './components/ui'
import { api } from './lib/api'
import { useAsync } from './lib/useAsync'

export default function App() {
  const { data: health } = useAsync(() => api.health(), [])
  // The front door renders without the app shell. A signed-out visitor should
  // not see a nav whose every link bounces them straight back here.
  const atFrontDoor = useLocation().pathname === '/welcome'

  return (
    <div className="app">
      {!atFrontDoor && (
      <header className="appbar">
        <div className="appbar__inner">
          <NavLink to="/" className="brand">
            LoopSatellite <small>EAST KOLKATA WETLANDS</small>
          </NavLink>
          <nav className="nav">
            <NavLink to="/" end>
              Map
            </NavLink>
            <NavLink to="/queue">
              Review
              {health?.data.anomaly_count ? ` (${health.data.anomaly_count})` : ''}
            </NavLink>
            <NavLink to="/data-sources">Data sources</NavLink>
            <SignOutButton />
          </nav>
        </div>
      </header>
      )}

      {!atFrontDoor && health?.data.is_synthetic && (
        <div className="banner">
          <div className="banner__inner">
            Demonstration data — these pond boundaries and measurements are synthetic.
            Do not act on them.{' '}
            <NavLink to="/data-sources" style={{ color: 'inherit' }}>
              See exactly what is real →
            </NavLink>
          </div>
        </div>
      )}

      {health && !health.data.precomputed && (
        <div className="page">
          <Note tone="error">
            {health.data.detail ??
              'No measurement data is loaded. Build the bundle with backend/data_pipeline/run_pipeline.sh.'}
          </Note>
        </div>
      )}

      <main className="app__main" style={{ flex: 1 }}>
        <Routes>
          {/* The front door. Public by definition — it is how you get in. */}
          <Route path="/welcome" element={<WelcomePage />} />

          {/* Public on purpose: it answers "how do we know this works on real
              data?" with a link somebody can open. The backend keeps
              /api/provenance public to match. */}
          <Route path="/data-sources" element={<DataSourcesPage />} />

          <Route
            path="/"
            element={
              <RequireSession>
                <DashboardPage />
              </RequireSession>
            }
          />
          <Route
            path="/queue"
            element={
              <RequireSession>
                <QueuePage />
              </RequireSession>
            }
          />
          <Route
            path="/pond/:pondId"
            element={
              <RequireSession>
                <PondDetailPage health={health} />
              </RequireSession>
            }
          />
          <Route
            path="*"
            element={
              <div className="page">
                <EmptyState title="Page not found">
                  That address doesn't exist. Everything in LoopSatellite is reachable
                  from the map.
                </EmptyState>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  )
}
