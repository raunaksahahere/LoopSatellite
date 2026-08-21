import { VerificationQueue } from '../components/queue/VerificationQueue'
import { ReportDownloadButton } from '../components/report/ReportDownloadButton'
import { Back } from '../components/ui'

export function QueuePage() {
  return (
    <div className="page">
      <Back to="/">Back to the map</Back>

      <header className="page__head">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h1>Ponds to review</h1>
          <ReportDownloadButton scope="all" />
        </div>
        <p>
          Water losses that the season does not explain, most urgent first. Each one
          has been measured from satellite images — open it to see the evidence and
          record what you found.
        </p>
      </header>

      <VerificationQueue />
    </div>
  )
}
