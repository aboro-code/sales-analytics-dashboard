import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../lib/api'

/**
 * The API runs on a free tier that sleeps after inactivity, and the first
 * request can take 30–60 s while the container boots. Ping /health first and,
 * if it's slow, explain what's happening instead of showing a stalled page.
 */
export function WakeGate({ children }: { children: ReactNode }) {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.health(signal),
    retry: 30,
    retryDelay: 2500,
    staleTime: Infinity,
  })
  const [slow, setSlow] = useState(false)
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    if (health.isSuccess) return
    const t = setTimeout(() => setSlow(true), 1500)
    const i = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => {
      clearTimeout(t)
      clearInterval(i)
    }
  }, [health.isSuccess])

  if (health.isSuccess) return <>{children}</>

  if (health.isError) {
    return (
      <Centered>
        <p className="text-base font-semibold text-ink-1">The API isn't responding</p>
        <p className="max-w-md text-sm text-ink-3">{health.error.message}</p>
        <button onClick={() => health.refetch()} className="mt-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-ink">Try again</button>
      </Centered>
    )
  }

  if (!slow) return <Centered><div className="skeleton h-2 w-40" /></Centered>

  return (
    <Centered>
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-line border-t-[var(--accent)]" aria-hidden />
      <p className="text-base font-semibold text-ink-1">Waking up the server…</p>
      <p className="max-w-md text-sm text-ink-3">
        The API runs on a free hosting tier that sleeps when idle. The first visit takes about 30–60 seconds to boot;
        after that the dashboard responds in milliseconds.
      </p>
      <p className="tabular text-xs text-ink-3">{seconds}s elapsed</p>
    </Centered>
  )
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex min-h-[70vh] flex-col items-center justify-center gap-3 px-4 text-center" role="status">{children}</div>
}
