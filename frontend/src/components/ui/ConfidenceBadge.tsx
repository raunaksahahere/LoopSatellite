import type { ConfidenceBand } from '../../lib/types'
import { CONFIDENCE_LABEL } from '../../lib/format'

interface Props {
  band: ConfidenceBand
  /** The underlying score, exposed only as a tooltip — officers work off the band. */
  score?: number
  compact?: boolean
}

/**
 * Colour-coded confidence. The decimal score never becomes the primary reading:
 * an officer needs "act on this" / "look closer", not 0.83.
 */
export function ConfidenceBadge({ band, score, compact = false }: Props) {
  const title =
    score !== undefined
      ? `Detection confidence ${(score * 100).toFixed(0)} out of 100, scored from the size of the loss, how long it lasted, and whether the pond recovered.`
      : undefined

  return (
    <span className={`badge badge--${band}`} title={title}>
      <span className="badge__dot" aria-hidden="true" />
      {compact ? band : CONFIDENCE_LABEL[band]}
    </span>
  )
}
