import { useState } from 'react'
import { postAPI } from '../../api/client'
import type { ProductKnowledgeCompleteRequest, ProductKnowledgeCompleteResponse } from '../../types'

interface Props {
  onComplete: (data: ProductKnowledgeCompleteResponse) => void
  setIsProcessing: (val: boolean) => void
  isProcessing: boolean
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('Failed to read image file'))
    reader.readAsDataURL(file)
  })
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
    currency: 'MYR',
    commission_amount: undefined,
    commission_rate: '',
    size_or_volume: '',
    package_notes: '',
    source_lane: 'OWNED',
    image_url: '',
    product_url: '',
    source_url: '',
    tiktok_product_url: '',
    tiktok_shop_url: '',
    paste_anything_about_product: '',
    image_base64: '',
    image_filename: '',
  })

  const [selectedImageName, setSelectedImageName] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsProcessing(true)
    try {
      const result = await postAPI<ProductKnowledgeCompleteResponse>('/api/product-knowledge/complete', formData)
      onComplete(result)
    } catch (err) {
      console.error('Completion failed:', err)
      alert('Failed to complete product knowledge. Check console.')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleImageUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const imageBase64 = await readFileAsDataUrl(file)
      setSelectedImageName(file.name)
      setFormData(prev => ({
        ...prev,
        image_base64: imageBase64,
        image_filename: file.name,
      }))
    } catch (err) {
      console.error('Failed to read selected image:', err)
      alert('Failed to load image file.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Product Name</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all"
            placeholder="e.g. Bosmax Herbs"
            value={formData.product_name}
            onChange={e => setFormData({ ...formData, product_name: e.target.value })}
            required
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Source Lane</label>
          <select
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white outline-none focus:border-indigo-500/50 transition-all"
            value={formData.source_lane}
            onChange={e => setFormData({ ...formData, source_lane: e.target.value })}
          >
            <option value="OWNED">OWNED</option>
            <option value="MANUAL">MANUAL</option>
            <option value="FASTMOSS_REFERENCE">FASTMOSS_REFERENCE</option>
            <option value="TIKTOKSHOP_DRAFT">TIKTOKSHOP_DRAFT</option>
            <option value="UNKNOWN_REVIEW_REQUIRED">UNKNOWN_REVIEW_REQUIRED</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Size / Volume</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="e.g. 5 ML, 500ml, 1.2kg"
            value={formData.size_or_volume}
            onChange={e => setFormData({ ...formData, size_or_volume: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Price</label>
          <input
            type="number"
            step="0.01"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="0.00"
            value={formData.price ?? ''}
            onChange={e => setFormData({ ...formData, price: e.target.value ? parseFloat(e.target.value) : undefined })}
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Currency</label>
          <input
            type="text"
            className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
            placeholder="MYR"
            value={formData.currency || ''}
            onChange={e => setFormData({ ...formData, currency: e.target.value })}
          />
        </div>
      </div>

      <section className="space-y-4 rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-5">
        <div className="space-y-1">
          <h4 className="text-[11px] font-bold uppercase tracking-[0.24em] text-indigo-300">
            Media, Source & Commercial Evidence
          </h4>
          <p className="text-xs text-slate-400">
            Capture URLs, pricing, commission, packaging, and product image evidence here. Missing facts are allowed, but this section should stay visible and explicit during intake.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Commission Amount</label>
            <input
              type="number"
              step="0.01"
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
              placeholder="0.00"
              value={formData.commission_amount ?? ''}
              onChange={e => setFormData({ ...formData, commission_amount: e.target.value ? parseFloat(e.target.value) : undefined })}
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Commission Rate</label>
            <input
              type="text"
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
              placeholder="e.g. 15%"
              value={formData.commission_rate || ''}
              onChange={e => setFormData({ ...formData, commission_rate: e.target.value })}
            />
          </div>
          <div className="space-y-2 lg:col-span-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Package Notes</label>
            <input
              type="text"
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
              placeholder="e.g. Trial bottle, dropper cap, roll on"
              value={formData.package_notes || ''}
              onChange={e => setFormData({ ...formData, package_notes: e.target.value })}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Product URL / Source URL</label>
            <input
              type="url"
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
              placeholder="https://"
              value={formData.product_url || formData.source_url || ''}
              onChange={e => setFormData({ ...formData, product_url: e.target.value, source_url: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">TikTok Shop Product / Shop URL</label>
            <input
              type="url"
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
              placeholder="https://shop.tiktok.com/..."
              value={formData.tiktok_product_url || formData.tiktok_shop_url || ''}
              onChange={e => setFormData({ ...formData, tiktok_product_url: e.target.value, tiktok_shop_url: e.target.value })}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Image URL</label>
            <input
              type="url"
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 transition-all"
              placeholder="https://example.com/product.jpg"
              value={formData.image_url || ''}
              onChange={e => setFormData({ ...formData, image_url: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1">Upload Product Image</label>
            <input
              type="file"
              accept="image/*"
              onChange={handleImageUpload}
              className="block w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-indigo-500/10 file:text-indigo-400 hover:file:bg-indigo-500/20 transition-all cursor-pointer"
            />
            <div className="text-[11px] text-slate-500">
              {selectedImageName ? `Selected image: ${selectedImageName}` : 'Optional. Stored as draft evidence until controlled commit.'}
            </div>
          </div>
        </div>
      </section>

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
            placeholder="e.g. married men, gym enthusiasts, feminine care users"
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
