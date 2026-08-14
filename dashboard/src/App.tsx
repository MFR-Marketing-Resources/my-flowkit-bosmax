import {
	Activity,
	Bot,
	Briefcase,
	ChevronDown,
	Film,
	FolderOpen,
	Gauge,
	Image as ImageIcon,
	Layers,
	LayoutDashboard,
	Menu,
	PackageSearch,
	PenLine,
	ScrollText,
	Send,
	Settings as SettingsIcon,
	Siren,
	Sparkles,
	Tags,
	Users,
	Video,
	X,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
	BrowserRouter,
	Navigate,
	NavLink,
	Route,
	Routes,
	useLocation,
} from "react-router-dom";
import { fetchAPI } from "./api/client";
import {
	useWebSocketContext,
	WebSocketProvider,
} from "./contexts/WebSocketContext";
import {
	DEACTIVATED_SURFACE_REDIRECTS,
	isDeactivatedSurfacePath,
} from "./deactivatedSurfaces";
import ApprovedPackagesPage from "./pages/ApprovedPackagesPage";
import AssetRegistryPage from "./pages/AssetRegistryPage";
import AvatarRegistryPage from "./pages/AvatarRegistryPage";
import CreativeLibraryPage from "./pages/CreativeLibraryPage";
import CreativeProductionStudioPage from "./pages/CreativeProductionStudioPage";
import CreativeLibraryWorkspacePage from "./pages/CreativeLibraryWorkspacePage";
import CockpitSettingsPage from "./pages/CockpitSettingsPage";
import CopyIntelligencePage from "./pages/CopyIntelligencePage";
import CopySetRegistryPage from "./pages/CopySetRegistryPage";
import DashboardPage from "./pages/DashboardPage";
import ReportingExecutivePage from "./pages/ReportingExecutivePage";
import ReportingOperationsPage from "./pages/ReportingOperationsPage";
import OperatorPage from "./pages/OperatorPage";
import FacelessVideoPage from "./pages/FacelessVideoPage";
import MontagePage from "./pages/MontagePage";
import PosterBuilderPage from "./pages/PosterBuilderPage";
import PostizPublishPage from "./pages/PostizPublishPage";
import ResultsHubPage from "./pages/ResultsHubPage";
import ProductionQueuePage from "./pages/ProductionQueuePage";
import RpaQueueControlPage from "./pages/RpaQueueControlPage";
import ProductRegistrationPage from "./pages/ProductRegistrationPage";
import ProductTypeRegistryPage from "./pages/ProductTypeRegistryPage";
import ProductsSalesAnalyzerPage from "./pages/ProductsSalesAnalyzerPage";
import ProductDetailPage from "./pages/ProductDetailPage";
import PromptPreviewPage from "./pages/PromptPreviewPage";
import SettingsPage from "./pages/SettingsPage";
import TroubleshootPage from "./pages/TroubleshootPage";
import WorkspaceGenerationPackagesPage from "./pages/WorkspaceGenerationPackagesPage";
import WorkspaceJobsPage from "./pages/WorkspaceJobsPage";
import LibraryPage from "./pages/LibraryPage";
import type { TelemetrySummary } from "./types";

const ALL_NAV_GROUPS = [
	{
		label: "VIDEO PRODUCTION",
		items: [
			{ to: "/operator/t2v", icon: Video, label: "Text to Video" },
			{ to: "/operator/hybrid", icon: Sparkles, label: "Hybrid" },
			{ to: "/operator/f2v", icon: Sparkles, label: "Frames" },
			{ to: "/operator/i2v", icon: Layers, label: "Ingredients" },
			{ to: "/operator/faceless", icon: Film, label: "Faceless Video" },
			{ to: "/operator/montage", icon: Layers, label: "Montage" },
			{ to: "/production-studio", icon: Video, label: "Production Studio" },
		],
	},
	{
		label: "IMAGE PRODUCTION",
		items: [
			{ to: "/operator/img", icon: ImageIcon, label: "Image Gen" },
			{ to: "/assets/img-cockpit", icon: Sparkles, label: "IMG Cockpit" },
			{ to: "/assets/img-fastlane", icon: Sparkles, label: "IMG Fastlane" },
			{
				to: "/creative/poster-builder",
				icon: ImageIcon,
				label: "Poster Builder",
			},
		],
	},
	{
		label: "LIBRARY",
		items: [
			{ to: "/library/videos", icon: Video, label: "Video Library" },
			{ to: "/library/images", icon: ImageIcon, label: "Image Library" },
			{ to: "/results", icon: FolderOpen, label: "Results" },
		],
	},
	{
		label: "PUBLISH & JOBS",
		items: [
			{ to: "/postiz", icon: Send, label: "Postiz Publish" },
			{ to: "/workspace/jobs", icon: Activity, label: "Workspace Jobs" },
		],
	},
	{
		label: "PRODUCTS",
		items: [
			{ to: "/products", icon: PackageSearch, label: "Product Catalog" },
			{
				to: "/product-registration",
				icon: ScrollText,
				label: "Smart Registration",
			},
		],
	},
	{
		label: "CREATIVE ASSETS",
		items: [
			{
				to: "/assets/creative-library",
				icon: Briefcase,
				label: "Creative Library",
			},
			{ to: "/assets/avatar-registry", icon: Users, label: "Avatar Registry" },
		],
	},
	{
		label: "REPORTING",
		items: [
			{ to: "/reporting/executive", icon: Gauge, label: "Executive" },
			{ to: "/reporting/operations", icon: Siren, label: "Operations" },
		],
	},
	{
		label: "ADVANCED",
		items: [
			{
				to: "/workspace/generation-packages",
				icon: PackageSearch,
				label: "Prompt Handoff Bank",
			},
			{
				to: "/approved-packages",
				icon: PackageSearch,
				label: "Approved Packages",
			},
			{ to: "/production-queue", icon: Film, label: "Production Queue" },
			{ to: "/rpa-queue-control", icon: Bot, label: "RPA Queue Control" },
			{
				to: "/assets/creative-library/workspace",
				icon: Sparkles,
				label: "Asset Workspace",
			},
			{
				to: "/assets/scene-context-registry",
				icon: Sparkles,
				label: "Scene Registry",
			},
			{ to: "/asset-registry", icon: Layers, label: "Asset Registry" },
			{
				to: "/assets/product-type-registry",
				icon: Tags,
				label: "Product Type Registry",
			},
			{ to: "/creative/copy-registry", icon: PenLine, label: "Copy Registry" },
			{
				to: "/creative/copy-intelligence",
				icon: Users,
				label: "Copy Intelligence",
			},
			{
				to: "/creative/cockpit-settings",
				icon: Gauge,
				label: "Cockpit Settings",
			},
			{ to: "/prompt-preview", icon: Sparkles, label: "Prompt Preview" },
			{ to: "/troubleshoot", icon: Siren, label: "Troubleshoot" },
		],
	},
	{
		label: "SYSTEM",
		items: [
			{ to: "/home", icon: LayoutDashboard, label: "Overview", exact: true },
			{ to: "/settings", icon: SettingsIcon, label: "Settings" },
		],
	},
];

const NAV_GROUPS = ALL_NAV_GROUPS.map((group) => ({
	...group,
	items: group.items.filter((item) => !isDeactivatedSurfacePath(item.to)),
}));

function PageTitle() {
	const loc = useLocation();
	let label = "Dashboard";
	for (const group of NAV_GROUPS) {
		const match = group.items.find((n) =>
			n.exact ? loc.pathname === n.to : loc.pathname.startsWith(n.to),
		);
		if (match) {
			label = match.label;
			break;
		}
	}
	return <span>{label}</span>;
}

function EmbeddedRouteReporter() {
	const location = useLocation();
	const isPortalMode =
		new URLSearchParams(location.search).get("portal") === "side";

	useEffect(() => {
		if (!isPortalMode || typeof window === "undefined") {
			return;
		}
		if (
			window.parent === window ||
			typeof window.parent?.postMessage !== "function"
		) {
			return;
		}

		window.parent.postMessage(
			{
				type: "FLOWKIT_DASHBOARD_ROUTE_SYNC",
				label: document.title || "Flow Kit",
				url: `${window.location.origin}${location.pathname}${location.search}`,
				pathname: location.pathname,
				search: location.search,
			},
			window.location.origin,
		);
	}, [isPortalMode, location.pathname, location.search]);

	return null;
}

function Layout() {
	const location = useLocation();
	const { isConnected } = useWebSocketContext();
	const isPortalMode =
		new URLSearchParams(location.search).get("portal") === "side";
	const [isCompactNav, setIsCompactNav] = useState(
		() => isPortalMode || window.innerWidth < 1180,
	);
	const [navOpen, setNavOpen] = useState(
		() => !isPortalMode && window.innerWidth >= 1180,
	);
	const [portalSummary, setPortalSummary] = useState<TelemetrySummary | null>(
		null,
	);

	const activeGroupLabel = NAV_GROUPS.find((navGroup) =>
		navGroup.items.some((item) =>
			item.exact
				? location.pathname === item.to
				: location.pathname.startsWith(item.to),
		),
	)?.label;

	const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => {
		try {
			const saved = window.localStorage.getItem("bosmax:navCollapsed");
			if (saved) return new Set(JSON.parse(saved) as string[]);
		} catch {
			/* ignore malformed persisted state */
		}
		// First visit: keep only the active group open so the sidebar stays compact.
		return new Set(
			NAV_GROUPS.map((navGroup) => navGroup.label).filter(
				(label) => label !== activeGroupLabel,
			),
		);
	});

	const toggleGroup = (label: string) => {
		setCollapsedGroups((prev) => {
			const next = new Set(prev);
			if (next.has(label)) next.delete(label);
			else next.add(label);
			try {
				window.localStorage.setItem(
					"bosmax:navCollapsed",
					JSON.stringify([...next]),
				);
			} catch {
				/* ignore persistence failure */
			}
			return next;
		});
	};

	const withPortalQuery = (path: string) => {
		if (!isPortalMode) return path;
		return `${path}${path.includes("?") ? "&" : "?"}portal=side`;
	};

	useEffect(() => {
		const syncViewportMode = () => {
			const compact = isPortalMode || window.innerWidth < 1180;
			setIsCompactNav(compact);

			if (!compact) {
				setNavOpen(true);
				return;
			}

			if (isPortalMode) {
				setNavOpen(false);
				return;
			}

			setNavOpen((current) => current && window.innerWidth > 720);
		};

		syncViewportMode();
		window.addEventListener("resize", syncViewportMode);
		return () => window.removeEventListener("resize", syncViewportMode);
	}, [isPortalMode]);

	useEffect(() => {
		if (isCompactNav) {
			setNavOpen(false);
		}
	}, [isCompactNav]);

	useEffect(() => {
		if (!isPortalMode) {
			setPortalSummary(null);
			return;
		}

		let inFlight = false;
		const loadSummary = () => {
			if (document.hidden || inFlight) {
				return;
			}
			inFlight = true;
			void fetchAPI<TelemetrySummary>("/api/telemetry/summary")
				.then(setPortalSummary)
				.catch(() => {})
				.finally(() => {
					inFlight = false;
				});
		};
		const handleVisibilityChange = () => {
			if (!document.hidden) {
				loadSummary();
			}
		};

		loadSummary();
		document.addEventListener("visibilitychange", handleVisibilityChange);
		const timer = window.setInterval(loadSummary, 15000);
		return () => {
			document.removeEventListener("visibilitychange", handleVisibilityChange);
			window.clearInterval(timer);
		};
	}, [isPortalMode]);

	const portalQuickLinks = [
		{ to: "/home", label: "Ops" },
		{ to: "/operator/t2v", label: "T2V" },
		{ to: "/operator/hybrid", label: "HYBRID" },
		{ to: "/operator/f2v", label: "FRAMES" },
		{ to: "/library/videos", label: "VIDEOS" },
		{ to: "/library/images", label: "IMAGES" },
		{ to: "/operator/i2v", label: "I2V" },
		{ to: "/operator/img", label: "IMG" },
		{ to: "/operator/faceless", label: "FACELESS" },
		{ to: "/operator/montage", label: "MONTAGE" },
		{ to: "/assets/creative-library", label: "Creative" },
		{ to: "/workspace/generation-packages", label: "Bank" },
		{ to: "/workspace/jobs", label: "Jobs" },
		{ to: "/troubleshoot", label: "Issues" },
	].filter((link) => !isDeactivatedSurfacePath(link.to));

	const portalLiveLabel = portalSummary
		? `${portalSummary.processing + portalSummary.flow_running} live • ${portalSummary.queued + portalSummary.waiting_flow} waiting • ${portalSummary.failed} failed`
		: "Loading live system state";

	return (
		<div className="relative flex h-screen overflow-hidden bg-slate-950 text-slate-200">
			<EmbeddedRouteReporter />
			{isCompactNav && navOpen && (
				<button
					type="button"
					aria-label="Close navigation overlay"
					className="absolute inset-0 z-30 bg-slate-950/72 backdrop-blur-[2px]"
					onClick={() => setNavOpen(false)}
				/>
			)}

			{/* Left sidebar */}
			<aside
				className={`${isCompactNav ? "absolute inset-y-0 left-0 z-40 w-64 max-w-[84vw] shadow-2xl shadow-slate-950/50 transition-transform duration-200" : "w-56 flex-shrink-0"} ${isCompactNav && !navOpen ? "-translate-x-full" : "translate-x-0"} flex flex-col border-r border-slate-800 bg-slate-900/92 backdrop-blur-xl`}
			>
				<div className="flex items-center justify-between px-5 py-5 md:px-6 md:py-6">
					<div className="flex items-center gap-2">
						<div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20">
							B
						</div>
						<span className="font-bold tracking-tight text-white">
							BOSMAX <span className="text-blue-500">V4</span>
						</span>
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
					{NAV_GROUPS.map((group) => {
						const collapsed = collapsedGroups.has(group.label);
						return (
							<div key={group.label}>
								<button
									type="button"
									onClick={() => toggleGroup(group.label)}
									className="w-full flex items-center justify-between px-3 mb-2 text-[10px] font-bold tracking-widest text-slate-500 uppercase hover:text-slate-300 transition-colors"
								>
									{group.label}
									<ChevronDown
										size={12}
										className={`transition-transform duration-200 ${collapsed ? "-rotate-90" : ""}`}
									/>
								</button>
								{!collapsed && (
									<div className="space-y-1">
										{group.items.map(({ to, icon: Icon, label, exact }) => (
											<NavLink
												key={to}
												to={withPortalQuery(to)}
												end={exact}
												className={({ isActive }) =>
													`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all duration-200 group ${
														isActive
															? "bg-blue-600/10 text-blue-400 font-medium"
															: "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
													}`
												}
											>
												<Icon
													size={14}
													className="group-hover:scale-110 transition-transform duration-200"
												/>
												{label}
											</NavLink>
										))}
									</div>
								)}
							</div>
						);
					})}
				</nav>

				<div className="p-4 border-t border-slate-800">
					<div className="flex items-center gap-2 px-2 py-1.5 rounded bg-slate-800/30 text-[10px]">
						<div
							className={`w-1.5 h-1.5 rounded-full ${isConnected ? "bg-green-500 animate-pulse" : "bg-red-500"}`}
						/>
						<span className="text-slate-400 font-medium uppercase tracking-wider">
							{isConnected ? "Agent Online" : "Agent Offline"}
						</span>
					</div>
				</div>
			</aside>

			{/* Main area */}
			<div
				className={`flex min-w-0 flex-col flex-1 overflow-hidden bg-slate-950 ${isPortalMode ? "relative" : ""}`}
			>
				{/* Top header */}
				<header
					className={`border-b border-slate-800 bg-slate-950/50 px-4 py-3 backdrop-blur-md flex-shrink-0 transition-all duration-300 ${isPortalMode ? "sticky top-0 z-20" : "md:px-8 md:py-4"}`}
				>
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
							<h1
								className={`truncate font-semibold tracking-wide text-slate-100 ${isPortalMode ? "text-xs uppercase tracking-[0.18em]" : "text-sm md:text-base"}`}
							>
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
								<div
									className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${isConnected ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-red-500/30 bg-red-500/10 text-red-200"}`}
								>
									<span
										className={`h-1.5 w-1.5 rounded-full ${isConnected ? "bg-emerald-400" : "bg-red-400"}`}
									/>
									{isConnected ? "Agent Online" : "Agent Offline"}
								</div>
							)}
						</div>
					</div>

					{isPortalMode && (
						<div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
							{portalQuickLinks.map((link) => (
								<NavLink
									key={link.to}
									to={withPortalQuery(link.to)}
									end={link.to === "/"}
									className={({ isActive }) =>
										`inline-flex whitespace-nowrap rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] transition-all duration-200 ${isActive ? "border-blue-400/60 bg-blue-500/15 text-blue-200" : "border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-500 hover:text-slate-200"}`
									}
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
				<main className="min-w-0 flex-1 overflow-auto">
					<Routes>
						{/* Modular Workspace Routes */}
						<Route
							path="/operator"
							element={
								<Navigate to={withPortalQuery("/operator/hybrid")} replace />
							}
						/>
						{Object.entries(DEACTIVATED_SURFACE_REDIRECTS).map(
							([path, redirectTo]) => (
								<Route
									key={path}
									path={path}
									element={
										<Navigate to={withPortalQuery(redirectTo)} replace />
									}
								/>
							),
						)}
						<Route
							path="/operator/hybrid"
							element={<OperatorPage mode="HYBRID" />}
						/>
						<Route
							path="/library/videos"
							element={<LibraryPage kind="video" />}
						/>
						<Route
							path="/library/images"
							element={<LibraryPage kind="image" />}
						/>
						<Route path="/results" element={<ResultsHubPage />} />
						<Route
							path="/reporting/executive"
							element={<ReportingExecutivePage />}
						/>
						<Route
							path="/reporting/operations"
							element={<ReportingOperationsPage />}
						/>
						<Route path="/operator/faceless" element={<FacelessVideoPage />} />
						<Route path="/operator/montage" element={<MontagePage />} />
						<Route path="/workspace/jobs" element={<WorkspaceJobsPage />} />
						<Route
							path="/workspace/generation-packages"
							element={<WorkspaceGenerationPackagesPage />}
						/>
						<Route
							path="/approved-packages"
							element={<ApprovedPackagesPage />}
						/>

						<Route
							path="/production-queue"
							element={<ProductionQueuePage />}
						/>
						<Route
							path="/production-studio"
							element={<CreativeProductionStudioPage />}
						/>
						<Route
							path="/rpa-queue-control"
							element={<RpaQueueControlPage />}
						/>
						<Route path="/postiz" element={<PostizPublishPage />} />
						<Route path="/asset-registry" element={<AssetRegistryPage />} />
						<Route
							path="/assets/creative-library/workspace"
							element={<CreativeLibraryWorkspacePage />}
						/>
						<Route
							path="/assets/avatar-registry"
							element={<AvatarRegistryPage />}
						/>
						<Route
							path="/assets/product-type-registry"
							element={<ProductTypeRegistryPage />}
						/>
						<Route
							path="/assets/creative-library"
							element={<CreativeLibraryPage />}
						/>
						<Route
							path="/product-registration"
							element={<ProductRegistrationPage />}
						/>
						<Route
							path="/creative/poster-builder"
							element={<PosterBuilderPage />}
						/>
						<Route
							path="/creative/cockpit-settings"
							element={<CockpitSettingsPage />}
						/>
						<Route
							path="/creative/copy-registry"
							element={<CopySetRegistryPage />}
						/>
						<Route
							path="/creative/copy-intelligence"
							element={<CopyIntelligencePage />}
						/>
						<Route path="/products" element={<ProductsSalesAnalyzerPage />} />
						<Route path="/product/:id" element={<ProductDetailPage />} />
						<Route path="/prompt-preview" element={<PromptPreviewPage />} />

						{/* System Routes */}
						<Route path="/settings" element={<SettingsPage />} />
						<Route path="/troubleshoot" element={<TroubleshootPage />} />

						{/* Default Dashboard */}
						<Route path="/" element={<Navigate to={withPortalQuery("/operator/hybrid")} replace />} />
						<Route path="/home" element={<DashboardPage />} />
					</Routes>
				</main>
			</div>
		</div>
	);
}

export default function App() {
	return (
		<BrowserRouter>
			<WebSocketProvider>
				<Layout />
			</WebSocketProvider>
		</BrowserRouter>
	);
}
