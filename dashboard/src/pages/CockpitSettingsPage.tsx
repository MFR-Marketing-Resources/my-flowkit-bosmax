import { Gauge } from "lucide-react";
import {
	usePosterBuilderSettings,
	type PosterSettingOption,
} from "../api/posterBuilderSettings";

// Read-only Creative Cockpit — the single source of truth (SSOT) that the Poster
// Builder dropdowns also consume. It VIEWS canonical settings and shows each
// value's provenance. No mutation, no generation, no token spend. This is a NEW
// surface; the ADR-008 frozen "Prompt Preview" page is intentionally untouched.

function SourceTag({ source }: { source: string }) {
	const tone =
		source === "not_configured" || source === "fallback"
			? "border-amber-500/40 text-amber-200"
			: "border-slate-700 text-slate-400";
	return (
		<span
			className={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase ${tone}`}
			data-testid="cockpit-source-tag"
		>
			source: {source}
		</span>
	);
}

function DimensionTable({
	title,
	testid,
	options,
	source,
}: {
	title: string;
	testid: string;
	options: PosterSettingOption[];
	source: string;
}) {
	return (
		<div
			className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"
			data-testid={testid}
		>
			<div className="flex items-center justify-between gap-2">
				<h4 className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-200">
					{title}
				</h4>
				<SourceTag source={source} />
			</div>
			<ul className="mt-3 space-y-1.5">
				{options.map((opt) => (
					<li key={opt.id} className="text-xs text-slate-300">
						<span className="font-semibold text-slate-100">{opt.label}</span>
						{opt.default ? (
							<span className="ml-2 rounded bg-emerald-600/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-emerald-200">
								default
							</span>
						) : null}
						{opt.description ? (
							<span className="ml-2 text-slate-500">— {opt.description}</span>
						) : null}
						<span className="ml-2 text-[10px] text-slate-600">({opt.id})</span>
					</li>
				))}
			</ul>
		</div>
	);
}

export default function CockpitSettingsPage() {
	const s = usePosterBuilderSettings();
	const dimSource = s.sources?.poster_dimensions ?? "config";

	return (
		<div
			className="mx-auto max-w-6xl space-y-6 p-4 md:p-8"
			data-testid="cockpit-settings-page"
		>
			<header>
				<div className="flex items-center gap-2 text-blue-300">
					<Gauge size={20} />
					<span className="text-[10px] font-bold uppercase tracking-[0.2em]">
						Creative Cockpit
					</span>
				</div>
				<h1 className="mt-1 text-2xl font-bold text-slate-100">
					Prompt / Builder Settings (SSOT)
				</h1>
				<p className="mt-2 max-w-3xl text-sm text-slate-400">
					Canonical creative settings consumed by the Poster Builder and future
					builder surfaces. Read-only view: it shows what each dropdown offers and
					where the value comes from. This page runs no generation and spends no
					credits.
				</p>
			</header>

			{/* Poster Builder settings */}
			<section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
				<h3 className="text-sm font-bold text-slate-100">Poster Builder Settings</h3>
				<p className="mt-1 text-xs text-slate-400">
					Dimension option lists. The Poster Builder Auto/Manual dropdowns read
					these exact values.
				</p>
				<div className="mt-4 grid gap-3 md:grid-cols-2">
					<DimensionTable
						title="Objectives"
						testid="cockpit-dim-objectives"
						options={s.poster_objectives}
						source={dimSource}
					/>
					<DimensionTable
						title="Poster Types"
						testid="cockpit-dim-types"
						options={s.poster_types}
						source={dimSource}
					/>
					<DimensionTable
						title="Languages"
						testid="cockpit-dim-languages"
						options={s.languages}
						source={dimSource}
					/>
					<DimensionTable
						title="Visual Routes"
						testid="cockpit-dim-visual-routes"
						options={s.visual_routes}
						source={dimSource}
					/>
					<DimensionTable
						title="Human Presence Modes"
						testid="cockpit-dim-human-presence"
						options={s.human_presence_modes}
						source={dimSource}
					/>
					<DimensionTable
						title="Text Density"
						testid="cockpit-dim-text-density"
						options={s.text_density_options}
						source={dimSource}
					/>
				</div>
			</section>

			{/* Flow Mirror settings */}
			<section
				className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5"
				data-testid="cockpit-flow-mirror"
			>
				<div className="flex items-center justify-between gap-2">
					<h3 className="text-sm font-bold text-slate-100">Flow Mirror Settings</h3>
					<SourceTag source={s.flow_mirror.source} />
				</div>
				<p className="mt-1 text-xs text-slate-400">
					Image output controls mirrored from the image-gen SSOT (models.json). The
					Poster Builder Flow Mirror panel uses the same values.
				</p>
				<div className="mt-4 grid gap-4 md:grid-cols-3">
					<div>
						<p className="text-[10px] font-bold uppercase text-slate-500">Aspect ratios</p>
						<p className="mt-1 text-sm text-slate-200">
							{s.flow_mirror.aspect_ratios.join("  ·  ")}
						</p>
						<p className="mt-1 text-[10px] text-slate-500">
							default {s.flow_mirror.defaults.aspect_ratio}
						</p>
					</div>
					<div>
						<p className="text-[10px] font-bold uppercase text-slate-500">Counts</p>
						<p className="mt-1 text-sm text-slate-200">
							{s.flow_mirror.counts.map((c) => `${c}x`).join("  ·  ")}
						</p>
						<p className="mt-1 text-[10px] text-slate-500">
							default {s.flow_mirror.defaults.count}x
						</p>
					</div>
					<div>
						<p className="text-[10px] font-bold uppercase text-slate-500">Image models</p>
						<ul className="mt-1 space-y-1">
							{s.flow_mirror.image_models.map((m) => (
								<li key={m.key} className="text-sm text-slate-200">
									{m.label}
									{m.pending ? (
										<span className="ml-2 rounded bg-amber-600/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-amber-200">
											pending id
										</span>
									) : null}
								</li>
							))}
						</ul>
						<p className="mt-1 text-[10px] text-slate-500">
							default {s.flow_mirror.defaults.image_model}
						</p>
					</div>
				</div>
			</section>

			{/* Copy components */}
			<section
				className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5"
				data-testid="cockpit-copy-components"
			>
				<div className="flex items-center justify-between gap-2">
					<h3 className="text-sm font-bold text-slate-100">Copy Components</h3>
					<SourceTag source={s.copy_components.source} />
				</div>
				<div className="mt-3 grid gap-3 text-xs text-slate-300 md:grid-cols-2">
					<p>
						<span className="text-slate-500">Routes: </span>
						{s.copy_components.routes.length
							? s.copy_components.routes.join("  ·  ")
							: "Not configured yet"}
					</p>
					<p>
						<span className="text-slate-500">Copy sets: </span>
						{s.copy_components.copy_sets_scope} scope ·{" "}
						<code className="text-slate-400">{s.copy_components.copy_sets_endpoint}</code>
					</p>
					<p>
						<span className="text-slate-500">Copy landbank: </span>
						{s.copy_components.landbank_products > 0
							? `${s.copy_components.landbank_products} product(s) with a landbank`
							: "Not configured yet"}
					</p>
				</div>
			</section>

			{/* AI assist status */}
			<section
				className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5"
				data-testid="cockpit-ai-status"
			>
				<div className="flex items-center justify-between gap-2">
					<h3 className="text-sm font-bold text-slate-100">AI Assist Status</h3>
					<SourceTag source={s.ai_provider.source} />
				</div>
				<div className="mt-3 grid gap-3 text-xs text-slate-300 md:grid-cols-2">
					<p>
						<span className="text-slate-500">Copy lane: </span>
						{s.ai_provider.lane}
					</p>
					<p>
						<span className="text-slate-500">Status: </span>
						<span
							className={
								s.ai_provider.configured ? "text-emerald-200" : "text-amber-200"
							}
							data-testid="cockpit-ai-status-value"
						>
							{s.ai_provider.configured ? "configured" : "unavailable"}
						</span>
					</p>
					<p>
						<span className="text-slate-500">Provider: </span>
						{s.ai_provider.provider_id || "—"}
					</p>
					<p>
						<span className="text-slate-500">Model: </span>
						{s.ai_provider.model_id || "—"}
					</p>
					<p>
						<span className="text-slate-500">Execution enabled: </span>
						{s.ai_provider.execution_enabled ? "yes" : "no"}
					</p>
				</div>
				<p className="mt-3 text-[10px] text-slate-500">
					No API keys or secrets are shown here. AI copy generation is spent only on
					explicit operator action in the Poster Builder.
				</p>
			</section>
		</div>
	);
}
