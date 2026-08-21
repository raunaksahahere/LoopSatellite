export type ConfidenceBand = 'high' | 'medium' | 'low'
export type ConversionSignal = 'built_up' | 'bare' | 'none'
export type Outcome = 'confirmed' | 'seasonal' | 'unclear' | 'already_actioned'

export interface Geometry {
  type: 'Polygon' | 'MultiPolygon'
  coordinates: number[][][] | number[][][][]
}

export interface PondProperties {
  id: string
  name: string | null
  ward: string | null
  mouza: string | null
  centroid_lon: number
  centroid_lat: number
  baseline_area_m2: number | null
  provenance: string | null
  anomaly_count: number
  worst_confidence_band: ConfidenceBand | null
}

export interface PondFeature {
  type: 'Feature'
  geometry: Geometry
  properties: PondProperties
}

export interface PondCollection {
  type: 'FeatureCollection'
  features: PondFeature[]
}

export interface Anomaly {
  id: string
  pond_id: string
  pond_name: string | null
  ward: string | null
  mouza: string | null
  centroid_lon: number | null
  centroid_lat: number | null
  window_start: string
  window_end: string
  detected_on: string
  confidence: number
  confidence_band: ConfidenceBand
  loss_pct: number
  loss_m2: number | null
  loss_ha: number | null
  baseline_area_m2: number | null
  observed_area_m2: number | null
  residual_z: number | null
  recovered: boolean
  persistence_months: number | null
  data_quality: number | null
  conversion_signal: ConversionSignal | null
  conversion_label: string | null
  status: string
  chip_url: string | null
  provenance: string | null
  summary?: string
  reviewed_at?: string
  reviewed_by?: string | null
}

export interface DetectionExplanation {
  summary: string
  reasons: string[]
  confidence: number
  confidence_band: ConfidenceBand
  seasonality_note: string
  technical: string
  llm_involvement: string
}

export interface ConversionExplanation {
  signal: ConversionSignal | null
  label: string
  summary: string
  technical: string | null
}

export interface Measurement {
  summary: string
  technical: string
}

export interface Verification {
  id: number
  anomaly_id: string
  outcome: Outcome
  officer_note: string | null
  officer_name: string | null
  verified_at: string
}

export interface AnomalyDetail {
  anomaly: Anomaly
  detection: DetectionExplanation
  conversion: ConversionExplanation
  measurement: Measurement
  verifications: Verification[]
}

export interface TimeSeriesPoint {
  month: string
  observed_m2: number
  expected_m2: number
  interpolated: boolean
}

export interface TimeSeries {
  pond_id: string
  capacity_m2: number
  n_interpolated: number
  points: TimeSeriesPoint[]
  measurement?: Measurement
}

export interface QueueResponse {
  total: number
  pending: number
  reviewed: number
  storage: string
  items: Anomaly[]
}

export interface Health {
  status: string
  data: {
    precomputed: boolean
    generated_at?: string
    pond_count?: number
    anomaly_count?: number
    is_synthetic?: boolean
    pond_provenance?: string[]
    detail?: string
  }
  llm: {
    configured: boolean
    model: string | null
    search_provider: string
    search_configured: boolean
  }
  verification_storage: string
}

export interface EvidenceFinding {
  title: string
  url: string | null
  source: string | null
  published: string | null
  snippet: string
  relevance: 'direct' | 'contextual' | 'unrelated'
  why_relevant: string
}

export interface EvidenceResponse {
  anomaly_id: string
  query_used: string
  findings: EvidenceFinding[]
  searched: boolean
  note: string | null
}

export interface RetrievedProvision {
  document: string
  citation: string
  quote: string
  score: number
  relevance_note: string | null
}

export interface NoticeResponse {
  anomaly_id: string
  grounded: boolean
  provisions: RetrievedProvision[]
  draft: string | null
  disclaimer: string
  llm_used: boolean
  note: string | null
}

export interface ParsedFilter {
  ward?: string | null
  mouza?: string | null
  min_loss_pct?: number | null
  max_loss_pct?: number | null
  recovered?: boolean | null
  conversion_signal?: ConversionSignal | null
  confidence_band?: ConfidenceBand | null
  min_confidence?: number | null
  since?: string | null
  until?: string | null
}

export interface NLQueryResponse {
  question: string
  filter: ParsedFilter
  interpretation: string
  results: Anomaly[]
  count: number
  unparsed: string[]
}
