import { useState } from 'react'
import type { Insight } from '../lib/api'
import { filterKey, type Filters } from '../lib/filters'
import { useAiSummary, useInsights, useMeta } from '../lib/queries'
import { Card, QueryBoundary } from './ui'

const TONE: Record<Insight['tone'], { label: string; icon: string; cls: string }> = {
  positive: { label: 'Strength', icon: '▲', cls: 'text-good' },
  warning: { label: 'Watch', icon: '!', cls: 'text-bad' },
  neutral: { label: 'Fact', icon: '•', cls: 'text-ink-3' },
}

export function InsightsPanel({ filters }: { filters: Filters }) {
  const q = useInsights(filters)
  const aiEnabled = useMeta().data?.ai_summary === true
  const key = filterKey(filters)
  const [requested, setRequested] = useState<string | null>(null)
  // Disabled queries still return cached data, so a brief already generated for
  // this filter set reappears without another model call.
  const ai = useAiSummary(filters, aiEnabled && requested === key)
  const showAi = ai.data || ai.isFetching || (ai.isError && requested === key)

  return (
    <Card
      title="Insights"
      subtitle="Generated from the same SQL as the charts. Rule-based, so every number is exact. Updates with your filters."
      actions={
        aiEnabled && !ai.data ? (
          <button
            type="button"
            onClick={() => (ai.isError ? ai.refetch() : setRequested(key))}
            disabled={ai.isFetching}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-accent px-3 text-xs font-semibold text-ink-1 transition-colors hover:bg-surface-2 disabled:opacity-60"
          >
            <span aria-hidden>✦</span>
            {ai.isFetching ? 'Writing summary…' : 'AI summary'}
          </button>
        ) : undefined
      }
    >
      {showAi && <AiBrief query={ai} />}
      <QueryBoundary query={q} height={160} isEmpty={(d) => d.insights.length === 0}>
        {(d) => (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {d.insights.map((i) => {
              const t = TONE[i.tone]
              return (
                <li key={i.id} className="rounded-lg bg-surface-2 p-3">
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold">
                    <span className={t.cls} aria-hidden>{t.icon}</span>
                    <span className="text-ink-1">{i.title}</span>
                    <span className="sr-only">({t.label})</span>
                  </div>
                  <p className="text-[13px] leading-relaxed text-ink-2">{i.text}</p>
                </li>
              )
            })}
          </ul>
        )}
      </QueryBoundary>
    </Card>
  )
}

function AiBrief({ query }: { query: ReturnType<typeof useAiSummary> }) {
  if (query.isError) {
    return (
      <p role="alert" className="mb-3 rounded-lg border border-line bg-surface-2 p-3 text-[13px] text-ink-2">
        AI summary unavailable: {query.error.message}
      </p>
    )
  }
  if (!query.data) {
    return (
      <div aria-busy className="mb-3 animate-pulse rounded-lg border border-line bg-surface-2 p-4">
        <p className="text-[13px] text-ink-3">Claude is reading this view's numbers…</p>
        <div className="mt-3 h-3 w-3/4 rounded bg-line" />
        <div className="mt-2 h-3 w-2/3 rounded bg-line" />
      </div>
    )
  }
  const d = query.data
  return (
    <section aria-label="AI summary" className="mb-4 rounded-lg border border-accent/60 bg-surface-2 p-4">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-3 uppercase tracking-wide">
        <span aria-hidden>✦</span> AI summary
      </div>
      <p className="text-[15px] font-semibold leading-snug text-ink-1">{d.headline}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-ink-2">
        {d.points.map((p) => <li key={p}>{p}</li>)}
      </ul>
      {d.actions.length > 0 && (
        <>
          <p className="mt-3 text-xs font-semibold text-ink-1">Suggested next steps</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-ink-2">
            {d.actions.map((a) => <li key={a}>{a}</li>)}
          </ul>
        </>
      )}
      <p className="mt-3 text-[11px] text-ink-3">
        Written by {d.model} from the computed facts on this page. The model copies numbers, it doesn't calculate them.
      </p>
    </section>
  )
}
