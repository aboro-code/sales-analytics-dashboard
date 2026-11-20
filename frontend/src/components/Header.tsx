import { useEffect, useState } from 'react'
import { onTiming, type Timing } from '../lib/api'

type Theme = 'system' | 'light' | 'dark'

function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('theme') as Theme) || 'system'
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    const el = document.documentElement
    if (theme === 'system') delete el.dataset.theme
    else el.dataset.theme = theme
    try {
      localStorage.setItem('theme', theme)
    } catch { /* storage blocked */ }
  }, [theme])
  return [theme, setTheme] as const
}

export function Header({ brand }: { brand?: string }) {
  const [theme, setTheme] = useTheme()
  const next: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }
  const icon = { system: '◐', light: '☀', dark: '☾' }[theme]

  return (
    <header className="flex items-start justify-between gap-3 sm:items-center">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <img src="/favicon.svg" alt="" className="h-9 w-9 shrink-0" />
        <div className="min-w-0">
          <h1 className="text-lg font-semibold leading-tight text-ink-1 sm:text-xl">Sales Analytics</h1>
          <p className="text-xs text-ink-3">Restaurant orders across 6 Bengaluru outlets</p>
        </div>
        {brand && (
          <span
            className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium text-ink-2"
            title="The dataset contains a single brand, so brand is shown here rather than offered as a filter."
          >
            Brand: {brand}
          </span>
        )}
      </div>
      <button
        onClick={() => setTheme(next[theme])}
        className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-sm text-ink-2 hover:text-ink-1"
        aria-label={`Theme: ${theme}. Switch to ${next[theme]}`}
        title={`Theme: ${theme}`}
      >
        <span aria-hidden>{icon}</span>
        <span className="hidden capitalize sm:inline">{theme}</span>
      </button>
    </header>
  )
}

/** Shows the last API round trip so performance is visible, not just claimed. */
export function PerfFooter({ build }: { build?: Record<string, string> }) {
  const [t, setT] = useState<Timing | null>(null)
  useEffect(() => onTiming((x) => { if (x.path !== '/health') setT(x) }), [])
  return (
    <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4 text-xs text-ink-3">
      <span className="tabular">
        {t ? (
          <>
            Last API call <code className="text-ink-2">{t.path}</code>: server {Number.isFinite(t.serverMs) ? `${t.serverMs.toFixed(1)} ms` : 'n/a'}
            {' · '}round trip {t.totalMs.toFixed(0)} ms{t.cache ? ` · cache ${t.cache}` : ''}
          </>
        ) : 'Waiting for data…'}
      </span>
      {build && (
        <span>
          {Number(build.rows).toLocaleString('en-IN')} rows · built {build.built_at?.slice(0, 10)} · {build.engine}
        </span>
      )}
    </footer>
  )
}
