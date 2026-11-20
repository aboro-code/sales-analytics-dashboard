/**
 * Categorical colour follows the *entity*, never its rank: the slot is fixed
 * by the entity's position in the canonical list from /api/meta, so filtering
 * or re-sorting never repaints a survivor.
 */
const SLOTS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)']

/** Canonical display order for the mix charts (largest first in this dataset). */
export const ORDER_TYPE_ORDER = ['Dine-In', 'Delivery', 'Takeaway']
export const SETTLEMENT_ORDER = ['Cash/Card/Coupon', 'ZomatoPay', 'SwiggyPay', 'Dineout']

export function colorFor(name: string, canonical: string[]): string {
  const i = canonical.indexOf(name)
  return i >= 0 && i < SLOTS.length ? SLOTS[i] : 'var(--ink-3)'
}

export const SERIES_1 = 'var(--series-1)'
