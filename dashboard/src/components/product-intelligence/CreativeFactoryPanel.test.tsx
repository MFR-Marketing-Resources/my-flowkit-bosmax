import '@testing-library/jest-dom/vitest'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/creativeFactory', () => ({
  getProductCapacity: vi.fn(),
  getBuildPlan: vi.fn(),
  buildVerified: vi.fn(),
}))

import * as api from '../../api/creativeFactory'
import type { BuildPlan, ProductCapacity } from '../../api/creativeFactory'
import { CreativeFactoryPanel } from './CreativeFactoryPanel'

const CAPACITY: ProductCapacity = {
  product_id: 'p1',
  benefit_counts: { VERIFIED: 2 },
  verified_benefits: 2,
  ready_benefits: 2,
  creative_factory_ready: true,
  totals: { angles: 6, hooks: 36, bodies: 18, ctas: 18, combinations: 324 },
  default_benefit_capacity: 162,
  per_benefit: [
    { benefit_id: 'BEN_a', benefit: 'A', status: 'VERIFIED', angles: 3, hooks: 18, bodies: 9, ctas: 9, combinations: 162, stale_atoms: 0, complete: true, ready: true },
  ],
}

const PLAN: BuildPlan = {
  product_id: 'p1',
  verified_benefit_count: 2,
  expected_provider_calls: 2,
  benefits: [
    { benefit_id: 'BEN_a', benefit: 'A' },
    { benefit_id: 'BEN_b', benefit: 'B' },
  ],
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('CreativeFactoryPanel', () => {
  it('renders deterministic capacity totals and the ready badge', async () => {
    vi.mocked(api.getProductCapacity).mockResolvedValue(CAPACITY)
    vi.mocked(api.getBuildPlan).mockResolvedValue(PLAN)
    render(<CreativeFactoryPanel productId="p1" />)

    const tiles = await screen.findByTestId('capacity-tiles')
    expect(within(tiles).getByText('324')).toBeInTheDocument()
    expect(screen.getByText('FACTORY READY')).toBeInTheDocument()
    expect(screen.getByTestId('expected-calls')).toHaveTextContent('2')
  })

  it('gates the batch build behind explicit confirmation', async () => {
    vi.mocked(api.getProductCapacity).mockResolvedValue(CAPACITY)
    vi.mocked(api.getBuildPlan).mockResolvedValue(PLAN)
    vi.mocked(api.buildVerified).mockResolvedValue({
      product_id: 'p1',
      confirmed: true,
      verified_benefit_count: 2,
      provider_calls: 2,
      results: [
        { benefit_id: 'BEN_a', status: 'COMPLETED' },
        { benefit_id: 'BEN_b', status: 'COMPLETED' },
      ],
    })
    render(<CreativeFactoryPanel productId="p1" />)

    const button = (await screen.findByTestId('batch-build-button')) as HTMLButtonElement
    expect(button.disabled).toBe(true) // disabled until confirmed

    fireEvent.click(screen.getByTestId('batch-confirm'))
    expect(button.disabled).toBe(false)

    fireEvent.click(button)
    await waitFor(() => expect(api.buildVerified).toHaveBeenCalledWith('p1', true))
  })
})
