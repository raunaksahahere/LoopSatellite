import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { NLQueryBar } from '../components/llm/NLQueryBar'
import { MapView } from '../components/map/MapView'
import { ErrorState, Loading } from '../components/ui'
import { api } from '../lib/api'
import type { NLQueryResponse } from '../lib/types'
import { useAsync } from '../lib/useAsync'

/**
 * The map is the anchor of the app: every other view is reachable from here and
 * returns here. Ponds are coloured by the worst confidence band flagged against
 * them, so the eye lands on the cases that matter before reading anything.
 */
export function DashboardPage() {
  const navigate = useNavigate()
  const [queryResult, setQueryResult] = useState<NLQueryResponse | null>(null)
  const { data, loading, error, reload } = useAsync(() => api.ponds(), [])

  const highlighted = useMemo(
    () => (queryResult ? [...new Set(queryResult.results.map((r) => r.pond_id))] : undefined),
    [queryResult],
  )

  if (loading && !data) {
    return (
      <div className="page">
        <Loading label="Loading the wetland map…" rows={2} />
      </div>
    )
  }
  if (error) {
    return (
      <div className="page">
        <ErrorState error={error} onRetry={reload} />
      </div>
    )
  }
  if (!data) return null

  return (
    <div className="mapshell">
      <div className="maparea">
        <MapView
          ponds={data}
          highlighted={highlighted}
          onSelect={(pondId) => navigate(`/pond/${pondId}`)}
        />
      </div>

      <div className="mapshell__overlay">
        <NLQueryBar onResult={setQueryResult} />
        <div className="maplegend">
          <span>
            <i style={{ background: '#b3261e' }} /> High confidence
          </span>
          <span>
            <i style={{ background: '#c9820f' }} /> Needs a closer look
          </span>
          <span>
            <i style={{ background: '#3f6b3a' }} /> Low confidence
          </span>
          <span>
            <i style={{ background: '#2b7fb8' }} /> Nothing flagged
          </span>
        </div>
      </div>
    </div>
  )
}
