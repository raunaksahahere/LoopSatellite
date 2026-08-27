import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { authConfigured, beginDemoSession, signInWithPassword } from '../lib/auth'
import { Note } from '../components/ui'

/**
 * The front door.
 *
 * Two ways in, and which ones appear depends on the deployment:
 *
 *   Sign in         a real operator. Can record verifications and start
 *                   monitoring new areas.
 *   Continue as demo  read everything, write nothing. Shown when sign-in is not
 *                   configured, because a deployment with no auth server and no
 *                   way in would be a locked building with the keys inside.
 *
 * The demo door is not a hole. `backend/app/core/auth.py` gives it a distinct
 * read-only principal and refuses it on the two routes that cost something:
 * recording a verdict, and submitting an area — which spends Earth Engine quota
 * against a personal token.
 */
export function WelcomePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const destination = (location.state as { from?: string } | null)?.from || '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signInWithPassword(email, password)
      navigate(destination, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign you in.')
    } finally {
      setBusy(false)
    }
  }

  function enterDemo() {
    beginDemoSession()
    navigate(destination, { replace: true })
  }

  return (
    <main className="frontdoor">
      <div className="frontdoor__panel">
        <p className="frontdoor__kicker">LOOP ERRORS · SP-01</p>
        <h1 className="frontdoor__title">LoopSatellite</h1>
        <p className="frontdoor__purpose">
          Telling the difference between a wetland pond that shrank because it's
          April and one that shrank because someone filled it in.
        </p>

        {authConfigured ? (
          <>
            <form className="frontdoor__form" onSubmit={submit} noValidate>
              <label className="label" htmlFor="signin-email">
                Email
              </label>
              <input
                id="signin-email"
                className="input"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={error ? true : undefined}
              />

              <label className="label" htmlFor="signin-password" style={{ marginTop: '0.7rem' }}>
                Password
              </label>
              <input
                id="signin-password"
                className="input"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />

              {error && (
                <div style={{ marginTop: '0.75rem' }}>
                  <Note tone="error">{error}</Note>
                </div>
              )}

              <button
                type="submit"
                className="btn btn--primary btn--block"
                style={{ marginTop: '1rem' }}
                disabled={busy}
              >
                {busy ? 'Signing in…' : 'Sign in'}
              </button>
            </form>

            <button type="button" className="frontdoor__demo" onClick={enterDemo}>
              Continue as demo
            </button>
            <p className="frontdoor__note">
              A demo session sees every finding but cannot record a review or start
              monitoring a new area.
            </p>
          </>
        ) : (
          <>
            <p className="frontdoor__note" role="status">
              Sign-in is not configured on this deployment, so everything runs in
              demo mode.
            </p>
            <button
              type="button"
              className="btn btn--primary btn--block"
              style={{ marginTop: '1rem' }}
              onClick={enterDemo}
            >
              Continue as demo
            </button>
          </>
        )}

        <Link className="frontdoor__aside" to="/data-sources">
          How do we know this works on real data? →
        </Link>
      </div>
    </main>
  )
}
