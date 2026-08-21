import { useMemo } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'

import { TimeSeriesChart } from '../components/charts/TimeSeriesChart'
import { EvidencePanel } from '../components/llm/EvidencePanel'
import { NoticeDraft } from '../components/llm/NoticeDraft'
import { BeforeAfterSlider } from '../components/map/BeforeAfterSlider'
import { VerifyForm } from '../components/queue/VerifyForm'
import { ReportDownloadButton } from '../components/report/ReportDownloadButton'
import {
  Back,
  Card,
  ConfidenceBadge,
  EmptyState,
  ErrorState,
  Loading,
  Note,
  Stat,
  TechnicalDetail,
} from '../components/ui'
import { api } from '../lib/api'
import { describeWindow, formatArea, formatHectares, formatPercent } from '../lib/format'
import type { Health } from '../lib/types'
import { useAsync } from '../lib/useAsync'

/**
 * One pond, end to end: the measurement, the flagged events, why they were
 * flagged, what the record says, what the law says, and the officer's verdict.
 *
 * Everything above the LLM panels is statistics. Everything in them started from
 * a finding that was already made.
 */
export function PondDetailPage({ health }: { health: Health | null }) {
  const { pondId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('event')

  const series = useAsync(() => api.timeseries(pondId), [pondId])
  const events = useAsync(() => api.anomalies({ pond_id: pondId }), [pondId])

  const anomalies = events.data?.items ?? []
  const active = useMemo(
    () => anomalies.find((a) => a.id === selectedId) ?? anomalies[0],
    [anomalies, selectedId],
  )

  const detail = useAsync(
    () => (active ? api.anomaly(active.id) : Promise.resolve(null)),
    [active?.id],
  )

  if (series.error) return <Shell><ErrorState error={series.error} onRetry={series.reload} /></Shell>
  if (series.loading || events.loading) {
    return <Shell><Loading label="Loading this pond…" rows={3} /></Shell>
  }
  if (!series.data) return null

  const pondName = active?.pond_name ?? pondId

  return (
    <Shell>
      <header className="page__head">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h1>{pondName}</h1>
          {active && <ReportDownloadButton scope="anomaly" anomalyId={active.id} includeNotice />}
        </div>
        <p>
          {[active?.mouza, active?.ward].filter(Boolean).join(' · ') ||
            'East Kolkata Wetlands'}{' '}
          · boundary area {formatArea(series.data.capacity_m2)}
        </p>
      </header>

      {anomalies.length > 1 && (
        <div className="row" style={{ marginBottom: '1rem' }}>
          <span className="hint">{anomalies.length} separate events on this pond:</span>
          {anomalies.map((a) => (
            <button
              key={a.id}
              type="button"
              className="chip"
              style={
                a.id === active?.id
                  ? { borderColor: 'var(--accent)', color: 'var(--accent)' }
                  : undefined
              }
              onClick={() => setParams({ event: a.id })}
            >
              {describeWindow(a.window_start, a.window_end)}
            </button>
          ))}
        </div>
      )}

      {!active ? (
        <EmptyState title="Nothing flagged for this pond">
          This pond's water surface has stayed within its own seasonal pattern
          throughout the record. The chart below shows the measurements it was judged
          against.
        </EmptyState>
      ) : (
        <div className="row" style={{ marginBottom: '1rem', gap: '0.6rem' }}>
          <ConfidenceBadge band={active.confidence_band} score={active.confidence} />
          {!active.recovered && <span className="badge badge--neutral">Still not recovered</span>}
          {active.conversion_label && (
            <span className="badge badge--neutral">{active.conversion_label}</span>
          )}
        </div>
      )}

      <div className="detail">
        <div className="stack">
          <Card title="Water surface over time">
            <TimeSeriesChart
              points={series.data.points}
              anomalies={anomalies}
              activeAnomalyId={active?.id}
            />
          </Card>

          {active && (
            <Card title="Before and after">
              <BeforeAfterSlider anomaly={active} />
            </Card>
          )}

          {detail.data && (
            <Card title="Why this was flagged">
              <div className="stats" style={{ marginBottom: '1rem' }}>
                <Stat label="Water lost" value={formatPercent(active!.loss_pct)} />
                <Stat label="Area lost" value={formatHectares(active!.loss_ha)} />
                <Stat
                  label="Period"
                  value={describeWindow(active!.window_start, active!.window_end)}
                />
                <Stat label="Recovered" value={active!.recovered ? 'Yes' : 'No'} />
              </div>

              <p>{detail.data.detection.summary}</p>
              <ul className="reasons">
                {detail.data.detection.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>

              <Note tone="plain">{detail.data.detection.seasonality_note}</Note>

              <h3 style={{ marginTop: '1rem' }}>What replaced the water</h3>
              <p>{detail.data.conversion.summary}</p>

              <TechnicalDetail label="How this was measured and tested">
                <p>{detail.data.measurement.technical}</p>
                <p>{detail.data.detection.technical}</p>
                {detail.data.conversion.technical && <p>{detail.data.conversion.technical}</p>}
                <p>Language model involvement in this finding: {detail.data.detection.llm_involvement}</p>
              </TechnicalDetail>
            </Card>
          )}

          {active && <EvidencePanel anomalyId={active.id} llmConfigured={Boolean(health?.llm.configured)} />}
          {active && <NoticeDraft anomalyId={active.id} />}
        </div>

        <div className="stack">
          {active && detail.data && (
            <VerifyForm
              anomalyId={active.id}
              existing={detail.data.verifications}
              onSaved={() => detail.reload()}
            />
          )}

          <Card title="About this pond" flat>
            <div className="stack" style={{ gap: '0.6rem' }}>
              <div>
                <div className="stat__label">Reference</div>
                <div>{pondId}</div>
              </div>
              <div>
                <div className="stat__label">Months of record</div>
                <div>{series.data.points.length}</div>
              </div>
              <div>
                <div className="stat__label">Months filled in</div>
                <div>
                  {series.data.n_interpolated}{' '}
                  <span className="hint">(no usable satellite pass)</span>
                </div>
              </div>
              {active?.provenance && (
                <div>
                  <div className="stat__label">Boundary source</div>
                  <div>{active.provenance}</div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="page">
      <Back to="/queue">Back to the review list</Back>
      {children}
    </div>
  )
}
