import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { activateAccount, primeCsrf, resetPassword } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { AuthCard } from './LoginPage'

export type PasswordTokenMode = 'activate' | 'reset'

const PASSWORD_POLICY_GUIDANCE = 'Use 12–256 characters with upper- and lower-case letters and a number.'

function tokenFromHash(hash: string): string {
  const fragment = hash.startsWith('#') ? hash.slice(1) : hash
  if (!fragment) return ''
  try {
    return (new URLSearchParams(fragment).get('token') || '').trim()
  } catch {
    return ''
  }
}

export default function PasswordTokenPage({ mode }: { mode: PasswordTokenMode }) {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const initialToken = useMemo(() => tokenFromHash(location.hash), [location.hash])
  const [token, setToken] = useState(initialToken)
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!initialToken || !location.hash) return
    // Keep the one-time token in component memory only. The fragment is
    // removed from the visible URL before the user can submit the form.
    navigate({ pathname: location.pathname, search: location.search, hash: '' }, { replace: true })
    if (typeof window !== 'undefined' && window.location.hash) {
      window.history.replaceState(window.history.state, document.title, `${location.pathname}${location.search}`)
    }
  }, [initialToken, location.hash, location.pathname, location.search, navigate])

  const isActivation = mode === 'activate'
  const title = isActivation ? 'Activate your BOSMAX account' : 'Set a new BOSMAX password'
  const description = isActivation
    ? 'Complete the one-time setup token before signing in. Your staff profile remains separate from account access.'
    : 'Complete the one-time reset token to replace the account password.'
  const submitLabel = isActivation ? 'Activate account' : 'Set new password'
  const successMessage = isActivation
    ? 'Account activated. Your authenticated staff session is ready.'
    : 'Password updated. Your authenticated staff session is ready.'

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (!token) {
        throw new Error('Enter the one-time token from your setup or reset link.')
      }
      await primeCsrf()
      if (isActivation) {
        await activateAccount(token, password, confirmation)
      } else {
        await resetPassword(token, password, confirmation)
      }
      setToken('')
      setPassword('')
      setConfirmation('')
      setSuccess(true)
      await auth.refresh()
      navigate('/home', { replace: true })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `${submitLabel} failed.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard eyebrow="BOSMAX STAFF ACCESS" title={title} description={description}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4" autoComplete="off">
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
          One-time token
          <input
            value={token}
            onChange={(event) => setToken(event.target.value)}
            type="password"
            autoComplete="off"
            required
            aria-describedby="token-help"
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100"
          />
        </label>
        <p id="token-help" className="text-xs text-slate-500">The token is kept in memory only and is never saved to browser storage.</p>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
          New password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="new-password"
            minLength={12}
            required
            aria-describedby="password-help"
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100"
          />
        </label>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
          Confirm password
          <input
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            type="password"
            autoComplete="new-password"
            minLength={12}
            required
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100"
          />
        </label>
        <p id="password-help" className="text-xs text-slate-500">{PASSWORD_POLICY_GUIDANCE}</p>
        {error ? <p role="alert" className="text-sm text-rose-300">{error}</p> : null}
        {success ? <p role="status" className="text-sm text-emerald-300">{successMessage}</p> : null}
        <button type="submit" disabled={busy} className="w-full rounded-xl bg-cyan-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-50">{busy ? `${submitLabel}…` : submitLabel}</button>
      </form>
      <div className="mt-5 flex flex-wrap justify-center gap-x-4 gap-y-2 text-xs font-semibold">
        <Link to="/login" className="text-cyan-300">Return to sign in</Link>
        {isActivation ? <Link to="/reset-password" className="text-slate-400 hover:text-slate-200">Have a reset token?</Link> : <Link to="/activate-account" className="text-slate-400 hover:text-slate-200">Have a setup token?</Link>}
      </div>
    </AuthCard>
  )
}
