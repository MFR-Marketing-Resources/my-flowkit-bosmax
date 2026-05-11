export const KUALA_LUMPUR_TIMEZONE = 'Asia/Kuala_Lumpur'

const dateTimeFormatter = new Intl.DateTimeFormat('en-MY', {
  timeZone: KUALA_LUMPUR_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

const dateFormatter = new Intl.DateTimeFormat('en-MY', {
  timeZone: KUALA_LUMPUR_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

export function formatKualaLumpurDateTime(value: string | null | undefined, fallback = '—') {
  if (!value) return fallback

  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return fallback

  return `${dateTimeFormatter.format(date)} MYT`
}

export function formatKualaLumpurDate(value: string | null | undefined, fallback = '—') {
  if (!value) return fallback

  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return fallback

  return dateFormatter.format(date)
}