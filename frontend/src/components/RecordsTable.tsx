import { useEffect, useState } from 'react'
import { api, type RecordRow } from '../lib/api'
import { filterKey, type Filters } from '../lib/filters'
import { formatDateTime, formatINR, formatNum } from '../lib/format'
import { useRecords } from '../lib/queries'
import { Card, QueryBoundary } from './ui'

type SortKey = keyof Pick<RecordRow, 'order_ts' | 'bill_no' | 'outlet' | 'item_group' | 'item' | 'price' | 'quantity' | 'revenue' | 'order_type' | 'settlement'>

const COLUMNS: { key: SortKey; label: string; align?: 'right'; render?: (r: RecordRow) => string; hideSm?: boolean }[] = [
  { key: 'order_ts', label: 'Date & time', render: (r) => formatDateTime(r.order_ts) },
  { key: 'bill_no', label: 'Bill', hideSm: true },
  { key: 'outlet', label: 'Outlet' },
  { key: 'item', label: 'Item' },
  { key: 'item_group', label: 'Category', hideSm: true },
  { key: 'price', label: 'Price', align: 'right', render: (r) => formatINR(r.price), hideSm: true },
  { key: 'quantity', label: 'Qty', align: 'right' },
  { key: 'revenue', label: 'Revenue', align: 'right', render: (r) => formatINR(r.revenue) },
  { key: 'order_type', label: 'Type', hideSm: true },
  { key: 'settlement', label: 'Channel', hideSm: true },
]

const PAGE_SIZE = 25

/** Server-side paginated and sorted: the browser never holds more than one page. */
export function RecordsTable({ filters }: { filters: Filters }) {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<SortKey>('order_ts')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const key = filterKey(filters)

  useEffect(() => setPage(1), [key]) // new filters -> back to page 1

  const q = useRecords(filters, page, PAGE_SIZE, sort, order)
  const total = q.data?.total ?? 0
  const pages = q.data?.pages ?? 1

  const onSort = (k: SortKey) => {
    if (k === sort) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else {
      setSort(k)
      setOrder(['price', 'quantity', 'revenue', 'order_ts'].includes(k) ? 'desc' : 'asc')
    }
    setPage(1)
  }

  return (
    <Card
      title="Records"
      subtitle={q.data ? `${formatNum(total)} line items match` : 'Raw line items'}
      actions={
        <a
          href={api.exportUrl(filters)}
          download
          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-accent-ink hover:opacity-90"
          title="Download every matching row as CSV (streamed by the server)"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden><path d="M8 2v8m0 0 3-3m-3 3L5 7M3 13h10" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Export CSV{q.data ? ` (${formatNum(total)})` : ''}
        </a>
      }
    >
      <QueryBoundary query={q} height={420} isEmpty={(d) => d.total === 0}>
        {(d) => (
          <>
            <div className="-mx-4 overflow-x-auto sm:mx-0">
              <table className="w-full min-w-[480px] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-ink-3">
                    {COLUMNS.map((c) => (
                      <th key={c.key} scope="col"
                        aria-sort={sort === c.key ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
                        className={`px-2 py-2 font-medium whitespace-nowrap first:pl-4 sm:first:pl-2 ${c.align === 'right' ? 'text-right' : ''} ${c.hideSm ? 'hidden md:table-cell' : ''}`}>
                        <button onClick={() => onSort(c.key)} className="inline-flex items-center gap-1 hover:text-ink-1">
                          {c.label}
                          <span aria-hidden className={sort === c.key ? 'text-ink-1' : 'opacity-0'}>{order === 'asc' ? '↑' : '↓'}</span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="tabular">
                  {d.rows.map((r, i) => (
                    <tr key={`${r.bill_no}-${r.item}-${i}`} className="border-b border-line last:border-0 hover:bg-surface-2">
                      {COLUMNS.map((c) => (
                        <td key={c.key}
                          className={`px-2 py-2 whitespace-nowrap text-ink-2 first:pl-4 sm:first:pl-2 ${c.align === 'right' ? 'text-right' : ''} ${c.hideSm ? 'hidden md:table-cell' : ''} ${c.key === 'revenue' ? 'font-medium text-ink-1' : ''}`}>
                          {c.render ? c.render(r) : String(r[c.key])}
                          {c.key === 'item' && r.price === 0 && <span className="ml-1.5 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-3">free</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <nav className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3" aria-label="Pagination">
              <span className="tabular">
                {formatNum((page - 1) * PAGE_SIZE + 1)}–{formatNum(Math.min(page * PAGE_SIZE, d.total))} of {formatNum(d.total)}
              </span>
              <div className="flex items-center gap-1">
                <PageBtn onClick={() => setPage(1)} disabled={page === 1} label="First page">«</PageBtn>
                <PageBtn onClick={() => setPage((p) => p - 1)} disabled={page === 1} label="Previous page">‹ Prev</PageBtn>
                <span className="tabular px-2 text-ink-2">Page {formatNum(page)} / {formatNum(pages)}</span>
                <PageBtn onClick={() => setPage((p) => p + 1)} disabled={page >= pages} label="Next page">Next ›</PageBtn>
                <PageBtn onClick={() => setPage(pages)} disabled={page >= pages} label="Last page">»</PageBtn>
              </div>
            </nav>
          </>
        )}
      </QueryBoundary>
    </Card>
  )
}

function PageBtn({ children, onClick, disabled, label }: { children: React.ReactNode; onClick: () => void; disabled: boolean; label: string }) {
  return (
    <button onClick={onClick} disabled={disabled} aria-label={label}
      className="rounded-md border border-line px-2 py-1 text-ink-1 hover:bg-surface-2 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent">
      {children}
    </button>
  )
}
