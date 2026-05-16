import { useState } from 'react'
import ProductKnowledgeIntakeForm from '../components/product-registration/ProductKnowledgeIntakeForm'
import ProductKnowledgeResultPanel from '../components/product-registration/ProductKnowledgeResultPanel'
import type { ProductKnowledgeCompleteResponse } from '../types'

export default function ProductRegistrationPage() {
  const [result, setResult] = useState<ProductKnowledgeCompleteResponse | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)

  const handleComplete = (data: ProductKnowledgeCompleteResponse) => {
    setResult(data)
  }

  return (
    <div className="flex h-full flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-8 overflow-y-auto">
      <div className="mb-6 flex flex-col gap-4 lg:mb-8 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">Smart Product Registration</h2>
          <p className="text-sm italic text-slate-400">Transforming messy product knowledge into structured Product Intelligence.</p>
        </div>
        <div className="flex items-center gap-3">
           <div className="px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-[10px] font-bold uppercase tracking-widest">
             Phase 3: Product Knowledge Intake
           </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-8">
        <div className="space-y-8">
          <section className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6 shadow-2xl backdrop-blur-sm">
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-white">Product Knowledge Intake</h3>
              <p className="text-xs text-slate-500 mt-1">Paste any text, ingredients, or benefits. The system will extract facts and suggest a profile.</p>
            </div>
            <ProductKnowledgeIntakeForm 
              onComplete={handleComplete} 
              setIsProcessing={setIsProcessing}
              isProcessing={isProcessing}
            />
          </section>

          {result && (
            <section className="rounded-3xl border border-slate-800 bg-slate-900/40 p-6 shadow-2xl backdrop-blur-sm animate-in fade-in slide-in-from-bottom-4 duration-700">
              <div className="mb-6 flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-white">Intelligence Extraction Report</h3>
                  <p className="text-xs text-slate-500 mt-1">Status: <span className={result.completion_status === 'COMPLETION_READY' ? 'text-emerald-400' : 'text-amber-400'}>{result.completion_status}</span></p>
                </div>
                <div className={`px-2 py-1 rounded text-[10px] font-bold ${result.input_quality_status === 'SUFFICIENT' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}>
                  QUALITY: {result.input_quality_status}
                </div>
              </div>
              
              <ProductKnowledgeResultPanel result={result} />
            </section>
          )}
        </div>

        <aside className="space-y-6">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <h4 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-4">Governance & Authority</h4>
            <div className="space-y-4 text-xs">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]" />
                <p className="text-slate-400 leading-relaxed">
                  <strong className="text-slate-200">Declared Evidence:</strong> All manual input is treated as "Declared" and requires Source Anchor verification for canonical truth.
                </p>
              </div>
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.5)]" />
                <p className="text-slate-400 leading-relaxed">
                  <strong className="text-slate-200">Claim Gate:</strong> Any health or medical keywords trigger <code className="bg-slate-800 px-1 rounded text-amber-300">CLAIM_REVIEW_REQUIRED</code>.
                </p>
              </div>
              <div className="flex items-start gap-3">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]" />
                <p className="text-slate-400 leading-relaxed">
                  <strong className="text-slate-200">No DB Writes:</strong> This module is currently <strong className="text-red-400 italic">PREVIEW ONLY</strong>. Database mutation is disabled.
                </p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
             <h4 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-4">Intake Tips</h4>
             <ul className="list-disc list-inside text-xs text-slate-400 space-y-2">
               <li>Paste the full TikTok Shop product description</li>
               <li>Include ingredient lists for beauty products</li>
               <li>Declare weight/volume (e.g. 500ml, 1kg)</li>
               <li>Mention USP like "Anti-leak" or "Fast-drying"</li>
             </ul>
          </div>
        </aside>
      </div>
    </div>
  )
}
