import { useClerk } from '@clerk/clerk-react'
import { useState } from 'react'

import { authConfigured } from '../../lib/auth'
import { useSession } from '../../lib/session'

export function SignOutButton() {
  const { status, email, name } = useSession()
  const clerk = useClerk()
  const [busy, setBusy] = useState(false)

  // Nothing to sign out of when Clerk is not configured.
  if (!authConfigured || status !== 'signed-in') return null

  return (
    <button
      type="button"
      className="chip"
      disabled={busy}
      title={name ? `${name}${email ? ` · ${email}` : ''}` : (email ?? undefined)}
      onClick={async () => {
        setBusy(true)
        try {
          await clerk.signOut({ redirectUrl: '/' })
        } finally {
          setBusy(false)
        }
      }}
    >
      Sign out
    </button>
  )
}
