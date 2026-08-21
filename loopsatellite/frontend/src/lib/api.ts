import type {
  Anomaly,
  AnomalyDetail,
  EvidenceResponse,
  Health,
  NLQueryResponse,
  NoticeResponse,
  PondCollection,
  QueueResponse,
  TimeSeries,
  Verification,
} from './types'

// Empty base => same origin, which the Vite dev proxy forwards to the API.
const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly hint?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(
      'Could not reach the LoopSatellite service.',
      0,
      'Is the backend running on port 8000?',
    )
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    let hint: string | undefined
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      if (typeof body.hint === 'string') hint = body.hint
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(detail, response.status, hint)
  }

  return response.json() as Promise<T>
}

function query(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export const api = {
  health: () => request<Health>('/api/health'),

  ponds: (params: { ward?: string; mouza?: string; bbox?: string } = {}) =>
    request<PondCollection>(`/api/ponds${query(params)}`),

  wards: () => request<{ wards: string[]; mouzas: string[] }>('/api/ponds/wards'),

  timeseries: (pondId: string) => request<TimeSeries>(`/api/ponds/${pondId}/timeseries`),

  anomalies: (params: Record<string, string | number | boolean | undefined> = {}) =>
    request<{ count: number; items: Anomaly[] }>(`/api/anomalies${query(params)}`),

  anomaly: (id: string) => request<AnomalyDetail>(`/api/anomalies/${encodeURIComponent(id)}`),

  queue: (params: { limit?: number; include_reviewed?: boolean } = {}) =>
    request<QueueResponse>(`/api/queue${query(params)}`),

  verify: (
    anomalyId: string,
    body: { outcome: string; officer_note?: string; officer_name?: string },
  ) =>
    request<Verification>(`/api/queue/${encodeURIComponent(anomalyId)}/verify`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  evidence: (anomalyId: string) =>
    request<EvidenceResponse>('/api/llm/evidence', {
      method: 'POST',
      body: JSON.stringify({ anomaly_id: anomalyId }),
    }),

  notice: (anomalyId: string, officerName?: string) =>
    request<NoticeResponse>('/api/llm/notice', {
      method: 'POST',
      body: JSON.stringify({ anomaly_id: anomalyId, officer_name: officerName || null }),
    }),

  ask: (question: string) =>
    request<NLQueryResponse>('/api/llm/query', {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),

  reportPdfUrl: (params: {
    scope: 'anomaly' | 'ward' | 'all'
    anomaly_id?: string
    ward?: string
    officer_name?: string
    include_notice?: boolean
  }) => `${BASE}/api/reports/pdf${query(params)}`,
}
