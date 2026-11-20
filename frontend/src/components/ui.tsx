import type { ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'

// ---------------------------------------------------------------- Card
interface CardProps {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}

export function Card({ title, subtitle, actions, children, className = '' }: CardProps) {
  return (
    <section className={`min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-ink-1">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[13px] text-ink-3">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------- Query states
interface QueryBoundaryProps<T> {
  query: UseQueryResult<T>
  height: number
  isEmpty?: (data: T) => boolean
  children: (data: T) => ReactNode
}

/**
 * Loading → skeleton; error → retry; empty → message. On refetch (filters
 * changed) the previous render stays visible at reduced opacity rather than
 * flashing a skeleton, so the layout never jumps.
 */
export function QueryBoundary<T>({ query, height, isEmpty, children }: QueryBoundaryProps<T>) {
  if (query.isPending) return <div className="skeleton w-full" style={{ height }} aria-busy="true" aria-label="Loading" />
  if (query.isError) return <ErrorState height={height} error={query.error} onRetry={() => query.refetch()} />
  if (isEmpty?.(query.data)) return <EmptyState height={height} />
  const refreshing = query.isFetching && query.isPlaceholderData
  return (
    <div className={`transition-opacity duration-200 ${refreshing ? 'opacity-50' : 'opacity-100'}`} aria-busy={refreshing}>
      {children(query.data)}
    </div>
  )
}

export function ErrorState({ height, error, onRetry }: { height: number; error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong'
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg bg-surface-2 p-4 text-center" style={{ minHeight: height }} role="alert">
      <p className="text-sm font-medium text-ink-1">Couldn't load this view</p>
      <p className="max-w-sm text-xs text-ink-3">{msg}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-1 rounded-md border border-line px-3 py-1.5 text-xs font-medium text-ink-1 hover:bg-surface">
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ height, message = 'No orders match these filters.' }: { height: number; message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg bg-surface-2 p-4 text-center" style={{ minHeight: height }}>
      <p className="text-sm font-medium text-ink-2">{message}</p>
      <p className="text-xs text-ink-3">Try widening the date range or clearing a filter.</p>
    </div>
  )
}

// ---------------------------------------------------------------- Segmented control
interface SegmentedProps<T extends string> {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}

export function Segmented<T extends string>({ value, options, onChange, label }: SegmentedProps<T>) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
            value === o.value ? 'bg-surface text-ink-1 shadow-sm' : 'text-ink-3 hover:text-ink-1'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- Tooltip shell
export function TooltipBox({ title, rows }: { title: ReactNode; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold text-ink-1">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4 text-ink-2">
          <span className="flex items-center gap-1.5">
            {r.color && <span className="inline-block h-2 w-2 rounded-full" style={{ background: r.color }} />}
            {r.label}
          </span>
          <span className="tabular font-medium text-ink-1">{r.value}</span>
        </div>
      ))}
    </div>
  )
}
