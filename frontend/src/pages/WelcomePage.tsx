import { SignIn, SignUp } from '@clerk/clerk-react'
import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'

import { authConfigured } from '../lib/auth'
import { useSession } from '../lib/session'
import { Loading, Note } from '../components/ui'

/**
 * Clerk's widget on a light card, in both themes.
 *
 * It shipped unreadable: the front door panel is `--surface`, which is #16211f
 * under a dark system theme, and Clerk's default appearance drew its own dark
 * text straight onto it. The headings and field labels were very nearly
 * invisible while the inputs and its footer stayed white — a form nobody could
 * fill in.
 *
 * Rather than theme the widget twice and re-check both, the card is pinned
 * light and the colours are set explicitly. Measured against white: body ink
 * 16.5:1, muted 7.3:1, the accent 6.0:1, and white on the accent button 6.0:1 —
 * all clear AAA except the button, which is AA at its size. The surrounding
 * panel stays dark, so the form reads as an inset card rather than a theme
 * that lost an argument with itself.
 */
const CLERK_APPEARANCE = {
  variables: {
    colorBackground: '#ffffff',
    colorText: '#16211f',
    colorTextSecondary: '#4a5a57',
    colorInputBackground: '#ffffff',
    colorInputText: '#16211f',
    colorPrimary: '#0f6f6c',
    colorTextOnPrimaryBackground: '#ffffff',
    colorNeutral: '#16211f',
    borderRadius: '8px',
  },
  elements: {
    rootBox: { width: '100%' },
    card: { boxShadow: 'none', border: 'none', background: 'transparent' },
  },
} as const

/**
 * The sign-in door at /welcome.
 *
 * One way in, and it has two halves: sign in, or create an account. The
 * "Continue as demo" button that used to sit here is gone. It existed because a
 * visitor with no account had no way in at all; Clerk offers sign-up, so the
 * reason is gone — and with it a header that let anyone read the entire API
 * without ever having an account.
 *
 * The public homepage at / is what a visitor sees before this, and it explains
 * the product. This page has one job.
 *
 * Accessibility is Clerk's here rather than ours: <SignIn /> ships a labelled,
 * keyboard-navigable form with its own error handling, and reimplementing that
 * around their API would be a worse form with the same behaviour.
 */
export function WelcomePage() {
  const location = useLocation()
  const { status } = useSession()
  const [mode, setMode] = useState<'sign-in' | 'sign-up'>('sign-in')

  // '/' is the public homepage, so a successful sign-in must not land back on
  // it — that reads as "nothing happened".
  const destination = (location.state as { from?: string } | null)?.from || '/map'

  if (status === 'loading') {
    return (
      <main className="frontdoor">
        <div className="frontdoor__col">
          <Loading label="Checking your session" rows={2} />
        </div>
      </main>
    )
  }

  if (status === 'signed-in') return <Navigate to={destination} replace />

  return (
    <main className="frontdoor">
      <div className="frontdoor__col">
        <header className="frontdoor__masthead">
          <p className="frontdoor__kicker">LOOP ERRORS · SP-01</p>
          <h1 className="frontdoor__title">LoopSatellite</h1>
          <p className="frontdoor__purpose">
            Telling the difference between a wetland pond that shrank because
            it's April and one that shrank because someone filled it in.
          </p>
        </header>

        {!authConfigured ? (
          <Note tone="warn">
            {/* On the gradient now, not inside a light panel. */}
            Sign-in is not configured on this deployment, so the API is running
            open. Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> here and{' '}
            <code>CLERK_ISSUER</code> on the API to switch it on.
          </Note>
        ) : (
          <>
            <div className="frontdoor__tabs" role="tablist" aria-label="Sign in or create an account">
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'sign-in'}
                className={mode === 'sign-in' ? 'is-active' : ''}
                onClick={() => setMode('sign-in')}
              >
                Sign in
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'sign-up'}
                className={mode === 'sign-up' ? 'is-active' : ''}
                onClick={() => setMode('sign-up')}
              >
                Create an account
              </button>
            </div>

            <div className="frontdoor__clerk">
              {mode === 'sign-in' ? (
                <SignIn
                  routing="virtual"
                  signUpUrl="/welcome"
                  forceRedirectUrl={destination}
                  appearance={CLERK_APPEARANCE}
                />
              ) : (
                <SignUp
                  routing="virtual"
                  signInUrl="/welcome"
                  forceRedirectUrl={destination}
                  appearance={CLERK_APPEARANCE}
                />
              )}
            </div>
          </>
        )}

        <Link className="frontdoor__aside" to="/">
          ← What is this?
        </Link>
      </div>
    </main>
  )
}
