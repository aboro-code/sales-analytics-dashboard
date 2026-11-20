import { useEffect, useId, useMemo, useRef, useState } from 'react'

interface Option { value: string; label?: string; group?: string }

interface Props {
  label: string
  options: Option[]
  selected: string[]
  onChange: (values: string[]) => void
  searchable?: boolean
}

/** Dropdown checklist. Empty selection means "all" (no filter). */
export function MultiSelect({ label, options, selected, onChange, searchable = false }: Props) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return needle ? options.filter((o) => (o.label ?? o.value).toLowerCase().includes(needle)) : options
  }, [options, q])

  const toggle = (v: string) => onChange(selected.includes(v) ? selected.filter((s) => s !== v) : [...selected, v])

  const summary =
    selected.length === 0 ? 'All' : selected.length === 1 ? selected[0] : `${selected.length} selected`

  let lastGroup: string | undefined
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={`flex h-9 w-full items-center justify-between gap-2 rounded-lg border px-3 text-left text-sm transition-colors sm:w-auto sm:min-w-[150px] ${
          selected.length ? 'border-accent bg-surface text-ink-1' : 'border-line bg-surface text-ink-2 hover:border-ink-3'
        }`}
      >
        <span className="truncate">
          <span className="text-ink-3">{label}: </span>
          <span className="font-medium text-ink-1">{summary}</span>
        </span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}>
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div
          id={id}
          role="listbox"
          aria-multiselectable
          className="absolute left-0 z-30 mt-1 w-full min-w-[240px] rounded-lg border border-line bg-surface p-1 shadow-xl sm:w-72"
        >
          {searchable && (
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`Search ${label.toLowerCase()}…`}
              className="mb-1 h-8 w-full rounded-md border border-line bg-surface-2 px-2 text-sm text-ink-1 outline-none focus:border-accent"
            />
          )}
          <div className="max-h-72 overflow-y-auto">
            {filtered.map((o) => {
              const header = o.group && o.group !== lastGroup ? o.group : null
              lastGroup = o.group
              const checked = selected.includes(o.value)
              return (
                <div key={o.value}>
                  {header && <div className="px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wide text-ink-3 uppercase">{header}</div>}
                  <label
                    role="option"
                    aria-selected={checked}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink-1 hover:bg-surface-2"
                  >
                    <input type="checkbox" checked={checked} onChange={() => toggle(o.value)} className="h-4 w-4 accent-[var(--accent)]" />
                    <span className="truncate">{o.label ?? o.value}</span>
                  </label>
                </div>
              )
            })}
            {filtered.length === 0 && <p className="px-2 py-3 text-sm text-ink-3">No matches</p>}
          </div>
          <div className="mt-1 flex justify-between border-t border-line px-1 pt-1">
            <button className="rounded px-2 py-1 text-xs text-ink-2 hover:text-ink-1" onClick={() => onChange(options.map((o) => o.value))}>
              Select all
            </button>
            <button className="rounded px-2 py-1 text-xs text-ink-2 hover:text-ink-1" onClick={() => onChange([])}>
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
