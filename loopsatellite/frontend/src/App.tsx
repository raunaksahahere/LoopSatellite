import { NavLink, Route, Routes } from 'react-router-dom'

import { DashboardPage } from './pages/DashboardPage'
import { PondDetailPage } from './pages/PondDetailPage'
import { QueuePage } from './pages/QueuePage'
import { EmptyState, Note } from './components/ui'
import { api } from './lib/api'
import { useAsync } from './lib/useAsync'

export default function App() {
  const { data: health } = useAsync(() => api.health(), [])

  return (
    <div className="app">
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
          </nav>
        </div>
      </header>

      {health?.data.is_synthetic && (
        <div className="banner">
          <div className="banner__inner">
            Demonstration data — these pond boundaries and measurements are synthetic.
            Do not act on them.
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
          <Route path="/" element={<DashboardPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/pond/:pondId" element={<PondDetailPage health={health} />} />
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
