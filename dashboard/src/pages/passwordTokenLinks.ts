export function buildTokenLink(path: '/activate-account' | '/reset-password', token: string): string {
  const origin = typeof window === 'undefined' ? '' : window.location.origin
  return `${origin}${path}#token=${encodeURIComponent(token)}`
}
