import { useEffect, useState } from 'react'

import { api } from '../../lib/api'
import type { AreaCapability } from '../../lib/types'
import { useAction, useAsync } from '../../lib/useAsync'
import { Note } from '../ui'

const PRESETS = [1, 5, 10, 25]
const MIN_KM = 0.5
const MAX_KM = 50

export interface RadiusSelection {
  name: string
  lat: number
  lon: number
  radiusKm: number
}

/**
 * Pick a point and a radius, instead of drawing a freehand polygon.
 *
 * A circle is the right shape for this job: an officer thinks in "how far around
 * here", every officer draws the same circle for the same question, and the
 * result is two numbers that can be typed, logged and reproduced — none of which
 * is true of a hand-drawn outline.
 *
 * Everything here is client-side until "Start monitoring" is pressed. The circle
 * preview costs nothing and hits no endpoint.
 */
export function LocationRadiusPicker({
  selection,
  onChange,
  onSubmitted,
}: {
  selection: RadiusSelection | null
  onChange: (selection: RadiusSelection | null) => void
  onSubmitted?: (areaId: string) => void
}) {
  const [radiusKm, setRadiusKm] = useState(5)
  const [name, setName] = useState('')
  const capability = useAsync<AreaCapability>(() => api.areaCapability(), [])
  const submit = useAction(api.submitArea)

  // Keep the parent's circle in step with the slider.
  useEffect(() => {
    if (selection && selection.radiusKm !== radiusKm) {
      onChange({ ...selection, radiusKm })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [radiusKm])

  const canSubmit = capability.data?.can_submit ?? false

  async function start() {
    if (!selection) return
    const area = await submit.run({
      name: name.trim() || selection.name,
      lat: selection.lat,
      lon: selection.lon,
      radius_km: selection.radiusKm,
    })
    if (area) onSubmitted?.(area.id)
  }

  return (
    <div className="card">
      <h2 style={{ fontSize: '1rem', marginBottom: '0.35rem' }}>Monitor a new area</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        {selection
          ? 'Set how far around this point to look, then start monitoring.'
          : 'Tap anywhere on the map to choose a centre point.'}
      </p>

      {selection && (
        <>
          <div className="row" style={{ gap: '0.4rem', margin: '0.7rem 0 0.2rem' }}>
            <span className="badge badge--accent">
              {selection.lat.toFixed(4)}, {selection.lon.toFixed(4)}
            </span>
            <button type="button" className="chip" onClick={() => onChange(null)}>
              Clear
            </button>
          </div>

          <label className="label" htmlFor="radius-slider" style={{ marginTop: '0.8rem' }}>
            Look within <strong>{radiusKm} km</strong>
          </label>
          <div className="chips" style={{ marginBottom: '0.5rem' }}>
            {PRESETS.map((km) => (
              <button
                key={km}
                type="button"
                className="chip"
                aria-pressed={radiusKm === km}
                style={
                  radiusKm === km
                    ? { borderColor: 'var(--accent)', color: 'var(--accent)' }
                    : undefined
                }
                onClick={() => setRadiusKm(km)}
              >
                {km} km
              </button>
            ))}
          </div>
          <input
            id="radius-slider"
            type="range"
            min={MIN_KM}
            max={MAX_KM}
            step={0.5}
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
            style={{ width: '100%', height: 40 }}
          />

          <label className="label" htmlFor="area-name" style={{ marginTop: '0.6rem' }}>
            Name this area
          </label>
          <input
            id="area-name"
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={selection.name}
          />

          {capability.data && !canSubmit && (
            <div style={{ marginTop: '0.75rem' }}>
              <Note tone="warn">{capability.data.reason}</Note>
            </div>
          )}

          {submit.error && (
            <div style={{ marginTop: '0.75rem' }}>
              <Note tone="error">{submit.error.message}</Note>
            </div>
          )}

          <button
            type="button"
            className="btn btn--primary btn--block"
            style={{ marginTop: '0.8rem' }}
            disabled={!canSubmit || submit.pending}
            onClick={() => void start()}
          >
            {submit.pending ? 'Starting…' : 'Start monitoring this area'}
          </button>

          <p className="hint" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
            This takes {capability.data?.typical_duration ?? 'several minutes'} — it is not
            a question you can ask and get an answer to straight away.{' '}
            {capability.data?.why_slow}
          </p>
        </>
      )}
    </div>
  )
}
