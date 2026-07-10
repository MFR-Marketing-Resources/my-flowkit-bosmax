import { useState } from "react";
import {
	approvePosterCopySet,
	createPosterCopySet,
	generatePosterDirections,
	recommendPosterAngles,
	regeneratePosterField,
} from "../../api/posterCopySets";
import {
	POSTER_COPY_APPROVAL_PHRASE,
	type PosterAngleRecommendation,
	type PosterCopyDirection,
	type PosterCopySet,
} from "../../types/posterCopySet";

/** AI Angle + Copy step (POSTER_BUILDER_V2).
 *
 * angle recommendations → operator picks one → 3 poster-native copy directions
 * → select/edit/regenerate-one-field → approve as a reusable Poster Copy Set.
 * AI calls fire only on explicit clicks; unconfigured lanes fall back to
 * curated angles + deterministic directions (no hidden spend). */
export default function PosterAngleCopyStep({
	productId,
	archetype,
	recipeId,
	language,
	onApproved,
}: {
	productId: string;
	archetype: string;
	recipeId: string;
	language: string;
	onApproved: (copySet: PosterCopySet) => void;
}) {
	const [angles, setAngles] = useState<PosterAngleRecommendation[]>([]);
	const [selectedAngle, setSelectedAngle] = useState("");
	const [directions, setDirections] = useState<PosterCopyDirection[]>([]);
	const [picked, setPicked] = useState<PosterCopyDirection | null>(null);
	const [warnings, setWarnings] = useState<string[]>([]);
	const [error, setError] = useState("");
	const [loading, setLoading] = useState<"" | "angles" | "directions" | "approve">("");
	const [regenField, setRegenField] = useState("");
	const [approved, setApproved] = useState<PosterCopySet | null>(null);

	const loadAngles = async (refreshAi: boolean) => {
		setLoading("angles");
		setError("");
		try {
			const res = await recommendPosterAngles({
				product_id: productId,
				archetype,
				refresh_ai: refreshAi,
			});
			setAngles(res.angles);
			setWarnings(res.warnings ?? []);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Gagal memuat angle.");
		} finally {
			setLoading("");
		}
	};

	const loadDirections = async (angle: string) => {
		setSelectedAngle(angle);
		setPicked(null);
		setApproved(null);
		setLoading("directions");
		setError("");
		try {
			const res = await generatePosterDirections({
				product_id: productId,
				archetype,
				angle,
				language,
				count: 3,
			});
			setDirections(res.directions);
			setWarnings(res.warnings ?? []);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Gagal menjana arah copy.");
		} finally {
			setLoading("");
		}
	};

	const editPicked = (field: string, value: string | string[]) => {
		setApproved(null);
		setPicked((prev) =>
			prev
				? {
						...prev,
						[field]: value,
						field_provenance: { ...prev.field_provenance, [field]: "OPERATOR_EDIT" },
					}
				: prev,
		);
	};

	const handleRegenerateField = async (field: string) => {
		if (!picked) return;
		setRegenField(field);
		setError("");
		try {
			const res = await regeneratePosterField({
				product_id: productId,
				archetype,
				angle: selectedAngle,
				field,
				language,
				fields: {
					primary_message: picked.primary_message,
					support_message: picked.support_message,
					proof_points: picked.proof_points,
					cta: picked.cta,
					disclaimer: picked.disclaimer,
				},
			});
			editPicked(res.field, res.value);
			setPicked((prev) =>
				prev
					? {
							...prev,
							field_provenance: {
								...prev.field_provenance,
								[res.field]: res.provenance,
							},
						}
					: prev,
			);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Regenerate medan gagal.");
		} finally {
			setRegenField("");
		}
	};

	const handleApprove = async () => {
		if (!picked) return;
		setLoading("approve");
		setError("");
		try {
			const created = await createPosterCopySet({
				product_id: productId,
				objective: recipeId,
				archetype,
				angle: selectedAngle,
				primary_message: picked.primary_message,
				support_message: picked.support_message,
				proof_points: picked.proof_points.filter((p) => p.trim()),
				cta: picked.cta,
				disclaimer: picked.disclaimer,
				tone: picked.tone,
				language,
				field_provenance: picked.field_provenance,
			});
			const done = await approvePosterCopySet(
				created.poster_copy_set_id,
				POSTER_COPY_APPROVAL_PHRASE,
			);
			setApproved(done);
			setPicked(null);
			setDirections([]);
			setSelectedAngle("");
			onApproved(done);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Kelulusan Poster Copy Set gagal.");
		} finally {
			setLoading("");
		}
	};

	const fieldRow = (
		label: string,
		field: keyof PosterCopyDirection & string,
		value: string,
		maxLength: number,
	) => (
		<div className="flex items-center gap-2">
			<label className="w-24 shrink-0 text-[10px] font-bold uppercase text-slate-500">
				{label}
			</label>
			<input
				value={value}
				maxLength={maxLength}
				data-testid={`poster-direction-${field}`}
				onChange={(e) => editPicked(field, e.target.value)}
				className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-100"
			/>
			<button
				type="button"
				title="Jana semula medan ini sahaja (AI)"
				data-testid={`poster-regen-${field}`}
				disabled={regenField !== ""}
				onClick={() => void handleRegenerateField(field)}
				className="rounded-lg border border-slate-700 px-2 py-1.5 text-[11px] text-slate-300 hover:border-blue-500/40 disabled:opacity-40"
			>
				{regenField === field ? "…" : "↻"}
			</button>
		</div>
	);

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 space-y-4"
			data-testid="poster-angle-copy-step"
		>
			<div className="flex items-center justify-between">
				<h3 className="text-sm font-bold text-slate-100">3. Angle &amp; Copy (AI)</h3>
				<div className="flex gap-2">
					<button
						type="button"
						data-testid="poster-load-angles"
						disabled={loading !== ""}
						onClick={() => void loadAngles(false)}
						className="rounded-xl border border-slate-700 px-3 py-1.5 text-[11px] font-semibold text-slate-300 disabled:opacity-40"
					>
						Angle disyorkan
					</button>
					<button
						type="button"
						data-testid="poster-load-angles-ai"
						disabled={loading !== ""}
						onClick={() => void loadAngles(true)}
						className="rounded-xl border border-blue-500/40 bg-blue-600/10 px-3 py-1.5 text-[11px] font-semibold text-blue-200 disabled:opacity-40"
					>
						{loading === "angles" ? "Menjana…" : "Angle AI +"}
					</button>
				</div>
			</div>

			{angles.length > 0 ? (
				<div className="flex flex-wrap gap-2" data-testid="poster-angle-list">
					{angles.map((a) => (
						<button
							key={a.angle}
							type="button"
							title={a.rationale}
							onClick={() => void loadDirections(a.angle)}
							className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold ${
								selectedAngle === a.angle
									? "border-blue-400 bg-blue-500/20 text-blue-100"
									: "border-slate-700 text-slate-300 hover:border-blue-500/40"
							}`}
						>
							{a.angle}
							{a.source === "AI" ? " ✦" : ""}
						</button>
					))}
				</div>
			) : (
				<p className="text-xs text-slate-500">
					Klik <strong>Angle disyorkan</strong> untuk mula — tak perlu tahu
					copywriting; sistem cadangkan angle jualan yang sesuai.
				</p>
			)}

			{loading === "directions" ? (
				<p className="text-xs text-slate-400">Menjana 3 arah copy poster…</p>
			) : null}

			{directions.length > 0 && !picked ? (
				<div className="grid gap-3 md:grid-cols-3" data-testid="poster-direction-cards">
					{directions.map((d, i) => (
						<button
							key={`${d.primary_message}-${i}`}
							type="button"
							data-testid={`poster-direction-card-${i}`}
							onClick={() => setPicked(d)}
							className="rounded-xl border border-slate-700 bg-slate-900/60 p-3 text-left hover:border-blue-500/50"
						>
							<div className="text-sm font-bold text-slate-100">{d.primary_message}</div>
							{d.support_message ? (
								<div className="mt-1 text-[11px] text-slate-400">{d.support_message}</div>
							) : null}
							<div className="mt-2 flex flex-wrap gap-1">
								{d.proof_points.map((p) => (
									<span
										key={p}
										className="rounded-full border border-slate-700 px-2 py-0.5 text-[10px] text-slate-300"
									>
										{p}
									</span>
								))}
							</div>
							<div className="mt-2 text-[11px] font-bold text-blue-300">{d.cta}</div>
						</button>
					))}
				</div>
			) : null}

			{picked ? (
				<div className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/40 p-3">
					<div className="flex items-center justify-between">
						<p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
							Edit copy terpilih (↻ = jana semula satu medan)
						</p>
						<button
							type="button"
							onClick={() => setPicked(null)}
							className="text-[11px] text-slate-400 underline"
						>
							Tukar arah
						</button>
					</div>
					{fieldRow("Mesej utama", "primary_message", picked.primary_message, 48)}
					{fieldRow("Sokongan", "support_message", picked.support_message, 72)}
					<div className="flex items-center gap-2">
						<label className="w-24 shrink-0 text-[10px] font-bold uppercase text-slate-500">
							Proof points
						</label>
						<input
							value={picked.proof_points.join(" | ")}
							data-testid="poster-direction-proof_points"
							onChange={(e) =>
								editPicked(
									"proof_points",
									e.target.value.split("|").map((s) => s.trim()),
								)
							}
							className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-100"
						/>
						<button
							type="button"
							data-testid="poster-regen-proof_points"
							disabled={regenField !== ""}
							onClick={() => void handleRegenerateField("proof_points")}
							className="rounded-lg border border-slate-700 px-2 py-1.5 text-[11px] text-slate-300 disabled:opacity-40"
						>
							{regenField === "proof_points" ? "…" : "↻"}
						</button>
					</div>
					{fieldRow("CTA", "cta", picked.cta, 24)}
					{fieldRow("Disclaimer", "disclaimer", picked.disclaimer, 100)}
					<button
						type="button"
						data-testid="poster-approve-copy-set"
						disabled={loading === "approve" || !picked.primary_message || !picked.cta}
						onClick={() => void handleApprove()}
						className="mt-2 rounded-xl border border-emerald-500/50 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
					>
						{loading === "approve"
							? "Meluluskan…"
							: "Lulus & simpan Poster Copy Set"}
					</button>
				</div>
			) : null}

			{approved ? (
				<p data-testid="poster-copy-set-approved" className="text-[11px] text-emerald-300">
					✓ Poster Copy Set diluluskan (v{approved.version} ·{" "}
					{approved.poster_copy_set_id}) — boleh diguna semula untuk kempen lain.
				</p>
			) : null}
			{warnings.map((w) => (
				<p key={w} className="text-[11px] text-amber-300">
					{w}
				</p>
			))}
			{error ? (
				<p data-testid="poster-angle-copy-error" className="text-[11px] text-rose-300">
					{error}
				</p>
			) : null}
		</section>
	);
}
