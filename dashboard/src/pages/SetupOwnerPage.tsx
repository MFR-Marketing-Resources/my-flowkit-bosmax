import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { primeCsrf } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { AuthCard } from './LoginPage'

export default function SetupOwnerPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await primeCsrf()
      await auth.setupOwner(displayName, email, password, confirmation)
      navigate('/home', { replace: true })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Owner setup failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard eyebrow="BOSMAX FIRST-OWNER BOOTSTRAP" title="Create the first owner" description="This one-time form creates a StaffProfile, UserAccount, OWNER role assignment, session, and audit event atomically. BOSMAX never receives credentials through chat or terminal.">
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">Display name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100" /></label>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">Owner email<input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="username" required className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100" /></label>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="new-password" minLength={12} required className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100" /></label>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">Confirm password<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} type="password" autoComplete="new-password" minLength={12} required className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100" /></label>
        <p className="text-xs text-slate-500">Use at least 12 characters with upper- and lower-case letters and a number.</p>
        {error ? <p role="alert" className="text-sm text-rose-300">{error}</p> : null}
        <button type="submit" disabled={busy} className="w-full rounded-xl bg-cyan-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-50">{busy ? 'Creating owner…' : 'Create first owner'}</button>
      </form>
    </AuthCard>
  )
}
