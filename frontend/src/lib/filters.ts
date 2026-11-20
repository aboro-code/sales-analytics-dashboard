import { useCallback, useEffect, useState } from 'react'

export interface Filters {
  start: string | null
  end: string | null
  outlets: string[]
  groups: string[]
  items: string[]
  order_types: string[]
  settlements: string[]
}

export type ListKey = 'outlets' | 'groups' | 'items' | 'order_types' | 'settlements'
export const LIST_KEYS: ListKey[] = ['outlets', 'groups', 'items', 'order_types', 'settlements']

export const EMPTY_FILTERS: Filters = {
  start: null, end: null, outlets: [], groups: [], items: [], order_types: [], settlements: [],
}

/** Comma-separated lists keep shared URLs short; the API accepts both forms. */
export function filtersToParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.start) p.set('start', f.start)
  if (f.end) p.set('end', f.end)
  for (const k of LIST_KEYS) if (f[k].length) p.set(k, [...f[k]].sort().join(','))
  return p
}

const ISO = /^\d{4}-\d{2}-\d{2}$/

export function filtersFromSearch(search: string): Filters {
  const p = new URLSearchParams(search)
  const list = (k: string) => (p.get(k) ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  const date = (k: string) => {
    const v = p.get(k)
    return v && ISO.test(v) ? v : null
  }
  return {
    start: date('start'),
    end: date('end'),
    outlets: list('outlets'),
    groups: list('groups'),
    items: list('items'),
    order_types: list('order_types'),
    settlements: list('settlements'),
  }
}

/** Stable key for TanStack Query: order of selected values must not matter. */
export function filterKey(f: Filters) {
  return filtersToParams(f).toString()
}

export function activeFilterCount(f: Filters) {
  return (f.start || f.end ? 1 : 0) + LIST_KEYS.reduce((n, k) => n + (f[k].length ? 1 : 0), 0)
}

/**
 * Filter state that lives in the URL (?start=…&outlets=A,B) so any view is
 * shareable and survives reloads. replaceState avoids polluting history with
 * every click; the back button still works across page loads.
 */
export function useUrlFilters() {
  const [filters, setFiltersState] = useState<Filters>(() => filtersFromSearch(window.location.search))

  useEffect(() => {
    const qs = filtersToParams(filters).toString()
    const url = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`
    window.history.replaceState(null, '', url)
  }, [filters])

  useEffect(() => {
    const onPop = () => setFiltersState(filtersFromSearch(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const setFilters = useCallback((update: Partial<Filters> | ((f: Filters) => Filters)) => {
    setFiltersState((prev) => (typeof update === 'function' ? update(prev) : { ...prev, ...update }))
  }, [])

  const toggleValue = useCallback((key: ListKey, value: string) => {
    setFiltersState((prev) => {
      const has = prev[key].includes(value)
      return { ...prev, [key]: has ? prev[key].filter((v) => v !== value) : [...prev[key], value] }
    })
  }, [])

  const reset = useCallback(() => setFiltersState(EMPTY_FILTERS), [])

  return { filters, setFilters, toggleValue, reset }
}

/** Debounce a value: rapid multi-select clicks become one request burst. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}
