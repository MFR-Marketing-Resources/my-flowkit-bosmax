import { useState } from 'react'
import { postAPI } from '../../api/client'
import type { ProductKnowledgeCompleteRequest, ProductKnowledgeCompleteResponse } from '../../types'

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
    usage_text: '',
    ingredients_text: '',
    target_customer_text: '',
    warnings_text: '',
    price: undefined,
    commission_rate: '',
    size_or_volume: '',
    source_lane: 'MANUAL',
    paste_anything_about_product: ''
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


  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Row 1: Basic Identity */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-2">
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
      </div>

      {/* Row 2: Specs & Commercials */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Size / Volume</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="e.g. 500ml, 1.2kg"
            value={formData.size_or_volume}
            onChange={e => setFormData({ ...formData, size_or_volume: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Price (RM)</label>
          <input
            type="number"
            step="0.01"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="0.00"
            value={formData.price || ''}
            onChange={e => setFormData({ ...formData, price: e.target.value ? parseFloat(e.target.value) : undefined })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Commission Rate</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="e.g. 15%"
            value={formData.commission_rate}
            onChange={e => setFormData({ ...formData, commission_rate: e.target.value })}
          />
        </div>
      </div>

      {/* Row 3: Main Knowledge */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Product Description</label>
          <textarea
            className="w-full h-32 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all resize-none"
            placeholder="Technical specs, origin, or general knowledge..."
            value={formData.product_knowledge_text}
            onChange={e => setFormData({ ...formData, product_knowledge_text: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Paste Anything (Smart Extract)</label>
          <textarea
            className="w-full h-32 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all resize-none italic"
            placeholder="Paste raw TikTok Shop description or raw chat history here. The system will auto-extract benefits and claims."
            value={formData.paste_anything_about_product}
            onChange={e => setFormData({ ...formData, paste_anything_about_product: e.target.value })}
          />
        </div>
      </div>

      {/* Row 4: Attributes */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Benefits / USP</label>
          <textarea
            className="w-full h-24 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all resize-none"
            placeholder="Key selling points..."
            value={formData.benefits_text}
            onChange={e => setFormData({ ...formData, benefits_text: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Usage / Cara Guna</label>
          <textarea
            className="w-full h-24 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all resize-none"
            placeholder="Step by step instructions..."
            value={formData.usage_text}
            onChange={e => setFormData({ ...formData, usage_text: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Ingredients</label>
          <textarea
            className="w-full h-24 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all resize-none"
            placeholder="Chemicals, extracts, etc..."
            value={formData.ingredients_text}
            onChange={e => setFormData({ ...formData, ingredients_text: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Warnings / Pantang</label>
          <textarea
            className="w-full h-24 rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all resize-none"
            placeholder="Allergies, age limits, etc..."
            value={formData.warnings_text}
            onChange={e => setFormData({ ...formData, warnings_text: e.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-col md:flex-row gap-6 items-end">
        <div className="flex-1 space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Target Customer</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="e.g. Mothers with babies, gym enthusiasts"
            value={formData.target_customer_text}
            onChange={e => setFormData({ ...formData, target_customer_text: e.target.value })}
          />
        </div>
        <button
          type="submit"
          disabled={isProcessing || !formData.product_name}
          className={`px-8 py-3 rounded-xl font-bold uppercase tracking-widest text-xs transition-all shadow-lg min-w-[240px] ${isProcessing ? 'bg-slate-800 text-slate-500 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-500/20 hover:shadow-indigo-500/40'}`}
        >
          {isProcessing ? 'Analyzing Intelligence...' : 'Run Smart Completion'}
        </button>
      </div>
    </form>
  )
}
