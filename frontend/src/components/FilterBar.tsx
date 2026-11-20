import type { Meta } from '../lib/api'
import { activeFilterCount, type Filters, type ListKey } from '../lib/filters'
import { formatPeriod } from '../lib/format'
import { MultiSelect } from './MultiSelect'

interface Props {
  meta: Meta
  filters: Filters
  setFilters: (f: Partial<Filters>) => void
  reset: () => void
}

function shift(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/**
 * Presets are anchored to the *latest date in the data*, not today: the dataset
 * ends on its max_date, so "last 30 days" relative to the wall clock would be empty.
 */
function presets(meta: Meta) {
  const max = meta.max_date
  const clamp = (d: string) => (d < meta.min_date ? meta.min_date : d)
  return [
    { id: '7d', label: 'Last 7d', start: clamp(shift(max, -6)), end: max },
    { id: '30d', label: 'Last 30d', start: clamp(shift(max, -29)), end: max },
    { id: '90d', label: 'Last 90d', start: clamp(shift(max, -89)), end: max },
    { id: 'ytd', label: 'This year', start: clamp(`${max.slice(0, 4)}-01-01`), end: max },
    { id: 'all', label: 'All', start: null, end: null },
  ] as const
}

const DIMENSIONS: { key: ListKey; label: string; options: (m: Meta) => { value: string; group?: string }[]; searchable?: boolean }[] = [
  { key: 'outlets', label: 'Outlet', options: (m) => m.outlets.map((v) => ({ value: v })) },
  { key: 'groups', label: 'Category', options: (m) => m.groups.map((v) => ({ value: v })) },
  { key: 'items', label: 'Item', options: (m) => m.items.map((i) => ({ value: i.item, group: i.item_group })), searchable: true },
  { key: 'order_types', label: 'Order type', options: (m) => m.order_types.map((v) => ({ value: v })) },
  { key: 'settlements', label: 'Channel', options: (m) => m.settlements.map((v) => ({ value: v })) },
]

export function FilterBar({ meta, filters, setFilters, reset }: Props) {
  const ps = presets(meta)
  const active = ps.find((p) => p.start === filters.start && p.end === filters.end)?.id
  const count = activeFilterCount(filters)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Date range preset" className="inline-flex flex-wrap rounded-lg bg-surface-2 p-0.5">
          {ps.map((p) => (
            <button
              key={p.id}
              role="radio"
              aria-checked={active === p.id}
              onClick={() => setFilters({ start: p.start, end: p.end })}
              className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                active === p.id ? 'bg-surface text-ink-1 shadow-sm' : 'text-ink-3 hover:text-ink-1'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 text-sm">
          <label className="sr-only" htmlFor="start">Start date</label>
          <input
            id="start"
            type="date"
            min={meta.min_date}
            max={filters.end ?? meta.max_date}
            value={filters.start ?? meta.min_date}
            onChange={(e) => setFilters({ start: e.target.value || null })}
            className="tabular h-9 rounded-lg border border-line bg-surface px-2 text-ink-1"
          />
          <span className="text-ink-3">→</span>
          <label className="sr-only" htmlFor="end">End date</label>
          <input
            id="end"
            type="date"
            min={filters.start ?? meta.min_date}
            max={meta.max_date}
            value={filters.end ?? meta.max_date}
            onChange={(e) => setFilters({ end: e.target.value || null })}
            className="tabular h-9 rounded-lg border border-line bg-surface px-2 text-ink-1"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap sm:items-center">
        {DIMENSIONS.map((d) => (
          <MultiSelect
            key={d.key}
            label={d.label}
            options={d.options(meta)}
            selected={filters[d.key]}
            onChange={(values) => setFilters({ [d.key]: values } as Partial<Filters>)}
            searchable={d.searchable}
          />
        ))}
        <button
          onClick={reset}
          disabled={count === 0}
          className="h-9 rounded-lg px-3 text-sm font-medium text-accent hover:bg-surface-2 disabled:cursor-default disabled:text-ink-3 disabled:hover:bg-transparent"
        >
          Reset{count ? ` (${count})` : ''}
        </button>
      </div>
      <p className="text-xs text-ink-3">
        Showing {formatPeriod(filters.start ?? meta.min_date)} – {formatPeriod(filters.end ?? meta.max_date)}
        {count > 0 && ' · filters are saved in the URL, so you can share this view'}
      </p>
    </div>
  )
}
