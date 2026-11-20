import type { Insight } from '../lib/api'
import type { Filters } from '../lib/filters'
import { useInsights } from '../lib/queries'
import { Card, QueryBoundary } from './ui'

const TONE: Record<Insight['tone'], { label: string; icon: string; cls: string }> = {
  positive: { label: 'Strength', icon: '▲', cls: 'text-good' },
  warning: { label: 'Watch', icon: '!', cls: 'text-bad' },
  neutral: { label: 'Fact', icon: '•', cls: 'text-ink-3' },
}

export function InsightsPanel({ filters }: { filters: Filters }) {
  const q = useInsights(filters)
  return (
    <Card
      title="Insights"
      subtitle="Generated from the same SQL as the charts. Rule-based, so every number is exact. Updates with your filters."
    >
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
