import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import OnDemandCopyRendererPanel from './OnDemandCopyRendererPanel'
import type { CandidateStatus, CopyRenderCandidate, CopyRenderSession } from '../../api/copyRender'

vi.mock('../../api/copyRender', () => ({
  createSession: vi.fn(),
  generateSuggestions: vi.fn(),
  lockCandidate: vi.fn(),
  unlockCandidate: vi.fn(),
  finalizeSession: vi.fn(),
  prepareSelected: vi.fn(),
  newRequestId: () => 'req-test-00000001',
}))

import * as api from '../../api/copyRender'

function sess(over: Partial<CopyRenderSession> = {}): CopyRenderSession {
  return {
    session_id: 'CRS_1', product_id: 'p', benefit_id: 'b', lane: 'HYBRID',
    duration_seconds: 16, target_language: 'BM_MS', formula_id: 'PAS', word_budget: 44,
    target_count: 2, locked_count: 0, status: 'OPEN', regenerate_enabled: true,
    total_unique_capacity: 162, used_recipe_count: 0, remaining_unique_capacity: 162,
    candidates: [], batches: [], finalized_at: null, ...over,
  }
}

function cand(id: string, status: CandidateStatus, text: string): CopyRenderCandidate {
  return {
    candidate_id: id, status, recipe_fingerprint: `${id}fp`, text_digest: `${id}td`,
    batch_id: 'B1', artifact_id: `${id}art`, full_copy_text: text, word_count: 5, stages: [],
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('OnDemandCopyRendererPanel', () => {
  it('generates and renders the five suggestion scripts', async () => {
    ;(api.createSession as Mock).mockResolvedValue(sess())
    ;(api.generateSuggestions as Mock).mockResolvedValue(
      sess({ candidates: [cand('c1', 'SHOWN', 'Script one'), cand('c2', 'SHOWN', 'Script two')] }))

    render(<OnDemandCopyRendererPanel productId="p" benefitId="b" durationSeconds={16} lane="HYBRID" defaultTarget={2} />)
    fireEvent.click(screen.getByTestId('cr-generate'))

    await waitFor(() => expect(screen.getAllByTestId('cr-candidate')).toHaveLength(2))
    expect(screen.getByText('Script one')).toBeInTheDocument()
    expect(screen.getByText('Script two')).toBeInTheDocument()
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(api.generateSuggestions).toHaveBeenCalledWith('CRS_1', 'req-test-00000001')
  })

  it('locks to target, finalizes, prepares packages and reports the selection', async () => {
    const onSel = vi.fn()
    ;(api.createSession as Mock).mockResolvedValue(sess({ target_count: 1 }))
    ;(api.generateSuggestions as Mock).mockResolvedValue(
      sess({ target_count: 1, candidates: [cand('c1', 'SHOWN', 'Only script')] }))
    ;(api.lockCandidate as Mock).mockResolvedValue(
      sess({ target_count: 1, locked_count: 1, status: 'TARGET_COMPLETE', regenerate_enabled: false,
             candidates: [cand('c1', 'LOCKED', 'Only script')] }))
    ;(api.finalizeSession as Mock).mockResolvedValue(
      sess({ target_count: 1, locked_count: 1, status: 'FINALIZED', finalized_at: 't',
             candidates: [cand('c1', 'FINALIZED', 'Only script')] }))
    ;(api.prepareSelected as Mock).mockResolvedValue(
      { session_id: 'CRS_1', lane: 'HYBRID', package_count: 1, enqueued: false,
        packages: [{ candidate_id: 'c1', package_id: 'wep_1', status: 'READY', reused: false }] })

    render(
      <OnDemandCopyRendererPanel productId="p" benefitId="b" durationSeconds={16} lane="HYBRID"
        defaultTarget={1} onCopySelected={onSel} />)

    fireEvent.click(screen.getByTestId('cr-generate'))
    await waitFor(() => expect(screen.getByTestId('cr-candidate')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(screen.getByTestId('cr-progress')).toHaveTextContent('Selected 1/1'))

    fireEvent.click(screen.getByTestId('cr-proceed'))
    await waitFor(() => expect(screen.getByTestId('cr-finalized')).toBeInTheDocument())

    expect(api.finalizeSession).toHaveBeenCalledWith('CRS_1')
    expect(api.prepareSelected).toHaveBeenCalledWith('CRS_1')
    expect(onSel).toHaveBeenCalledTimes(1)
    expect(onSel.mock.calls[0][0].prepared.package_count).toBe(1)
    expect(onSel.mock.calls[0][0].prepared.enqueued).toBe(false)
  })

  it('disables Regenerate when the server disables it (target reached)', async () => {
    ;(api.createSession as Mock).mockResolvedValue(sess({ target_count: 1 }))
    ;(api.generateSuggestions as Mock).mockResolvedValue(
      sess({ target_count: 1, locked_count: 1, status: 'TARGET_COMPLETE', regenerate_enabled: false,
             candidates: [cand('c1', 'LOCKED', 'Only script')] }))

    render(<OnDemandCopyRendererPanel productId="p" benefitId="b" durationSeconds={16} lane="HYBRID" defaultTarget={1} />)
    fireEvent.click(screen.getByTestId('cr-generate'))
    await waitFor(() => expect(screen.getByTestId('cr-regenerate')).toBeDisabled())
  })
})
