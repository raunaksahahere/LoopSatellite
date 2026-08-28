import { useState } from 'react'

import { api } from '../../lib/api'
import { formatDateTime, OUTCOME_LABEL } from '../../lib/format'
import type { Outcome, Verification } from '../../lib/types'
import { useAction } from '../../lib/useAsync'
import { Card, Note } from '../ui'

const OPTIONS: { value: Outcome; help: string }[] = [
  { value: 'confirmed', help: 'You went, or you have reliable word, and the water is gone.' },
  { value: 'seasonal', help: 'The pond was drawn down and will refill — nothing to act on.' },
  { value: 'unclear', help: 'Not enough to decide yet. Keep it on the list.' },
  { value: 'already_actioned', help: 'A notice or case already exists for this site.' },
]

/**
 * The officer's verdict. This is the only thing the app writes down, and it is
 * what eventually tells us whether the detector is any good.
 */
export function VerifyForm({
  anomalyId,
  existing,
  onSaved,
}: {
  anomalyId: string
  existing: Verification[]
  onSaved: () => void
}) {
  const [outcome, setOutcome] = useState<Outcome | ''>('')
  const [note, setNote] = useState('')
  const [name, setName] = useState('')
  const { pending, error, run } = useAction(api.verify)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!outcome) return
    const saved = await run(anomalyId, {
      outcome,
      officer_note: note || undefined,
      officer_name: name || undefined,
    })
    if (saved) {
      setOutcome('')
      setNote('')
      onSaved()
    }
  }

  return (
    <Card title="What did you find?">
      {existing.length > 0 && (
        <div style={{ marginBottom: '1rem' }}>
          <Note tone="plain">
            Last recorded: <strong>{OUTCOME_LABEL[existing[0].outcome] ?? existing[0].outcome}</strong>
            {existing[0].officer_name ? ` by ${existing[0].officer_name}` : ''} on{' '}
            {formatDateTime(existing[0].verified_at)}
            {existing[0].officer_note ? ` — “${existing[0].officer_note}”` : ''}
          </Note>
        </div>
      )}

      <form onSubmit={submit}>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ padding: 0 }}>
            Your decision
          </legend>
          <div className="stack" style={{ gap: '0.4rem' }}>
            {OPTIONS.map((option) => (
              <label
                key={option.value}
                className="row"
                style={{
                  gap: '0.65rem',
                  alignItems: 'flex-start',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.6rem 0.75rem',
                  cursor: 'pointer',
                  background: outcome === option.value ? 'var(--accent-soft)' : 'transparent',
                  flexWrap: 'nowrap',
                  minHeight: 'var(--tap)',
                }}
              >
                <input
                  type="radio"
                  name="outcome"
                  value={option.value}
                  checked={outcome === option.value}
                  onChange={() => setOutcome(option.value)}
                  style={{ marginTop: '0.35rem', width: 20, height: 20 }}
                />
                <span>
                  <strong>{OUTCOME_LABEL[option.value]}</strong>
                  <br />
                  <span className="hint">{option.help}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="label" htmlFor="verify-note" style={{ marginTop: '1rem' }}>
          Notes (optional)
        </label>
        <textarea
          id="verify-note"
          className="textarea"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="What you saw, who you spoke to, anything worth recording."
        />

        <label className="label" htmlFor="verify-name" style={{ marginTop: '0.75rem' }}>
          Your name (optional)
        </label>
        <input
          id="verify-name"
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
        />

        {error && (
          <div style={{ marginTop: '0.75rem' }}>
            <Note tone="error">{error.message}</Note>
          </div>
        )}

        <button
          type="submit"
          className="btn btn--primary btn--block"
          style={{ marginTop: '1rem' }}
          disabled={!outcome || pending}
        >
          {pending ? 'Saving…' : 'Record this decision'}
        </button>
      </form>
    </Card>
  )
}
