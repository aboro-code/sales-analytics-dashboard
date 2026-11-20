/** Indian number formatting: 1,23,45,678 grouping and lakh / crore short forms. */
const inrFull = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const inrPaise = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const num = new Intl.NumberFormat('en-IN')

export const formatINR = (v: number) => inrFull.format(v)
export const formatINR2 = (v: number) => inrPaise.format(v)
export const formatNum = (v: number) => num.format(v)

/** ₹6.95 Cr, ₹12.4 L, ₹48.2K, ₹629 */
export function formatINRShort(v: number, digits = 2): string {
  const a = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (a >= 1e7) return `${sign}₹${trim((a / 1e7).toFixed(digits))} Cr`
  if (a >= 1e5) return `${sign}₹${trim((a / 1e5).toFixed(digits))} L`
  if (a >= 1e3) return `${sign}₹${trim((a / 1e3).toFixed(1))}K`
  return `${sign}₹${Math.round(a)}`
}

/** Compact counts: 1.1L orders, 43.4K */
export function formatCountShort(v: number): string {
  const a = Math.abs(v)
  if (a >= 1e7) return `${trim((v / 1e7).toFixed(2))} Cr`
  if (a >= 1e5) return `${trim((v / 1e5).toFixed(2))} L`
  if (a >= 1e3) return `${trim((v / 1e3).toFixed(1))}K`
  return String(Math.round(v))
}

export const formatPct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`

function trim(s: string) {
  return s.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** '2026-03-18' -> '18 Mar 2026'; '2026-03' -> 'Mar 2026' */
export function formatPeriod(period: string, withYear = true): string {
  const [y, m, d] = period.split('-')
  const mon = MONTHS[Number(m) - 1]
  if (!d) return `${mon} ${y}`
  return withYear ? `${Number(d)} ${mon} ${y}` : `${Number(d)} ${mon}`
}

export function formatDateTime(ts: string): string {
  const [date, time] = ts.split(' ')
  return `${formatPeriod(date)}, ${time?.slice(0, 5) ?? ''}`
}

export const WEEKDAYS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function formatHour(h: number): string {
  const suffix = h < 12 || h === 24 ? 'am' : 'pm'
  return `${h % 12 || 12}${suffix}`
}
