import { useState, useEffect } from 'react'
import { fetchAPI, deleteAPI } from '../api/client'
import type { Project, Video, Scene } from '../types'
import VideoGallery from '../components/gallery/VideoGallery'
import { ConfirmActionModal } from '../components/ui'

const PAGE_SIZE_VIDEOS = 20

export default function GalleryPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [videos, setVideos] = useState<Video[]>([])
  const [selectedVideo, setSelectedVideo] = useState<string>('')
  const [scenes, setScenes] = useState<Scene[]>([])
  const [loading, setLoading] = useState(false)
  const [currentPageVideos, setCurrentPageVideos] = useState(1)
  const [confirmDeleteVideo, setConfirmDeleteVideo] = useState(false)
  const [deletingVideo, setDeletingVideo] = useState(false)

  useEffect(() => {
    fetchAPI<Project[]>('/api/projects')
      .then(ps => {
        const active = ps.filter(p => p.status !== 'DELETED')
        setProjects(active)
        if (active.length > 0) setSelectedProject(active[0].id)
      })
      .catch(console.error)
  }, [])

  useEffect(() => {
    if (!selectedProject) return
    setVideos([])
    setSelectedVideo('')
    setScenes([])
    setCurrentPageVideos(1)
    fetchAPI<Video[]>(`/api/videos?project_id=${selectedProject}`)
      .then(vs => {
        setVideos(vs)
        if (vs.length > 0) setSelectedVideo(vs[0].id)
      })
      .catch(console.error)
  }, [selectedProject])

  useEffect(() => {
    if (!selectedVideo) return
    setLoading(true)
    fetchAPI<Scene[]>(`/api/scenes?video_id=${selectedVideo}`)
      .then(setScenes)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [selectedVideo])

  const totalPagesVideos = Math.ceil(videos.length / PAGE_SIZE_VIDEOS)
  const safePageVideos = Math.min(Math.max(1, currentPageVideos), totalPagesVideos || 1)
  const paginatedVideos = videos.slice((safePageVideos - 1) * PAGE_SIZE_VIDEOS, safePageVideos * PAGE_SIZE_VIDEOS)

  const handleDeleteVideo = async () => {
    if (!selectedVideo) return
    setDeletingVideo(true)
    try {
      await deleteAPI(`/api/videos/${selectedVideo}`)
      const updated = videos.filter(v => v.id !== selectedVideo)
      setVideos(updated)
      setScenes([])
      setSelectedVideo(updated.length > 0 ? updated[0].id : '')
    } catch (err) {
      console.error(err)
    } finally {
      setDeletingVideo(false)
      setConfirmDeleteVideo(false)
    }
  }

  const handleDeleteScene = async (sceneId: string) => {
    try {
      await deleteAPI(`/api/scenes/${sceneId}`)
      setScenes(prev => prev.filter(s => s.id !== sceneId))
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Filters */}
      <div className="flex gap-3 flex-wrap items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs" style={{ color: 'var(--muted)' }}>Project</label>
          <select
            value={selectedProject}
            onChange={e => setSelectedProject(e.target.value)}
            className="text-xs px-2 py-1.5 rounded outline-none"
            style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
          >
            {projects.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {videos.length > 0 && (
          <div className="flex flex-col gap-1">
            <label className="text-xs" style={{ color: 'var(--muted)' }}>Video</label>
            <div className="flex items-center gap-2">
              <select
                value={selectedVideo}
                onChange={e => { setSelectedVideo(e.target.value); setCurrentPageVideos(1) }}
                className="text-xs px-2 py-1.5 rounded outline-none"
                style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
              >
                {paginatedVideos.map(v => (
                  <option key={v.id} value={v.id}>{v.title}</option>
                ))}
              </select>

              {/* Video pagination controls */}
              {totalPagesVideos > 1 && (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setCurrentPageVideos(p => Math.max(1, p - 1))}
                    disabled={safePageVideos === 1}
                    className="px-2 py-1 rounded text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
                  >
                    ‹
                  </button>
                  <span className="text-xs" style={{ color: 'var(--muted)' }}>{safePageVideos}/{totalPagesVideos}</span>
                  <button
                    type="button"
                    onClick={() => setCurrentPageVideos(p => Math.min(totalPagesVideos, p + 1))}
                    disabled={safePageVideos === totalPagesVideos}
                    className="px-2 py-1 rounded text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
                  >
                    ›
                  </button>
                </div>
              )}

              {/* Delete video button */}
              {selectedVideo && (
                <button
                  type="button"
                  onClick={() => setConfirmDeleteVideo(true)}
                  className="flex items-center gap-1 px-2 py-1.5 rounded text-xs font-medium"
                  style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}
                  title="Delete this video"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  Delete Video
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-xs" style={{ color: 'var(--muted)' }}>Loading scenes...</div>
      ) : (
        <VideoGallery scenes={scenes} onDeleteScene={handleDeleteScene} />
      )}

      {/* Delete video confirm — shared standard ConfirmActionModal */}
      <ConfirmActionModal
        open={confirmDeleteVideo}
        title="Delete this video?"
        body="This will permanently delete the video and all its scenes. This cannot be undone."
        confirmLabel="Delete"
        tone="danger"
        busy={deletingVideo}
        onConfirm={handleDeleteVideo}
        onCancel={() => setConfirmDeleteVideo(false)}
      />
    </div>
  )
}
