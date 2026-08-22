import { useCallback, useEffect, useState } from 'react'
import { getAPI, postAPI } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type Tab = 'staff' | 'roles' | 'sessions' | 'audit'

interface StaffRow {
  user_id: string
  staff_id: string
  display_name: string
  email: string
  account_status: string
  staff_active: boolean
  last_login_at?: string | null
  created_at: string
  role_codes: string[]
}

interface RoleRow {
  role_code: string
  display_name: string
  description: string
  permission_codes: string[]
}

interface SessionRow {
  session_id: string
  user_id: string
  display_name: string
  email: string
  staff_id: string
  created_at: string
  expires_at: string
  last_seen_at: string
}

interface AuditRow {
  event_id: string
  event_type: string
  actor_user_id?: string | null
  target_user_id?: string | null
  success: boolean
  metadata: Record<string, unknown>
  created_at: string
}

interface StaffResponse { staff: StaffRow[] }
interface RolesResponse { roles: RoleRow[]; permissions: Array<{ permission_code: string; display_name: string; description: string }> }
interface SessionsResponse { sessions: SessionRow[] }
interface AuditResponse { events: AuditRow[] }

function displayDate(value?: string | null): string {
  if (!value) return 'Never'
  return new Date(value).toLocaleString()
}

export default function StaffAccessPage() {
  const auth = useAuth()
  const [tab, setTab] = useState<Tab>('staff')
  const [staff, setStaff] = useState<StaffRow[]>([])
  const [roles, setRoles] = useState<RoleRow[]>([])
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('VIEWER')
  const [oneTimeToken, setOneTimeToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!auth.hasPermission('staff.read')) return
    setError('')
    try {
      const [staffResponse, roleResponse, sessionResponse, auditResponse] = await Promise.all([
        getAPI<StaffResponse>('/api/system/staff-access/staff'),
        getAPI<RolesResponse>('/api/system/staff-access/roles'),
        getAPI<SessionsResponse>('/api/system/staff-access/sessions'),
        getAPI<AuditResponse>('/api/system/staff-access/audit?limit=200'),
      ])
      setStaff(staffResponse.staff)
      setRoles(roleResponse.roles)
      setSessions(sessionResponse.sessions)
      setAudit(auditResponse.events)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Staff access data unavailable.')
    }
  }, [auth])

  useEffect(() => { void load() }, [load])

  const invite = async () => {
    setBusy(true)
    setError('')
    setOneTimeToken('')
    try {
      const result = await postAPI<{ user: StaffRow; setup_token: string }>('/api/system/staff-access/staff', {
        display_name: displayName,
        email,
        role_codes: [inviteRole],
      })
      setOneTimeToken(result.setup_token)
      setDisplayName('')
      setEmail('')
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create staff invite.')
    } finally {
      setBusy(false)
    }
  }

  const accountAction = async (userId: string, action: 'suspend' | 'disable' | 'reactivate' | 'terminate' | 'reset') => {
    if (action === 'terminate' && !window.confirm('Terminate this account? Historical StaffProfile attribution will be preserved.')) return
    setBusy(true)
    setError('')
    try {
      if (action === 'reset') {
        const result = await postAPI<{ reset_token: string }>(`/api/system/staff-access/staff/${userId}/reset`, {})
        setOneTimeToken(result.reset_token)
      } else {
        await postAPI(`/api/system/staff-access/staff/${userId}/${action}`, { reason: `OWNER_${action.toUpperCase()}` })
      }
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Account action failed.')
    } finally {
      setBusy(false)
    }
  }

  const assignRole = async (userId: string, roleCode: string) => {
    setBusy(true)
    setError('')
    try {
      await postAPI(`/api/system/staff-access/staff/${userId}/roles`, { role_codes: [roleCode] })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Role change failed.')
    } finally {
      setBusy(false)
    }
  }

  const revokeSession = async (sessionId: string) => {
    setBusy(true)
    try {
      await postAPI(`/api/system/staff-access/sessions/${sessionId}/revoke`, { reason: 'OWNER_REVOKED' })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Session revoke failed.')
    } finally {
      setBusy(false)
    }
  }

  if (!auth.hasPermission('staff.read')) {
    return <div className="min-h-full bg-slate-950 p-8 text-sm text-rose-300">You do not have permission to view staff access.</div>
  }

  return (
    <div className="min-h-full bg-slate-950 px-4 py-5 text-slate-100 md:px-8">
      <header className="mb-5 rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-5">
        <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-300">System · Access authority</p>
        <h1 className="mt-2 text-2xl font-bold">Staff &amp; Access</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-400">Account authority is separate from canonical StaffProfile attribution. Termination revokes access and preserves historical production lineage.</p>
      </header>

      <div className="mb-5 flex flex-wrap gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-2">
        {(['staff', 'roles', 'sessions', 'audit'] as Tab[]).map((item) => (
          <button key={item} type="button" onClick={() => setTab(item)} className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-wider ${tab === item ? 'bg-cyan-500/15 text-cyan-200' : 'text-slate-500 hover:text-slate-200'}`}>{item === 'staff' ? 'Staff Directory' : item === 'roles' ? 'Roles & Permissions' : item === 'sessions' ? 'Sessions' : 'Access Audit'}</button>
        ))}
      </div>

      {error ? <p role="alert" className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p> : null}
      {oneTimeToken ? <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-100"><p className="font-bold">One-time setup/reset token — copy it now</p><p className="mt-2 break-all font-mono text-xs">{oneTimeToken}</p><p className="mt-2 text-xs text-amber-200/70">It is shown once, expires, and is stored server-side only as a hash. It is not written to the access audit.</p></div> : null}

      {tab === 'staff' ? (
        <div className="space-y-5">
          {auth.hasPermission('staff.manage') ? <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5"><h2 className="text-sm font-bold">Invite staff account</h2><div className="mt-3 grid gap-3 md:grid-cols-4"><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Display name" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" /><input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" type="email" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm" /><select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm">{roles.map((role) => <option key={role.role_code} value={role.role_code}>{role.role_code}</option>)}</select><button type="button" disabled={busy || !displayName.trim() || !email.trim()} onClick={() => void invite()} className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold disabled:opacity-50">Create invite</button></div></section> : null}
          <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/40"><table className="w-full min-w-[920px] text-left text-xs"><thead className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500"><tr><th className="p-4">Staff</th><th className="p-4">Email</th><th className="p-4">Role</th><th className="p-4">Account / staff</th><th className="p-4">Last login</th><th className="p-4">Actions</th></tr></thead><tbody>{staff.map((item) => <tr key={item.user_id} className="border-b border-slate-800/70"><td className="p-4"><p className="font-semibold text-slate-100">{item.display_name}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{item.staff_id}</p></td><td className="p-4 text-slate-300">{item.email}</td><td className="p-4"><select value={item.role_codes[0] ?? 'VIEWER'} disabled={!auth.hasPermission('roles.manage') || busy} onChange={(event) => void assignRole(item.user_id, event.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">{roles.map((role) => <option key={role.role_code} value={role.role_code}>{role.role_code}</option>)}</select></td><td className="p-4"><span className={item.account_status === 'ACTIVE' ? 'text-emerald-300' : 'text-amber-300'}>{item.account_status}</span><span className="mx-1 text-slate-600">·</span><span className={item.staff_active ? 'text-emerald-300' : 'text-rose-300'}>{item.staff_active ? 'STAFF ACTIVE' : 'STAFF INACTIVE'}</span></td><td className="p-4 text-slate-400">{displayDate(item.last_login_at)}</td><td className="p-4"><div className="flex flex-wrap gap-2">{auth.hasPermission('staff.manage') ? <>{item.account_status === 'ACTIVE' ? <><button type="button" onClick={() => void accountAction(item.user_id, 'suspend')} disabled={busy} className="rounded border border-amber-500/40 px-2 py-1 text-[10px] text-amber-200 disabled:opacity-50">Suspend</button><button type="button" onClick={() => void accountAction(item.user_id, 'disable')} disabled={busy} className="rounded border border-orange-500/40 px-2 py-1 text-[10px] text-orange-200 disabled:opacity-50">Disable</button></> : item.account_status !== 'TERMINATED' ? <button type="button" onClick={() => void accountAction(item.user_id, 'reactivate')} disabled={busy} className="rounded border border-emerald-500/40 px-2 py-1 text-[10px] text-emerald-200 disabled:opacity-50">Reactivate</button> : null}<button type="button" onClick={() => void accountAction(item.user_id, 'reset')} disabled={busy || item.account_status === 'TERMINATED'} className="rounded border border-cyan-500/40 px-2 py-1 text-[10px] text-cyan-200 disabled:opacity-50">Reset</button><button type="button" onClick={() => void accountAction(item.user_id, 'terminate')} disabled={busy || item.account_status === 'TERMINATED'} className="rounded border border-rose-500/40 px-2 py-1 text-[10px] text-rose-200 disabled:opacity-50">Terminate</button></> : null}</div></td></tr>)}</tbody></table></section>
        </div>
      ) : null}

      {tab === 'roles' ? <section className="grid gap-4 md:grid-cols-2">{roles.map((role) => <article key={role.role_code} className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5"><div className="flex items-center justify-between"><h2 className="font-bold">{role.role_code}</h2><span className="text-[10px] uppercase tracking-wider text-slate-500">Built-in</span></div><p className="mt-2 text-xs text-slate-400">{role.description}</p><div className="mt-4 flex flex-wrap gap-2">{role.permission_codes.map((permission) => <span key={permission} className="rounded border border-cyan-500/20 bg-cyan-500/5 px-2 py-1 font-mono text-[10px] text-cyan-200">{permission}</span>)}</div></article>)}</section> : null}

      {tab === 'sessions' ? <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/40"><table className="w-full min-w-[780px] text-left text-xs"><thead className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500"><tr><th className="p-4">Staff</th><th className="p-4">Session</th><th className="p-4">Last seen</th><th className="p-4">Expires</th><th className="p-4" /></tr></thead><tbody>{sessions.map((item) => <tr key={item.session_id} className="border-b border-slate-800/70"><td className="p-4"><p>{item.display_name}</p><p className="text-slate-500">{item.email}</p></td><td className="p-4 font-mono text-[10px] text-slate-500">{item.session_id}</td><td className="p-4 text-slate-400">{displayDate(item.last_seen_at)}</td><td className="p-4 text-slate-400">{displayDate(item.expires_at)}</td><td className="p-4 text-right">{auth.hasPermission('sessions.revoke') ? <button type="button" disabled={busy} onClick={() => void revokeSession(item.session_id)} className="rounded border border-rose-500/40 px-2 py-1 text-[10px] text-rose-200 disabled:opacity-50">Revoke</button> : null}</td></tr>)}</tbody></table></section> : null}

      {tab === 'audit' ? <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/40"><table className="w-full min-w-[820px] text-left text-xs"><thead className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500"><tr><th className="p-4">Time</th><th className="p-4">Event</th><th className="p-4">Actor</th><th className="p-4">Target</th><th className="p-4">Result</th></tr></thead><tbody>{audit.map((item) => <tr key={item.event_id} className="border-b border-slate-800/70"><td className="p-4 text-slate-400">{displayDate(item.created_at)}</td><td className="p-4 font-semibold text-slate-200">{item.event_type}</td><td className="p-4 font-mono text-[10px] text-slate-500">{item.actor_user_id ?? '—'}</td><td className="p-4 font-mono text-[10px] text-slate-500">{item.target_user_id ?? '—'}</td><td className={item.success ? 'p-4 text-emerald-300' : 'p-4 text-rose-300'}>{item.success ? 'SUCCESS' : 'DENIED'}</td></tr>)}</tbody></table></section> : null}
    </div>
  )
}
