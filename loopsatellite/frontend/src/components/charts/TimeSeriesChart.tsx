import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatMonth } from '../../lib/format'
import type { Anomaly, TimeSeriesPoint } from '../../lib/types'

/**
 * Observed water surface against what the season says to expect.
 *
 * The whole product argument is in this one picture: the purple line is what this
 * pond normally holds in this month of the year, the teal line is what it actually
 * held, and the shaded band is the window the statistics flagged. A pond that
 * shrinks every April tracks the purple line down and is never flagged.
 *
 * One y-axis, on purpose — both series are the same measure in the same unit.
 */

interface Props {
  points: TimeSeriesPoint[]
  anomalies?: Anomaly[]
  /** Which anomaly window to emphasise, if the page has one selected. */
  activeAnomalyId?: string
  height?: number
}

interface Row {
  month: string
  label: string
  observed: number
  expected: number
  interpolated: boolean
}

export function TimeSeriesChart({ points, anomalies = [], activeAnomalyId, height = 320 }: Props) {
  const [asTable, setAsTable] = useState(false)

  const rows: Row[] = useMemo(
    () =>
      points.map((p) => ({
        month: p.month,
        label: formatMonth(p.month),
        observed: round(p.observed_m2 / 10_000),
        expected: round(p.expected_m2 / 10_000),
        interpolated: p.interpolated,
      })),
    [points],
  )

  if (!rows.length) {
    return <p className="hint">No measurements for this pond yet.</p>
  }

  const windows = anomalies
    .map((a) => ({
      id: a.id,
      from: a.window_start.slice(0, 7),
      to: a.window_end.slice(0, 7),
      active: a.id === activeAnomalyId,
    }))
    .filter((w) => rows.some((r) => r.month === w.from))

  // Label roughly one tick a year, so the axis stays readable on a phone.
  const tickInterval = Math.max(1, Math.round(rows.length / 7)) - 1

  return (
    <figure style={{ margin: 0 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: '0.4rem' }}>
        <figcaption className="hint">
          Water surface area, hectares — measured each month against the seasonal
          expectation.
        </figcaption>
        <button type="button" className="chip" onClick={() => setAsTable((v) => !v)}>
          {asTable ? 'Show as chart' : 'Show as table'}
        </button>
      </div>

      {asTable ? (
        <DataTable rows={rows} />
      ) : (
        <div style={{ width: '100%', height }}>
          <ResponsiveContainer>
            <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />

              {windows.map((w) => (
                <ReferenceArea
                  key={w.id}
                  x1={w.from}
                  x2={w.to}
                  fill="var(--chart-anomaly)"
                  fillOpacity={w.active ? 0.16 : 0.07}
                  stroke="var(--chart-anomaly)"
                  strokeOpacity={w.active ? 0.5 : 0.2}
                  strokeDasharray="4 3"
                />
              ))}

              <XAxis
                dataKey="month"
                tickFormatter={formatMonth}
                interval={tickInterval}
                tick={{ fill: 'var(--chart-axis)', fontSize: 12 }}
                axisLine={{ stroke: 'var(--chart-grid)' }}
                tickLine={false}
                minTickGap={12}
              />
              <YAxis
                width={54}
                tick={{ fill: 'var(--chart-axis)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `${v}`}
                label={{
                  value: 'hectares',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fill: 'var(--chart-axis)', fontSize: 11 },
                }}
              />

              <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--chart-axis)', strokeDasharray: '3 3' }} />
              <Legend
                verticalAlign="top"
                align="left"
                height={30}
                iconType="plainline"
                wrapperStyle={{ fontSize: 13, color: 'var(--ink-2)' }}
              />

              <Line
                name="Expected for the season"
                type="monotone"
                dataKey="expected"
                stroke="var(--chart-expected)"
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                activeDot={false}
                isAnimationActive={false}
              />
              <Line
                name="Actually measured"
                type="monotone"
                dataKey="observed"
                stroke="var(--chart-observed)"
                strokeWidth={2}
                dot={<MeasuredDot />}
                activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--chart-surface)' }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <p className="hint" style={{ marginTop: '0.5rem' }}>
        Shaded bands mark the periods flagged as water loss. Hollow points are months
        with no usable satellite pass — the value there is filled in between
        neighbours, not measured.
      </p>
    </figure>
  )
}

/** Solid dot for a measured month, hollow for an interpolated one. */
function MeasuredDot(props: {
  cx?: number
  cy?: number
  payload?: Row
}) {
  const { cx, cy, payload } = props
  if (cx === undefined || cy === undefined || !payload) return null
  if (payload.interpolated) {
    return (
      <circle
        cx={cx}
        cy={cy}
        r={3}
        fill="var(--chart-surface)"
        stroke="var(--chart-observed)"
        strokeWidth={1.5}
      />
    )
  }
  return <circle cx={cx} cy={cy} r={2.2} fill="var(--chart-observed)" />
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: { payload: Row }[]
}) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const delta = row.observed - row.expected
  return (
    <div className="card card--flat" style={{ padding: '0.6rem 0.75rem', fontSize: 13 }}>
      <strong>{row.label}</strong>
      <div style={{ marginTop: '0.35rem', display: 'grid', gap: '0.15rem' }}>
        <span>
          <Swatch color="var(--chart-observed)" /> Measured {row.observed.toFixed(2)} ha
          {row.interpolated && <em className="hint"> (filled in)</em>}
        </span>
        <span>
          <Swatch color="var(--chart-expected)" dashed /> Expected {row.expected.toFixed(2)} ha
        </span>
        <span className="hint">
          {delta < 0 ? `${Math.abs(delta).toFixed(2)} ha below` : `${delta.toFixed(2)} ha above`}{' '}
          the seasonal expectation
        </span>
      </div>
    </div>
  )
}

function Swatch({ color, dashed = false }: { color: string; dashed?: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        width: 14,
        height: 0,
        marginRight: 6,
        verticalAlign: 'middle',
        borderTop: `2px ${dashed ? 'dashed' : 'solid'} ${color}`,
      }}
    />
  )
}

function DataTable({ rows }: { rows: Row[] }) {
  return (
    <div style={{ maxHeight: 320, overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr>
            <Th>Month</Th>
            <Th align="right">Measured (ha)</Th>
            <Th align="right">Expected (ha)</Th>
            <Th>Source</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.month}>
              <Td>{row.label}</Td>
              <Td align="right">{row.observed.toFixed(2)}</Td>
              <Td align="right">{row.expected.toFixed(2)}</Td>
              <Td>{row.interpolated ? 'Filled in' : 'Measured'}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      style={{
        textAlign: align,
        padding: '0.35rem 0.5rem',
        borderBottom: '1px solid var(--line)',
        position: 'sticky',
        top: 0,
        background: 'var(--surface)',
        fontSize: 12,
        color: 'var(--ink-3)',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {children}
    </th>
  )
}

function Td({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <td style={{ textAlign: align, padding: '0.35rem 0.5rem', borderBottom: '1px solid var(--line)' }}>
      {children}
    </td>
  )
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}
