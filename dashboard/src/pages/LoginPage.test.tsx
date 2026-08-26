import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import LoginPage from './LoginPage'
import { primeCsrf } from '../api/auth'
import { useAuth } from '../auth/AuthContext'

vi.mock('../api/auth', () => ({
  primeCsrf: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: vi.fn(),
}))

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
beforeEach(() => {
  vi.mocked(primeCsrf).mockResolvedValue({ ok: true })
  vi.mocked(useAuth).mockReturnValue({
    loading: false,
    error: '',
    user: null,
    setupRequired: false,
    refresh: vi.fn(),
    login: vi.fn().mockResolvedValue({}),
    setupOwner: vi.fn(),
    logout: vi.fn(),
    hasPermission: vi.fn().mockReturnValue(false),
  } as unknown as ReturnType<typeof useAuth>)
})

describe('LoginPage', () => {
  it('keeps the normal login flow and exposes activation/reset entry points', async () => {
    render(<MemoryRouter initialEntries={['/login']}><LocationProbe /><LoginPage /></MemoryRouter>)

    expect(screen.getByRole('link', { name: 'Have a setup token? Activate account' })).toHaveAttribute('href', '/activate-account')
    expect(screen.getByRole('link', { name: 'Have a reset token? Set new password' })).toHaveAttribute('href', '/reset-password')
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'operator@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'StrongPassword123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(vi.mocked(useAuth)().login).toHaveBeenCalledWith('operator@example.test', 'StrongPassword123'))
    expect(primeCsrf).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/home'))
  })
})
