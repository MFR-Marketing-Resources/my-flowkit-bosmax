import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  fetchCurrentSession,
  login as loginRequest,
  logout as logoutRequest,
  setupOwner as setupOwnerRequest,
  type AuthUser,
} from '../api/auth'

interface AuthContextValue {
  loading: boolean
  error: string
  user: AuthUser | null
  setupRequired: boolean
  refresh: () => Promise<void>
  login: (email: string, password: string) => Promise<AuthUser>
  setupOwner: (displayName: string, email: string, password: string, confirmation: string) => Promise<AuthUser>
  logout: () => Promise<void>
  hasPermission: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [setupRequired, setSetupRequired] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const current = await fetchCurrentSession()
      setUser(current.user)
      setSetupRequired(current.setup_required)
      setError('')
    } catch (cause) {
      setUser(null)
      setError(errorMessage(cause, 'Authentication status unavailable.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginRequest(email, password)
    setUser(result.user)
    setSetupRequired(false)
    setError('')
    return result.user
  }, [])

  const setupOwner = useCallback(async (displayName: string, email: string, password: string, confirmation: string) => {
    const result = await setupOwnerRequest(displayName, email, password, confirmation)
    setUser(result.user)
    setSetupRequired(false)
    setError('')
    return result.user
  }, [])

  const logout = useCallback(async () => {
    await logoutRequest()
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    loading,
    error,
    user,
    setupRequired,
    refresh,
    login,
    setupOwner,
    logout,
    hasPermission: (permission: string) => Boolean(user?.permissions.includes(permission)),
  }), [loading, error, user, setupRequired, refresh, login, setupOwner, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
