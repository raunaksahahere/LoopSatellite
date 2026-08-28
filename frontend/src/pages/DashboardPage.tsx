import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { AreaStatusCard } from '../components/areas/AreaStatusCard'
import { NLQueryBar } from '../components/llm/NLQueryBar'
import { LocationRadiusPicker } from '../components/map/LocationRadiusPicker'
import type { RadiusSelection } from '../components/map/LocationRadiusPicker'
import { MapView } from '../components/map/MapView'
import type { Circle } from '../components/map/MapView'
import { ErrorState, Loading } from '../components/ui'
import { api } from '../lib/api'
import type { NLQueryResponse } from '../lib/types'
import { useAsync } from '../lib/useAsync'

type Mode = 'ask' | 'monitor'

/**
 * The map is the anchor of the app: every other view is reachable from here and
 * returns here. Ponds are coloured by the worst confidence band flagged against
 * them, so the eye lands on the cases that matter before reading anything.
 *
 * Two things happen on this screen, and they are kept apart on purpose:
 *
 *   Ask       a question about areas already measured. Answers immediately.
 *   Monitor   a new area nobody has looked at. Starts a job that takes minutes.
 *
 * They are one tab apart rather than one button apart, because an officer who
 * confuses them either waits for an answer they could have had instantly, or
 * expects an instant answer to something that cannot be instant.
 */
export function DashboardPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('ask')
  const [queryResult, setQueryResult] = useState<NLQueryResponse | null>(null)
  const [selection, setSelection] = useState<RadiusSelection | null>(null)
  const [submittedAreaId, setSubmittedAreaId] = useState<string | null>(null)
  const { data, loading, error, reload } = useAsync(() => api.ponds(), [])

  const highlighted = useMemo(
    () => (queryResult ? [...new Set(queryResult.results.map((r) => r.pond_id))] : undefined),
    [queryResult],
  )

  // One circle overlay, from whichever mode is driving.
  const circle: Circle | null = useMemo(() => {
    if (mode === 'monitor' && selection) {
      return { lat: selection.lat, lon: selection.lon, radiusKm: selection.radiusKm }
    }
    if (mode === 'ask' && queryResult?.place && queryResult.radius_km) {
      return {
        lat: queryResult.place.lat,
        lon: queryResult.place.lon,
        radiusKm: queryResult.radius_km,
      }
    }
    return null
  }, [mode, selection, queryResult])

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
          circle={circle}
          focus={mode === 'ask' ? circle : null}
          onPickPoint={
            mode === 'monitor'
              ? (lat, lon) =>
                  setSelection({
                    name: `Area at ${lat.toFixed(3)}, ${lon.toFixed(3)}`,
                    lat,
                    lon,
                    radiusKm: selection?.radiusKm ?? 5,
                  })
              : undefined
          }
        />
      </div>

      <div className="mapshell__overlay">
        <div className="modeswitch" role="tablist" aria-label="What do you want to do?">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'ask'}
            className="modeswitch__tab"
            onClick={() => setMode('ask')}
          >
            Ask about an area
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'monitor'}
            className="modeswitch__tab"
            onClick={() => setMode('monitor')}
          >
            Monitor a new area
          </button>
        </div>

        {mode === 'ask' ? (
          <NLQueryBar onResult={setQueryResult} />
        ) : (
          <>
            <LocationRadiusPicker
              selection={selection}
              onChange={setSelection}
              onSubmitted={setSubmittedAreaId}
            />
            {submittedAreaId && (
              <AreaStatusCard
                areaId={submittedAreaId}
                onDone={() => {
                  setSelection(null)
                  reload()
                }}
              />
            )}
          </>
        )}

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
