import { OUTCOME_LABEL } from '../../lib/format'
import type { Verification } from '../../lib/types'

/**
 * Where this finding has got to, and what moves it forward.
 *
 * Without it the page ends at the evidence and stops. Detection is the easy half
 * of an environmental-monitoring claim; the half that gets asked about is what
 * happened next, and a page that never says leaves the reader to assume nothing
 * did.
 *
 * Every state here is read from records that exist — the officer verdicts in
 * `verifications` — rather than from a workflow this application does not run.
 * There is no "filed with WBPCB" state because nothing here files anything, and
 * inventing one would be claiming an integration that does not exist.
 */
export function CaseStatus({ verifications }: { verifications: Verification[] }) {
  const latest = verifications[0] ?? null

  if (!latest) {
    return (
      <div className="casestatus casestatus--open">
        <p className="casestatus__state">Awaiting review</p>
        <p className="casestatus__next">
          Nobody has looked at this yet. Recording a verdict below is what turns it
          from a flag into a finding — and a confirmed one can be drafted into a
          notice, with the provisions quoted from the statute rather than
          paraphrased.
        </p>
      </div>
    )
  }

  const outcome = OUTCOME_LABEL[latest.outcome] ?? latest.outcome
  const next: Record<string, string> = {
    confirmed:
      'Reviewed and confirmed. Draft the notice below — it quotes the provisions ' +
      'it relies on, so it can be checked rather than trusted.',
    seasonal:
      'Reviewed and set aside as seasonal. It stays on the record: a pond ruled ' +
      'seasonal once and flagged again later is worth a second look, not a second ' +
      'dismissal.',
    unclear:
      'Reviewed and still unclear. It stays in the queue. The usual next step is ' +
      'the evidence search below, or a site visit.',
    already_actioned:
      'Already being dealt with elsewhere. Kept so the same site is not opened ' +
      'twice by two different officers.',
  }

  return (
    <div className={`casestatus casestatus--${latest.outcome}`}>
      <p className="casestatus__state">
        {outcome}
        {latest.officer_name ? ` · ${latest.officer_name}` : ''}
      </p>
      <p className="casestatus__next">{next[latest.outcome] ?? ''}</p>
      {verifications.length > 1 && (
        <p className="casestatus__history">
          {verifications.length} reviews recorded on this finding.
        </p>
      )}
    </div>
  )
}
