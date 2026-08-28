import { Link } from 'react-router-dom'

import { describeWindow, formatHectares, formatPercent, OUTCOME_LABEL } from '../../lib/format'
import type { Anomaly, Outcome } from '../../lib/types'
import { ConfidenceBadge } from '../ui/ConfidenceBadge'

/**
 * One row of the verification queue. Deliberately one action ("Review") — an
 * officer working through a list should never have to choose between buttons.
 */
export function QueueCard({ anomaly }: { anomaly: Anomaly }) {
  const reviewed = anomaly.status && anomaly.status !== 'pending'

  return (
    <article className={`qcard qcard--${anomaly.confidence_band}`}>
      <Link
        to={`/pond/${anomaly.pond_id}?event=${encodeURIComponent(anomaly.id)}`}
        className="qcard__chip"
        tabIndex={-1}
        aria-hidden="true"
      >
        <img
          src={`/precomputed/chips/${anomaly.id}_after.svg`}
          alt=""
          loading="lazy"
          onError={(e) => {
            e.currentTarget.style.visibility = 'hidden'
          }}
        />
      </Link>

      <div className="qcard__body">
        <div className="row" style={{ gap: '0.5rem' }}>
          <ConfidenceBadge band={anomaly.confidence_band} score={anomaly.confidence} />
          {!anomaly.recovered && <span className="badge badge--neutral">Still not recovered</span>}
          {reviewed && (
            <span className="badge badge--accent">
              {OUTCOME_LABEL[anomaly.status as Outcome] ?? anomaly.status}
            </span>
          )}
        </div>

        <div className="qcard__title" style={{ marginTop: '0.45rem' }}>
          {anomaly.pond_name ?? anomaly.pond_id}
        </div>

        <p className="qcard__summary">
          {anomaly.summary ??
            `Lost ${formatPercent(anomaly.loss_pct)} of its expected water surface.`}
        </p>

        <div className="qcard__meta">
          <span>{[anomaly.mouza, anomaly.ward].filter(Boolean).join(' · ') || 'Location unknown'}</span>
          <span>{describeWindow(anomaly.window_start, anomaly.window_end)}</span>
          <span>{formatHectares(anomaly.loss_ha)} lost</span>
          {anomaly.conversion_label && <span>{anomaly.conversion_label}</span>}
        </div>
      </div>

      <Link
        className="btn btn--primary"
        to={`/pond/${anomaly.pond_id}?event=${encodeURIComponent(anomaly.id)}`}
      >
        Review
      </Link>
    </article>
  )
}
