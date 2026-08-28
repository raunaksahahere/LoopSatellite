import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { signOut } from '../../lib/auth'
import { useSession } from '../../lib/session'

export function SignOutButton() {
  const { status, isDemo, email } = useSession()
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  if (status !== 'signed-in') return null

  return (
    <button
      type="button"
      className="chip"
      disabled={busy}
      title={isDemo ? 'Demo session — you can look, but not record anything' : (email ?? undefined)}
      onClick={async () => {
        setBusy(true)
        try {
          await signOut()
          navigate('/welcome', { replace: true })
        } finally {
          setBusy(false)
        }
      }}
    >
      {isDemo ? 'Leave demo' : 'Sign out'}
    </button>
  )
}
