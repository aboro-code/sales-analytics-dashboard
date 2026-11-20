import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { BreakdownRow, Dimension } from '../lib/api'
import type { Filters } from '../lib/filters'
import { formatINR, formatINR2, formatINRShort, formatNum, formatPct } from '../lib/format'
import { useBreakdown } from '../lib/queries'
import { Card, QueryBoundary, TooltipBox } from './ui'

interface Props {
  filters: Filters
  dim: Dimension
  title: string
  subtitle?: string
  limit?: number
  layout: 'vertical' | 'horizontal'
  /** Click a bar to toggle that value as a filter (cross-filtering). */
  onSelect?: (name: string) => void
  selected?: string[]
}

/**
 * Single series, so a single colour (slot 1). Selected bars stay full colour
 * and the rest recede, which highlights rather than repaints.
 */
export function BarBreakdown({ filters, dim, title, subtitle, limit, layout, onSelect, selected = [] }: Props) {
  const q = useBreakdown(filters, dim, limit)
  const height = layout === 'horizontal' ? Math.max(220, (limit ?? 7) * 30 + 20) : 260

  return (
    <Card title={title} subtitle={subtitle ?? (onSelect ? 'Click a bar to filter by it' : undefined)}>
      <QueryBoundary query={q} height={height} isEmpty={(d) => d.rows.length === 0}>
        {(d) => (
          <div style={{ height }}>
            <ResponsiveContainer width="100%" height="100%">
              {layout === 'vertical' ? (
                <BarChart data={d.rows} margin={{ top: 20, right: 4, bottom: 0, left: 0 }} barCategoryGap="22%">
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="name" tickLine={false} axisLine={{ stroke: 'var(--axis)' }} interval={0}
                    tick={{ fontSize: 11 }} tickFormatter={(v: string) => (v.length > 12 ? `${v.slice(0, 11)}…` : v)} />
                  <YAxis tickFormatter={(v) => formatINRShort(v, 1)} tickLine={false} axisLine={false} width={60} />
                  <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={(p) => <BarTip {...p} />} />
                  <Bar dataKey="revenue" radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false}
                    onClick={(row: unknown) => onSelect?.((row as BreakdownRow).name)} className={onSelect ? 'cursor-pointer' : ''}>
                    {d.rows.map((r) => <Cell key={r.name} fill="var(--series-1)" fillOpacity={selected.length && !selected.includes(r.name) ? 0.3 : 1} />)}
                    <LabelList dataKey="share" position="top" formatter={(v: unknown) => formatPct(Number(v), 0)} fill="var(--ink-3)" fontSize={11} />
                  </Bar>
                </BarChart>
              ) : (
                <BarChart data={d.rows} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }} barCategoryGap="18%">
                  <CartesianGrid horizontal={false} />
                  <XAxis type="number" tickFormatter={(v) => formatINRShort(v, 1)} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="name" width={150} tickLine={false} axisLine={false} interval={0}
                    tick={{ fontSize: 12 }} tickFormatter={(v: string) => (v.length > 22 ? `${v.slice(0, 21)}…` : v)} />
                  <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={(p) => <BarTip {...p} />} />
                  <Bar dataKey="revenue" radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={false}
                    onClick={(row: unknown) => onSelect?.((row as BreakdownRow).name)} className={onSelect ? 'cursor-pointer' : ''}>
                    {d.rows.map((r) => <Cell key={r.name} fill="var(--series-1)" fillOpacity={selected.length && !selected.includes(r.name) ? 0.3 : 1} />)}
                    <LabelList dataKey="revenue" position="right" formatter={(v: unknown) => formatINRShort(Number(v), 1)} fill="var(--ink-2)" fontSize={11} />
                  </Bar>
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        )}
      </QueryBoundary>
    </Card>
  )
}

function BarTip({ active, payload }: { active?: boolean; payload?: readonly { payload?: unknown }[] }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload as BreakdownRow
  return (
    <TooltipBox title={r.name} rows={[
      { label: 'Revenue', value: formatINR(r.revenue) },
      { label: 'Share', value: formatPct(r.share) },
      { label: 'Orders', value: formatNum(r.orders) },
      { label: 'Units', value: formatNum(r.quantity) },
      { label: 'Revenue / order', value: formatINR2(r.aov) },
    ]} />
  )
}
