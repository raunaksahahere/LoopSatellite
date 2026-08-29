import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { AreaStatusCard } from '../components/areas/AreaStatusCard'
import { NLQueryBar } from '../components/llm/NLQueryBar'
import { LocationRadiusPicker } from '../components/map/LocationRadiusPicker'
import type { RadiusSelection } from '../components/map/LocationRadiusPicker'
import { MapView } from '../components/map/MapView'
import type { Circle } from '../components/map/MapView'
import { ErrorState, Loading } from '../components/ui'
import { api } from '../lib/api'
import type { NLQueryResponse, PondCollection } from '../lib/types'
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
  const [areaPonds, setAreaPonds] = useState<PondCollection | null>(null)
  // Bumped when a job reaches a terminal state, to re-fetch what it measured.
  const [areaVersion, setAreaVersion] = useState(0)
  const { data, loading, error, reload } = useAsync(() => api.ponds(), [])

  // Water bodies a submitted area measured.
  //
  // The base map is the precomputed bundle and only that, so an area could
  // finish, report "2 water bodies · 4 unexplained water losses", and draw
  // nothing — leaving the result on a card next to a map that disagreed with it.
  // These are merged into the same layer so they colour by confidence like
  // everything else.
  useEffect(() => {
    if (!submittedAreaId) {
      setAreaPonds(null)
      return
    }
    let cancelled = false
    api
      .areaWaterbodies(submittedAreaId)
      .then((fc) => {
        if (!cancelled) setAreaPonds(fc.features.length ? fc : null)
      })
      .catch(() => {
        // Not fatal: the card still reports the result. Nothing to say here.
        if (!cancelled) setAreaPonds(null)
      })
    return () => {
      cancelled = true
    }
  }, [submittedAreaId, areaVersion])

  const highlighted = useMemo(
    () => (queryResult ? [...new Set(queryResult.results.map((r) => r.pond_id))] : undefined),
    [queryResult],
  )

  // One collection for the map: the bundle, plus anything a submitted area
  // measured. Same shape, same properties, so one layer renders both.
  const mapPonds: PondCollection | null = useMemo(() => {
    if (!data) return null
    if (!areaPonds) return data
    return { ...data, features: [...data.features, ...areaPonds.features] }
  }, [data, areaPonds])

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
          ponds={mapPonds ?? data}
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
                  // The job only just wrote its water bodies; fetch them again
                  // now there is something to fetch.
                  setAreaVersion((n) => n + 1)
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
