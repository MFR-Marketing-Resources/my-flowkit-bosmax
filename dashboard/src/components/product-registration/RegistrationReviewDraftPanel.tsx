import { useState, useEffect } from 'react'
import type { RegistrationReviewDraft, RegistrationCommitResponse } from '../../types'
import { patchAPI, postAPI } from '../../api/client'

interface Props {
  draft: RegistrationReviewDraft
  onUpdate: (updated: RegistrationReviewDraft) => void
  onClear: () => void
}

export default function RegistrationReviewDraftPanel({ draft, onUpdate, onClear }: Props) {
  const [approvals, setApprovals] = useState<Record<string, boolean>>(draft.approval_checklist)
  const [isCommitting, setIsCommitting] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirmPhrase, setConfirmPhrase] = useState('')
  const [commitResult, setCommitResult] = useState<RegistrationCommitResponse | null>(null)
  const [isUpdating, setIsUpdating] = useState(false)

  // Sync state if draft changes
  useEffect(() => {
    setApprovals(draft.approval_checklist)
  }, [draft.approval_checklist])

  const toggleApproval = async (field: string) => {
    if (isUpdating || draft.review_status === 'COMMITTED') return
    
    const newStatus = !approvals[field]
    setIsUpdating(true)
    
    try {
      const updated = await patchAPI<RegistrationReviewDraft>(
        `/api/product-registration/review-drafts/${draft.review_draft_id}/field-decisions`,
        {
          approved_fields: newStatus ? [field] : [],
          rejected_fields: !newStatus ? [field] : [],
          edited_declared_evidence: {},
          requested_more_evidence_fields: []
        }
      )
      onUpdate(updated)
      setApprovals(updated.approval_checklist)
    } catch (err) {
      console.error('Failed to update field decision:', err)
    } finally {
      setIsUpdating(false)
    }
  }

  const handleCommit = async () => {
    if (confirmPhrase !== 'REGISTER_OWNED_PRODUCT') return
    
    setIsCommitting(true)
    try {
      const result = await postAPI<RegistrationCommitResponse>(
        `/api/product-registration/review-drafts/${draft.review_draft_id}/commit`,
        {
          draft_id: draft.review_draft_id,
          write_back_confirmed: true,
          user_confirmation_phrase: confirmPhrase,
          commit_reason: 'Manual registration approval'
        }
      )
      setCommitResult(result)
      if (result.commit_status === 'COMMITTED') {
        // Fetch updated draft to show committed status
        const updated = await patchAPI<RegistrationReviewDraft>(
          `/api/product-registration/review-drafts/${draft.review_draft_id}/field-decisions`,
          { approved_fields: [], rejected_fields: [], edited_declared_evidence: {}, requested_more_evidence_fields: [] }
        )
        onUpdate(updated)
        setShowConfirm(false)
      }
    } catch (err) {
      console.error('Commit failed:', err)
      setCommitResult({
        commit_status: 'FAILED',
        write_back_performed: false,
        errors: ['Network or server error']
      })
    } finally {
      setIsCommitting(false)
    }
  }

  const exportJSON = () => {
    const data = { ...draft, approval_checklist: approvals }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${draft.review_draft_id}.json`
    a.click()
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMMITTED': return 'text-blue-400 bg-blue-400/10'
      case 'REVIEW_READY': return 'text-emerald-400 bg-emerald-400/10'
      case 'NEEDS_HUMAN_REVIEW': return 'text-amber-400 bg-amber-400/10'
      case 'BLOCKED': return 'text-red-400 bg-red-400/10'
      default: return 'text-slate-400 bg-slate-400/10'
    }
  }

  const isReadyToCommit = 
    draft.review_status !== 'BLOCKED' && 
    draft.review_status !== 'COMMITTED' &&
    draft.claim_gate !== 'CLAIM_BLOCKED' &&
    approvals['normalized_name'] === true &&
    draft.human_review_fields.every(f => approvals[f] === true)

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Header & Status */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-xl border border-indigo-500/20">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
            </svg>
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Review Draft ID</div>
            <h3 className="text-lg font-bold text-white">{draft.review_draft_id}</h3>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Status</div>
            <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${getStatusColor(draft.review_status)}`}>
              {draft.review_status}
            </span>
          </div>
          <div className="h-10 w-px bg-slate-800 hidden md:block" />
          <button 
            onClick={onClear}
            className="px-4 py-2 text-xs font-bold text-slate-400 hover:text-white transition-colors"
          >
            Clear Draft
          </button>
        </div>
      </div>

      {/* Governance Banner */}
      <div className={`p-4 rounded-xl border flex items-center gap-3 ${
        draft.review_status === 'COMMITTED' ? 'bg-blue-500/10 border-blue-500/30' : 'bg-blue-500/5 border-blue-500/20'
      }`}>
        <svg className={`w-5 h-5 shrink-0 ${draft.review_status === 'COMMITTED' ? 'text-blue-400' : 'text-blue-400'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-xs text-blue-300 font-medium">
          Governance: <span className="font-bold">{draft.write_back_status}</span>. 
          {draft.review_status === 'COMMITTED' 
            ? ' This product has been committed to the canonical database.' 
            : ' Gated write-back requires approval of all review fields and a confirmation phrase.'}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left Column: Evidence & Candidates */}
        <div className="space-y-8">
          {/* Declared Evidence */}
          <section className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800">
            <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-4 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
              Declared Evidence
            </h4>
            <div className="space-y-3">
              {Object.entries(draft.declared_evidence_fields).map(([key, value]) => (
                <div key={key} className="flex justify-between items-start gap-4 p-3 rounded-lg bg-slate-800/30 border border-slate-700/50">
                  <span className="text-[10px] font-bold text-slate-500 uppercase shrink-0 mt-1">{key.replace(/_/g, ' ')}</span>
                  <span className="text-xs text-slate-300 text-right line-clamp-3">{String(value)}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Canonical Candidates */}
          <section className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800">
            <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-4 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              Canonical Candidates
            </h4>
            <div className="space-y-3">
              {Object.entries(draft.canonical_candidate_fields).map(([key, value]) => {
                if (value === null || value === undefined || value === '') return null
                const isApproved = approvals[key]
                const isRejected = draft.rejection_checklist[key]
                return (
                  <div key={key} className={`flex items-center justify-between p-3 rounded-lg border transition-all ${
                    isApproved ? 'bg-emerald-500/5 border-emerald-500/30' : 
                    isRejected ? 'bg-red-500/5 border-red-500/30 opacity-60' : 'bg-slate-800/30 border-slate-700/50'
                  }`}>
                    <div className="flex flex-col gap-1 overflow-hidden">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-slate-500 uppercase">{key.replace(/_/g, ' ')}</span>
                        {draft.human_review_fields.includes(key) && !isApproved && (
                          <span className="text-[8px] font-bold text-amber-500 bg-amber-500/10 px-1 rounded">REVIEW REQ</span>
                        )}
                      </div>
                      <span className="text-sm text-white font-medium truncate">
                        {Array.isArray(value) ? value.join(', ') : String(value)}
                      </span>
                    </div>
                    {draft.review_status !== 'COMMITTED' && (
                      <button
                        onClick={() => toggleApproval(key)}
                        disabled={isUpdating}
                        className={`ml-4 p-2 rounded-lg transition-all ${
                          isApproved ? 'bg-emerald-500 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                        } ${isUpdating ? 'opacity-50 cursor-wait' : ''}`}
                      >
                        {isApproved ? (
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                        ) : (
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                          </svg>
                        )}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        </div>

        {/* Right Column: Review & Safety */}
        <div className="space-y-8">
          {/* Claim Gate */}
          <section className={`p-6 rounded-2xl border ${
            draft.claim_gate === 'CLAIM_SAFE' ? 'bg-emerald-500/5 border-emerald-500/20' : 
            draft.claim_gate === 'CLAIM_BLOCKED' ? 'bg-red-500/5 border-red-500/20' : 'bg-amber-500/5 border-amber-500/20'
          }`}>
            <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-4">Claim Safety Check</h4>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold text-slate-500 uppercase">Status</span>
                <span className={`text-xs font-bold uppercase ${
                  draft.claim_gate === 'CLAIM_SAFE' ? 'text-emerald-400' : 
                  draft.claim_gate === 'CLAIM_BLOCKED' ? 'text-red-400' : 'text-amber-400'
                }`}>
                  {draft.claim_gate}
                </span>
              </div>
              {draft.claim_tokens.length > 0 && (
                <div>
                  <span className="text-[10px] font-bold text-slate-500 uppercase block mb-2">Detected Tokens</span>
                  <div className="flex flex-wrap gap-2">
                    {draft.claim_tokens.map(t => (
                      <span key={t} className="px-2 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300 border border-slate-700">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {draft.copy_safety_notes && (
                <div className="p-3 rounded-lg bg-black/20 text-xs text-slate-400 italic leading-relaxed">
                  {draft.copy_safety_notes}
                </div>
              )}
            </div>
          </section>

          {/* Human Review / Blocked */}
          <section className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800">
            <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-4">Authority Risks</h4>
            <div className="space-y-4">
              {draft.blocked_fields.length > 0 && (
                <div className="space-y-2">
                  <span className="text-[10px] font-bold text-red-500 uppercase">Blocked Fields</span>
                  <div className="flex flex-wrap gap-2">
                    {draft.blocked_fields.map(f => (
                      <span key={f} className="px-2 py-1 rounded bg-red-500/10 text-[10px] text-red-400 border border-red-500/20 font-bold uppercase">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {draft.human_review_fields.length > 0 && (
                <div className="space-y-2">
                  <span className="text-[10px] font-bold text-amber-500 uppercase">Review Required ({draft.human_review_fields.filter(f => !approvals[f]).length} Remaining)</span>
                  <div className="flex flex-wrap gap-2">
                    {draft.human_review_fields.map(f => (
                      <span key={f} className={`px-2 py-1 rounded text-[10px] font-bold uppercase border transition-all ${
                        approvals[f] ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                      }`}>
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {draft.missing_required_evidence.length > 0 && (
                <div className="space-y-2">
                  <span className="text-[10px] font-bold text-slate-500 uppercase">Missing Evidence</span>
                  <div className="flex flex-wrap gap-2">
                    {draft.missing_required_evidence.map(f => (
                      <span key={f} className="px-2 py-1 rounded bg-slate-800 text-[10px] text-slate-400 border border-slate-700">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Mode Readiness */}
          <section className="p-6 rounded-2xl bg-slate-900/50 border border-slate-800">
            <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-4">Mode Readiness</h4>
            <div className="space-y-4">
              {Object.entries(draft.readiness_by_mode).map(([mode, data]) => (
                <div key={mode} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-slate-500 uppercase">{mode.replace(/_/g, ' ')}</span>
                    <span className={`text-[10px] font-bold uppercase ${data.status === 'READY' ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {data.status}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500">{data.detail}</div>
                  <div className="w-full h-1 bg-slate-800 rounded-full mt-1 overflow-hidden">
                    <div className={`h-full transition-all duration-1000 ${data.status === 'READY' ? 'w-full bg-emerald-500' : 'w-1/2 bg-amber-500'}`} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Action Buttons */}
          <div className="pt-4 flex flex-col gap-4">
            <div className="flex gap-4">
              <button
                onClick={exportJSON}
                className="flex-1 py-3 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold uppercase tracking-widest transition-all border border-slate-700"
              >
                Export Draft JSON
              </button>
              <button
                onClick={() => setShowConfirm(true)}
                disabled={!isReadyToCommit || draft.review_status === 'COMMITTED'}
                className={`flex-1 py-3 px-4 rounded-xl text-xs font-bold uppercase tracking-widest transition-all border ${
                  isReadyToCommit && draft.review_status !== 'COMMITTED'
                    ? 'bg-indigo-500 hover:bg-indigo-400 text-white border-indigo-400 shadow-lg shadow-indigo-500/20'
                    : 'bg-indigo-500/10 text-indigo-400/40 border-indigo-500/10 cursor-not-allowed'
                }`}
              >
                {draft.review_status === 'COMMITTED' ? 'Committed' : 'Commit to DB'}
              </button>
            </div>
            
            {showConfirm && (
              <div className="p-6 rounded-2xl bg-slate-900 border border-indigo-500/50 shadow-2xl animate-in zoom-in-95 duration-200">
                <h5 className="text-sm font-bold text-white mb-2">Registration Authority Gate</h5>
                <p className="text-[10px] text-slate-400 mb-4 leading-relaxed">
                  You are about to commit this product to the canonical database. This action is persistent and will make the product available for asset generation.
                </p>
                <div className="space-y-3">
                  <div>
                    <label className="text-[10px] font-bold text-slate-500 uppercase mb-1 block">Confirmation Phrase</label>
                    <input 
                      type="text"
                      value={confirmPhrase}
                      onChange={e => setConfirmPhrase(e.target.value)}
                      placeholder="Type REGISTER_OWNED_PRODUCT"
                      className="w-full bg-black/40 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder:text-slate-600 focus:border-indigo-500 outline-none transition-all"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setShowConfirm(false)}
                      className="flex-1 py-2 rounded-lg bg-slate-800 text-slate-400 text-[10px] font-bold uppercase hover:text-white transition-all"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleCommit}
                      disabled={confirmPhrase !== 'REGISTER_OWNED_PRODUCT' || isCommitting}
                      className={`flex-1 py-2 rounded-lg text-[10px] font-bold uppercase transition-all ${
                        confirmPhrase === 'REGISTER_OWNED_PRODUCT' 
                          ? 'bg-indigo-500 text-white hover:bg-indigo-400 shadow-lg shadow-indigo-500/20' 
                          : 'bg-slate-700 text-slate-500 cursor-not-allowed'
                      }`}
                    >
                      {isCommitting ? 'Committing...' : 'Authorize Commit'}
                    </button>
                  </div>
                </div>
                {commitResult?.errors && (
                  <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-[10px] text-red-400 font-medium">
                    {commitResult.errors.join(', ')}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
