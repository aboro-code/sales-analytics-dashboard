import type { Filters } from './filters'
import { filtersToParams } from './filters'

/**
 * Base URL of the API. Empty by default: calls go to same-origin /api, which
 * Vite proxies in dev and Vercel rewrites to the API in production (see
 * vercel.json). Same-origin requests avoid CORS preflights and are not blocked
 * by privacy shields (e.g. Brave) that drop cross-site "analytics" requests.
 * Set VITE_API_URL only to call an API on another origin directly.
 */
export const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

// ---------------------------------------------------------------- types
export interface Meta {
  outlets: string[]
  groups: string[]
  items: { item: string; item_group: string; price: number }[]
  order_types: string[]
  settlements: string[]
  brands: string[]
  min_date: string
  max_date: string
  build: Record<string, string>
  /** True when the server has an AI key configured (optional feature). */
  ai_summary?: boolean
}

export interface AiSummary {
  headline: string
  points: string[]
  actions: string[]
  model: string
  provider: 'groq' | 'anthropic'
  /** Every number in the brief was found in the computed facts (server-checked). */
  verified: boolean
  unverified_numbers: string[]
  generated_ms: number
}

export interface Summary {
  total_records: number
  orders: number
  revenue: number
  aov: number
  items_sold: number
  avg_items_per_order: number
  free_items: number
  active_days: number
  avg_daily_revenue: number
  top_outlet: { name: string | null; revenue: number } | null
  top_item: { name: string | null; revenue: number; quantity: number } | null
}

export type Granularity = 'day' | 'week' | 'month'
export interface TimePoint {
  period: string; orders: number; revenue: number; items: number; aov: number
  /** days of the period inside the data/filter range, and whether that is less than the full period */
  days: number; period_days: number; partial: boolean
}
export interface Timeseries { granularity: Granularity; points: TimePoint[] }

export type Dimension = 'outlet' | 'group' | 'item' | 'order_type' | 'settlement'
export interface BreakdownRow { name: string; revenue: number; orders: number; quantity: number; share: number; aov: number }
export interface Breakdown { dim: Dimension; rows: BreakdownRow[] }

export interface HeatCell { weekday: number; hour: number; orders: number; revenue: number }

export interface Insight { id: string; title: string; text: string; tone: 'positive' | 'neutral' | 'warning'; value?: unknown }

export interface RecordRow {
  bill_no: number; order_ts: string; outlet: string; item_group: string; item: string
  price: number; quantity: number; revenue: number; order_type: string; settlement: string; brand: string
}
export interface RecordsPage {
  page: number; page_size: number; total: number; pages: number; sort: string; order: 'asc' | 'desc'; rows: RecordRow[]
}

// ---------------------------------------------------------------- timing telemetry
/** Last API timing, shown in the footer so performance is visible, not claimed. */
export interface Timing { path: string; serverMs: number; totalMs: number; cache: string | null }
type Listener = (t: Timing) => void
const listeners = new Set<Listener>()
export function onTiming(fn: Listener) {
  listeners.add(fn)
  return () => void listeners.delete(fn)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// ---------------------------------------------------------------- fetch
export async function getJSON<T>(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const qs = params && [...params].length ? `?${params}` : ''
  const t0 = performance.now()
  const res = await fetch(`${API_URL}${path}${qs}`, { signal })
  const totalMs = performance.now() - t0
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  const timing: Timing = {
    path,
    serverMs: Number(res.headers.get('X-Query-Time-ms') ?? NaN),
    totalMs,
    cache: res.headers.get('X-Cache'),
  }
  listeners.forEach((l) => l(timing))
  return res.json() as Promise<T>
}

export const api = {
  health: (signal?: AbortSignal) => getJSON<{ status: string; rows: number }>('/health', undefined, signal),
  meta: (signal?: AbortSignal) => getJSON<Meta>('/api/meta', undefined, signal),
  summary: (f: Filters, signal?: AbortSignal) => getJSON<Summary>('/api/summary', filtersToParams(f), signal),
  timeseries: (f: Filters, granularity: Granularity, signal?: AbortSignal) => {
    const p = filtersToParams(f)
    p.set('granularity', granularity)
    return getJSON<Timeseries>('/api/timeseries', p, signal)
  },
  breakdown: (f: Filters, dim: Dimension, limit?: number, signal?: AbortSignal) => {
    const p = filtersToParams(f)
    p.set('dim', dim)
    if (limit) p.set('limit', String(limit))
    return getJSON<Breakdown>('/api/breakdown', p, signal)
  },
  heatmap: (f: Filters, signal?: AbortSignal) => getJSON<{ cells: HeatCell[] }>('/api/heatmap', filtersToParams(f), signal),
  insights: (f: Filters, signal?: AbortSignal) => getJSON<{ insights: Insight[] }>('/api/insights', filtersToParams(f), signal),
  aiSummary: (f: Filters, signal?: AbortSignal) => getJSON<AiSummary>('/api/ai-summary', filtersToParams(f), signal),
  records: (f: Filters, page: number, pageSize: number, sort: string, order: 'asc' | 'desc', signal?: AbortSignal) => {
    const p = filtersToParams(f)
    p.set('page', String(page))
    p.set('page_size', String(pageSize))
    p.set('sort', sort)
    p.set('order', order)
    return getJSON<RecordsPage>('/api/records', p, signal)
  },
  exportUrl: (f: Filters) => {
    const p = filtersToParams(f)
    const qs = [...p].length ? `?${p}` : ''
    return `${API_URL}/api/export.csv${qs}`
  },
}
