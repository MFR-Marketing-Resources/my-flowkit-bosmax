import {
	useCallback,
	useEffect,
	useMemo,
	useState,
	type FormEvent,
	type ReactNode,
} from "react";
import { useNavigate, useParams } from "react-router-dom";

import { fetchAPI, patchAPI } from "../api/client";
import {
	fetchProductStrategyTypeRegistry,
	reviewProductStrategyTaxonomy,
} from "../api/products";
import type { Product, ProductStrategyTypeRegistryResponse } from "../types";
import ProductIntelligenceReviewDraftPanel from "../components/product-intelligence/ProductIntelligenceReviewDraftPanel";
import CreativeSetupPanel from "../components/product-intelligence/CreativeSetupPanel";
import RecommendedScenePromptsCard from "../components/product-intelligence/RecommendedScenePromptsCard";
import RecommendedCameraPresetsCard from "../components/product-intelligence/RecommendedCameraPresetsCard";
import CreativeHandoffPreview from "../components/product-intelligence/CreativeHandoffPreview";
import ProductVisualReadinessPanel from "../components/product-registration/ProductVisualReadinessPanel";

// One clean full-screen editor for ONE product. Opened from All Products →
// "Open". Reuses the proven panels (PI review, creative setup multi-tick,
// recommendation cards) in a consistent house-style layout — no cramped
// three-column Sales-Analyzer clutter.

type DetailTab = "EDIT" | "INTELLIGENCE" | "CREATIVE" | "VISUAL";

const EDIT_FIELDS: { key: string; label: string }[] = [
	{ key: "product_short_name", label: "Short Name" },
	{ key: "brand", label: "Brand" },
	{ key: "price", label: "Price (RM)" },
	{ key: "commission_rate", label: "Commission Rate" },
	{ key: "commission_amount", label: "Commission Amount (RM)" },
	{ key: "category", label: "Category" },
	{ key: "subcategory", label: "Subcategory" },
	{ key: "type", label: "Type" },
];

// System / taxonomy plumbing — set by the pipeline, rarely edited by hand.
const EDIT_FIELDS_ADVANCED: { key: string; label: string }[] = [
	{ key: "physics_class", label: "Physics Class" },
	{ key: "silo", label: "Silo" },
	{ key: "trigger_id", label: "Trigger ID" },
	{ key: "formula", label: "Formula" },
	{ key: "claim_risk_level", label: "Claim Risk Level" },
];

const CARD = "rounded-2xl border border-slate-800 bg-slate-900/40 p-6 shadow-xl";
const LABEL = "text-[10px] font-bold uppercase tracking-widest text-slate-500 ml-1";
const INPUT =
	"w-full rounded-xl border border-slate-700 bg-slate-800/50 px-3.5 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all";
const BTN_PRIMARY =
	"rounded-xl bg-indigo-600 px-5 py-2.5 text-xs font-bold uppercase tracking-widest text-white shadow-lg hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500 transition-all";

const SOURCE_BADGE: Record<string, string> = {
	FASTMOSS: "bg-indigo-500/20 text-indigo-300",
	TIKTOKSHOP: "bg-pink-500/20 text-pink-300",
	MANUAL: "bg-emerald-500/20 text-emerald-300",
	IMPORTED: "bg-amber-500/20 text-amber-300",
};

const resolveThumb = (p: Product): string | null =>
	p.image_url || p.rendered_img_src || p.image_analysis?.image_url || null;

export default function ProductDetailPage() {
	const { id = "" } = useParams();
	const navigate = useNavigate();

	const [product, setProduct] = useState<Product | null>(null);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [tab, setTab] = useState<DetailTab>("EDIT");

	const [registry, setRegistry] =
		useState<ProductStrategyTypeRegistryResponse | null>(null);

	// Edit form (identity + commerce). Flat string map, mirrors PATCH payload.
	const [editForm, setEditForm] = useState<Record<string, string>>({});
	const [copywritingAngle, setCopywritingAngle] = useState("");
	const [editSaving, setEditSaving] = useState(false);
	const [editMsg, setEditMsg] = useState<{ ok: boolean; text: string } | null>(
		null,
	);

	// Taxonomy (cluster → dependent product type).
	const [taxCluster, setTaxCluster] = useState("");
	const [taxType, setTaxType] = useState("");
	const [taxSaving, setTaxSaving] = useState(false);
	const [taxMsg, setTaxMsg] = useState<{ ok: boolean; text: string } | null>(
		null,
	);

	const loadProduct = useCallback(async () => {
		if (!id) return;
		setLoading(true);
		setLoadError(null);
		try {
			const p = await fetchAPI<Product>(
				`/api/products/${encodeURIComponent(id)}`,
			);
			setProduct(p);
			setEditForm({
				product_short_name: p.product_short_name || "",
				brand: p.brand || "",
				price: p.price != null ? String(p.price) : "",
				commission_rate: p.commission_rate || "",
				commission_amount:
					p.commission_amount != null ? String(p.commission_amount) : "",
				category: p.category || "",
				subcategory: p.subcategory || "",
				type: p.type || "",
				physics_class: p.physics_class || "",
				silo: p.silo || "",
				trigger_id: p.trigger_id || "",
				formula: p.formula || "",
				claim_risk_level: p.claim_risk_level || "",
			});
			setCopywritingAngle(p.copywriting_angle || "");
			setTaxCluster(p.strategy_taxonomy?.cluster || "");
			setTaxType(p.strategy_taxonomy?.product_type_group || "");
		} catch (e) {
			setLoadError(e instanceof Error ? e.message : "Failed to load product");
		} finally {
			setLoading(false);
		}
	}, [id]);

	useEffect(() => {
		void loadProduct();
	}, [loadProduct]);

	useEffect(() => {
		let cancelled = false;
		void fetchProductStrategyTypeRegistry()
			.then((r) => {
				if (!cancelled) setRegistry(r);
			})
			.catch(() => {
				/* non-fatal — taxonomy dropdowns simply stay empty */
			});
		return () => {
			cancelled = true;
		};
	}, []);

	const clusters = useMemo(
		() =>
			(registry?.clusters ?? [])
				.filter((c) => c && c !== "generic_unclassified")
				.slice()
				.sort(),
		[registry],
	);
	// Dependent: product types registered under the chosen cluster.
	const typeOptions = useMemo(
		() =>
			(registry?.items ?? []).filter((i) => i.cluster === taxCluster),
		[registry, taxCluster],
	);
	const selectedTaxEntry = useMemo(
		() =>
			typeOptions.find((i) => i.product_type_group === taxType) || null,
		[typeOptions, taxType],
	);

	async function handleEditSave(e: FormEvent) {
		e.preventDefault();
		if (!product) return;
		setEditSaving(true);
		setEditMsg(null);
		try {
			const payload: Record<string, string | number | null> = {};
			const all = { ...editForm, copywriting_angle: copywritingAngle };
			for (const [key, val] of Object.entries(all)) {
				if (val === "") payload[key] = null;
				else if (key === "price" || key === "commission_amount") {
					const n = Number.parseFloat(val);
					payload[key] = Number.isNaN(n) ? null : n;
				} else payload[key] = val;
			}
			await patchAPI(`/api/products/${encodeURIComponent(product.id)}`, payload);
			await loadProduct();
			setEditMsg({ ok: true, text: "Saved." });
		} catch (err) {
			setEditMsg({
				ok: false,
				text: err instanceof Error ? err.message : "Failed to save",
			});
		} finally {
			setEditSaving(false);
		}
	}

	async function handleTaxonomySave() {
		if (!product) return;
		if (!selectedTaxEntry) {
			setTaxMsg({ ok: false, text: "Pick a cluster then a product type." });
			return;
		}
		setTaxSaving(true);
		setTaxMsg(null);
		try {
			await reviewProductStrategyTaxonomy(product.id, {
				expected_product_fingerprint:
					product.strategy_taxonomy?.product_fingerprint || "",
				cluster: selectedTaxEntry.cluster,
				product_type_group: selectedTaxEntry.product_type_group,
				matched_scene_strategy_id: selectedTaxEntry.matched_scene_strategy_id,
				scene_coverage_status: selectedTaxEntry.scene_coverage_status,
				review_status: "VERIFIED",
				reviewer_id: "owner",
				reviewer_note: "Cluster/type updated via product editor",
			});
			await loadProduct();
			setTaxMsg({ ok: true, text: "Cluster / type saved." });
		} catch (err) {
			setTaxMsg({
				ok: false,
				text: err instanceof Error ? err.message : "Failed to save taxonomy",
			});
		} finally {
			setTaxSaving(false);
		}
	}

	const thumb = product ? resolveThumb(product) : null;
	const clusterType =
		[
			product?.strategy_taxonomy?.cluster,
			product?.strategy_taxonomy?.product_type_group,
		]
			.filter(Boolean)
			.join(" · ") || "—";

	return (
		<div className="flex h-full flex-col overflow-y-auto bg-slate-950 px-4 py-4 md:px-8 md:py-6">
			<button
				type="button"
				onClick={() => navigate("/product-registration?tab=all")}
				className="mb-4 w-fit rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-[11px] font-bold uppercase tracking-widest text-slate-300 transition-colors hover:text-white"
			>
				← All Products
			</button>

			{loading ? (
				<div className="p-10 text-center text-sm text-slate-500">Loading product…</div>
			) : loadError || !product ? (
				<div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-6">
					<div className="text-sm font-bold text-amber-200">
						This product could not be opened
					</div>
					<p className="mt-1 text-xs leading-relaxed text-amber-100/80">
						{loadError ||
							"No product record resolves for this id."}{" "}
						If this is a FastMoss reference row, convert it via Smart Registration
						/ Import FastMoss first.
					</p>
				</div>
			) : (
				<>
					{/* Header summary */}
					<div className={`${CARD} mb-5`}>
						<div className="flex flex-wrap items-start gap-4">
							{thumb ? (
								<img
									src={thumb}
									alt=""
									className="h-20 w-20 shrink-0 rounded-xl border border-slate-700 object-cover"
									onError={(e) => {
										(e.target as HTMLImageElement).style.display = "none";
									}}
								/>
							) : (
								<div className="h-20 w-20 shrink-0 rounded-xl border border-slate-700 bg-slate-800" />
							)}
							<div className="min-w-0 flex-1">
								<h2 className="text-lg font-bold leading-snug text-white md:text-xl">
									{product.product_display_name || product.raw_product_title}
								</h2>
								<div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
									<span
										className={`rounded px-1.5 py-0.5 font-bold ${
											SOURCE_BADGE[product.source || ""] ||
											"bg-slate-600/20 text-slate-400"
										}`}
									>
										{product.source}
									</span>
									<span className="text-slate-400">{clusterType}</span>
									{product.lifecycle_status ? (
										<span className="rounded bg-slate-700/40 px-1.5 py-0.5 font-bold text-slate-300">
											{product.lifecycle_status.replace(/_/g, " ")}
										</span>
									) : null}
								</div>
								<div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-slate-400">
									<span>
										Price:{" "}
										<span className="text-slate-200">
											{product.price != null ? `RM ${Number(product.price).toFixed(2)}` : "—"}
										</span>
									</span>
									<span>
										Comm:{" "}
										<span className="text-slate-200">
											{product.commission_rate || "—"}
										</span>
									</span>
									<span>
										Sold:{" "}
										<span className="text-slate-200">
											{(product.sold_count ?? product.product_sold_count ?? null) != null
												? Number(
														product.sold_count ?? product.product_sold_count,
													).toLocaleString()
												: "—"}
										</span>
									</span>
								</div>
							</div>
						</div>
					</div>

					{/* Tabs */}
					<div
						role="tablist"
						aria-label="Product detail sections"
						className="mb-5 flex w-fit gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1"
					>
						{(
							[
								["EDIT", "Edit & Save"],
								["INTELLIGENCE", "Product Intelligence"],
								["CREATIVE", "Creative Setup"],
								["VISUAL", "Visual / Canva"],
							] as [DetailTab, string][]
						).map(([value, label]) => (
							<button
								key={value}
								type="button"
								role="tab"
								aria-selected={tab === value}
								onClick={() => setTab(value)}
								className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest transition-all ${
									tab === value
										? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/20"
										: "text-slate-400 hover:text-white"
								}`}
							>
								{label}
							</button>
						))}
					</div>

					{/* Per-tab helper: what this tab does + how to fill / where to save. */}
					<div className="mb-5 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3 text-[11px] leading-relaxed text-slate-400">
						{tab === "EDIT" && (
							<>
								Edit this product's identity, price / commission, and cluster / type.
								Each card saves on its own — <Hl>Save Changes</Hl> writes the identity
								&amp; commerce fields; <Hl>Save Cluster / Type</Hl> updates the taxonomy
								(cluster → its product type).
							</>
						)}
						{tab === "INTELLIGENCE" && (
							<>
								Product Truth — description, benefits, usage, ingredients, warnings, and
								buyer persona. Some fields are intentionally blank (claim-critical ones
								are never auto-invented). To fill them: press{" "}
								<Hl>AI Fill Missing (DeepSeek)</Hl> — it proposes values for empty fields
								only, review-only, never overwrites your text (spends DeepSeek tokens) —
								or type them in. Then <Hl>Save Draft</Hl> → <Hl>Approve Draft</Hl>.{" "}
								<Hl>Recompute (Validate)</Hl> re-checks readiness deterministically (no
								AI, free).
							</>
						)}
						{tab === "CREATIVE" && (
							<>
								Choose the people and scenes for this product. Camera presets follow the
								selected scene automatically. Use <Hl>Smart suggest</Hl>, then{" "}
								<Hl>Save Selection</Hl> and <Hl>Approve</Hl>. Planning only — nothing is
								generated here.
							</>
						)}
						{tab === "VISUAL" && (
							<>
								Review the original, automatic, and manual cutout candidates, Canva handoff,
								provenance, and Exact Commerce approval in this tab. No provider operation
								starts unless explicitly triggered by the operator.
							</>
						)}
					</div>

					{tab === "VISUAL" && (
						<ProductVisualReadinessPanel
							productId={product.id}
							productSourceUrl={product.tiktok_product_url || product.source_url}
							readiness={product.visual_readiness}
							showApprovalForm
							onChanged={(visualReadiness) =>
								setProduct((previous) =>
									previous ? { ...previous, visual_readiness: visualReadiness } : previous,
								)
							}
						/>
					)}

					{tab === "EDIT" && (
						<div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
							{/* Identity & Commerce */}
							<form onSubmit={handleEditSave} className={CARD}>
								<h3 className="mb-4 text-base font-semibold text-white">
									Identity &amp; Commerce
								</h3>
								<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
									{EDIT_FIELDS.map((f) => (
										<div key={f.key} className="space-y-1.5">
											<label className={LABEL}>{f.label}</label>
											<input
												className={INPUT}
												value={editForm[f.key] ?? ""}
												onChange={(e) =>
													setEditForm((prev) => ({
														...prev,
														[f.key]: e.target.value,
													}))
												}
											/>
										</div>
									))}
								</div>
								<details className="mt-4 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
									<summary className="cursor-pointer text-[10px] font-bold uppercase tracking-widest text-slate-500">
										Advanced taxonomy — set automatically, rarely edited
									</summary>
									<div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
										{EDIT_FIELDS_ADVANCED.map((f) => (
											<div key={f.key} className="space-y-1.5">
												<label className={LABEL}>{f.label}</label>
												<input
													className={INPUT}
													value={editForm[f.key] ?? ""}
													onChange={(e) =>
														setEditForm((prev) => ({ ...prev, [f.key]: e.target.value }))
													}
												/>
											</div>
										))}
									</div>
								</details>
								<div className="mt-4 space-y-1.5">
									<label className={LABEL}>Copywriting Angle</label>
									<textarea
										className={`${INPUT} h-24 resize-none`}
										value={copywritingAngle}
										onChange={(e) => setCopywritingAngle(e.target.value)}
									/>
								</div>
								<div className="mt-5 flex items-center gap-3">
									<button type="submit" disabled={editSaving} className={BTN_PRIMARY}>
										{editSaving ? "Saving…" : "Save Changes"}
									</button>
									{editMsg && (
										<span
											className={`text-xs ${editMsg.ok ? "text-emerald-400" : "text-red-400"}`}
										>
											{editMsg.text}
										</span>
									)}
								</div>
							</form>

							{/* Cluster & Product Type (dependent dropdown) */}
							<div className={CARD}>
								<h3 className="mb-1 text-base font-semibold text-white">
									Cluster &amp; Product Type
								</h3>
								<p className="mb-4 text-[11px] text-slate-500">
									Current:{" "}
									<span className="font-mono text-slate-300">{clusterType}</span>. Pick
									a cluster, then its product type. Saved as VERIFIED.
								</p>
								<div className="space-y-4">
									<div className="space-y-1.5">
										<label className={LABEL}>Cluster</label>
										<select
											className={INPUT}
											value={taxCluster}
											onChange={(e) => {
												setTaxCluster(e.target.value);
												setTaxType(""); // dependent: type resets with its cluster
											}}
										>
											<option value="">— select cluster —</option>
											{clusters.map((c) => (
												<option key={c} value={c}>
													{c}
												</option>
											))}
										</select>
									</div>
									<div className="space-y-1.5">
										<label className={LABEL}>
											Product Type{taxCluster ? ` · ${taxCluster}` : ""}
										</label>
										<select
											className={INPUT}
											value={taxType}
											onChange={(e) => setTaxType(e.target.value)}
											disabled={!taxCluster}
										>
											<option value="">
												{taxCluster ? "— select product type —" : "Pick a cluster first"}
											</option>
											{typeOptions.map((i) => (
												<option key={i.product_type_group} value={i.product_type_group}>
													{i.display_name || i.product_type_group} · {i.registry_status}
												</option>
											))}
										</select>
									</div>
									<div className="flex items-center gap-3">
										<button
											type="button"
											disabled={taxSaving || !selectedTaxEntry}
											onClick={handleTaxonomySave}
											className={BTN_PRIMARY}
										>
											{taxSaving ? "Saving…" : "Save Cluster / Type"}
										</button>
										{taxMsg && (
											<span
												className={`text-xs ${taxMsg.ok ? "text-emerald-400" : "text-red-400"}`}
											>
												{taxMsg.text}
											</span>
										)}
									</div>
								</div>
							</div>
						</div>
					)}

					{tab === "INTELLIGENCE" && (
						<ProductIntelligenceReviewDraftPanel
							productId={product.id}
							onApproved={async () => {
								await loadProduct();
							}}
						/>
					)}

					{tab === "CREATIVE" && (
						<div data-testid="creative-setup-tab" className="space-y-5">
							<CreativeSetupPanel productId={product.id} />
							<details
								data-testid="creative-reference-library"
								className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"
							>
								<summary className="cursor-pointer list-none text-sm font-bold text-slate-200 hover:text-white">
									Reference library <span className="ml-2 text-xs font-normal text-slate-500">optional prompt and camera detail</span>
								</summary>
								<div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
									<RecommendedScenePromptsCard productId={product.id} />
									<RecommendedCameraPresetsCard productId={product.id} />
								</div>
							</details>
							<details
								data-testid="creative-handoff-disclosure"
								className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"
							>
								<summary className="cursor-pointer list-none text-sm font-bold text-slate-200 hover:text-white">
									Generation handoff <span className="ml-2 text-xs font-normal text-slate-500">preview only · no generation</span>
								</summary>
								<div className="mt-4">
									<CreativeHandoffPreview productId={product.id} />
								</div>
							</details>
						</div>
					)}
				</>
			)}
		</div>
	);
}

// Inline highlight for the per-tab helper — points the eye at the exact button.
function Hl({ children }: { children: ReactNode }) {
	return <span className="font-semibold text-slate-200">{children}</span>;
}
