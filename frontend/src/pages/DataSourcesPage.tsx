import { DataSources } from '../components/provenance/DataSources'
import { Back, ErrorState, Loading } from '../components/ui'
import { api } from '../lib/api'
import { useAsync } from '../lib/useAsync'

export function DataSourcesPage() {
  const { data, loading, error, reload } = useAsync(() => api.provenance(), [])

  return (
    <div className="page">
      <Back to="/map">Back to the map</Back>

      <header className="page__head">
        <h1>How do we know this works on real data?</h1>
        <p>
          Every layer this app draws, what produced the version you are looking at,
          and what would produce it for real. Nothing here is inferred from the data
          describing itself — the statuses are declared in the code that serves this
          page.
        </p>
      </header>

      {loading && !data && <Loading label="Loading data sources…" rows={4} />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && <DataSources data={data} />}
    </div>
  )
}
