import { api } from '../../lib/api'
import { useAction } from '../../lib/useAsync'
import type { EvidenceFinding } from '../../lib/types'
import { Card, Note } from '../ui'

const RELEVANCE_LABEL: Record<EvidenceFinding['relevance'], string> = {
  direct: 'About this site',
  contextual: 'About the area',
  unrelated: 'Turned up, but not relevant',
}

const RELEVANCE_CLASS: Record<EvidenceFinding['relevance'], string> = {
  direct: 'badge--high',
  contextual: 'badge--medium',
  unrelated: 'badge--neutral',
}

/**
 * Evidence corroboration.
 *
 * This panel cannot change the finding above it. The water loss was measured;
 * this only asks whether anyone wrote anything down about it at the time.
 */
export function EvidencePanel({
  anomalyId,
  llmConfigured,
}: {
  anomalyId: string
  llmConfigured: boolean
}) {
  const { data, pending, error, run } = useAction(api.evidence)

  return (
    <Card title="Is there a paper trail?">
      <p className="hint" style={{ marginTop: 0 }}>
        Searches news reports, notices and public records for this locality and
        this period. Anything found is listed with its source so you can check it
        yourself.
      </p>

      {!llmConfigured && (
        <Note tone="warn">
          Evidence search needs a language model to be configured. The water-loss
          finding above does not depend on it.
        </Note>
      )}

      <button
        type="button"
        className="btn btn--primary"
        style={{ marginTop: '0.75rem' }}
        disabled={pending || !llmConfigured}
        onClick={() => run(anomalyId)}
      >
        {pending ? 'Searching…' : data ? 'Search again' : 'Search the record'}
      </button>

      {error && (
        <div style={{ marginTop: '0.75rem' }}>
          <Note tone="error">{error.message}</Note>
        </div>
      )}

      {data && (
        <div style={{ marginTop: '1rem' }}>
          {data.note && (
            <Note tone={data.findings.length ? 'plain' : 'warn'}>{data.note}</Note>
          )}

          {data.findings.map((finding, i) => (
            <article className="finding" key={`${finding.url ?? finding.title}-${i}`}>
              <div className="row" style={{ gap: '0.5rem', marginBottom: '0.3rem' }}>
                <span className={`badge ${RELEVANCE_CLASS[finding.relevance]}`}>
                  {RELEVANCE_LABEL[finding.relevance]}
                </span>
                {finding.published && <span className="hint">{finding.published}</span>}
              </div>
              <h4>
                {finding.url ? (
                  <a href={finding.url} target="_blank" rel="noreferrer noopener">
                    {finding.title}
                  </a>
                ) : (
                  finding.title
                )}
              </h4>
              {finding.source && <div className="hint">{finding.source}</div>}
              <blockquote>{finding.snippet}</blockquote>
              <p className="hint" style={{ margin: 0 }}>
                {finding.why_relevant}
              </p>
            </article>
          ))}

          <details className="tech">
            <summary>What was searched for</summary>
            <p>{data.query_used}</p>
          </details>
        </div>
      )}
    </Card>
  )
}
