import { useState } from 'react'
import { postAPI } from '../../api/client'
import { ProductKnowledgeCompleteRequest, ProductKnowledgeCompleteResponse } from '../../types'

interface Props {
  onComplete: (data: ProductKnowledgeCompleteResponse) => void
  setIsProcessing: (val: boolean) => void
  isProcessing: boolean
}

export default function ProductKnowledgeIntakeForm({ onComplete, setIsProcessing, isProcessing }: Props) {
  const [formData, setFormData] = useState<ProductKnowledgeCompleteRequest>({
    product_name: '',
    product_knowledge_text: '',
    benefits_text: '',
    size_or_volume: '',
    source_lane: 'MANUAL'
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsProcessing(true)
    try {
      const result = await postAPI<ProductKnowledgeCompleteResponse>('/api/product-knowledge/complete', formData as any)
      onComplete(result)
    } catch (err) {
      console.error('Completion failed:', err)
      alert('Failed to complete product knowledge. Check console.')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleQuickPaste = (text: string) => {
    setFormData(prev => ({ ...prev, product_knowledge_text: text }))
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Product Name</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all"
            placeholder="e.g. Bosmax Liquid Detergent"
            value={formData.product_name}
            onChange={e => setFormData({ ...formData, product_name: e.target.value })}
            required
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Size / Volume / Weight</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all"
            placeholder="e.g. 500ml, 1.2kg"
            value={formData.size_or_volume}
            onChange={e => setFormData({ ...formData, size_or_volume: e.target.value })}
          />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Product Knowledge / Description</label>
        <textarea
          className="w-full h-32 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all resize-none"
          placeholder="Paste full description, technical specs, or general knowledge here..."
          value={formData.product_knowledge_text}
          onChange={e => setFormData({ ...formData, product_knowledge_text: e.target.value })}
        />
        <div className="flex gap-2 mt-2">
          <button 
            type="button" 
            onClick={() => handleQuickPaste('Contoh: Sabun dobi wangi, 500ml, botol biru, sesuai untuk baju budak.')}
            className="text-[9px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 transition"
          >
            Load Example
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Benefits / USP (Optional)</label>
          <textarea
            className="w-full h-24 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all resize-none"
            placeholder="List benefits one per line..."
            value={formData.benefits_text}
            onChange={e => setFormData({ ...formData, benefits_text: e.target.value })}
          />
        </div>
        <div className="space-y-4">
           <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Intake Lane</label>
            <select 
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white outline-none focus:border-indigo-500/50 transition-all"
              value={formData.source_lane}
              onChange={e => setFormData({ ...formData, source_lane: e.target.value })}
            >
              <option value="MANUAL">MANUAL (Owned Brand)</option>
              <option value="FASTMOSS">FASTMOSS (Affiliate Draft)</option>
              <option value="TIKTOKSHOP">TIKTOKSHOP (Affiliate Draft)</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={isProcessing || !formData.product_name}
            className={`w-full py-3 rounded-xl font-bold uppercase tracking-widest text-xs transition-all shadow-lg ${isProcessing ? 'bg-slate-800 text-slate-500 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-500/20 hover:shadow-indigo-500/40'}`}
          >
            {isProcessing ? 'Analyzing Intelligence...' : 'Run Smart Completion'}
          </button>
        </div>
      </div>
    </form>
  )
}
