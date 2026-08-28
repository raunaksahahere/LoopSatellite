import { useEffect, useState } from 'react'

import { authClient, authConfigured, demoSessionActive, onDemoSessionChanged } from './auth'

export type SessionStatus = 'loading' | 'signed-in' | 'signed-out'

export interface Session {
  status: SessionStatus
  isDemo: boolean
  email: string | null
}

/**
 * Whether this tab has a session, and of which kind.
 *
 * Three states rather than two, and 'loading' is load-bearing: redirecting on it
 * bounces a signed-in operator to the front door on every hard refresh, before
 * the session has had a chance to resolve.
 */
export function useSession(): Session {
  const [demo, setDemo] = useState(demoSessionActive)
  const [status, setStatus] = useState<SessionStatus>(
    // With no auth server there is nothing to wait for: it is the demo flag or
    // nothing, and that is knowable synchronously.
    authConfigured ? 'loading' : demoSessionActive() ? 'signed-in' : 'signed-out',
  )
  const [email, setEmail] = useState<string | null>(null)

  useEffect(() => onDemoSessionChanged(() => setDemo(demoSessionActive())), [])

  useEffect(() => {
    let cancelled = false
    if (!authConfigured) {
      setStatus(demo ? 'signed-in' : 'signed-out')
      return
    }
    if (demo) {
      setStatus('signed-in')
      return
    }
    void (async () => {
      try {
        const session = await authClient?.getSession?.()
        if (cancelled) return
        const user = session?.data?.user ?? null
        setEmail(user?.email ?? null)
        setStatus(user ? 'signed-in' : 'signed-out')
      } catch {
        if (!cancelled) setStatus('signed-out')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [demo])

  return { status, isDemo: demo, email }
}
