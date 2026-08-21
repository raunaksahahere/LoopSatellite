import type { ConfidenceBand, Outcome } from './types'

/** Plain-language label for a confidence band. Officers see this, not the score. */
export const CONFIDENCE_LABEL: Record<ConfidenceBand, string> = {
  high: 'High confidence',
  medium: 'Needs a closer look',
  low: 'Low confidence',
}

export const OUTCOME_LABEL: Record<Outcome, string> = {
  confirmed: 'Confirmed on the ground',
  seasonal: 'Seasonal — not a loss',
  unclear: 'Still unclear',
  already_actioned: 'Already being dealt with',
}

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/** '2024-11-01' or '2024-11' -> 'Nov 2024' */
export function formatMonth(value: string): string {
  const [year, month] = value.split('-')
  const index = Number(month) - 1
  if (!year || Number.isNaN(index) || !MONTHS[index]) return value
  return `${MONTHS[index]} ${year}`
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatArea(m2: number | null | undefined): string {
  if (m2 === null || m2 === undefined) return '—'
  const ha = m2 / 10_000
  if (ha < 1) return `${Math.round(m2).toLocaleString()} m²`
  return `${ha.toFixed(2)} ha`
}

export function formatHectares(ha: number | null | undefined): string {
  if (ha === null || ha === undefined) return '—'
  return `${ha.toFixed(2)} ha`
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(digits)}%`
}

/** Window description an officer can read out loud. */
export function describeWindow(start: string, end: string): string {
  const from = formatMonth(start)
  const to = formatMonth(end)
  return from === to ? from : `${from} – ${to}`
}
