import type { ReactNode } from 'react'
import { ApiError } from '../api'
import type { Tone } from '../labels'

export function Badge({ tone = 'neutral', children, testId }: { tone?: Tone; children: ReactNode; testId?: string }) {
  return (
    <span className={`badge badge-${tone}`} data-testid={testId}>
      {children}
    </span>
  )
}

export function Alert({ tone = 'info', title, children }: { tone?: 'info' | 'warning' | 'success'; title?: string; children?: ReactNode }) {
  return (
    <div className={`alert alert-${tone}`} role="status">
      {title && <strong>{title}</strong>}
      {children && <div>{children}</div>}
    </div>
  )
}

const conflictTitles: Record<string, string> = {
  STOCK_UNAVAILABLE: 'Materiał niedostępny',
  STALE_PLAN: 'Plan nieaktualny',
  PROJECT_LOCKED: 'Projekt zablokowany',
  PLAN_NOT_RESERVED: 'Plan nie jest zarezerwowany',
}

/** Czytelna prezentacja błędu API: komunikat `detail` i lista `problems`. */
export function ErrorAlert({ error, onClose }: { error: unknown; onClose?: () => void }) {
  if (!error) return null
  const apiError = error instanceof ApiError ? error : null
  const message = apiError?.message ?? (error instanceof Error ? error.message : 'Nieznany błąd')
  const title = apiError?.status === 409 ? `Konflikt: ${conflictTitles[apiError.code] ?? 'stan się zmienił'}` : 'Błąd'
  return (
    <div className="alert alert-error" role="alert" data-testid="error-alert">
      <div className="alert-head">
        <strong>{title}</strong>
        {onClose && (
          <button type="button" className="alert-close" onClick={onClose} aria-label="Zamknij">
            ×
          </button>
        )}
      </div>
      <div>{message}</div>
      {apiError && apiError.problems.length > 0 && (
        <ul>
          {apiError.problems.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Spinner({ label = 'Ładowanie…' }: { label?: string }) {
  return (
    <div className="spinner-row" aria-busy="true">
      <span className="spinner" /> {label}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}
