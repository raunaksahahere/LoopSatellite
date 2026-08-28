/**
 * Clerk, for a Vite SPA.
 *
 * Sign-in *and* sign-up. That is the change that let the demo door go: the door
 * existed because a visitor with no account had no way in at all, and now they
 * can make one in thirty seconds.
 *
 * **This gate decides what renders, not what is served.** It runs on the
 * visitor's machine and a debugger steps straight over it. Every protected API
 * route verifies the token itself in `backend/app/core/auth.py`; that is the real
 * boundary, and this is the polite version of it.
 *
 * The token is fetched per request rather than held in a module variable. Clerk
 * session tokens are short-lived by design — around a minute — and a cached one
 * is a 401 in the middle of an officer's work.
 */

/**
 * Blank until a Clerk application is wired up. Everything below degrades to
 * "signed out, and say why" rather than throwing, so the app still builds and
 * runs before that happens.
 */
export const CLERK_PUBLISHABLE_KEY: string =
  import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ?? ''

export const authConfigured = Boolean(CLERK_PUBLISHABLE_KEY)

/**
 * Set by `ClerkTokenBridge` once Clerk has mounted.
 *
 * `api.ts` is a plain module — it has no hooks and no React context — but the
 * only supported way to read a Clerk token is `useAuth().getToken()`. Rather
 * than thread a client through every call site, one component publishes the
 * getter here and the API layer reads it.
 *
 * Null before Clerk mounts and after sign-out, which is correct in both cases:
 * requests then carry no Authorization header and the API answers 401.
 */
let tokenGetter: (() => Promise<string | null>) | null = null

export function setTokenGetter(getter: (() => Promise<string | null>) | null): void {
  tokenGetter = getter
}

export async function sessionToken(): Promise<string | null> {
  if (!tokenGetter) return null
  try {
    return await tokenGetter()
  } catch {
    return null
  }
}

/**
 * What to put on an API request. Nothing is sent when there is no session, and
 * the API answers 401 — which is the correct thing for it to do.
 */
export async function sessionHeaders(): Promise<Record<string, string>> {
  const token = await sessionToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
