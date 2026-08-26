import { getAPI, postAPI } from './client'

export interface AuthUser {
  user_id: string
  staff_id: string
  display_name: string
  email: string
  account_status: string
  staff_active: boolean
  role_codes: string[]
  permissions: string[]
  session?: {
    session_id: string
    created_at: string
    expires_at: string
    last_seen_at: string
  }
}

export interface CurrentSessionResponse {
  authenticated: boolean
  setup_required: boolean
  user: AuthUser | null
}

export interface AuthSessionResponse {
  authenticated: true
  user: AuthUser
  session: {
    session_id: string
    created_at: string
    expires_at: string
    last_seen_at: string
  }
}

export interface SetupStatusResponse {
  setup_required: boolean
  configured: boolean
}

export function fetchCurrentSession(): Promise<CurrentSessionResponse> {
  return getAPI<CurrentSessionResponse>('/api/auth/current-session')
}

export function fetchSetupStatus(): Promise<SetupStatusResponse> {
  return getAPI<SetupStatusResponse>('/api/auth/bootstrap-status')
}

export function primeCsrf(): Promise<{ ok: boolean }> {
  return getAPI<{ ok: boolean }>('/api/auth/csrf')
}

export function login(email: string, password: string): Promise<AuthSessionResponse> {
  return postAPI<AuthSessionResponse>('/api/auth/login', { email, password })
}

export function completePasswordTokenFlow(
  path: '/api/auth/activate-account' | '/api/auth/reset-password',
  token: string,
  password: string,
  password_confirmation: string,
): Promise<AuthSessionResponse> {
  return postAPI<AuthSessionResponse>(path, { token, password, password_confirmation })
}

export function activateAccount(
  token: string,
  password: string,
  password_confirmation: string,
): Promise<AuthSessionResponse> {
  return completePasswordTokenFlow('/api/auth/activate-account', token, password, password_confirmation)
}

export function resetPassword(
  token: string,
  password: string,
  password_confirmation: string,
): Promise<AuthSessionResponse> {
  return completePasswordTokenFlow('/api/auth/reset-password', token, password, password_confirmation)
}

export function setupOwner(
  display_name: string,
  email: string,
  password: string,
  password_confirmation: string,
): Promise<AuthSessionResponse> {
  return postAPI<AuthSessionResponse>('/api/auth/setup-owner', {
    display_name,
    email,
    password,
    password_confirmation,
  })
}

export function logout(): Promise<{ ok: boolean }> {
  return postAPI<{ ok: boolean }>('/api/auth/logout', {})
}
