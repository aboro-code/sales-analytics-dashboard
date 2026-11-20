import { useMemo, useState } from 'react'
import type { HeatCell } from '../lib/api'
import type { Filters } from '../lib/filters'
import { formatHour, formatINR, formatNum, WEEKDAYS_SHORT } from '../lib/format'
import { useHeatmap } from '../lib/queries'
import { Card, QueryBoundary } from './ui'

const STEPS = 8 // --seq-0 … --seq-7 (one hue, light → dark)

/**
 * Weekday × hour grid of order counts with a sequential single-hue scale.
 * Plain CSS grid rather than a chart library: it's a table of cells, and this
 * keeps it accessible (each cell has a label) and fast.
 */
export function Heatmap({ filters }: { filters: Filters }) {
  const q = useHeatmap(filters)
  const [hover, setHover] = useState<HeatCell | null>(null)

  return (
    <Card title="Peak hours" subtitle="Orders by weekday and hour of day">
      <QueryBoundary query={q} height={260} isEmpty={(d) => d.cells.length === 0}>
        {(d) => <Grid cells={d.cells} hover={hover} setHover={setHover} />}
      </QueryBoundary>
    </Card>
  )
}

function Grid({ cells, hover, setHover }: { cells: HeatCell[]; hover: HeatCell | null; setHover: (c: HeatCell | null) => void }) {
  const { hours, lookup, max } = useMemo(() => {
    const hs = [...new Set(cells.map((c) => c.hour))].sort((a, b) => a - b)
    const lo = hs[0] ?? 11
    const hi = hs[hs.length - 1] ?? 23
    const range = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i)
    const map = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c]))
    return { hours: range, lookup: map, max: Math.max(1, ...cells.map((c) => c.orders)) }
  }, [cells])

  const step = (v: number) => (v <= 0 ? 0 : Math.min(STEPS - 1, 1 + Math.floor((v / max) * (STEPS - 1.0001))))
  const total = cells.reduce((n, c) => n + c.orders, 0)

  return (
    <div>
      <div className="overflow-x-auto">
        <div
          className="grid min-w-[520px] gap-[2px]"
          style={{ gridTemplateColumns: `36px repeat(${hours.length}, minmax(0, 1fr))` }}
          onMouseLeave={() => setHover(null)}
          role="table"
          aria-label="Orders by weekday and hour"
        >
          <div />
          {hours.map((h) => (
            <div key={h} className="tabular pb-1 text-center text-[11px] text-ink-3">{formatHour(h)}</div>
          ))}
          {WEEKDAYS_SHORT.map((wd, w) => (
            <div key={wd} className="contents" role="row">
              <div className="flex items-center text-[11px] text-ink-3" role="rowheader">{wd}</div>
              {hours.map((h) => {
                const c = lookup.get(`${w}-${h}`) ?? { weekday: w, hour: h, orders: 0, revenue: 0 }
                const s = step(c.orders)
                const isHover = hover?.weekday === w && hover?.hour === h
                return (
                  <div
                    key={h}
                    role="cell"
                    tabIndex={0}
                    aria-label={`${wd} ${formatHour(h)}: ${formatNum(c.orders)} orders`}
                    onMouseEnter={() => setHover(c)}
                    onFocus={() => setHover(c)}
                    className={`h-7 rounded-[4px] outline-none ${isHover ? 'ring-2 ring-[var(--ink-1)]' : ''}`}
                    style={{ background: `var(--seq-${s})` }}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="min-h-[18px] text-ink-2" aria-live="polite">
          {hover ? (
            <>
              <span className="font-semibold text-ink-1">{WEEKDAYS_SHORT[hover.weekday]} {formatHour(hover.hour)}–{formatHour(hover.hour + 1)}</span>
              {' · '}{formatNum(hover.orders)} orders ({total ? ((hover.orders / total) * 100).toFixed(1) : 0}%) · {formatINR(hover.revenue)}
            </>
          ) : (
            <span className="text-ink-3">Hover or focus a cell for details</span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-ink-3">
          <span>Fewer</span>
          {Array.from({ length: STEPS - 1 }, (_, i) => (
            <span key={i} className="h-3 w-4 rounded-[3px]" style={{ background: `var(--seq-${i + 1})` }} />
          ))}
          <span>More</span>
        </div>
      </div>
    </div>
  )
}
