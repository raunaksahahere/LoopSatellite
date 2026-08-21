import { api } from '../../lib/api'

interface Props {
  scope: 'anomaly' | 'ward' | 'all'
  anomalyId?: string
  ward?: string
  includeNotice?: boolean
  label?: string
  variant?: 'primary' | 'plain'
}

/**
 * Straight anchor to the PDF endpoint — no fetch, no blob, no spinner to get
 * stuck. The browser handles the download, which is one less thing to fail in
 * front of an audience.
 */
export function ReportDownloadButton({
  scope,
  anomalyId,
  ward,
  includeNotice = false,
  label,
  variant = 'plain',
}: Props) {
  const href = api.reportPdfUrl({
    scope,
    anomaly_id: anomalyId,
    ward,
    include_notice: includeNotice || undefined,
  })

  const text =
    label ??
    (scope === 'anomaly'
      ? 'Download this case as PDF'
      : scope === 'ward'
        ? `Download the ${ward} report`
        : 'Download the full report')

  return (
    <a className={variant === 'primary' ? 'btn btn--primary' : 'btn'} href={href} download>
      <span aria-hidden="true">↓</span> {text}
    </a>
  )
}
