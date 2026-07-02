import {
	AlertTriangle,
	CheckCircle2,
	Clipboard,
	ExternalLink,
	FolderOpen,
	PackageCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchProductCatalog } from "../api/products";
import {
	createWorkspaceExecutionPackage,
	fetchApprovedProductPackage,
	fetchWorkspaceExecutionPackageHistory,
} from "../api/workspacePackages";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type {
	ApprovedProductPackage,
	Product,
	WorkspaceExecutionPackage,
	WorkspaceMode,
} from "../types";

const MODES: WorkspaceMode[] = ["T2V", "F2V", "I2V", "IMG"];

function workspaceRouteForSurface(mode: WorkspaceMode): string {
	if (mode === "HYBRID") return "/operator/hybrid";
	return `/operator/${mode.toLowerCase()}`;
}

function historySurfaceLabel(item: WorkspaceExecutionPackage): string {
	if (item.source_mode === "HYBRID") return "HYBRID";
	if (item.source_mode === "FRAMES") return "FRAMES";
	return item.mode;
}

export default function ApprovedPackagesPage() {
	const navigate = useNavigate();
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [packagesByMode, setPackagesByMode] = useState<
		Partial<Record<WorkspaceMode, ApprovedProductPackage | null>>
	>({});
	const [modeErrors, setModeErrors] = useState<
		Partial<Record<WorkspaceMode, string>>
	>({});
	const [history, setHistory] = useState<WorkspaceExecutionPackage[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [activeMode, setActiveMode] = useState<WorkspaceMode>("T2V");
	const [notice, setNotice] = useState<string>("");

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items))
			.catch((error: Error) =>
				setNotice(error.message || "Failed to load product catalog."),
			);
	}, []);

	useEffect(() => {
		if (!selectedProduct) {
			setPackagesByMode({});
			setModeErrors({});
			setHistory([]);
			return;
		}

		setIsLoading(true);
		setNotice("");
		void Promise.allSettled(
			MODES.map(async (mode) => {
				const payload = await fetchApprovedProductPackage(
					selectedProduct.id,
					mode,
				);
				return { mode, payload };
			}),
		)
			.then((results) => {
				const nextPackages: Partial<
					Record<WorkspaceMode, ApprovedProductPackage | null>
				> = {};
				const nextErrors: Partial<Record<WorkspaceMode, string>> = {};
				for (const result of results) {
					if (result.status === "fulfilled") {
						nextPackages[result.value.mode] = result.value.payload;
						continue;
					}
					const match = /mode=([A-Z0-9]+)/i.exec(String(result.reason));
					const mode =
						(match?.[1]?.toUpperCase() as WorkspaceMode) ||
						MODES[results.indexOf(result)];
					nextErrors[mode] =
						result.reason instanceof Error
							? result.reason.message
							: String(result.reason);
				}
				setPackagesByMode(nextPackages);
				setModeErrors(nextErrors);
			})
			.finally(() => setIsLoading(false));

		void fetchWorkspaceExecutionPackageHistory(
			selectedProduct.id,
			undefined,
			12,
		)
			.then(setHistory)
			.catch(() => {});
	}, [selectedProduct]);

	const activePackage = packagesByMode[activeMode] || null;
	const handleCopyPrompt = async (pkg: ApprovedProductPackage) => {
		await navigator.clipboard.writeText(pkg.prompt_text);
		setNotice(`Copied approved ${pkg.mode} prompt.`);
	};

	const handleOpenWorkspace = async (
		mode: WorkspaceMode,
		sourceMode?: "HYBRID" | "FRAMES",
	) => {
		if (!selectedProduct) return;
		const jobMode = mode === "HYBRID" ? "F2V" : mode;
		const executionPackage = await createWorkspaceExecutionPackage({
			product_id: selectedProduct.id,
			mode: jobMode,
			...(sourceMode ? { source_mode: sourceMode } : {}),
		});
		navigate(workspaceRouteForSurface(mode), {
			state: { workspaceExecutionPackage: executionPackage },
		});
	};

	return (
		<div className="space-y-6 px-4 py-6 md:px-8">
			<div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
				<div>
					<h2 className="text-2xl font-bold tracking-tight text-white">
						Approved Product Packages
					</h2>
					<p className="text-sm text-slate-400">
						Manual fallback and workspace bridge surface. Prompt and cached
						image stay available even when automation is offline.
					</p>
				</div>
				<div className="w-full max-w-xl">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={setSelectedProduct}
					/>
				</div>
			</div>

			{notice ? (
				<div className="rounded-2xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm text-blue-100">
					{notice}
				</div>
			) : null}

			<div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
				<div className="space-y-4">
					<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
							Approved Modes
						</div>
						<div className="space-y-2">
							{MODES.map((mode) => {
								const pkg = packagesByMode[mode];
								const error = modeErrors[mode];
								return (
									<button
										key={mode}
										type="button"
										onClick={() => setActiveMode(mode)}
										className={`flex w-full items-center justify-between rounded-xl border px-3 py-3 text-left transition ${
											activeMode === mode
												? "border-blue-500/50 bg-blue-500/10"
												: "border-slate-800 bg-slate-950/70"
										}`}
									>
										<div>
											<div className="text-sm font-semibold text-white">
												{mode}
											</div>
											<div className="text-[11px] text-slate-400">
												{pkg
													? pkg.production_generation_allowed
														? "Production approved"
														: "Fallback package"
													: error
														? "Blocked"
														: isLoading
															? "Loading..."
															: "Unavailable"}
											</div>
										</div>
										{pkg ? (
											<CheckCircle2 className="text-emerald-400" size={16} />
										) : (
											<AlertTriangle className="text-amber-400" size={16} />
										)}
									</button>
								);
							})}
						</div>
					</div>

					<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
						<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
							Recent Workspace Packages
						</div>
						<div className="space-y-2">
							{history.length === 0 ? (
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-4 text-xs text-slate-500">
									No execution packages stored yet for this product.
								</div>
							) : (
								history.map((item) => (
									<div
										key={item.workspace_execution_package_id}
										className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3"
									>
										<div className="text-xs font-semibold text-white">
											{historySurfaceLabel(item)}
										</div>
										<div className="mt-1 text-[11px] text-slate-400">
											{item.workspace_execution_package_id}
										</div>
										<div className="mt-2 text-[11px] text-slate-500">
											{item.prompt_preview}
										</div>
									</div>
								))
							)}
						</div>
					</div>
				</div>

				<div className="space-y-4">
					{activePackage ? (
						<>
							<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
								<div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
									<div>
										<div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
											Package Status
										</div>
										<h3 className="mt-2 text-xl font-bold text-white">
											{activePackage.product_name} · {activePackage.mode}
										</h3>
										<div className="mt-2 flex flex-wrap gap-2 text-[11px]">
											<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-emerald-200">
												{activePackage.approval_status}
											</span>
											<span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-blue-200">
												image {activePackage.image_reference_status}
											</span>
										</div>
									</div>
									<div className="flex flex-wrap gap-2">
										<button
											type="button"
											onClick={() => void handleCopyPrompt(activePackage)}
											className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-blue-400/50"
										>
											<Clipboard size={14} />
											Copy Approved Prompt
										</button>
										{activeMode === "F2V" ? (
											<>
												<button
													type="button"
													onClick={() => void handleOpenWorkspace("HYBRID", "HYBRID")}
													className="inline-flex items-center gap-2 rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-100 hover:border-blue-400/60"
												>
													<FolderOpen size={14} />
													Open Hybrid Workspace
												</button>
												<button
													type="button"
													onClick={() => void handleOpenWorkspace("F2V", "FRAMES")}
													className="inline-flex items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-xs font-semibold text-violet-100 hover:border-violet-400/60"
												>
													<FolderOpen size={14} />
													Open Frames Workspace
												</button>
											</>
										) : (
											<button
												type="button"
												onClick={() => void handleOpenWorkspace(activeMode)}
												className="inline-flex items-center gap-2 rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-100 hover:border-blue-400/60"
											>
												<FolderOpen size={14} />
												Open in Workspace
											</button>
										)}
									</div>
								</div>
							</div>

							<div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
								<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
									<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
										Prompt Text
									</div>
									<textarea
										readOnly
										value={activePackage.prompt_text}
										className="h-[420px] w-full resize-none rounded-2xl border border-slate-800 bg-slate-950 p-4 font-mono text-sm text-slate-200"
									/>
								</div>

								<div className="space-y-4">
									<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
										<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
											Asset Slots
										</div>
										<div className="space-y-3">
											{activePackage.asset_slots.map((slot) => (
												<div
													key={slot.slot_key}
													className="rounded-xl border border-slate-800 bg-slate-950/70 p-3"
												>
													<div className="flex items-center justify-between gap-3">
														<div className="text-sm font-semibold text-white">
															{slot.slot_key}
														</div>
														<div className="text-[11px] text-slate-400">
															{slot.required ? "Required" : "Optional"}
														</div>
													</div>
													<div className="mt-2 text-[11px] text-slate-500">
														default {slot.default_source}
													</div>
													{slot.resolved_asset?.preview_url ? (
														<div className="mt-3 space-y-2">
															<img
																src={slot.resolved_asset.preview_url}
																alt={slot.resolved_asset.label}
																className="aspect-[4/5] w-full rounded-xl object-cover"
															/>
															<div className="flex gap-2">
																<a
																	href={slot.resolved_asset.preview_url}
																	target="_blank"
																	rel="noreferrer"
																	className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200"
																>
																	<ExternalLink size={12} />
																	Preview
																</a>
																<a
																	href={slot.resolved_asset.download_url}
																	target="_blank"
																	rel="noreferrer"
																	className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200"
																>
																	<PackageCheck size={12} />
																	Download
																</a>
															</div>
														</div>
													) : null}
												</div>
											))}
										</div>
									</div>

									<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
										<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
											Manual Fallback Checklist
										</div>
										<ul className="space-y-2 text-sm text-slate-300">
											{activePackage.manual_fallback.execution_checklist.map(
												(item) => (
													<li
														key={item}
														className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2"
													>
														{item}
													</li>
												),
											)}
										</ul>
										<div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-3 text-xs text-amber-100">
											{activePackage.manual_fallback.operator_warning}
										</div>
									</div>
								</div>
							</div>
						</>
					) : (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-8 text-sm text-slate-400">
							Select a product to load approved package history and manual
							fallback assets.
						</div>
					)}
				</div>
			</div>
		</div>
	);
}
