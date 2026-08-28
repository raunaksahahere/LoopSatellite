import { useState } from 'react'

import { api } from '../../lib/api'
import { useAction } from '../../lib/useAsync'
import { Card, Note } from '../ui'

/**
 * Regulatory grounding and notice drafting.
 *
 * The provisions are shown *above* the draft on purpose. They are what the notice
 * rests on, they were retrieved from the source instruments, and they are quoted
 * verbatim. If retrieval found nothing, no draft appears at all — the panel says
 * so instead of producing a plausible-looking notice.
 */
export function NoticeDraft({ anomalyId }: { anomalyId: string }) {
  const [officer, setOfficer] = useState('')
  const [copied, setCopied] = useState(false)
  const { data, pending, error, run } = useAction(api.notice)

  async function copy() {
    if (!data?.draft) return
    try {
      await navigator.clipboard.writeText(data.draft)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Card title="What the law says, and a draft notice">
      <p className="hint" style={{ marginTop: 0 }}>
        Every provision below was looked up in the source text and is quoted word for
        word. Nothing here is written from memory.
      </p>

      <label className="label" htmlFor="notice-officer" style={{ marginTop: '0.75rem' }}>
        Your name (optional — appears in the signature block)
      </label>
      <input
        id="notice-officer"
        className="input"
        value={officer}
        onChange={(e) => setOfficer(e.target.value)}
        placeholder="e.g. S. Mondal"
        autoComplete="name"
      />

      <button
        type="button"
        className="btn btn--primary"
        style={{ marginTop: '0.75rem' }}
        disabled={pending}
        onClick={() => run(anomalyId, officer)}
      >
        {pending ? 'Looking up the provisions…' : data ? 'Draft again' : 'Find the law and draft'}
      </button>

      {error && (
        <div style={{ marginTop: '0.75rem' }}>
          <Note tone="error">{error.message}</Note>
        </div>
      )}

      {data && (
        <div style={{ marginTop: '1rem' }}>
          {!data.grounded ? (
            <Note tone="warn">{data.note}</Note>
          ) : (
            <>
              <h3 style={{ marginBottom: '0.5rem' }}>Provisions found</h3>
              {data.provisions.map((p) => (
                <div className="provision" key={p.citation}>
                  <div className="provision__cite">{p.citation}</div>
                  <div className="provision__doc">{p.document}</div>
                  <blockquote>{p.quote}</blockquote>
                </div>
              ))}

              {data.note && (
                <div style={{ margin: '0.75rem 0' }}>
                  <Note tone="plain">{data.note}</Note>
                </div>
              )}

              <div className="row" style={{ justifyContent: 'space-between', margin: '1rem 0 0.5rem' }}>
                <h3 style={{ margin: 0 }}>Draft notice</h3>
                <button type="button" className="chip" onClick={copy}>
                  {copied ? 'Copied' : 'Copy text'}
                </button>
              </div>

              <pre className="draft">{data.draft}</pre>

              <div style={{ marginTop: '0.75rem' }}>
                <Note tone="warn">{data.disclaimer}</Note>
              </div>

              <details className="tech">
                <summary>How this draft was produced</summary>
                <p>
                  {data.llm_used
                    ? 'Written by the configured language model, restricted to the provisions above, and re-checked afterwards for any citation that was not retrieved.'
                    : 'Assembled from a fixed template with no language model involved. The provisions are unaffected either way.'}
                </p>
              </details>
            </>
          )}
        </div>
      )}
    </Card>
  )
}
