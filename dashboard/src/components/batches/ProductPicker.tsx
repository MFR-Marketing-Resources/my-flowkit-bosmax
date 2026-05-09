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
    <div className="relative w-full" ref={dropdownRef}>
      <label className="text-[10px] uppercase font-bold opacity-50 mb-1 block">Select Product</label>
      <div
        onClick={() => !loading && setIsOpen(!isOpen)}
        className={`bg-card border rounded px-3 py-2 text-xs flex justify-between items-center cursor-pointer hover:border-accent transition-colors ${isOpen ? 'border-accent' : ''} ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <div className="truncate flex-1 mr-2">
          {selectedProduct ? (
            <div className="flex items-center gap-2">
              <span className="font-semibold text-accent">{selectedProduct.product_short_name}</span>
              <span className="opacity-40 text-[10px]">#{selectedProduct.id.slice(0, 8)}</span>
            </div>
          ) : (
            <span className="opacity-40">-- Search & Select Product --</span>
          )}
        </div>
        <Search size={12} className="opacity-40" />
      </div>

      {isOpen && (
        <div className="absolute z-50 mt-1 w-full bg-surface border border-accent/30 rounded-lg shadow-2xl overflow-hidden flex flex-col max-h-[400px]">
          <div className="p-2 border-b border-white/5 bg-card/50">
            <input
              autoFocus
              type="text"
              placeholder="Search by name, ID, category..."
              className="w-full bg-black/20 border border-white/10 rounded px-3 py-1.5 text-xs focus:border-accent outline-none"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="overflow-y-auto flex-1 custom-scrollbar">
            {sortedProducts.length > 0 ? (
              sortedProducts.map(p => (
                <div
                  key={p.id}
                  onClick={() => {
                    onSelect(p.id)
                    setIsOpen(false)
                    setSearch('')
                  }}
                  className={`p-3 border-b border-white/5 last:border-0 hover:bg-accent/5 cursor-pointer flex flex-col gap-1 transition-colors ${selectedProductId === p.id ? 'bg-accent/10 border-l-2 border-l-accent' : ''}`}
                >
                  <div className="flex justify-between items-start">
                    <div className="flex flex-col">
                      <span className="font-bold text-sm text-white/90">{p.product_short_name}</span>
                      <span className="text-[10px] opacity-40 font-mono">ID: {p.id}</span>
                    </div>
                    <div className="flex gap-1">
                      {p.source === 'FASTMOSS' && (
                        <span className="bg-purple-500/20 text-purple-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5">
                          <ShoppingBag size={8} /> FM
                        </span>
                      )}
                      {p.image_readiness_status === 'IMAGE_READY' || p.image_readiness_status === 'IMAGE_CACHE_READY' ? (
                        <span className="bg-green-500/20 text-green-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5">
                          <ImageIcon size={8} /> IMG
                        </span>
                      ) : (
                        <span className="bg-red-500/20 text-red-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5">
                          <AlertCircle size={8} /> NO IMG
                        </span>
                      )}
                      {p.prompt_readiness_status === 'READY' ? (
                        <span className="bg-blue-500/20 text-blue-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5">
                          <FileText size={8} /> PROMPT
                        </span>
                      ) : (
                        <span className="bg-orange-500/20 text-orange-400 text-[8px] font-bold px-1.5 py-0.5 rounded flex items-center gap-0.5">
                          <AlertCircle size={8} /> NEEDS_REV
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] opacity-60 italic">
                    <span>{p.category || 'No Category'}</span>
                    <span>•</span>
                    <span>{p.subcategory || 'No Sub'}</span>
                    <span>•</span>
                    <span className="bg-white/5 px-1 rounded">{p.type || 'Standard'}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-8 text-center opacity-40 text-xs italic">
                No products found matching "{search}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
