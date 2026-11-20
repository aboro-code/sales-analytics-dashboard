import { BarBreakdown } from './components/BarBreakdown'
import { FilterBar } from './components/FilterBar'
import { Header, PerfFooter } from './components/Header'
import { Heatmap } from './components/Heatmap'
import { InsightsPanel } from './components/InsightsPanel'
import { KpiCards } from './components/KpiCards'
import { MixDonut } from './components/MixDonut'
import { RecordsTable } from './components/RecordsTable'
import { TrendChart } from './components/TrendChart'
import { ErrorState } from './components/ui'
import { WakeGate } from './components/WakeGate'
import { ORDER_TYPE_ORDER, SETTLEMENT_ORDER } from './lib/colors'
import { useDebounced, useUrlFilters } from './lib/filters'
import { useMeta, useSummary } from './lib/queries'

export default function App() {
  return (
    <div className="mx-auto flex max-w-[1440px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <WakeGate>
        <Dashboard />
      </WakeGate>
    </div>
  )
}

function Dashboard() {
  const meta = useMeta()
  const { filters, setFilters, toggleValue, reset } = useUrlFilters()
  // The filter bar updates instantly; requests follow 300 ms after the last change.
  const f = useDebounced(filters, 300)
  const summary = useSummary(f)

  if (meta.isPending) {
    return (
      <>
        <div className="skeleton h-12 w-72" />
        <div className="skeleton h-24 w-full" />
      </>
    )
  }
  if (meta.isError) return <ErrorState height={300} error={meta.error} onRetry={() => meta.refetch()} />
  const m = meta.data

  return (
    <>
      <Header brand={m.brands.length === 1 ? m.brands[0] : undefined} />

      <div className="z-20 -mx-4 lg:sticky lg:top-0 border-b border-line bg-page/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <FilterBar meta={m} filters={filters} setFilters={setFilters} reset={reset} />
      </div>

      <KpiCards query={summary} />

      <InsightsPanel filters={f} />

      <TrendChart filters={f} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <BarBreakdown filters={f} dim="outlet" title="Revenue by outlet" layout="vertical"
          onSelect={(v) => toggleValue('outlets', v)} selected={filters.outlets} />
        <BarBreakdown filters={f} dim="group" title="Revenue by category" layout="horizontal"
          onSelect={(v) => toggleValue('groups', v)} selected={filters.groups} />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <MixDonut filters={f} dim="order_type" title="Order type mix" subtitle="Share of revenue" canonical={ORDER_TYPE_ORDER} />
        <MixDonut filters={f} dim="settlement" title="Payment & channel mix" subtitle="Share of revenue" canonical={SETTLEMENT_ORDER}
          note="Channel follows order type: ZomatoPay and SwiggyPay appear only on Delivery, and Dineout only on Dine-In and Takeaway. About 10% of delivery orders are direct (Cash/Card/Coupon)." />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <div className="min-w-0 lg:col-span-2">
          <BarBreakdown filters={f} dim="item" limit={10} title="Top 10 items" subtitle="By revenue" layout="horizontal"
            onSelect={(v) => toggleValue('items', v)} selected={filters.items} />
        </div>
        <div className="min-w-0 lg:col-span-3">
          <Heatmap filters={f} />
        </div>
      </div>

      <RecordsTable filters={f} />

      <PerfFooter build={m.build} />
    </>
  )
}
