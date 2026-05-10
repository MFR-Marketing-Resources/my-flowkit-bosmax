import type { Product } from '../types'

function normalizeMoneyValue(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) return null
  return Math.round(numericValue * 100) / 100
}

function parseCommissionRate(rate: string | null | undefined): number | null {
  if (!rate) return null
  const numericValue = Number(String(rate).replace('%', '').trim())
  if (!Number.isFinite(numericValue)) return null
  return numericValue
}

export function formatCurrencyDisplay(value: number | string | null | undefined, currency: string | null | undefined = 'MYR'): string {
  const normalizedValue = normalizeMoneyValue(value)
  if (normalizedValue === null) return 'NOT_AVAILABLE'
  const currencyCode = (currency || 'MYR').trim() || 'MYR'
  return `${currencyCode} ${normalizedValue.toFixed(2)}`
}

export function formatCommissionRateDisplay(rate: string | null | undefined): string {
  const parsedRate = parseCommissionRate(rate)
  if (parsedRate === null) return 'NOT_AVAILABLE'
  return Number.isInteger(parsedRate) ? `${parsedRate}%` : `${parsedRate.toFixed(2).replace(/\.?0+$/, '')}%`
}

export function formatCommissionDisplay(product: Pick<Product, 'price' | 'currency' | 'commission_amount' | 'commission_rate'>): string {
  const normalizedPrice = normalizeMoneyValue(product.price)
  const normalizedAmount = normalizeMoneyValue(product.commission_amount)
  const parsedRate = parseCommissionRate(product.commission_rate)

  let commissionAmount = normalizedAmount
  if (commissionAmount === null && normalizedPrice !== null && parsedRate !== null) {
    commissionAmount = Math.round(normalizedPrice * (parsedRate / 100) * 100) / 100
  }

  const amountLabel = commissionAmount === null ? 'NOT_AVAILABLE' : formatCurrencyDisplay(commissionAmount, product.currency)
  const rateLabel = formatCommissionRateDisplay(product.commission_rate)
  return `Comm: ${amountLabel} / ${rateLabel}`
}

export function formatTaxonomyPath(category: string | null | undefined, subcategory: string | null | undefined, type: string | null | undefined): string {
  const parts = [category, subcategory, type].filter((value): value is string => Boolean(value && value.trim()))
  return parts.length ? parts.join(' > ') : 'NOT_AVAILABLE'
}