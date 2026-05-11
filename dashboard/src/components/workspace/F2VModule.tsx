import React, { useState, useEffect, useMemo } from 'react'
import { Sparkles, Upload, ArrowRight, Info, Filter, Camera, User, Palette } from 'lucide-react'
import { fetchAPI, postAPI } from '../../api/client'
import type { Product, Scene, UploadedAsset, Orientation } from '../../types'

interface F2VModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
}

export default function F2VModule({ onExecute, isExecuting }: F2VModuleProps) {
  // --- States from Original Monolith ---
  const [products, setProducts] = useState<Product[]>([])
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>('')
  const [filterSubCategory, setFilterSubCategory] = useState<string>('')
  const [filterType, setFilterType] = useState<string>('')
  
  // Creative States
  const [selectedCharacter, setSelectedCharacter] = useState<string>('')
  const [selectedCamera, setSelectedCamera] = useState<string>('')
  const [selectedStyle, setSelectedStyle] = useState<string>('')
  const [manualPrompt, setManualPrompt] = useState('')
  
  // Mirror States
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [model, setModel] = useState('Veo 3.1 - Pro')
  const [startAsset, setStartAsset] = useState<UploadedAsset | null>(null)
  const [endAsset, setEndAsset] = useState<UploadedAsset | null>(null)

  // --- Data Fetching ---
  useEffect(() => {
    fetchAPI<{ items: Product[] }>('/api/products?limit=200').then(res => {
      setProducts(res.items)
    })
  }, [])

  // --- Computed Filters ---
  const categories = useMemo(() => Array.from(new Set(products.map(p => p.category).filter(Boolean))), [products])
  const subCategories = useMemo(() => Array.from(new Set(products.filter(p => !filterCategory || p.category === filterCategory).map(p => p.sub_category).filter(Boolean))), [products, filterCategory])
  const types = useMemo(() => Array.from(new Set(products.filter(p => (!filterCategory || p.category === filterCategory) && (!filterSubCategory || p.sub_category === filterSubCategory)).map(p => p.type).filter(Boolean))), [products, filterCategory, filterSubCategory])

  const filteredProducts = useMemo(() => {
    return products.filter(p => {
      if (filterCategory && p.category !== filterCategory) return false
      if (filterSubCategory && p.sub_category !== filterSubCategory) return false
      if (filterType && p.type !== filterType) return false
      return true
    })
  }, [products, filterCategory, filterSubCategory, filterType])

  // --- Prompt Logic (Ported from Monolith) ---
  const generatedPrompt = useMemo(() => {
    if (!selectedProduct) return ''
    const parts = [
      `A professional cinematic shot of ${selectedProduct.raw_product_title}`,
      selectedCharacter ? `featuring ${selectedCharacter}` : '',
      selectedCamera ? `shot from ${selectedCamera} angle` : '',
      selectedStyle ? `in a ${selectedStyle} visual style` : 'realistic cinematic lighting',
      '8k resolution, highly detailed textures, smooth motion'
    ]
    return parts.filter(Boolean).join(', ')
  }, [selectedProduct, selectedCharacter, selectedCamera, selectedStyle])

  const finalPrompt = manualPrompt || generatedPrompt

  // --- Handlers ---
  const handleStartUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    // Logic to upload start frame
  }

  const handleEndUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    // Logic to upload end frame
  }

  return (
    <div className="flex h-full gap-6">
      {/* Main Workspace */}
      <div className="flex-1 space-y-6 overflow-y-auto pr-2 pb-12">
        
        {/* 1. Product Registry (Restored Filters) */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">1. Product Registry</h3>
            <div className="flex gap-2">
               <span className="text-[10px] text-slate-500">{filteredProducts.length} Products Found</span>
            </div>
          </div>
          
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            {/* Filter Bar */}
            <div className="grid grid-cols-3 gap-3">
              <select 
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] text-slate-300 outline-none focus:border-blue-500"
                value={filterCategory}
                onChange={e => { setFilterCategory(e.target.value); setFilterSubCategory(''); setFilterType(''); }}
              >
                <option value="">All Categories</option>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <select 
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] text-slate-300 outline-none focus:border-blue-500"
                value={filterSubCategory}
                onChange={e => { setFilterSubCategory(e.target.value); setFilterType(''); }}
              >
                <option value="">All Sub-Categories</option>
                {subCategories.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <select 
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] text-slate-300 outline-none focus:border-blue-500"
                value={filterType}
                onChange={e => setFilterType(e.target.value)}
              >
                <option value="">All Types</option>
                {types.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            {/* Product Selector */}
            <select 
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 text-sm text-slate-200 outline-none focus:border-blue-500 transition-colors font-bold"
              value={selectedProduct?.id || ''}
              onChange={(e) => {
                const p = products.find(p => p.id === e.target.value)
                setSelectedProduct(p || null)
              }}
            >
              <option value="">Select product for production...</option>
              {filteredProducts.map(p => (
                <option key={p.id} value={p.id}>{p.raw_product_title}</option>
              ))}
            </select>
          </div>
        </section>

        {/* 2. Creative Suite (Restored Character/Camera) */}
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Creative Suite</h3>
          <div className="grid grid-cols-3 gap-4">
             <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-2">
                <label className="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                  <User size={12} className="text-blue-500" /> Character
                </label>
                <select 
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none"
                  value={selectedCharacter}
                  onChange={e => setSelectedCharacter(e.target.value)}
                >
                  <option value="">No Character</option>
                  <option value="Sumikko Baby">Sumikko Baby</option>
                  <option value="Professional Model">Professional Model</option>
                </select>
             </div>
             <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-2">
                <label className="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                  <Camera size={12} className="text-purple-500" /> Camera Angle
                </label>
                <select 
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none"
                  value={selectedCamera}
                  onChange={e => setSelectedCamera(e.target.value)}
                >
                  <option value="">Default Angle</option>
                  <option value="Close-up">Close-up</option>
                  <option value="Low Angle">Low Angle</option>
                  <option value="Top-down">Top-down</option>
                </select>
             </div>
             <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-2">
                <label className="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                  <Palette size={12} className="text-pink-500" /> Style
                </label>
                <select 
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none"
                  value={selectedStyle}
                  onChange={e => setSelectedStyle(e.target.value)}
                >
                  <option value="">Cinematic Realistic</option>
                  <option value="3D Pixar Style">3D Pixar Style</option>
                  <option value="Studio Product Shot">Studio Product Shot</option>
                </select>
             </div>
          </div>
        </section>

        {/* 3. Visual Assets (F2V Slots) */}
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">3. Visual Assets (F2V Slots)</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="group relative aspect-[9/16] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {startAsset ? (
                 <img src={`http://127.0.0.1:8100/api/products/${startAsset.mediaId}/image`} className="w-full h-full object-cover" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300">Start Frame</span>
                 </>
               )}
               <input type="file" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleStartUpload} />
            </div>

            <div className="group relative aspect-[9/16] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {endAsset ? (
                 <img src={`http://127.0.0.1:8100/api/products/${endAsset.mediaId}/image`} className="w-full h-full object-cover" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300">End Frame (Optional)</span>
                 </>
               )}
               <input type="file" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleEndUpload} />
            </div>
          </div>
        </section>

        {/* 4. Prompt Injection (Restored Logic) */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">4. Prompt Injection</h3>
            {manualPrompt && (
              <span className="text-[10px] text-yellow-500 font-bold animate-pulse">Manual Override Active</span>
            )}
          </div>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="Your prompt will generate automatically from settings above..."
              value={finalPrompt}
              onChange={(e) => setManualPrompt(e.target.value)}
            />
            <div className="flex items-center gap-2 text-[10px] text-slate-500 italic">
              <Info size={12} />
              <span>BOSMAX will inject this exact DNA into the Google Flow prompt field.</span>
            </div>
          </div>
        </section>
        
        <div className="pt-4">
          <button 
            disabled={isExecuting || !finalPrompt || !startAsset}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isExecuting ? 'Executing Golden Sequence...' : 'START GENERATION'}
            {!isExecuting && <ArrowRight size={18} />}
          </button>
        </div>
      </div>

      {/* Google Flow Mirror Panel */}
      <div className="w-72 flex-shrink-0 flex flex-col gap-6 overflow-y-auto">
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Flow Mirror Settings</h3>
          <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Aspect Ratio</label>
              <div className="grid grid-cols-2 gap-2">
                <button 
                  onClick={() => setOrientation('VERTICAL')}
                  className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === 'VERTICAL' ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}
                >
                  9:16 (Vertical)
                </button>
                <button 
                  onClick={() => setOrientation('HORIZONTAL')}
                  className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === 'HORIZONTAL' ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}
                >
                  16:9 (Horizontal)
                </button>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Generation Model</label>
              <select 
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-bold text-slate-300 outline-none"
              >
                <option>Veo 3.1 - Pro</option>
                <option>Veo 3.1 - Lite</option>
                <option>Nano Banana 2</option>
              </select>
            </div>

            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Count</label>
              <div className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-[10px] font-bold text-slate-400">
                1 Video
              </div>
            </div>
          </div>
        </section>

        <section className="p-6 rounded-2xl border border-blue-500/10 bg-blue-500/5">
           <h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest mb-2">F2V Context</h4>
           <p className="text-[10px] text-blue-300/60 leading-relaxed italic">
             Stability is guaranteed by your reference assets.
             {selectedCharacter && ` Using reference Character: ${selectedCharacter}`}
           </p>
        </section>
      </div>
    </div>
  )
}
