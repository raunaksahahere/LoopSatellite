/**
 * The hero's instrument panel.
 *
 * It draws the one picture this entire application exists to produce: a pond's
 * water area over time, the seasonal shape the statistics expected, and the gap
 * between them that turns out not to be the dry season.
 *
 * The numbers are illustrative and the panel says so in its own footer. It is
 * not read from the bundle: a signed-out visitor has no session, the landing
 * page makes no API call, and a hero that silently fails to a blank box on a
 * cold Render instance is worse than one that is honestly a diagram.
 *
 * Two of the mockup's flourishes are deliberately absent — a rotating sweep and
 * a blur behind the panel. A permanently moving element on a page whose job is
 * one button is decoration, and blur over an opaque surface buys a repaint per
 * scroll and nothing else. The trace draws itself once and stops.
 */

/** Twelve months of "expected" — the seasonal shape, normalised 0-1. */
const EXPECTED = [0.86, 0.78, 0.66, 0.55, 0.5, 0.62, 0.85, 0.97, 1, 0.98, 0.94, 0.9]

/** The same pond observed. It tracks the season until month 7, then does not. */
const OBSERVED = [0.85, 0.77, 0.65, 0.56, 0.51, 0.6, 0.83, 0.52, 0.3, 0.24, 0.22, 0.21]

const W = 520
const H = 300
const PAD = { top: 28, right: 20, bottom: 34, left: 20 }

function path(series: number[]): string {
  const w = W - PAD.left - PAD.right
  const h = H - PAD.top - PAD.bottom
  return series
    .map((v, i) => {
      const x = PAD.left + (i / (series.length - 1)) * w
      const y = PAD.top + (1 - v) * h
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

/** The filled wedge between expected and observed — the loss itself. */
function gap(): string {
  const w = W - PAD.left - PAD.right
  const h = H - PAD.top - PAD.bottom
  const at = (i: number, v: number) =>
    [PAD.left + (i / 11) * w, PAD.top + (1 - v) * h] as const

  const forward = EXPECTED.slice(6).map((v, i) => at(i + 6, v))
  const back = OBSERVED.slice(6)
    .map((v, i) => at(i + 6, v))
    .reverse()
  return (
    `M${forward.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')} ` +
    `L${back.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')} Z`
  )
}

export function WetlandPanel() {
  return (
    <figure className="landing__instrument">
      <div className="landing__instrument-head">
        <span>
          Pond <b>EKW_00032</b>
        </span>
        <span>Open water area</span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={
          'A chart of one pond’s water area over twelve months. The measured area ' +
          'follows the expected seasonal curve until month seven, then falls far ' +
          'below it and does not return — the signature of a pond that was filled ' +
          'in rather than one that dried out.'
        }
      >
        <defs>
          <linearGradient id="ld-gap" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ff6b5e" stopOpacity="0.34" />
            <stop offset="100%" stopColor="#ff6b5e" stopOpacity="0.04" />
          </linearGradient>
        </defs>

        {/* grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = PAD.top + t * (H - PAD.top - PAD.bottom)
          return (
            <line
              key={t}
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y}
              y2={y}
              stroke="rgba(255,255,255,0.05)"
              strokeWidth="1"
            />
          )
        })}

        <path d={gap()} fill="url(#ld-gap)" />

        {/* expected: the seasonal shape the statistics predicted */}
        <path
          d={path(EXPECTED)}
          fill="none"
          stroke="#7d8b95"
          strokeWidth="1.5"
          strokeDasharray="4 3"
        />

        {/* observed */}
        <path
          className="landing__trace"
          d={path(OBSERVED)}
          fill="none"
          stroke="#2fd9c4"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* where the detector flagged it */}
        <line
          x1={PAD.left + (7 / 11) * (W - PAD.left - PAD.right)}
          x2={PAD.left + (7 / 11) * (W - PAD.left - PAD.right)}
          y1={PAD.top - 8}
          y2={H - PAD.bottom}
          stroke="#ff6b5e"
          strokeWidth="1"
          strokeDasharray="2 3"
        />
        <text
          x={PAD.left + (7 / 11) * (W - PAD.left - PAD.right) + 8}
          y={PAD.top - 12}
          fill="#ff6b5e"
          fontSize="11"
          fontFamily="ui-monospace, monospace"
          letterSpacing="0.08em"
        >
          FLAGGED
        </text>

        <text
          x={PAD.left}
          y={H - 12}
          fill="#7d8b95"
          fontSize="11"
          fontFamily="ui-monospace, monospace"
          letterSpacing="0.08em"
        >
          EXPECTED (SEASONAL)
        </text>
        <text
          x={W - PAD.right}
          y={H - 12}
          fill="#2fd9c4"
          fontSize="11"
          fontFamily="ui-monospace, monospace"
          letterSpacing="0.08em"
          textAnchor="end"
        >
          OBSERVED
        </text>
      </svg>

      <figcaption className="landing__instrument-foot">
        <span>Illustrative — not live data</span>
        <span>Satellite · 10 m detail</span>
      </figcaption>
    </figure>
  )
}
