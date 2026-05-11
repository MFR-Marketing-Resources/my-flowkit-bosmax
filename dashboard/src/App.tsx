import { BrowserRouter, NavLink, Routes, Route, useLocation } from 'react-router-dom'
import { 
  LayoutDashboard, FolderOpen, ScrollText, Film, Sparkles, PackageSearch, 
  Video, Layers, Image as ImageIcon, Settings as SettingsIcon, Activity,
  Briefcase
} from 'lucide-react'
import { WebSocketProvider, useWebSocketContext } from './contexts/WebSocketContext'
import DashboardPage from './pages/DashboardPage'
import ProjectsPage from './pages/ProjectsPage'
import LogsPage from './pages/LogsPage'
import GalleryPage from './pages/GalleryPage'
import OperatorPage from './pages/OperatorPage'
import ProductsSalesAnalyzerPage from './pages/ProductsSalesAnalyzerPage'
import BatchesPage from './pages/BatchesPage'
import SettingsPage from './pages/SettingsPage'

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
  const { isConnected } = useWebSocketContext()

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 text-slate-200">
      {/* Left sidebar */}
      <aside className="w-56 flex-shrink-0 flex flex-col border-r border-slate-800 bg-slate-900/50 backdrop-blur-xl">
        <div className="px-6 py-6 flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20">
            B
          </div>
          <span className="font-bold tracking-tight text-white">BOSMAX <span className="text-blue-500">V4</span></span>
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
                    to={to}
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
      <div className="flex flex-col flex-1 overflow-hidden bg-slate-950">
        {/* Top header */}
        <header className="flex items-center justify-between px-8 py-4 border-b border-slate-800 flex-shrink-0 bg-slate-950/50 backdrop-blur-md">
          <h1 className="text-sm font-semibold tracking-wide text-slate-100">
            <PageTitle />
          </h1>
          <div className="flex items-center gap-4">
            {/* User profile or other top actions can go here */}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Routes>
            {/* Modular Workspace Routes */}
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
