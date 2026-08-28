import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../lib/api'
import { useAsync } from '../../lib/useAsync'
import { EmptyState, ErrorState, Loading } from '../ui'
import { QueueCard } from './QueueCard'

/**
 * The officer's home screen: a ranked list, one action per row, nothing else.
 * "Nothing to review" is a designed state, not a blank panel.
 */
export function VerificationQueue() {
  const [includeReviewed, setIncludeReviewed] = useState(false)
  const { data, loading, error, reload } = useAsync(
    () => api.queue({ include_reviewed: includeReviewed }),
    [includeReviewed],
  )

  if (loading && !data) return <Loading label="Loading the review queue…" rows={4} />
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (!data) return null

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <p className="hint" style={{ margin: 0 }}>
          {data.pending} awaiting review · {data.reviewed} already dealt with
        </p>
        <button type="button" className="chip" onClick={() => setIncludeReviewed((v) => !v)}>
          {includeReviewed ? 'Hide reviewed' : 'Show reviewed too'}
        </button>
      </div>

      {data.items.length === 0 ? (
        data.reviewed > 0 ? (
          <EmptyState
            title="Nothing left to review"
            action={
              <button type="button" className="btn" onClick={() => setIncludeReviewed(true)}>
                Show what has been reviewed
              </button>
            }
          >
            Every flagged water-loss event has had a decision recorded against it. New
            events appear here after the next satellite run.
          </EmptyState>
        ) : (
          <EmptyState
            title="No water loss flagged"
            action={
              <Link className="btn" to="/map">
                Back to the map
              </Link>
            }
          >
            No pond in the East Kolkata Wetlands has lost more water than its own
            seasonal pattern accounts for. That is a good result, not an error.
          </EmptyState>
        )
      ) : (
        <div className="queue">
          {data.items.map((anomaly) => (
            <QueueCard key={anomaly.id} anomaly={anomaly} />
          ))}
        </div>
      )}
    </div>
  )
}
