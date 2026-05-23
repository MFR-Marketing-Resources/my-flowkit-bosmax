import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { fetchAPI, patchAPI, postAPI } from "../api/client";
import type { Project } from "../types";
import ProjectDetailPage from "./ProjectDetailPage";

type FilterTab = "ACTIVE" | "ARCHIVED" | "ALL";
type PageTab = "library" | "new";

interface Material {
	id: string;
	name: string;
}

function formatDate(iso: string) {
	return new Date(iso).toLocaleDateString("en-MY", {
		day: "2-digit",
		month: "short",
		year: "numeric",
	});
}

function StatusBadge({ status }: { status: string }) {
	const map: Record<string, string> = {
		ACTIVE: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
		ARCHIVED: "border-slate-600 bg-slate-800 text-slate-400",
		DELETED: "border-red-500/30 bg-red-500/10 text-red-300",
	};
	return (
		<span
			className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.14em] ${map[status] ?? "border-slate-700 bg-slate-900 text-slate-400"}`}
		>
			{status}
		</span>
	);
}

function TierBadge({ tier }: { tier: string | null }) {
	if (!tier) return null;
	const isTwo = tier.includes("TWO");
	return (
		<span
			className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.14em] ${isTwo ? "border-amber-500/30 bg-amber-500/10 text-amber-300" : "border-blue-500/30 bg-blue-500/10 text-blue-300"}`}
		>
			{isTwo ? "Tier 2" : "Tier 1"}
		</span>
	);
}

function ProjectCard({
	project,
	onClick,
	onArchive,
	onDelete,
	actionLoading,
}: {
	project: Project;
	onClick: () => void;
	onArchive: () => void;
	onDelete: () => void;
	actionLoading: boolean;
}) {
	const isArchived = project.status === "ARCHIVED";
	return (
		<div className="group flex flex-col rounded-2xl border border-slate-800 bg-slate-900/60 p-4 transition-colors hover:border-slate-700">
			{/* Clickable area */}
			<div
				role="button"
				tabIndex={0}
				className="flex-1 cursor-pointer"
				onClick={onClick}
				onKeyDown={(e) => e.key === "Enter" && onClick()}
			>
				<div className="mb-1 text-sm font-bold text-slate-100">{project.name}</div>
				{project.description && (
					<div className="mb-2 line-clamp-2 text-[11px] text-slate-400">
						{project.description}
					</div>
				)}
				<div className="flex flex-wrap items-center gap-1.5">
					<StatusBadge status={project.status} />
					<TierBadge tier={project.user_paygate_tier} />
					{project.material && (
						<span className="rounded-full border border-slate-700 bg-slate-800 px-2 py-0.5 text-[9px] uppercase tracking-[0.12em] text-slate-400">
							{project.material}
						</span>
					)}
				</div>
			</div>

			{/* Footer: date + actions */}
			<div className="mt-3 flex items-center justify-between border-t border-slate-800 pt-3">
				<span className="text-[10px] text-slate-500">{project.created_at ? formatDate(project.created_at) : "—"}</span>
				<div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
					<button
						type="button"
						disabled={actionLoading}
						onClick={(e) => { e.stopPropagation(); onArchive(); }}
						className={`rounded-lg border px-2 py-1 text-[10px] font-semibold transition-colors disabled:opacity-50 ${isArchived ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20" : "border-slate-700 bg-slate-800 text-slate-400 hover:text-amber-300"}`}
					>
						{actionLoading ? "..." : isArchived ? "Unarchive" : "Archive"}
					</button>
					<button
						type="button"
						disabled={actionLoading}
						onClick={(e) => { e.stopPropagation(); onDelete(); }}
						className="rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-400 transition-colors hover:bg-red-500/20 disabled:opacity-50"
					>
						Delete
					</button>
				</div>
			</div>
		</div>
	);
}

function NewProjectForm({
	onCreated,
}: {
	onCreated: (project: Project) => void;
}) {
	const [materials, setMaterials] = useState<Material[]>([]);
	const [form, setForm] = useState({
		name: "",
		description: "",
		story: "",
		material: "realistic",
		language: "en",
		user_paygate_tier: "PAYGATE_TIER_ONE",
	});
	const [submitting, setSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		fetchAPI<Material[]>("/api/materials")
			.then(setMaterials)
			.catch(() => {});
	}, []);

	async function handleSubmit(e: React.FormEvent) {
		e.preventDefault();
		if (!form.name.trim()) return;
		setSubmitting(true);
		setError(null);
		try {
			const created = await postAPI<Project>("/api/projects", form);
			onCreated(created);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to create project");
		} finally {
			setSubmitting(false);
		}
	}

	return (
		<form onSubmit={handleSubmit} className="flex flex-col gap-4">
			<div className="grid gap-4 md:grid-cols-2">
				{/* Name */}
				<div className="flex flex-col gap-1.5">
					<label className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
						Project Name <span className="text-red-400">*</span>
					</label>
					<input
						type="text"
						required
						value={form.name}
						onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
						placeholder="e.g. Skincare Campaign Q3"
						className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
					/>
				</div>

				{/* Material */}
				<div className="flex flex-col gap-1.5">
					<label className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
						Material (Style)
					</label>
					<select
						value={form.material}
						onChange={(e) => setForm((f) => ({ ...f, material: e.target.value }))}
						className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 focus:border-blue-500 focus:outline-none"
					>
						{materials.length > 0
							? materials.map((m) => (
									<option key={m.id} value={m.id}>
										{m.name}
									</option>
								))
							: (
									<>
										<option value="realistic">Realistic</option>
										<option value="3d_pixar">3D Pixar</option>
									</>
								)}
					</select>
				</div>

				{/* Language */}
				<div className="flex flex-col gap-1.5">
					<label className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
						Language
					</label>
					<select
						value={form.language}
						onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
						className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 focus:border-blue-500 focus:outline-none"
					>
						<option value="en">English</option>
						<option value="ms">Malay</option>
						<option value="zh">Chinese</option>
					</select>
				</div>

				{/* Tier */}
				<div className="flex flex-col gap-1.5">
					<label className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
						Paygate Tier
					</label>
					<select
						value={form.user_paygate_tier}
						onChange={(e) =>
							setForm((f) => ({ ...f, user_paygate_tier: e.target.value }))
						}
						className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 focus:border-blue-500 focus:outline-none"
					>
						<option value="PAYGATE_TIER_ONE">Tier 1</option>
						<option value="PAYGATE_TIER_TWO">Tier 2</option>
					</select>
				</div>
			</div>

			{/* Description */}
			<div className="flex flex-col gap-1.5">
				<label className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
					Description
				</label>
				<textarea
					value={form.description}
					onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
					placeholder="Short project description..."
					rows={2}
					className="resize-none rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
				/>
			</div>

			{/* Story */}
			<div className="flex flex-col gap-1.5">
				<label className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
					Story / Concept
				</label>
				<textarea
					value={form.story}
					onChange={(e) => setForm((f) => ({ ...f, story: e.target.value }))}
					placeholder="Optional narrative or creative brief..."
					rows={3}
					className="resize-none rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
				/>
			</div>

			{error && (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
					{error}
				</div>
			)}

			<div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[10px] text-amber-200">
				⚠ Creating a project requires the browser extension to be connected (Google Flow).
			</div>

			<button
				type="submit"
				disabled={submitting || !form.name.trim()}
				className="rounded-xl bg-blue-600 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
			>
				{submitting ? "Creating..." : "Create Project"}
			</button>
		</form>
	);
}

const PAGE_SIZE = 12;

export default function ProjectsPage() {
	const { id } = useParams<{ id?: string }>();
	const navigate = useNavigate();
	const [pageTab, setPageTab] = useState<PageTab>("library");
	const [filterTab, setFilterTab] = useState<FilterTab>("ACTIVE");
	const [projects, setProjects] = useState<Project[]>([]);
	const [loading, setLoading] = useState(true);
	const [search, setSearch] = useState("");
	const [currentPage, setCurrentPage] = useState(1);
	const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	function loadProjects() {
		setLoading(true);
		fetchAPI<Project[]>("/api/projects")
			.then(setProjects)
			.catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
			.finally(() => setLoading(false));
	}

	useEffect(() => { loadProjects(); }, []);

	async function handleArchiveToggle(project: Project) {
		const nextStatus = project.status === "ARCHIVED" ? "ACTIVE" : "ARCHIVED";
		setActionLoadingId(project.id);
		try {
			await patchAPI(`/api/projects/${project.id}`, { status: nextStatus });
			loadProjects();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to update status");
		} finally {
			setActionLoadingId(null);
		}
	}

	async function handleDelete(project: Project) {
		if (
			!window.confirm(
				`Delete project "${project.name}"?\n\nThis is permanent and cannot be undone.`,
			)
		)
			return;
		setActionLoadingId(project.id);
		try {
			await fetchAPI(`/api/projects/${project.id}`, { method: "DELETE" });
			loadProjects();
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to delete project");
		} finally {
			setActionLoadingId(null);
		}
	}

	// If there's a :id param, show detail page
	if (id) {
		return (
			<ProjectDetailPage
				projectId={id}
				onBack={() => navigate("/projects")}
				onRefreshList={loadProjects}
			/>
		);
	}

	const filtered = projects.filter((p) => {
		if (p.status === "DELETED") return false;
		if (filterTab !== "ALL" && p.status !== filterTab) return false;
		if (search.trim()) {
			const q = search.toLowerCase();
			return (
				p.name.toLowerCase().includes(q) ||
				(p.description ?? "").toLowerCase().includes(q)
			);
		}
		return true;
	});

	const counts: Record<FilterTab, number> = {
		ACTIVE: projects.filter((p) => p.status === "ACTIVE").length,
		ARCHIVED: projects.filter((p) => p.status === "ARCHIVED").length,
		ALL: projects.filter((p) => p.status !== "DELETED").length,
	};

	const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
	const safePage = Math.min(currentPage, totalPages);
	const paginated = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			{/* Header */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 flex items-center justify-between">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							Projects
						</div>
						<div className="mt-1 text-xs text-slate-400">
							{loading ? "Loading..." : `${counts.ACTIVE} active · ${counts.ARCHIVED} archived`}
						</div>
					</div>
				</div>
				{/* Sub-tab switcher */}
				<div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
					<button
						type="button"
						onClick={() => setPageTab("library")}
						className={`flex-1 rounded-lg py-2 text-[11px] font-bold uppercase tracking-[0.16em] transition-colors ${pageTab === "library" ? "bg-slate-800 text-slate-100 shadow-sm" : "text-slate-500 hover:bg-slate-800/60 hover:text-slate-200"}`}
					>
						Library — All Projects
					</button>
					<button
						type="button"
						onClick={() => setPageTab("new")}
						className={`flex-1 rounded-lg py-2 text-[11px] font-bold uppercase tracking-[0.16em] transition-colors ${pageTab === "new" ? "bg-blue-600/30 text-blue-200 shadow-sm" : "text-slate-500 hover:bg-slate-800/60 hover:text-slate-200"}`}
					>
						+ New Project
					</button>
				</div>
				{error && (
					<div className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
						<button type="button" onClick={() => setError(null)} className="ml-2 underline">dismiss</button>
					</div>
				)}
			</section>

			{/* Content */}
			{pageTab === "new" ? (
				<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
					<div className="mb-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
						Create New Project
					</div>
					<NewProjectForm
						onCreated={(proj) => {
							loadProjects();
							setPageTab("library");
							navigate(`/projects/${proj.id}`);
						}}
					/>
				</section>
			) : (
				<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
					{/* Filter row */}
					<div className="mb-4 flex flex-wrap items-center gap-3">
						{/* Status tabs */}
						<div className="flex gap-1">
							{(["ACTIVE", "ARCHIVED", "ALL"] as FilterTab[]).map((t) => (
								<button
									key={t}
									type="button"
									onClick={() => { setFilterTab(t); setCurrentPage(1); }}
									className={`rounded-lg border px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.14em] transition-colors ${filterTab === t ? "border-blue-500/40 bg-blue-500/15 text-blue-300" : "border-slate-700 bg-slate-900 text-slate-500 hover:text-slate-300"}`}
								>
									{t} ({counts[t]})
								</button>
							))}
						</div>
						{/* Search */}
						<input
							type="text"
							value={search}
							onChange={(e) => { setSearch(e.target.value); setCurrentPage(1); }}
							placeholder="Search projects..."
							className="ml-auto w-52 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
						/>
					</div>

					{loading ? (
						<div className="py-8 text-center text-sm text-slate-500">Loading projects...</div>
					) : filtered.length === 0 ? (
						<div className="py-8 text-center text-sm text-slate-500">
							{search ? `No projects match "${search}"` : `No ${filterTab.toLowerCase()} projects.`}
						</div>
					) : (
						<>
							<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
								{paginated.map((p) => (
									<ProjectCard
										key={p.id}
										project={p}
										onClick={() => navigate(`/projects/${p.id}`)}
										onArchive={() => handleArchiveToggle(p)}
										onDelete={() => handleDelete(p)}
										actionLoading={actionLoadingId === p.id}
									/>
								))}
							</div>
							{totalPages > 1 && (
								<div className="mt-5 flex items-center justify-between border-t border-slate-800 pt-4">
									<span className="text-[11px] text-slate-500">
										{(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length} projects
									</span>
									<div className="flex items-center gap-1">
										<button
											type="button"
											disabled={safePage <= 1}
											onClick={() => setCurrentPage((p) => p - 1)}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
										>
											← Prev
										</button>
										{Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
											<button
												key={n}
												type="button"
												onClick={() => setCurrentPage(n)}
												className={`min-w-[32px] rounded-lg border px-2 py-1.5 text-[11px] font-semibold transition-colors ${n === safePage ? "border-blue-500/40 bg-blue-500/15 text-blue-200" : "border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}
											>
												{n}
											</button>
										))}
										<button
											type="button"
											disabled={safePage >= totalPages}
											onClick={() => setCurrentPage((p) => p + 1)}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
										>
											Next →
										</button>
									</div>
								</div>
							)}
						</>
					)}
				</section>
			)}
		</div>
	);
}
