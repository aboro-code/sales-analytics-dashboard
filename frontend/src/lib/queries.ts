import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, type Dimension, type Granularity } from './api'
import { filterKey, type Filters } from './filters'

/*
 * One hook per endpoint. The query key embeds the normalised filter string, so
 * identical views are deduplicated and cached client-side; keepPreviousData
 * holds the old chart on screen while the new slice loads.
 */
const common = { placeholderData: keepPreviousData, staleTime: 5 * 60_000 } as const

export const useMeta = (enabled = true) =>
  useQuery({ queryKey: ['meta'], queryFn: ({ signal }) => api.meta(signal), staleTime: Infinity, enabled })

export const useSummary = (f: Filters) =>
  useQuery({ queryKey: ['summary', filterKey(f)], queryFn: ({ signal }) => api.summary(f, signal), ...common })

export const useTimeseries = (f: Filters, g: Granularity) =>
  useQuery({ queryKey: ['timeseries', filterKey(f), g], queryFn: ({ signal }) => api.timeseries(f, g, signal), ...common })

export const useBreakdown = (f: Filters, dim: Dimension, limit?: number) =>
  useQuery({ queryKey: ['breakdown', filterKey(f), dim, limit], queryFn: ({ signal }) => api.breakdown(f, dim, limit, signal), ...common })

export const useHeatmap = (f: Filters) =>
  useQuery({ queryKey: ['heatmap', filterKey(f)], queryFn: ({ signal }) => api.heatmap(f, signal), ...common })

export const useInsights = (f: Filters) =>
  useQuery({ queryKey: ['insights', filterKey(f)], queryFn: ({ signal }) => api.insights(f, signal), ...common })

export const useRecords = (f: Filters, page: number, pageSize: number, sort: string, order: 'asc' | 'desc') =>
  useQuery({
    queryKey: ['records', filterKey(f), page, pageSize, sort, order],
    queryFn: ({ signal }) => api.records(f, page, pageSize, sort, order, signal),
    ...common,
  })

/** AI brief: only fetched on demand (button click), never retried automatically. */
export const useAiSummary = (f: Filters, enabled: boolean) =>
  useQuery({
    queryKey: ['ai-summary', filterKey(f)],
    queryFn: ({ signal }) => api.aiSummary(f, signal),
    enabled,
    retry: false,
    staleTime: Infinity,
  })
