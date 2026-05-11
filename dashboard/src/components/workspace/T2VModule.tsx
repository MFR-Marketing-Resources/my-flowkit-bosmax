import React, { useState, useEffect, useMemo } from 'react'
import { ArrowRight, Info } from 'lucide-react'
import { fetchAPI } from '../../api/client'
import type { Product, Orientation } from '../../types'
import SearchableProductSelect from './SearchableProductSelect'

interface T2VModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
}

export default function T2VModule({ onExecute, isExecuting }: T2VModuleProps) {
  // --- States ---
  const [products, setProducts] = useState<Product[]>([])
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>('')
  const [filterSubCategory, setFilterSubCategory] = useState<string>('')
  const [filterType, setFilterType] = useState<string>('')
  
  const [manualPrompt, setManualPrompt] = useState('')
  
  // Mirror States
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [model, setModel] = useState('Veo 3.1 - Pro')

  // --- Data Fetching ---
  useEffect(() => {
    fetchAPI<{ items: Product[] }>('/api/products?limit=200').then(res => {
      setProducts(res.items)
    })
  }, [])

  // --- Computed Filters ---
  const categories = useMemo(() => Array.from(new Set(products.map(p => p.category).filter((c): c is string => !!c))), [products])
  const subCategories = useMemo(() => Array.from(new Set(products.filter(p => !filterCategory || p.category === filterCategory).map(p => p.subcategory).filter((s): s is string => !!s))), [products, filterCategory])
  const types = useMemo(() => Array.from(new Set(products.filter(p => (!filterCategory || p.category === filterCategory) && (!filterSubCategory || p.subcategory === filterSubCategory)).map(p => p.type).filter((t): t is string => !!t))), [products, filterCategory, filterSubCategory])

  const filteredProducts = useMemo(() => {
    return products.filter(p => {
      if (filterCategory && p.category !== filterCategory) return false
      if (filterSubCategory && p.subcategory !== filterSubCategory) return false
      if (filterType && p.type !== filterType) return false
      return true
    })
  }, [products, filterCategory, filterSubCategory, filterType])

  // --- Prompt Logic (TRUE AUTOMATED DNA) ---
  const generatedPrompt = useMemo(() => {
    if (!selectedProduct) return ''
    const p = selectedProduct
    
    // Assemble from product DNA fields
    const base = p.section_4_visual_action_prompt || p.raw_product_title
    const physics = p.section_5_product_physics_prompt || ''
    const context = p.scene_context || ''
    
    return [base, physics, context].filter(Boolean).join(', ')
  }, [selectedProduct])

  const finalPrompt = manualPrompt || generatedPrompt

  // --- Handlers ---
  const handleExecute = () => {
    onExecute({
      product_id: selectedProduct?.id,
      prompt: finalPrompt,
      orientation,
      model,
      mode: 'T2V'
    })
  }

  return (
    <div className="flex h-full gap-6">
      {/* Main Workspace */}
      <div className="flex-1 space-y-6 overflow-y-auto pr-2 pb-12">
        
        {/* 1. Product Registry */}
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

            <SearchableProductSelect 
              products={filteredProducts}
              selectedProduct={selectedProduct}
              onSelect={(p) => {
                setSelectedProduct(p)
                setManualPrompt('') 
              }}
            />
          </div>
        </section>

        {/* 2. Prompt Injection (TRUE AUTOMATED DNA) */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Prompt Injection</h3>
            {manualPrompt && (
              <span className="text-[10px] text-yellow-500 font-bold animate-pulse">Manual Override Active</span>
            )}
          </div>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-60 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="Your prompt will generate automatically from product DNA..."
              value={finalPrompt}
              onChange={(e) => setManualPrompt(e.target.value)}
            />
            <div className="flex items-center gap-2 text-[10px] text-slate-500 italic">
              <Info size={12} />
              <span>BOSMAX DNA injection is active. Prompt is built from Section 4/5/Creative Brief.</span>
            </div>
          </div>
        </section>
        
        <div className="pt-4">
          <button 
            onClick={handleExecute}
            disabled={isExecuting || !finalPrompt}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isExecuting ? 'Executing T2V Sequence...' : 'START GENERATION'}
            {!isExecuting && <ArrowRight size={18} />}
          </button>
        </div>
      </div>

      {/* Google Flow Mirror Panel */}
      <div className="w-72 flex-shrink-0 flex flex-col gap-6 overflow-y-auto pb-12">
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
           <h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest mb-2">T2V Context</h4>
           <div className="text-[10px] text-blue-300/60 leading-relaxed italic">
             {selectedProduct ? (
               <>
                 <div className="text-blue-400 font-bold mb-1">Product Intelligence Active:</div>
                 <div>Physics DNA: {selectedProduct.physics_class || 'General'}</div>
                 <div>Scale: {selectedProduct.product_scale || 'Normal'}</div>
                 <div className="mt-2 text-slate-400">Google Flow will generate visual based on text prompt only.</div>
               </>
             ) : (
               'BOSMAX will generate video based on the text prompt injected into Google Flow.'
             )}
           </div>
        </section>
      </div>
    </div>
  )
}
