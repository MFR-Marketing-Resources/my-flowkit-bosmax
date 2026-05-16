import type { ProductKnowledgeCompleteResponse } from '../../types'

interface Props {
  result: ProductKnowledgeCompleteResponse
}

export default function ProductKnowledgeResultPanel({ result }: Props) {
  return (
    <div className="space-y-8">
      {/* 1. Taxonomy & Family */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <label className="text-[9px] font-bold uppercase tracking-widest text-slate-500 block mb-2">Category</label>
          <div className="text-sm text-slate-200 font-medium truncate" title={result.suggested_category || 'Unknown'}>
            {result.suggested_category || '—'}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <label className="text-[9px] font-bold uppercase tracking-widest text-slate-500 block mb-2">Sub-Category</label>
          <div className="text-sm text-slate-200 font-medium truncate" title={result.suggested_subcategory || 'Unknown'}>
            {result.suggested_subcategory || '—'}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <label className="text-[9px] font-bold uppercase tracking-widest text-slate-500 block mb-2">Product Family</label>
          <div className={`text-sm font-bold truncate ${result.suggested_bosmax_product_family === 'UNKNOWN_REVIEW_REQUIRED' ? 'text-amber-400' : 'text-indigo-400'}`} title={result.suggested_bosmax_product_family || 'Unknown'}>
            {result.suggested_bosmax_product_family || 'UNKNOWN'}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <label className="text-[9px] font-bold uppercase tracking-widest text-slate-500 block mb-2">Copy Route</label>
          <div className="text-sm text-slate-200 font-medium truncate">
            {result.suggested_copy_route || '—'}
          </div>
        </div>
      </div>

      {/* 2. Physics & Handling */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 ml-1">Physics & Scale</h4>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-5 space-y-4">
            <div className="flex justify-between items-center border-b border-slate-800/50 pb-3">
              <span className="text-xs text-slate-400">Package Form</span>
              <span className="text-xs text-slate-200 font-mono uppercase">{result.suggested_package_form || '—'}</span>
            </div>
            <div className="flex justify-between items-center border-b border-slate-800/50 pb-3">
              <span className="text-xs text-slate-400">Physical State</span>
              <span className="text-xs text-slate-200 font-mono uppercase">{result.suggested_physical_state || '—'}</span>
            </div>
            <div className="flex justify-between items-center border-b border-slate-800/50 pb-3">
              <span className="text-xs text-slate-400">Physics Class</span>
              <span className="text-xs text-slate-200 font-mono uppercase">{result.suggested_physics_class || '—'}</span>
            </div>
            <div className="pt-2">
              <label className="text-[9px] font-bold uppercase tracking-widest text-slate-500 block mb-2">Handling Profile</label>
              <p className="text-xs text-slate-300 italic leading-relaxed">
                {result.suggested_handling_profile || 'No handling profile derived.'}
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 ml-1">Claim Safety & Risk</h4>
          <div className={`rounded-2xl border p-5 h-full ${result.claim_gate === 'CLAIM_SAFE' ? 'border-emerald-500/30 bg-emerald-500/5' : result.claim_gate === 'CLAIM_BLOCKED' ? 'border-red-500/30 bg-red-500/5' : 'border-amber-500/30 bg-amber-500/5'}`}>
            <div className="flex items-center justify-between mb-4">
              <div className={`px-2 py-1 rounded text-[9px] font-bold uppercase tracking-widest ${result.claim_gate === 'CLAIM_SAFE' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}>
                {result.claim_gate}
              </div>
              <div className="text-[10px] text-slate-500 font-mono">Risk: {result.claim_risk_level}</div>
            </div>
            
            {result.claim_tokens.length > 0 && (
              <div className="mb-4">
                <label className="text-[9px] font-bold uppercase tracking-widest text-slate-500 block mb-2">Detected Risk Tokens</label>
                <div className="flex flex-wrap gap-2">
                  {result.claim_tokens.map(token => (
                    <span key={token} className="px-2 py-0.5 rounded-full bg-slate-800 text-[10px] text-slate-300 border border-slate-700">
                      {token}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-auto pt-4 border-t border-slate-800/50">
               <p className="text-xs text-slate-400 leading-relaxed">
                 {result.copy_safety_notes || 'Safety analysis complete.'}
               </p>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Extracted USP List */}
      {result.suggested_usp_list.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 ml-1">Suggested USP Hooks</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {result.suggested_usp_list.map((usp, idx) => (
              <div key={idx} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 hover:border-indigo-500/30 transition-all cursor-default">
                <div className="text-[10px] text-slate-600 mb-2 font-mono">USP {idx + 1}</div>
                <p className="text-sm text-slate-300 leading-snug">{usp}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. Readiness by Mode */}
      <div className="space-y-4">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 ml-1">System Readiness</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Object.entries(result.readiness_by_mode).map(([mode, readiness]) => (
            <div key={mode} className="flex items-center gap-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
              <div className={`h-3 w-3 rounded-full shadow-[0_0_8px] ${readiness.status === 'READY' ? 'bg-emerald-500 shadow-emerald-500/50' : 'bg-amber-500 shadow-amber-500/50'}`} />
              <div className="flex-1">
                <div className="text-[10px] font-bold uppercase tracking-widest text-slate-200">{mode.replace(/_/g, ' ')}</div>
                <div className="text-xs text-slate-500 mt-0.5">{readiness.detail}</div>
              </div>
              {readiness.missing_evidence.length > 0 && (
                <div className="text-[9px] font-bold text-amber-500 uppercase">
                  {readiness.missing_evidence.length} Missing
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      
      {/* 5. Warnings */}
      {result.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
          <div className="text-[10px] font-bold text-amber-500 uppercase tracking-[0.2em] mb-2">Attention Required</div>
          <ul className="space-y-1">
            {result.warnings.map((w, idx) => (
              <li key={idx} className="text-xs text-amber-200/70 flex items-center gap-2">
                <span className="text-amber-500">•</span> {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
