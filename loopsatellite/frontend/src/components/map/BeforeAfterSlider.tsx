import { ReactCompareSlider, ReactCompareSliderImage } from 'react-compare-slider'

import { formatMonth } from '../../lib/format'
import type { Anomaly } from '../../lib/types'

/**
 * Before / after comparison for one flagged event.
 *
 * The chips come from precomputed/chips/. In the demo bundle they are schematic
 * extent diagrams, labelled as such on their face — they are not satellite
 * photographs and must never be presented as evidence of what a site looks like.
 * Drop real exported chips in with the same filenames and this picks them up
 * with no code change.
 */
export function BeforeAfterSlider({ anomaly }: { anomaly: Anomaly }) {
  const before = `/precomputed/chips/${anomaly.id}_before.svg`
  const after = `/precomputed/chips/${anomaly.id}_after.svg`

  return (
    <div>
      {/* The chips are square; keep them square so the extent squares stay to scale. */}
      <div className="compare" style={{ maxWidth: 360, margin: '0 auto', aspectRatio: '1' }}>
        <ReactCompareSlider
          itemOne={
            <ReactCompareSliderImage
              src={before}
              alt={`Water extent before, ${formatMonth(anomaly.window_start)}`}
              style={{ objectFit: 'contain' }}
            />
          }
          itemTwo={
            <ReactCompareSliderImage
              src={after}
              alt={`Water extent after, ${formatMonth(anomaly.detected_on)}`}
              style={{ objectFit: 'contain' }}
            />
          }
          style={{ height: '100%' }}
        />
      </div>
      <div className="compare__labels" style={{ maxWidth: 360, margin: '0.4rem auto 0' }}>
        <span>◀ Before — {formatMonth(anomaly.window_start)}</span>
        <span>After — {formatMonth(anomaly.detected_on)} ▶</span>
      </div>
      <p className="hint" style={{ marginTop: '0.5rem' }}>
        Drag the handle to compare. These are scale diagrams of the measured water
        extent, not photographs.
      </p>
    </div>
  )
}
