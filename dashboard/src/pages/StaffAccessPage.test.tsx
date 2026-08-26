import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import StaffAccessPage from './StaffAccessPage'
import { getAPI, postAPI } from '../api/client'
import { useAuth } from '../auth/AuthContext'

vi.mock('../api/client', () => ({
  getAPI: vi.fn(),
  postAPI: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: vi.fn(),
}))

const invitedStaff = {
  user_id: 'user-hermes',
  staff_id: 'staff-hermes',
  display_name: 'Hermes Flow Operator',
  email: 'hermes-flow@bosmax.local',
  account_status: 'INVITED',
  staff_active: true,
  last_login_at: null,
  created_at: '2026-08-27T00:00:00Z',
  role_codes: ['OPERATOR'],
}

const auth = {
  hasPermission: (permission: string) => ['staff.read', 'staff.manage', 'roles.manage'].includes(permission),
}

function mockReads() {
  vi.mocked(getAPI).mockImplementation(async (path: string) => {
    if (path.endsWith('/staff')) return { staff: [invitedStaff] }
    if (path.endsWith('/roles')) return { roles: [{ role_code: 'OPERATOR', display_name: 'Operator', description: 'Production operator', permission_codes: ['production.read', 'production.execute'] }], permissions: [] }
    if (path.endsWith('/sessions')) return { sessions: [] }
    if (path.includes('/audit')) return { events: [] }
    throw new Error(`Unexpected read ${path}`)
  })
}

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue(auth as ReturnType<typeof useAuth>)
  mockReads()
  vi.mocked(postAPI).mockResolvedValue({})
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('StaffAccessPage account lifecycle UX', () => {
  it('distinguishes INVITED account authority from active staff profile and produces an activation link', async () => {
    vi.mocked(postAPI).mockResolvedValueOnce({ user: invitedStaff, setup_token: 'setup-secret' })
    render(<MemoryRouter><StaffAccessPage /></MemoryRouter>)

    expect(await screen.findByText('Activation required before sign-in')).toBeInTheDocument()
    expect(screen.getByText('ACCOUNT:')).toBeInTheDocument()
    expect(screen.getByText('STAFF PROFILE:')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Display name'), { target: { value: 'Hermes Flow Operator' } })
    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'hermes-flow@bosmax.local' } })
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'OPERATOR' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create invite' }))

    expect(await screen.findByText('Staff account created')).toBeInTheDocument()
    expect(screen.getByText('setup-secret')).toBeInTheDocument()
    expect(screen.getByLabelText('Activation link')).toHaveValue(`${window.location.origin}/activate-account#token=setup-secret`)
    expect(screen.getByText('Activation required before sign-in')).toBeInTheDocument()
    expect(postAPI).toHaveBeenCalledWith('/api/system/staff-access/staff', {
      display_name: 'Hermes Flow Operator',
      email: 'hermes-flow@bosmax.local',
      role_codes: ['OPERATOR'],
    })

    fireEvent.click(screen.getByRole('button', { name: 'Copy Activation Link' }))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${window.location.origin}/activate-account#token=setup-secret`))
  })

  it('uses the reset link for a reset token without changing the account/staff authority labels', async () => {
    vi.mocked(postAPI).mockResolvedValueOnce({ reset_token: 'reset-secret' })
    render(<MemoryRouter><StaffAccessPage /></MemoryRouter>)

    await screen.findByText('Activation required before sign-in')
    fireEvent.click(screen.getAllByRole('button', { name: 'Reset' })[0])

    expect(await screen.findByText('Password reset issued')).toBeInTheDocument()
    expect(screen.getByLabelText('Reset link')).toHaveValue(`${window.location.origin}/reset-password#token=reset-secret`)
    expect(screen.getByText('ACCOUNT: INVITED · STAFF PROFILE: ACTIVE')).toBeInTheDocument()
    expect(postAPI).toHaveBeenCalledWith('/api/system/staff-access/staff/user-hermes/reset', {})
  })
})
