import { useState } from 'react'

import { api } from '../../lib/api'
import { useAction } from '../../lib/useAsync'
import type { NLQueryResponse } from '../../lib/types'
import { Note } from '../ui'

const EXAMPLES = [
  'problems around the East Kolkata Wetlands within 5 km',
  'ponds in Ward 108 that lost more than 20% and never recovered',
  'high-confidence losses where buildings are visible',
  'what is going on around Haldia for 5km',
]

/**
 * Ask a question in plain English.
 *
 * The model only turns the sentence into a filter — it never sees the records and
 * cannot alter a number. The filter it produced is shown back to the officer, so a
 * misreading is visible rather than silent.
 */
export function NLQueryBar({ onResult }: { onResult: (result: NLQueryResponse | null) => void }) {
  const [question, setQuestion] = useState('')
  const { data, pending, error, run } = useAction(api.ask)

  async function ask(text: string) {
    const trimmed = text.trim()
    if (trimmed.length < 3) return
    setQuestion(trimmed)
    const result = await run(trimmed)
    onResult(result)
  }

  function clear() {
    setQuestion('')
    onResult(null)
  }

  return (
    <div className="card">
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(question)
        }}
      >
        <label className="visually-hidden" htmlFor="ask-input">
          Ask about the flagged water-loss events
        </label>
        <input
          id="ask-input"
          className="input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about the ponds — e.g. which ones in Ward 108 never recovered"
          autoComplete="off"
        />
        <button type="submit" className="btn btn--primary" disabled={pending || question.trim().length < 3}>
          {pending ? 'Looking…' : 'Ask'}
        </button>
        {data && (
          <button type="button" className="btn" onClick={clear}>
            Clear
          </button>
        )}
      </form>

      {!data && (
        <div className="chips">
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="chip" onClick={() => void ask(example)}>
              {example}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div style={{ marginTop: '0.75rem' }}>
          <Note tone="error">{error.message}</Note>
        </div>
      )}

      {data && (
        <div style={{ marginTop: '0.85rem' }} aria-live="polite">
          {/* The answer, when the question was about a place. Composed from the
              numbers by a format string — never written by the model. */}
          {data.summary ? (
            <Note tone={data.count ? 'info' : 'warn'}>{data.summary}</Note>
          ) : (
            <Note tone={data.resolved === false ? 'warn' : 'info'}>
              {data.resolved === false ? (
                data.interpretation
              ) : (
                <>
                  <strong>{data.count}</strong> {data.count === 1 ? 'event' : 'events'} —{' '}
                  {data.interpretation}
                </>
              )}
            </Note>
          )}

          {data.place && (
            <p className="hint" style={{ margin: '0.5rem 0 0' }}>
              Centred on {data.place.display_name}
              {data.assumed_radius
                ? ` · no distance given, so we looked within ${data.radius_km} km`
                : ''}
            </p>
          )}

          {data.unparsed.length > 0 && (
            <ul className="reasons" style={{ marginTop: '0.6rem' }}>
              {data.unparsed.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}

          <details className="tech">
            <summary>How your question was read</summary>
            <p>
              {Object.entries(data.filter)
                .filter(([, value]) => value !== null && value !== undefined)
                .map(([key, value]) => `${key} = ${value}`)
                .join('  ·  ') || 'no filter — showing everything'}
            </p>
          </details>
        </div>
      )}
    </div>
  )
}
