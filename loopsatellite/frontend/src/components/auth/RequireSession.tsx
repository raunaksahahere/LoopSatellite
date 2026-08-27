import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useSession } from '../../lib/session'
import { Loading } from '../ui'

/**
 * The route guard.
 *
 * This decides what *renders*. It is JavaScript on the visitor's machine and a
 * debugger steps over it in a second, so it guards nothing on its own. Every
 * protected API route verifies the session itself in `backend/app/core/auth.py`.
 * This exists so a signed-out visitor sees a sensible page instead of a screen
 * full of 401s.
 */
export function RequireSession({ children }: { children: ReactNode }) {
  const { status } = useSession()
  const location = useLocation()

  // Never redirect on 'loading'. Doing so bounces a signed-in officer to the
  // front door on every hard refresh, before the session has resolved.
  if (status === 'loading') {
    return (
      <div className="page">
        <Loading label="Checking your session" rows={2} />
      </div>
    )
  }

  if (status === 'signed-out') {
    // `from` lets the front door send them back where they were headed.
    return <Navigate to="/welcome" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
