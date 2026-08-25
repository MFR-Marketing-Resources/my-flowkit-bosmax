import '@testing-library/jest-dom/vitest'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/creativeFactory', () => ({
  listBenefits: vi.fn(),
  createBenefit: vi.fn(),
  updateBenefit: vi.fn(),
  deleteBenefit: vi.fn(),
  recheckBenefit: vi.fn(),
  getReviewContext: vi.fn(),
  resolveReview: vi.fn(),
  buildBenefit: vi.fn(),
}))

import * as api from '../../api/creativeFactory'
import type { Benefit, BenefitStatus, ReviewContext } from '../../api/creativeFactory'
import { BenefitRegistryPanel } from './BenefitRegistryPanel'

function makeBenefit(over: Partial<Benefit> & { benefit_id: string; status: BenefitStatus }): Benefit {
  return {
    product_id: 'p1',
    canonical_text: 'Benefit text',
    benefit: 'Benefit text',
    usage_hint: null,
    pi_snapshot_id: 's1',
    pi_snapshot_version: 1,
    pi_check: { reason: 'ok', similarity: { score: 0.9, matched_text: 'x', method: 'jaccard' } },
    provenance: {},
    created_at: '',
    updated_at: '',
    ...over,
  }
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('BenefitRegistryPanel', () => {
  it('renders benefit rows with their PI status', async () => {
    vi.mocked(api.listBenefits).mockResolvedValue({
      product_id: 'p1',
      count: 2,
      benefits: [
        makeBenefit({ benefit_id: 'BEN_a', canonical_text: 'Melegakan kembung', status: 'VERIFIED' }),
        makeBenefit({ benefit_id: 'BEN_b', canonical_text: 'Ambiguous benefit', status: 'REVIEW_REQUIRED' }),
      ],
    })
    render(<BenefitRegistryPanel productId="p1" />)
    expect(await screen.findByText('Melegakan kembung')).toBeInTheDocument()
    expect(screen.getByText('VERIFIED')).toBeInTheDocument()
    expect(screen.getByText('REVIEW_REQUIRED')).toBeInTheDocument()
  })

  it('creates a benefit with the required text and optional usage hint', async () => {
    vi.mocked(api.listBenefits).mockResolvedValue({ product_id: 'p1', count: 0, benefits: [] })
    vi.mocked(api.createBenefit).mockResolvedValue(
      makeBenefit({ benefit_id: 'BEN_new', status: 'VERIFIED' }),
    )
    const onMutate = vi.fn()
    render(<BenefitRegistryPanel productId="p1" onMutate={onMutate} />)
    await screen.findByTestId('benefit-rows')

    fireEvent.change(screen.getByTestId('new-benefit-input'), { target: { value: 'Membantu kembung' } })
    fireEvent.change(screen.getByTestId('new-usage-input'), { target: { value: 'Sapu pada perut' } })
    fireEvent.click(screen.getByTestId('add-benefit-button'))

    await waitFor(() =>
      expect(api.createBenefit).toHaveBeenCalledWith('p1', 'Membantu kembung', 'Sapu pada perut'),
    )
    await waitFor(() => expect(onMutate).toHaveBeenCalled())
  })

  it('opens the audited review modal and verifies a REVIEW_REQUIRED benefit', async () => {
    vi.mocked(api.listBenefits).mockResolvedValue({
      product_id: 'p1',
      count: 1,
      benefits: [makeBenefit({ benefit_id: 'BEN_r', canonical_text: 'Ambiguous', status: 'REVIEW_REQUIRED' })],
    })
    const ctx: ReviewContext = {
      benefit: makeBenefit({ benefit_id: 'BEN_r', canonical_text: 'Ambiguous', status: 'REVIEW_REQUIRED' }),
      usage_hint: null,
      current_check: { reason: 'Insufficient similarity', similarity: { score: 0.2, matched_text: null, method: null } },
      approved_snapshot: { snapshot_id: 's1', version: 1, benefits: ['a', 'b'] },
      reviews: [],
      resolvable: true,
    }
    vi.mocked(api.getReviewContext).mockResolvedValue(ctx)
    vi.mocked(api.resolveReview).mockResolvedValue(makeBenefit({ benefit_id: 'BEN_r', status: 'VERIFIED' }))

    render(<BenefitRegistryPanel productId="p1" />)
    fireEvent.click(await screen.findByText('Review'))

    const modal = await screen.findByTestId('review-modal')
    expect(modal).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('review-note'), { target: { value: 'Valid paraphrase' } })
    fireEvent.click(screen.getByText('Verify Benefit'))

    await waitFor(() =>
      expect(api.resolveReview).toHaveBeenCalledWith('BEN_r', 'VERIFY', 'Valid paraphrase'),
    )
  })
})
