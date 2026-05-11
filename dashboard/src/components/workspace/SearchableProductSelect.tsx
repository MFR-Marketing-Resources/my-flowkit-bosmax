import { useState, useRef, useEffect } from 'react'
import { Search, ChevronDown, Check } from 'lucide-react'
import type { Product } from '../../types'

interface SearchableProductSelectProps {
  products: Product[]
  selectedProduct: Product | null
  onSelect: (product: Product | null) => void
}

export default function SearchableProductSelect({ products, selectedProduct, onSelect }: SearchableProductSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  const filtered = products.filter(p => 
    p.raw_product_title.toLowerCase().includes(search.toLowerCase())
  )

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="relative" ref={containerRef}>
      {/* Trigger Button */}
      <div 
        onClick={() => setIsOpen(!isOpen)}
        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 flex items-center justify-between cursor-pointer hover:border-blue-500/50 transition-all group"
      >
        <div className="flex-1 truncate">
          {selectedProduct ? (
            <span className="text-sm font-bold text-slate-200">{selectedProduct.raw_product_title}</span>
          ) : (
            <span className="text-sm text-slate-500">Search and select product...</span>
          )}
        </div>
        <ChevronDown size={18} className={`text-slate-500 group-hover:text-blue-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </div>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute z-50 w-full mt-2 bg-slate-900 border border-slate-800 rounded-xl shadow-2xl shadow-black/50 overflow-hidden backdrop-blur-xl">
          {/* Search Input */}
          <div className="p-3 border-bottom border-slate-800 bg-slate-950/50 flex items-center gap-2">
            <Search size={14} className="text-slate-500" />
            <input 
              autoFocus
              type="text" 
              className="bg-transparent border-none outline-none text-xs text-slate-300 w-full"
              placeholder="Search by name..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              onClick={e => e.stopPropagation()}
            />
          </div>

          {/* List */}
          <div className="max-h-64 overflow-y-auto py-2">
            {filtered.length > 0 ? (
              filtered.map(p => (
                <div 
                  key={p.id}
                  onClick={() => {
                    onSelect(p)
                    setIsOpen(false)
                    setSearch('')
                  }}
                  className={`px-4 py-3 text-[11px] cursor-pointer flex items-center justify-between transition-colors ${selectedProduct?.id === p.id ? 'bg-blue-600/20 text-blue-400' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}
                >
                  <span className="truncate pr-4">{p.raw_product_title}</span>
                  {selectedProduct?.id === p.id && <Check size={14} />}
                </div>
              ))
            ) : (
              <div className="px-4 py-6 text-center text-xs text-slate-600 italic">
                No products match your search.
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-2 border-t border-slate-800 bg-slate-950/20 text-right">
             <span className="text-[9px] text-slate-600 uppercase tracking-widest font-bold pr-2">{filtered.length} visible</span>
          </div>
        </div>
      )}
    </div>
  )
}
