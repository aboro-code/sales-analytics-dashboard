import type { UseQueryResult } from '@tanstack/react-query'
import type { Summary } from '../lib/api'
import { formatINR, formatINR2, formatINRShort, formatNum } from '../lib/format'

interface Tile { label: string; value: string; hint: string; title?: string }

function tiles(s: Summary): Tile[] {
  return [
    { label: 'Revenue', value: formatINRShort(s.revenue), hint: `${formatINRShort(s.avg_daily_revenue)} / day`, title: formatINR(s.revenue) },
    { label: 'Orders', value: formatNum(s.orders), hint: `${formatNum(s.active_days)} trading days`, title: formatNum(s.orders) },
    { label: 'Avg order value', value: formatINR2(s.aov), hint: 'revenue ÷ orders' },
    { label: 'Items sold', value: formatNum(s.items_sold), hint: `${s.avg_items_per_order.toFixed(2)} per order`, title: formatNum(s.items_sold) },
    { label: 'Line items', value: formatNum(s.total_records), hint: `${formatNum(s.free_items)} free dips incl.`, title: `${formatNum(s.total_records)} records` },
    { label: 'Top outlet', value: s.top_outlet?.name ?? '–', hint: s.top_outlet ? formatINRShort(s.top_outlet.revenue) : '' },
    { label: 'Top item', value: s.top_item?.name ?? '–', hint: s.top_item ? `${formatINRShort(s.top_item.revenue)} · ${formatNum(s.top_item.quantity)} sold` : '' },
  ]
}

export function KpiCards({ query }: { query: UseQueryResult<Summary> }) {
  if (query.isPending) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {Array.from({ length: 7 }, (_, i) => <div key={i} className="skeleton h-[92px]" />)}
      </div>
    )
  }
  if (query.isError) {
    return (
      <div role="alert" className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-2">
        Couldn't load KPIs: {query.error.message}{' '}
        <button className="font-medium text-accent" onClick={() => query.refetch()}>Retry</button>
      </div>
    )
  }
  const dim = query.isFetching && query.isPlaceholderData
  return (
    <div className={`grid grid-cols-2 gap-3 transition-opacity md:grid-cols-4 xl:grid-cols-7 ${dim ? 'opacity-50' : ''}`}>
      {tiles(query.data).map((t, i) => (
        <div
          key={t.label}
          title={t.title}
          className={`min-w-0 rounded-xl border border-line bg-surface p-4 ${i === 6 ? 'col-span-2 xl:col-span-1' : ''}`}
        >
          <div className="text-xs font-medium text-ink-3">{t.label}</div>
          <div className={`mt-1 truncate font-semibold text-ink-1 ${i >= 5 ? 'text-base' : 'text-2xl'}`}>{t.value}</div>
          <div className="mt-1 truncate text-xs text-ink-3">{t.hint}</div>
        </div>
      ))}
    </div>
  )
}
