import React, { useState, useEffect, useRef } from 'react'
import { Search, AlertCircle, Image as ImageIcon, FileText, ShoppingBag } from 'lucide-react'
import type { Product } from '../../types'

interface ProductPickerProps {
  products: Product[]
  selectedProductId: string
  onSelect: (productId: string) => void
  loading?: boolean
}

export const ProductPicker: React.FC<ProductPickerProps> = ({ products, selectedProductId, onSelect, loading }) => {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)

  const selectedProduct = products.find(p => p.id === selectedProductId)

  const filteredProducts = products.filter(p => {
    const searchLower = search.toLowerCase()
    return (
      p.product_short_name?.toLowerCase().includes(searchLower) ||
      p.product_display_name?.toLowerCase().includes(searchLower) ||
      p.id.toLowerCase().includes(searchLower) ||
      p.category?.toLowerCase().includes(searchLower) ||
      p.subcategory?.toLowerCase().includes(searchLower)
    )
  })

  // Prioritize FASTMOSS and READY
  const sortedProducts = [...filteredProducts].sort((a, b) => {
    // 1. Prioritize FASTMOSS
    const aIsFastMoss = a.source === 'FASTMOSS' ? 1 : 0
    const bIsFastMoss = b.source === 'FASTMOSS' ? 1 : 0
    if (aIsFastMoss !== bIsFastMoss) return bIsFastMoss - aIsFastMoss

    // 2. Prioritize READY / IMAGE_READY / IMAGE_CACHE_READY
    const aIsReady = (a.prompt_readiness_status === 'READY' || a.image_readiness_status === 'IMAGE_READY' || a.image_readiness_status === 'IMAGE_CACHE_READY') ? 1 : 0
    const bIsReady = (b.prompt_readiness_status === 'READY' || b.image_readiness_status === 'IMAGE_READY' || b.image_readiness_status === 'IMAGE_CACHE_READY') ? 1 : 0
    if (aIsReady !== bIsReady) return bIsReady - aIsReady

    return 0
  })

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="w-full flex flex-col gap-1" ref={dropdownRef}>
      <label className="text-[10px] uppercase font-bold opacity-50 block">Select Product</label>
      <div
        onClick={() => !loading && setIsOpen(!isOpen)}
        className={`bg-card border rounded px-3 py-2 text-xs flex justify-between items-center cursor-pointer hover:border-accent transition-colors ${isOpen ? 'border-accent shadow-[0_0_10px_rgba(var(--accent-rgb),0.1)]' : 'border-white/5'} ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <div className="truncate flex-1 mr-2">
          {selectedProduct ? (
            <div className="flex items-center gap-2">
              <span className="font-bold text-accent">{selectedProduct.product_short_name}</span>
              <span className="opacity-30 text-[10px] font-mono">#{selectedProduct.id.slice(0, 8)}</span>
            </div>
          ) : (
            <span className="opacity-40">-- Search & Select Product --</span>
          )}
        </div>
        <div className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}>
          <Search size={12} className="opacity-40" />
        </div>
      </div>

      {isOpen && (
        <div className="mt-1 w-full bg-surface border border-accent/20 rounded-lg overflow-hidden flex flex-col animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="p-2 border-b border-white/5 bg-black/20">
            <input
              autoFocus
              type="text"
              placeholder="Search by name, ID, category..."
              className="w-full bg-card border border-white/10 rounded px-3 py-2 text-xs focus:border-accent outline-none placeholder:opacity-30"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="overflow-y-auto flex-1 max-h-[280px] custom-scrollbar bg-black/10">
            {sortedProducts.length > 0 ? (
              sortedProducts.map(p => (
                <div
                  key={p.id}
                  onClick={() => {
                    onSelect(p.id)
                    setIsOpen(false)
                    setSearch('')
                  }}
                  className={`p-3 border-b border-white/5 last:border-0 hover:bg-accent/10 cursor-pointer flex flex-col gap-1.5 transition-all ${selectedProductId === p.id ? 'bg-accent/5 border-l-2 border-l-accent' : ''}`}
                >
                  <div className="flex justify-between items-start gap-3">
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className="font-bold text-[13px] text-white/90 truncate">{p.product_short_name}</span>
                      <span className="text-[9px] opacity-30 font-mono tracking-tighter truncate">ID: {p.id}</span>
                    </div>
                    <div className="flex flex-wrap justify-end gap-1 shrink-0">
                      {p.source === 'FASTMOSS' && (
                        <span className="bg-purple-500/20 text-purple-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-purple-500/10">
                          <ShoppingBag size={8} /> FM
                        </span>
                      )}
                      {p.image_readiness_status === 'IMAGE_READY' || p.image_readiness_status === 'IMAGE_CACHE_READY' ? (
                        <span className="bg-green-500/20 text-green-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-green-500/10">
                          <ImageIcon size={8} /> IMG
                        </span>
                      ) : (
                        <span className="bg-red-500/20 text-red-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-red-500/10">
                          <AlertCircle size={8} /> NO IMG
                        </span>
                      )}
                      {p.prompt_readiness_status === 'READY' ? (
                        <span className="bg-blue-500/20 text-blue-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-blue-500/10">
                          <FileText size={8} /> READY
                        </span>
                      ) : (
                        <span className="bg-orange-500/20 text-orange-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5 border border-orange-500/10">
                          <AlertCircle size={8} /> REV
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-[9px] opacity-40 font-medium">
                    <span className="truncate">{p.category || 'No Category'}</span>
                    <span className="opacity-20">•</span>
                    <span className="truncate">{p.subcategory || 'No Sub'}</span>
                    <span className="opacity-20">•</span>
                    <span className="bg-white/5 px-1 rounded-sm text-[8px] uppercase tracking-wider">{p.type || 'Standard'}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-8 text-center opacity-30 text-xs italic">
                No products found matching "{search}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
