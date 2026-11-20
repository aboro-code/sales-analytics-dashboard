import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { BreakdownRow, Dimension } from '../lib/api'
import { colorFor } from '../lib/colors'
import type { Filters } from '../lib/filters'
import { formatINR, formatINR2, formatINRShort, formatNum, formatPct } from '../lib/format'
import { useBreakdown } from '../lib/queries'
import { Card, QueryBoundary, TooltipBox } from './ui'

interface Props {
  filters: Filters
  dim: Extract<Dimension, 'order_type' | 'settlement'>
  title: string
  subtitle?: string
  canonical: string[]
  note?: string
}

/**
 * Part-to-whole with at most 4 slices. Every slice also has a legend row with
 * its share and value, so identity never relies on colour alone and the
 * low-contrast palette slots stay readable.
 */
export function MixDonut({ filters, dim, title, subtitle, canonical, note }: Props) {
  const q = useBreakdown(filters, dim)
  return (
    <Card title={title} subtitle={subtitle}>
      <QueryBoundary query={q} height={200} isEmpty={(d) => d.rows.length === 0}>
        {(d) => {
          // canonical order keeps slice positions stable across filters
          const rows = [...d.rows].sort((a, b) => canonical.indexOf(a.name) - canonical.indexOf(b.name))
          const totalOrders = rows.reduce((n, r) => n + r.orders, 0)
          return (
            <div className="flex flex-col items-center gap-4 sm:flex-row">
              <div className="relative h-[180px] w-[180px] shrink-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={rows} dataKey="revenue" nameKey="name" innerRadius={56} outerRadius={84}
                      paddingAngle={rows.length > 1 ? 1.5 : 0} stroke="var(--surface)" strokeWidth={2}
                      startAngle={90} endAngle={-270} isAnimationActive={false}>
                      {rows.map((r) => <Cell key={r.name} fill={colorFor(r.name, canonical)} />)}
                    </Pie>
                    <Tooltip content={({ active, payload }) => {
                      if (!active || !payload?.length) return null
                      const r = payload[0].payload as BreakdownRow
                      return <TooltipBox title={r.name} rows={[
                        { label: 'Revenue', value: formatINR(r.revenue), color: colorFor(r.name, canonical) },
                        { label: 'Share of revenue', value: formatPct(r.share) },
                        { label: 'Orders', value: formatNum(r.orders) },
                        { label: 'AOV', value: formatINR2(r.aov) },
                      ]} />
                    }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-[11px] text-ink-3">orders</span>
                  <span className="text-lg font-semibold text-ink-1">{formatNum(totalOrders)}</span>
                </div>
              </div>
              <ul className="w-full min-w-0 space-y-2">
                {rows.map((r) => (
                  <li key={r.name} className="flex items-center gap-2 text-sm">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: colorFor(r.name, canonical) }} />
                    <span className="min-w-0 flex-1 truncate text-ink-2">{r.name}</span>
                    <span className="tabular font-semibold text-ink-1">{formatPct(r.share)}</span>
                    <span className="tabular w-16 text-right text-xs text-ink-3">{formatINRShort(r.revenue, 1)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )
        }}
      </QueryBoundary>
      {note && <p className="mt-3 border-t border-line pt-3 text-xs text-ink-3">{note}</p>}
    </Card>
  )
}
