import { sessionHeaders } from './auth'
import type {
  Anomaly,
  AnomalyDetail,
  Area,
  AreaCapability,
  EvidenceResponse,
  Health,
  NLQueryResponse,
  NoticeResponse,
  PondCollection,
  Provenance,
  QueueResponse,
  TimeSeries,
  Verification,
} from './types'

// Empty base => same origin, which the Vite dev proxy forwards to the API.
const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * A static file served by the API, not by whatever host serves this bundle.
 *
 * The before/after chips live under `precomputed/` on the API. A root-relative
 * `/precomputed/...` works in development, because the Vite proxy forwards it —
 * and breaks in production, where the frontend is on Vercel and the API is on
 * Render, so the browser asks Vercel for a file it has never had. That is one
 * broken image per finding, on the panel that is meant to be the evidence.
 */
export function assetUrl(path: string): string {
  return `${BASE}/${path.replace(/^\/+/, '')}`
}

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
      headers: {
        'Content-Type': 'application/json',
        // A signed-in user sends a Clerk bearer token; nobody else sends
        // anything. Read fresh per request — Clerk's tokens are short-lived by
        // design and a cached one is a 401 mid-session.
        ...(await sessionHeaders()),
        ...(init?.headers ?? {}),
      },
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
    if (response.status === 403) hint = 'Sign in to do this.'
    if (response.status === 401) hint = 'Your session has expired — sign in again.'
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

  provenance: () => request<Provenance>('/api/provenance'),

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

  // --- Areas: the SLOW path. Submitting one starts a job, it does not answer
  // a question. Asking questions is `ask` above and returns in milliseconds.
  areaCapability: () => request<AreaCapability>('/api/areas/capability'),

  areas: (limit = 50) => request<{ count: number; items: Area[] }>(`/api/areas?limit=${limit}`),

  area: (id: string) => request<Area>(`/api/areas/${encodeURIComponent(id)}`),

  /** The water bodies one submitted area measured, shaped like /api/ponds. */
  areaWaterbodies: (id: string) =>
    request<PondCollection>(`/api/areas/${encodeURIComponent(id)}/waterbodies`),

  /**
   * Every water body every finished area has measured.
   *
   * Shared across accounts on purpose: the map shows what the system has
   * measured, not what this tab happened to start. It also survives a refresh,
   * which the per-tab version did not.
   */
  monitoredWaterbodies: () => request<PondCollection>('/api/areas/waterbodies'),

  submitArea: (body: {
    name: string
    lat: number
    lon: number
    radius_km: number
    requested_by?: string
  }) => request<Area>('/api/areas', { method: 'POST', body: JSON.stringify(body) }),

  reportPdfUrl: (params: {
    scope: 'anomaly' | 'ward' | 'all'
    anomaly_id?: string
    ward?: string
    officer_name?: string
    include_notice?: boolean
  }) => `${BASE}/api/reports/pdf${query(params)}`,
}
