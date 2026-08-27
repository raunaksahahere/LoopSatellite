import type { Provenance, ProvenanceStatus } from '../../lib/types'
import { Note } from '../ui'

const BADGE: Record<ProvenanceStatus, string> = {
  real: 'badge--low',
  synthetic: 'badge--medium',
  not_run: 'badge--neutral',
}

const LABEL: Record<ProvenanceStatus, string> = {
  real: 'Real',
  synthetic: 'Synthetic',
  not_run: 'Not run yet',
}

/**
 * Every layer on screen, and whether it is real.
 *
 * The point of showing this rather than burying it in a README: a synthetic
 * demo that says so is more trustworthy than one that stays quiet and hopes
 * nobody asks. Each row states what produced what you are looking at, and what
 * would produce it for real — so "how do we know this works on real data?" has
 * a URL for an answer.
 */
export function DataSources({ data }: { data: Provenance }) {
  const counts = Object.entries(data.counts)

  return (
    <div className="stack">
      <Note tone={data.bundle_is_synthetic ? 'warn' : 'info'}>{data.headline}</Note>

      <div className="card card--flat">
        <div className="stats">
          {counts.map(([key, value]) => (
            <div key={key}>
              <div className="stat__label">{key.replace(/_/g, ' ')}</div>
              <div className="stat__value">{value}</div>
            </div>
          ))}
        </div>
      </div>

      {data.layers.map((layer) => (
        <article className={`card provlayer provlayer--${layer.status}`} key={layer.key}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'start' }}>
            <h2 style={{ fontSize: '1.05rem' }}>{layer.label}</h2>
            <span className={`badge ${BADGE[layer.status]}`}>
              <span className="badge__dot" aria-hidden="true" />
              {LABEL[layer.status]}
            </span>
          </div>

          <dl className="provlayer__rows">
            <dt>On screen now</dt>
            <dd>{layer.on_screen}</dd>
            <dt>Real equivalent</dt>
            <dd>{layer.real_source}</dd>
          </dl>

          <p className="hint" style={{ margin: '0.6rem 0 0' }}>
            {layer.detail}
          </p>
        </article>
      ))}

      {data.fallbacks.length > 0 && (
        <section className="card">
          <h2 style={{ fontSize: '1.05rem', marginBottom: '0.5rem' }}>
            Why this bundle is synthetic
          </h2>
          <p className="hint" style={{ marginTop: 0 }}>
            The pipeline looked for real inputs, did not find them, and synthesised
            instead. It announced each one at the time; these are the same reasons.
          </p>
          <ul className="reasons">
            {data.fallbacks.map((f) => (
              <li key={f.step}>
                <code>{f.step}</code> — {f.reason}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2 style={{ fontSize: '1.05rem', marginBottom: '0.5rem' }}>To make it real</h2>
        <ol className="reasons">
          {data.to_make_it_real.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="hint" style={{ margin: '0.6rem 0 0' }}>
          Built by <code>{data.generated_by}</code>
          {data.generated_at ? ` · ${data.generated_at}` : ''}
        </p>
      </section>
    </div>
  )
}
