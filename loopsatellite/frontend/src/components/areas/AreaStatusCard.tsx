import { useEffect, useState } from 'react'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { Area } from '../../lib/types'
import { Note } from '../ui'

const POLL_MS = 5000

const STATUS_BADGE: Record<Area['status'], string> = {
  pending: 'badge--neutral',
  processing: 'badge--medium',
  ready: 'badge--low',
  failed: 'badge--high',
}

const STATUS_LABEL: Record<Area['status'], string> = {
  pending: 'Queued',
  processing: 'Working',
  ready: 'Ready',
  failed: 'Could not process',
}

/**
 * Progress on an area somebody asked us to start monitoring.
 *
 * Deliberately not a spinner. A spinner promises "any second now"; this promises
 * minutes and explains why, because the honest answer is that separating
 * encroachment from the dry season needs years of history and no amount of
 * engineering makes that instant.
 */
export function AreaStatusCard({ areaId, onDone }: { areaId: string; onDone?: (a: Area) => void }) {
  const [area, setArea] = useState<Area | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    async function poll() {
      try {
        const next = await api.area(areaId)
        if (cancelled) return
        setArea(next)
        setError(null)
        if (next.status === 'ready' || next.status === 'failed') {
          onDone?.(next)
          return // terminal — stop polling
        }
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      }
      timer = setTimeout(poll, POLL_MS)
    }

    void poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaId])

  if (error && !area) {
    return (
      <div className="card">
        <Note tone="error">{error}</Note>
      </div>
    )
  }
  if (!area) {
    return (
      <div className="card">
        <div className="skeleton" style={{ height: 64 }} />
      </div>
    )
  }

  const working = area.status === 'pending' || area.status === 'processing'

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ fontSize: '1rem' }}>{area.name}</h2>
        <span className={`badge ${STATUS_BADGE[area.status]}`}>
          <span className="badge__dot" aria-hidden="true" />
          {STATUS_LABEL[area.status]}
        </span>
      </div>

      <p style={{ margin: '0.5rem 0 0.25rem' }} aria-live="polite">
        {area.headline}
      </p>

      {working && (
        <>
          <div
            role="progressbar"
            aria-label="Processing this area"
            style={{
              height: 6,
              borderRadius: 3,
              overflow: 'hidden',
              background: 'var(--surface-2)',
              margin: '0.6rem 0',
            }}
          >
            <div
              style={{
                height: '100%',
                width: '35%',
                background: 'var(--accent)',
                animation: 'shimmer 1.6s ease-in-out infinite',
              }}
            />
          </div>
          <p className="hint" style={{ margin: 0 }}>
            {area.eta_note}
          </p>
        </>
      )}

      {area.status === 'failed' && area.error && (
        <div style={{ marginTop: '0.6rem' }}>
          <Note tone="error">{area.error}</Note>
        </div>
      )}

      {area.status === 'ready' && (
        <p className="hint" style={{ margin: '0.4rem 0 0' }}>
          {area.pond_count} water {area.pond_count === 1 ? 'body' : 'bodies'} measured
          {area.ready_at ? ` · finished ${formatDateTime(area.ready_at)}` : ''}. You can now
          ask questions about this area.
        </p>
      )}
    </div>
  )
}
