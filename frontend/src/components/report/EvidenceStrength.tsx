import type { Anomaly } from '../../lib/types'

/**
 * How well observed a finding is, next to the finding itself.
 *
 * The loss percentage and the hectares were presented with nothing beside them,
 * which invites the first question anyone numerate asks: how sure are you? The
 * honest answer here is not an error bar. The detector produces a confidence
 * score and a data-quality weight; it does not produce a confidence interval on
 * the loss percentage, and inventing one would be the same sin as inventing the
 * measurement.
 *
 * So this states what was actually behind the number: how many clear satellite
 * passes fell inside the flagged window, how many months of it had none and were
 * filled in from neighbours, and how much of the pond was visible on average.
 * A reader can then discount the finding themselves, which is the point.
 *
 * Zero clear passes is called out rather than shown as "0", because a window
 * made entirely of interpolated months is a different kind of claim and should
 * read as one.
 */
export function EvidenceStrength({ anomaly }: { anomaly: Anomaly }) {
  const passes = anomaly.clear_passes ?? null
  const filled = anomaly.months_interpolated ?? null
  const quality = anomaly.data_quality

  if (passes === null && quality === null) return null

  const noDirectEvidence = passes === 0

  return (
    <div className={`evidence${noDirectEvidence ? ' evidence--weak' : ''}`}>
      <p className="evidence__line">
        <strong>{anomaly.confidence_band} confidence</strong>
        {passes !== null && (
          <>
            {' · '}
            {passes === 0
              ? 'no clear satellite pass inside this window'
              : `${passes} clear satellite ${passes === 1 ? 'pass' : 'passes'}`}
          </>
        )}
        {filled ? ` · ${filled} month${filled === 1 ? '' : 's'} filled in` : ''}
        {quality !== null ? ` · pond ${Math.round(quality * 100)}% visible on average` : ''}
      </p>
      <p className="evidence__note">
        {noDirectEvidence
          ? 'Every month in this window was reconstructed from its neighbours because ' +
            'cloud left no usable pass. Treat the size of the loss as indicative and ' +
            'check the site before acting on it.'
          : 'These are counts of what was measured, not an error margin. The detector ' +
            'scores confidence and weights by how much of the pond was visible; it does ' +
            'not estimate a range around the loss percentage.'}
      </p>
    </div>
  )
}
