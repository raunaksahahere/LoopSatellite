import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export { ConfidenceBadge } from './ConfidenceBadge'

/* ------------------------------------------------------------------ Card */
export function Card({
  title,
  action,
  children,
  flat = false,
}: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  flat?: boolean
}) {
  return (
    <section className={flat ? 'card card--flat' : 'card'}>
      {(title || action) && (
        <div className="card__title">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {action && <div style={{ marginLeft: 'auto' }}>{action}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

/* ------------------------------------------------------------------ Note */
export function Note({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'warn' | 'error' | 'plain'
  children: ReactNode
}) {
  const cls = tone === 'plain' ? 'note' : `note note--${tone}`
  return (
    <p className={cls} role={tone === 'error' ? 'alert' : undefined} style={{ margin: 0 }}>
      {children}
    </p>
  )
}

/* -------------------------------------------------------------- Stat tile */
export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
    </div>
  )
}

/* ---------------------------------------------------------------- Loading */
export function Loading({ label = 'Loading…', rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div aria-live="polite" aria-busy="true">
      <span className="visually-hidden">{label}</span>
      <div className="stack" aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: i === 0 ? 84 : 64 }} />
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ Empty state */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

/* ------------------------------------------------------------- Error state */
export function ErrorState({
  error,
  onRetry,
}: {
  error: { message: string; hint?: string }
  onRetry?: () => void
}) {
  return (
    <div className="empty">
      <h2>Something went wrong</h2>
      <p>
        {error.message}
        {error.hint ? ` ${error.hint}` : ''}
      </p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

/* ------------------------------------------------------------- Back link */
export function Back({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link className="back" to={to}>
      <span aria-hidden="true">←</span> {children}
    </Link>
  )
}

/* -------------------------------------------------- Technical disclosure */
export function TechnicalDetail({ children, label = 'How this was detected' }: { children: ReactNode; label?: string }) {
  return (
    <details className="tech">
      <summary>{label}</summary>
      {children}
    </details>
  )
}
