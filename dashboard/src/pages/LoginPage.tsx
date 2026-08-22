import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { primeCsrf } from '../api/auth'
import { useAuth } from '../auth/AuthContext'

export default function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await primeCsrf()
      await auth.login(email, password)
      const destination = new URLSearchParams(location.search).get('next') || '/home'
      navigate(destination, { replace: true })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Sign in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard eyebrow="BOSMAX STAFF ACCESS" title="Sign in to BOSMAX" description="Use your staff account. Production attribution comes from this authenticated session.">
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="username" required className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100" />
        </label>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
          Password
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-sm text-slate-100" />
        </label>
        {error ? <p role="alert" className="text-sm text-rose-300">{error}</p> : null}
        <button type="submit" disabled={busy} className="w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-bold text-white disabled:opacity-50">{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      {auth.setupRequired ? <Link to="/setup-owner" className="mt-5 block text-center text-xs font-semibold text-cyan-300">No owner yet? Start first-owner setup</Link> : null}
    </AuthCard>
  )
}

export function AuthCard({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-8 text-slate-100">
      <main className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900/80 p-7 shadow-2xl shadow-slate-950/50">
        <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-cyan-300">{eyebrow}</p>
        <h1 className="mt-3 text-2xl font-bold">{title}</h1>
        <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
        <div className="mt-6">{children}</div>
      </main>
    </div>
  )
}
