import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Routes, Route, useLocation } from 'react-router-dom'
import { 
  LayoutDashboard, FolderOpen, ScrollText, Film, Sparkles, PackageSearch, 
  Video, Layers, Image as ImageIcon, Settings as SettingsIcon, Activity,
  Briefcase, Menu, X, Siren
} from 'lucide-react'
import { fetchAPI } from './api/client'
import { WebSocketProvider, useWebSocketContext } from './contexts/WebSocketContext'
import DashboardPage from './pages/DashboardPage'
import ProjectsPage from './pages/ProjectsPage'
import LogsPage from './pages/LogsPage'
import GalleryPage from './pages/GalleryPage'
import OperatorPage from './pages/OperatorPage'
import ProductsSalesAnalyzerPage from './pages/ProductsSalesAnalyzerPage'
import BatchesPage from './pages/BatchesPage'
import SettingsPage from './pages/SettingsPage'
import TroubleshootPage from './pages/TroubleshootPage'
import type { TelemetrySummary } from './types'

const NAV_GROUPS = [
  {
    label: 'WORKSPACE',
    items: [
      { to: '/operator/t2v', icon: Video, label: 'Text to Video' },
      { to: '/operator/f2v', icon: Sparkles, label: 'Frames (F2V)' },
      { to: '/operator/i2v', icon: Layers, label: 'Ingredients' },
      { to: '/operator/img', icon: ImageIcon, label: 'Image Gen' },
      { to: '/batches', icon: Briefcase, label: 'Batch Manager' },
    ]
  },
  {
    label: 'ASSETS',
    items: [
      { to: '/products', icon: PackageSearch, label: 'Products' },
      { to: '/projects', icon: FolderOpen, label: 'Projects' },
      { to: '/gallery', icon: Film, label: 'Gallery' },
    ]
  },
  {
    label: 'SYSTEM',
    items: [
      { to: '/settings', icon: SettingsIcon, label: 'Settings' },
      { to: '/health', icon: Activity, label: 'Health' },
      { to: '/troubleshoot', icon: Siren, label: 'Troubleshoot' },
      { to: '/logs', icon: ScrollText, label: 'Logs' },
      { to: '/', icon: LayoutDashboard, label: 'Overview', exact: true },
    ]
  }
]

function PageTitle() {
  const loc = useLocation()
  let label = 'Dashboard'
  for (const group of NAV_GROUPS) {
    const match = group.items.find(n => n.exact ? loc.pathname === n.to : loc.pathname.startsWith(n.to))
    if (match) {
      label = match.label
      break
    }
  }
  return <span>{label}</span>
}

function Layout() {
  const location = useLocation()
  const { isConnected } = useWebSocketContext()
  const isPortalMode = new URLSearchParams(location.search).get('portal') === 'side'
  const [isCompactNav, setIsCompactNav] = useState(() => isPortalMode || window.innerWidth < 1180)
  const [navOpen, setNavOpen] = useState(() => !isPortalMode && window.innerWidth >= 1180)
  const [portalSummary, setPortalSummary] = useState<TelemetrySummary | null>(null)

  const withPortalQuery = (path: string) => {
    if (!isPortalMode) return path
    return `${path}${path.includes('?') ? '&' : '?'}portal=side`
  }

  useEffect(() => {
    const syncViewportMode = () => {
      const compact = isPortalMode || window.innerWidth < 1180
      setIsCompactNav(compact)

      if (!compact) {
        setNavOpen(true)
        return
      }

      if (isPortalMode) {
        setNavOpen(false)
        return
      }

      setNavOpen(current => current && window.innerWidth > 720)
    }

    syncViewportMode()
    window.addEventListener('resize', syncViewportMode)
    return () => window.removeEventListener('resize', syncViewportMode)
  }, [isPortalMode])

  useEffect(() => {
    if (isCompactNav) {
      setNavOpen(false)
    }
  }, [isCompactNav, location.pathname])

  useEffect(() => {
    if (!isPortalMode) {
      setPortalSummary(null)
      return
    }

    const loadSummary = () => {
      fetchAPI<TelemetrySummary>('/api/telemetry/summary')
        .then(setPortalSummary)
        .catch(() => {})
    }

    loadSummary()
    const timer = window.setInterval(loadSummary, 4000)
    return () => window.clearInterval(timer)
  }, [isPortalMode])

  const portalQuickLinks = [
    { to: '/', label: 'Ops' },
    { to: '/operator/t2v', label: 'T2V' },
    { to: '/operator/f2v', label: 'F2V' },
    { to: '/operator/i2v', label: 'I2V' },
    { to: '/operator/img', label: 'IMG' },
    { to: '/troubleshoot', label: 'Issues' },
  ]

  const portalLiveLabel = portalSummary
    ? `${portalSummary.processing + portalSummary.flow_running} live • ${portalSummary.queued + portalSummary.waiting_flow} waiting • ${portalSummary.failed} failed`
    : 'Loading live system state'

  return (
    <div className="relative flex h-screen overflow-hidden bg-slate-950 text-slate-200">
      {isCompactNav && navOpen && (
        <button
          type="button"
          aria-label="Close navigation overlay"
          className="absolute inset-0 z-30 bg-slate-950/72 backdrop-blur-[2px]"
          onClick={() => setNavOpen(false)}
        />
      )}

      {/* Left sidebar */}
      <aside className={`${isCompactNav ? 'absolute inset-y-0 left-0 z-40 w-64 max-w-[84vw] shadow-2xl shadow-slate-950/50 transition-transform duration-200' : 'w-56 flex-shrink-0'} ${isCompactNav && !navOpen ? '-translate-x-full' : 'translate-x-0'} flex flex-col border-r border-slate-800 bg-slate-900/92 backdrop-blur-xl`}>
        <div className="flex items-center justify-between px-5 py-5 md:px-6 md:py-6">
          <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20">
            B
          </div>
          <span className="font-bold tracking-tight text-white">BOSMAX <span className="text-blue-500">V4</span></span>
          </div>
          {isCompactNav && (
            <button
              type="button"
              aria-label="Close navigation"
              onClick={() => setNavOpen(false)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-700 bg-slate-950/60 text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
            >
              <X size={16} />
            </button>
          )}
        </div>
        
        <nav className="flex-1 overflow-y-auto px-3 space-y-6 pb-6">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="px-3 mb-2 text-[10px] font-bold tracking-widest text-slate-500 uppercase">
                {group.label}
              </div>
              <div className="space-y-1">
                {group.items.map(({ to, icon: Icon, label, exact }) => (
                  <NavLink
                    key={to}
                    to={withPortalQuery(to)}
                    end={exact}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all duration-200 group ${
                        isActive
                          ? 'bg-blue-600/10 text-blue-400 font-medium'
                          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                      }`
                    }
                  >
                    <Icon size={14} className="group-hover:scale-110 transition-transform duration-200" />
                    {label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="p-4 border-t border-slate-800">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-slate-800/30 text-[10px]">
             <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
             <span className="text-slate-400 font-medium uppercase tracking-wider">
               {isConnected ? 'Agent Online' : 'Agent Offline'}
             </span>
          </div>
        </div>
      </aside>

      {/* Main area */}
      <div className={`flex flex-col flex-1 overflow-hidden bg-slate-950 ${isPortalMode ? 'relative' : ''}`}>
        {/* Top header */}
        <header className={`border-b border-slate-800 bg-slate-950/50 px-4 py-3 backdrop-blur-md flex-shrink-0 transition-all duration-300 ${isPortalMode ? 'sticky top-0 z-20' : 'md:px-8 md:py-4'}`}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              {isCompactNav && (
                <button
                  type="button"
                  aria-label="Open navigation"
                  onClick={() => setNavOpen(true)}
                  className="inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-slate-700 bg-slate-900/80 text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
                >
                  <Menu size={16} />
                </button>
              )}
              <h1 className={`truncate font-semibold tracking-wide text-slate-100 ${isPortalMode ? 'text-xs uppercase tracking-[0.18em]' : 'text-sm md:text-base'}`}>
                <PageTitle />
              </h1>
            </div>
            <div className="flex items-center gap-3">
              {isPortalMode && (
                <div className="hidden rounded-full border border-blue-500/20 bg-blue-500/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-200 md:inline-flex">
                  {portalLiveLabel}
                </div>
              )}
              {isCompactNav && (
                <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${isConnected ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' : 'border-red-500/30 bg-red-500/10 text-red-200'}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-red-400'}`} />
                  {isConnected ? 'Agent Online' : 'Agent Offline'}
                </div>
              )}
            </div>
          </div>

          {isPortalMode && (
            <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
              {portalQuickLinks.map(link => (
                <NavLink
                  key={link.to}
                  to={withPortalQuery(link.to)}
                  end={link.to === '/'}
                  className={({ isActive }) => `inline-flex whitespace-nowrap rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] transition-all duration-200 ${isActive ? 'border-blue-400/60 bg-blue-500/15 text-blue-200' : 'border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-500 hover:text-slate-200'}`}
                >
                  {link.label}
                </NavLink>
              ))}
              <div className="rounded-full border border-slate-700 bg-slate-950 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300 md:hidden">
                {portalLiveLabel}
              </div>
            </div>
          )}
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Routes>
            {/* Modular Workspace Routes */}
            <Route path="/operator" element={<Navigate to={withPortalQuery('/operator/f2v')} replace />} />
            <Route path="/operator/t2v" element={<OperatorPage mode="T2V" />} />
            <Route path="/operator/f2v" element={<OperatorPage mode="F2V" />} />
            <Route path="/operator/i2v" element={<OperatorPage mode="I2V" />} />
            <Route path="/operator/img" element={<OperatorPage mode="IMG" />} />
            
            <Route path="/batches" element={<BatchesPage />} />
            <Route path="/products" element={<ProductsSalesAnalyzerPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:id" element={<ProjectsPage />} />
            <Route path="/gallery" element={<GalleryPage />} />
            <Route path="/logs" element={<LogsPage />} />
            
            {/* System Routes */}
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/health" element={<div className="p-8 text-slate-400">Health Diagnostics Dashboard</div>} />
            <Route path="/troubleshoot" element={<TroubleshootPage />} />
            
            {/* Default Dashboard */}
            <Route path="/" element={<DashboardPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <WebSocketProvider>
        <Layout />
      </WebSocketProvider>
    </BrowserRouter>
  )
}
