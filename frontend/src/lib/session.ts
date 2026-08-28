import { useAuth, useUser } from '@clerk/clerk-react'

import { authConfigured } from './auth'

export type SessionStatus = 'loading' | 'signed-in' | 'signed-out'

export interface Session {
  status: SessionStatus
  email: string | null
  name: string | null
}

/**
 * Whether this tab has a session.
 *
 * Three states rather than two, and 'loading' is load-bearing: redirecting on it
 * bounces a signed-in officer to the front door on every hard refresh, before
 * Clerk has had a chance to resolve.
 *
 * There is no `isDemo` any more. The read-only demo principal is gone from both
 * ends — see backend/app/core/auth.py.
 */
export function useSession(): Session {
  const { isLoaded, isSignedIn } = useAuth()
  const { user } = useUser()

  // No Clerk key: nothing to wait for and nothing to sign into. The API is open
  // in that state and says so, so the UI treats it as signed in rather than
  // showing a door that leads nowhere.
  if (!authConfigured) return { status: 'signed-in', email: null, name: null }

  if (!isLoaded) return { status: 'loading', email: null, name: null }

  return {
    status: isSignedIn ? 'signed-in' : 'signed-out',
    email: user?.primaryEmailAddress?.emailAddress ?? null,
    name: user?.fullName ?? null,
  }
}
