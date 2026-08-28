/**
 * Neon Managed Better Auth, for a Vite SPA.
 *
 * Sign-in only. There is no sign-up call and no sign-up route: officers are added
 * directly by whoever runs the deployment.
 *
 * **This gate decides what renders, not what is served.** It runs on the
 * visitor's machine and a debugger steps straight over it. Every protected API
 * route verifies the token itself in `backend/app/core/auth.py`; that is the real
 * boundary, and this is the polite version of it.
 */
import { createAuthClient } from '@neondatabase/auth'
import { BetterAuthReactAdapter } from '@neondatabase/auth/react/adapters'

/**
 * Blank until Managed Better Auth is enabled on the Neon branch. Everything below
 * degrades to "signed out, and say why" rather than throwing, so the app still
 * builds and runs before that happens — which is the state it ships in today.
 */
export const AUTH_URL: string = import.meta.env.VITE_NEON_AUTH_URL ?? ''

export const authConfigured = Boolean(AUTH_URL)

const DEMO_SESSION_KEY = 'loopsatellite.demo-session'
const DEMO_SESSION_EVENT = 'loopsatellite-demo-session'

/** Must match `DEMO_HEADER` in backend/app/core/auth.py. */
export const DEMO_HEADER = 'X-LoopSatellite-Demo'

export const authClient = authConfigured
  ? createAuthClient(AUTH_URL, { adapter: BetterAuthReactAdapter() })
  : null

/** A tab-scoped fallback identity. It never creates a Neon Auth or database user. */
export function demoSessionActive(): boolean {
  try {
    return sessionStorage.getItem(DEMO_SESSION_KEY) === 'true'
  } catch {
    return false
  }
}

export function beginDemoSession(): void {
  try {
    sessionStorage.setItem(DEMO_SESSION_KEY, 'true')
  } catch {
    /* private window with storage blocked — the header simply won't be sent */
  }
  window.dispatchEvent(new Event(DEMO_SESSION_EVENT))
}

export function endDemoSession(): void {
  try {
    sessionStorage.removeItem(DEMO_SESSION_KEY)
  } catch {
    /* nothing to clear */
  }
  window.dispatchEvent(new Event(DEMO_SESSION_EVENT))
}

export function onDemoSessionChanged(listener: () => void): () => void {
  window.addEventListener(DEMO_SESSION_EVENT, listener)
  return () => window.removeEventListener(DEMO_SESSION_EVENT, listener)
}

/**
 * What to put on an API request. A demo tab sends the demo header; a signed-in
 * operator sends their bearer token. Neither is sent when there is no session,
 * and the API answers 401 — which is the correct thing for it to do.
 */
export async function sessionHeaders(): Promise<Record<string, string>> {
  if (demoSessionActive()) return { [DEMO_HEADER]: 'session' }
  const token = await sessionToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/**
 * The JWT for the current session, or null.
 *
 * Read fresh on every request rather than cached in a module variable: the token
 * has an expiry, and a stale one is a 401 in the middle of an officer's work.
 */
export async function sessionToken(): Promise<string | null> {
  if (!authClient) return null
  try {
    const session = await authClient.getSession()
    const data = (session as { data?: unknown })?.data ?? session
    return (
      (data as { session?: { token?: string }; token?: string })?.session?.token ??
      (data as { token?: string })?.token ??
      null
    )
  } catch {
    return null
  }
}

export async function signInWithPassword(email: string, password: string): Promise<void> {
  if (!authClient) throw new Error('Sign-in is not configured on this deployment.')
  const result = await authClient.signIn.email({ email, password })
  if (result?.error) throw new Error(result.error.message ?? 'Could not sign you in.')
}

export async function signOut(): Promise<void> {
  endDemoSession()
  await authClient?.signOut?.()
}
