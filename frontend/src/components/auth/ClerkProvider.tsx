import { ClerkProvider as ClerkReactProvider, useAuth } from '@clerk/clerk-react'
import { useEffect, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { CLERK_PUBLISHABLE_KEY, authConfigured, setTokenGetter } from '../../lib/auth'

/**
 * Publishes Clerk's `getToken` to the plain API module.
 *
 * `lib/api.ts` has no hooks and no React context, but the only supported way to
 * read a Clerk token is `useAuth().getToken()`. One component bridges the two
 * rather than threading a client through every call site.
 */
function ClerkTokenBridge({ children }: { children: ReactNode }) {
  const { getToken, isLoaded } = useAuth()

  useEffect(() => {
    if (!isLoaded) return
    setTokenGetter(() => getToken())
    return () => setTokenGetter(null)
  }, [getToken, isLoaded])

  return <>{children}</>
}

/**
 * Wraps the app in Clerk — or doesn't.
 *
 * With no publishable key this renders its children untouched. That is the
 * local-development state the backend mirrors: `CLERK_ISSUER` unset means the
 * API runs open and says so at /api/health. Rendering ClerkProvider with an
 * empty key throws on mount and takes the whole app down, which is a worse
 * failure than running open and being honest about it.
 */
export function AppClerkProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()

  if (!authConfigured) return <>{children}</>

  return (
    <ClerkReactProvider
      publishableKey={CLERK_PUBLISHABLE_KEY}
      // Keep sign-in inside the SPA rather than a full page load.
      routerPush={(to) => navigate(to)}
      routerReplace={(to) => navigate(to, { replace: true })}
      afterSignOutUrl="/"
    >
      <ClerkTokenBridge>{children}</ClerkTokenBridge>
    </ClerkReactProvider>
  )
}
