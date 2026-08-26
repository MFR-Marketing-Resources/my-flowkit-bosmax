import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import PasswordTokenPage from './PasswordTokenPage'
import { activateAccount, primeCsrf, resetPassword } from '../api/auth'
import { useAuth } from '../auth/AuthContext'

vi.mock('../api/auth', () => ({
  activateAccount: vi.fn(),
  primeCsrf: vi.fn(),
  resetPassword: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: vi.fn(),
}))

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>
}

function renderPage(mode: 'activate' | 'reset', entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <LocationProbe />
      <PasswordTokenPage mode={mode} />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({
    refresh: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(primeCsrf).mockResolvedValue({ ok: true })
  vi.mocked(activateAccount).mockResolvedValue({
    authenticated: true,
    user: {} as never,
    session: {} as never,
  })
  vi.mocked(resetPassword).mockResolvedValue({
    authenticated: true,
    user: {} as never,
    session: {} as never,
  })
})

describe('PasswordTokenPage', () => {
  it('renders activation form and consumes the token fragment from the URL', async () => {
    renderPage('activate', '/activate-account#token=setup-secret')

    expect(screen.getByRole('heading', { name: 'Activate your BOSMAX account' })).toBeInTheDocument()
    expect(screen.getByLabelText('New password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm password')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/activate-account'))
    expect(screen.getByLabelText('One-time token')).toHaveValue('setup-secret')
    expect(screen.getByTestId('location')).not.toHaveTextContent('setup-secret')
  })

  it('submits activation through the canonical endpoint and redirects after authentication', async () => {
    const auth = { refresh: vi.fn().mockResolvedValue(undefined) }
    vi.mocked(useAuth).mockReturnValue(auth as unknown as ReturnType<typeof useAuth>)
    renderPage('activate', '/activate-account#token=setup-secret')

    await waitFor(() => expect(screen.getByLabelText('One-time token')).toHaveValue('setup-secret'))
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'StrongPassword123' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'StrongPassword123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate account' }))

    await waitFor(() => expect(activateAccount).toHaveBeenCalledWith('setup-secret', 'StrongPassword123', 'StrongPassword123'))
    expect(primeCsrf).toHaveBeenCalledTimes(1)
    expect(auth.refresh).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/home'))
  })

  it('renders reset form and maps to the canonical reset endpoint', async () => {
    renderPage('reset', '/reset-password#token=reset-secret')

    expect(screen.getByRole('heading', { name: 'Set a new BOSMAX password' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('One-time token')).toHaveValue('reset-secret'))
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'AnotherPassword123' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'AnotherPassword123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Set new password' }))

    await waitFor(() => expect(resetPassword).toHaveBeenCalledWith('reset-secret', 'AnotherPassword123', 'AnotherPassword123'))
    expect(activateAccount).not.toHaveBeenCalled()
  })

  it('shows an understandable backend error without persisting token or password values', async () => {
    vi.mocked(activateAccount).mockRejectedValueOnce(new Error('API 400: TOKEN_INVALID_OR_EXPIRED'))
    renderPage('activate', '/activate-account#token=expired-secret')

    await waitFor(() => expect(screen.getByLabelText('One-time token')).toHaveValue('expired-secret'))
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'StrongPassword123' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'StrongPassword123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Activate account' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('TOKEN_INVALID_OR_EXPIRED')
    expect(window.localStorage.getItem('expired-secret')).toBeNull()
    expect(window.sessionStorage.getItem('expired-secret')).toBeNull()
    expect(screen.getByTestId('location')).not.toHaveTextContent('expired-secret')
  })
})
