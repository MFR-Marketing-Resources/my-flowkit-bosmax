import { useState } from 'react'
import type { Scene } from '../../types'
import VideoPlayer from './VideoPlayer'

const PAGE_SIZE_SCENES = 12

interface VideoGalleryProps {
  scenes: Scene[]
  onDeleteScene?: (id: string) => void
}

export default function VideoGallery({ scenes, onDeleteScene }: VideoGalleryProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const videoscenes = scenes.filter(s => s.vertical_video_url)

  const totalPages = Math.ceil(videoscenes.length / PAGE_SIZE_SCENES)
  const safePage = Math.min(Math.max(1, currentPage), totalPages || 1)
  const paginated = videoscenes.slice((safePage - 1) * PAGE_SIZE_SCENES, safePage * PAGE_SIZE_SCENES)

  if (videoscenes.length === 0) {
    return (
      <div className="flex items-center justify-center py-16" style={{ color: 'var(--muted)' }}>
        No completed videos yet.
      </div>
    )
  }

  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {paginated.map((scene, idx) => {
          const globalIdx = (safePage - 1) * PAGE_SIZE_SCENES + idx
          return (
            <div
              key={scene.id}
              className="relative rounded-lg overflow-hidden group/scene"
              style={{ border: '1px solid var(--border)', background: 'var(--card)' }}
            >
              <div
                className="cursor-pointer transition-transform hover:scale-105"
                onClick={() => setActiveIndex(globalIdx)}
              >
                {/* Thumbnail */}
                <div className="relative" style={{ aspectRatio: '9/16' }}>
                  {scene.vertical_image_url ? (
                    <img
                      src={scene.vertical_image_url}
                      alt={`Scene ${scene.display_order + 1}`}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center" style={{ background: 'var(--surface)', color: 'var(--muted)' }}>
                      No image
                    </div>
                  )}

                  {/* Overlay */}
                  <div className="absolute inset-0 flex flex-col justify-between p-2" style={{ background: 'linear-gradient(to bottom, rgba(0,0,0,0.4) 0%, transparent 30%, transparent 70%, rgba(0,0,0,0.6) 100%)' }}>
                    <div className="flex items-start justify-between">
                      <span className="text-xs font-bold px-1.5 py-0.5 rounded" style={{ background: 'rgba(0,0,0,0.6)', color: 'var(--text)' }}>
                        #{scene.display_order + 1}
                      </span>
                      <div className="flex gap-1">
                        {scene.vertical_video_url && (
                          <span title="Video ready" className="text-xs px-1 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.8)', color: '#fff' }}>
                            ✓
                          </span>
                        )}
                        {scene.vertical_upscale_url && (
                          <span title="Upscaled" className="text-xs px-1 py-0.5 rounded" style={{ background: 'rgba(245,158,11,0.8)', color: '#fff' }}>
                            ★
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-xs truncate" style={{ color: 'var(--text)' }}>
                      {scene.prompt?.slice(0, 60) ?? ''}
                    </div>
                  </div>
                </div>
              </div>

              {/* Delete button — shown on hover */}
              {onDeleteScene && (
                <button
                  type="button"
                  onClick={e => { e.stopPropagation(); setConfirmDelete(scene.id) }}
                  className="absolute top-2 right-2 opacity-0 group-hover/scene:opacity-100 transition-opacity p-1 rounded"
                  style={{ background: 'rgba(239,68,68,0.85)', color: '#fff' }}
                  title="Delete scene"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 mt-4">
          <button
            type="button"
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={safePage === 1}
            className="px-3 py-1 rounded text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
          >
            Prev
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map(pg => (
            <button
              key={pg}
              type="button"
              onClick={() => setCurrentPage(pg)}
              className="w-7 h-7 rounded text-xs"
              style={{
                background: safePage === pg ? 'var(--accent, #6366f1)' : 'var(--card)',
                color: safePage === pg ? '#fff' : 'var(--text)',
                border: '1px solid var(--border)',
              }}
            >
              {pg}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
            className="px-3 py-1 rounded text-xs disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
          >
            Next
          </button>
        </div>
      )}

      {/* Scene delete confirm modal */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.7)' }}>
          <div className="rounded-xl p-6 w-80 flex flex-col gap-4" style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
            <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Delete this scene?</p>
            <p className="text-xs" style={{ color: 'var(--muted)' }}>This will permanently remove the scene and its assets.</p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setConfirmDelete(null)}
                className="px-3 py-1.5 rounded text-xs"
                style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => { onDeleteScene!(confirmDelete); setConfirmDelete(null) }}
                className="px-3 py-1.5 rounded text-xs font-semibold"
                style={{ background: '#ef4444', color: '#fff' }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {activeIndex !== null && (
        <VideoPlayer
          scenes={videoscenes}
          initialIndex={activeIndex}
          onClose={() => setActiveIndex(null)}
        />
      )}
    </>
  )
}
