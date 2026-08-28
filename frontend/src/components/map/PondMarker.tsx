import { Link } from 'react-router-dom'

import { formatArea } from '../../lib/format'
import type { PondProperties } from '../../lib/types'
import { ConfidenceBadge } from '../ui/ConfidenceBadge'

/**
 * What a pond says when you tap it. One primary action ("Open this pond"), a
 * plain sentence about its state, and nothing else to decide.
 */
export function PondPopup({
  pond,
  onOpen,
}: {
  pond: PondProperties
  onOpen?: (pondId: string) => void
}) {
  const flagged = Number(pond.anomaly_count) > 0

  return (
    <div className="mappop">
      <h3>{pond.name ?? pond.id}</h3>
      <p>
        {[pond.mouza, pond.ward].filter(Boolean).join(' · ') || 'Location not recorded'}
        <br />
        Boundary area {formatArea(pond.baseline_area_m2)}
      </p>

      {flagged && pond.worst_confidence_band ? (
        <div className="row" style={{ marginBottom: '0.6rem' }}>
          <ConfidenceBadge band={pond.worst_confidence_band} />
          <span className="hint">
            {pond.anomaly_count} water-loss {Number(pond.anomaly_count) === 1 ? 'event' : 'events'}
          </span>
        </div>
      ) : (
        <p className="hint" style={{ marginBottom: '0.6rem' }}>
          No water loss flagged for this pond.
        </p>
      )}

      <Link
        className="btn btn--primary btn--sm btn--block"
        to={`/pond/${pond.id}`}
        onClick={() => onOpen?.(pond.id)}
      >
        Open this pond
      </Link>
    </div>
  )
}
