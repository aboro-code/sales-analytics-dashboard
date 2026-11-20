import { useState } from 'react'
import { Area, ComposedChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Granularity, TimePoint } from '../lib/api'
import type { Filters } from '../lib/filters'
import { formatCountShort, formatINR, formatINR2, formatINRShort, formatNum, formatPeriod } from '../lib/format'
import { useTimeseries } from '../lib/queries'
import { Card, QueryBoundary, Segmented, TooltipBox } from './ui'

type Metric = 'revenue' | 'orders' | 'aov'
const METRICS: Record<Metric, { label: string; axis: (v: number) => string; full: (v: number) => string }> = {
  revenue: { label: 'Revenue', axis: (v) => formatINRShort(v, 1), full: formatINR },
  orders: { label: 'Orders', axis: formatCountShort, full: formatNum },
  aov: { label: 'AOV', axis: (v) => `₹${Math.round(v)}`, full: formatINR2 },
}

type Row = TimePoint & { full: number | null; edge: number | null }

/**
 * Complete periods are drawn as the filled area. Periods cut off by the data
 * or filter range (e.g. a final week with only 2 days) are drawn as a dashed
 * continuation, so a half-week never reads as a sales collapse.
 */
function splitPartial(points: TimePoint[], metric: Metric): Row[] {
  return points.map((p, i) => {
    const v = p[metric]
    const touchesPartial = p.partial || points[i - 1]?.partial || points[i + 1]?.partial
    // AOV is a ratio, so a partial period is still comparable.
    if (metric === 'aov') return { ...p, full: v, edge: null }
    return { ...p, full: p.partial ? null : v, edge: touchesPartial ? v : null }
  })
}

/**
 * One measure at a time (toggle) instead of revenue + orders on two y-axes:
 * dual-axis charts imply a correlation that's only an artefact of scaling.
 */
export function TrendChart({ filters }: { filters: Filters }) {
  const [granularity, setGranularity] = useState<Granularity>('week')
  const [metric, setMetric] = useState<Metric>('revenue')
  const q = useTimeseries(filters, granularity)
  const m = METRICS[metric]
  const tickFmt = (p: string) => (granularity === 'month' ? formatPeriod(p) : formatPeriod(p, false))

  return (
    <Card
      title={`${m.label} over time`}
      subtitle={granularity === 'day' ? 'Daily totals' : `${granularity === 'week' ? 'Weeks start Monday. ' : ''}Dashed segments are partial ${granularity}s cut off by the date range`}
      actions={
        <>
          <Segmented label="Metric" value={metric} onChange={setMetric}
            options={[{ value: 'revenue', label: 'Revenue' }, { value: 'orders', label: 'Orders' }, { value: 'aov', label: 'AOV' }]} />
          <Segmented label="Granularity" value={granularity} onChange={setGranularity}
            options={[{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }]} />
        </>
      }
    >
      <QueryBoundary query={q} height={280} isEmpty={(d) => d.points.length === 0}>
        {(d) => (
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={splitPartial(d.points, metric)} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="period" tickFormatter={tickFmt} tickLine={false} axisLine={{ stroke: 'var(--axis)' }} minTickGap={28} />
                <YAxis tickFormatter={m.axis} tickLine={false} axisLine={false} width={64}
                  domain={metric === 'aov' ? ['auto', 'auto'] : [0, 'auto']} />
                <Tooltip
                  cursor={{ stroke: 'var(--ink-3)', strokeWidth: 1 }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const p = payload[0].payload as TimePoint
                    const title = granularity === 'week' ? `Week of ${formatPeriod(p.period)}` : formatPeriod(p.period)
                    return (
                      <TooltipBox title={<>{title}{p.partial && <span className="ml-1 font-normal text-ink-3">· partial, {p.days} of {p.period_days} days</span>}</>} rows={[
                        { label: 'Revenue', value: formatINR(p.revenue), color: metric === 'revenue' ? 'var(--series-1)' : undefined },
                        { label: 'Orders', value: formatNum(p.orders), color: metric === 'orders' ? 'var(--series-1)' : undefined },
                        { label: 'AOV', value: formatINR2(p.aov), color: metric === 'aov' ? 'var(--series-1)' : undefined },
                      ]} />
                    )
                  }}
                />
                <Area type="monotone" dataKey="full" stroke="var(--series-1)" strokeWidth={2} fill="url(#trendFill)"
                  dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} isAnimationActive={false} />
                <Line type="monotone" dataKey="edge" stroke="var(--series-1)" strokeWidth={2} strokeDasharray="4 4"
                  dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} isAnimationActive={false} legendType="none" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </QueryBoundary>
    </Card>
  )
}
