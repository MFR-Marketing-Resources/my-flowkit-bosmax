import { Gauge } from "lucide-react";
import {
	usePosterBuilderSettings,
	type PosterSettingOption,
} from "../api/posterBuilderSettings";
import { Badge, HelperText, Section } from "../components/ui";

// Read-only Creative Cockpit — the single source of truth (SSOT) the Poster
// Builder dropdowns also consume. It VIEWS canonical settings and shows each
// value's provenance. No mutation, no generation, no token spend.
//
// This page is the SETTINGS STANDARD: kit `Section` panels, a `Badge` for
// provenance in the section action slot, and any engine detail (endpoints, raw
// ids) tucked into a "Technical detail" disclosure. The ADR-008 frozen "Prompt
// Preview" page is intentionally untouched.

// Provenance chip — "where did this value come from". Amber when a setting is
// missing or on a fallback, neutral otherwise.
function SourceBadge({ source }: { source: string }) {
	const warn = source === "not_configured" || source === "fallback";
	return (
		<span data-testid="cockpit-source-tag">
			<Badge tone={warn ? "warn" : "neutral"}>source: {source}</Badge>
		</span>
	);
}

function DimensionCard({
	title,
	testid,
	options,
}: {
	title: string;
	testid: string;
	options: PosterSettingOption[];
}) {
	return (
		<div
			className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"
			data-testid={testid}
		>
			<h4 className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-200">
				{title}
			</h4>
			<ul className="mt-3 space-y-1.5">
				{options.map((opt) => (
					<li key={opt.id} className="text-xs text-slate-300">
						<span className="font-semibold text-slate-100">{opt.label}</span>
						{opt.default ? (
							<Badge tone="success" className="ml-2">
								default
							</Badge>
						) : null}
						{opt.description ? (
							<span className="ml-2 text-slate-500">— {opt.description}</span>
						) : null}
					</li>
				))}
			</ul>
		</div>
	);
}

export default function CockpitSettingsPage() {
	const s = usePosterBuilderSettings();

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
					Canonical creative settings the Poster Builder and future builder
					surfaces read from. This is a read-only view — it runs no generation
					and spends no credits.
				</p>
			</header>

			<Section
				title="Poster Builder settings"
				helper="Dimension option lists — the Poster Builder Auto and Manual dropdowns read these exact values."
			>
				<div className="grid gap-3 md:grid-cols-2">
					<DimensionCard
						title="Objectives"
						testid="cockpit-dim-objectives"
						options={s.poster_objectives}
					/>
					<DimensionCard
						title="Poster types"
						testid="cockpit-dim-types"
						options={s.poster_types}
					/>
					<DimensionCard
						title="Languages"
						testid="cockpit-dim-languages"
						options={s.languages}
					/>
					<DimensionCard
						title="Visual routes"
						testid="cockpit-dim-visual-routes"
						options={s.visual_routes}
					/>
					<DimensionCard
						title="Human presence modes"
						testid="cockpit-dim-human-presence"
						options={s.human_presence_modes}
					/>
					<DimensionCard
						title="Text density"
						testid="cockpit-dim-text-density"
						options={s.text_density_options}
					/>
				</div>
			</Section>

			<div data-testid="cockpit-flow-mirror">
				<Section
					title="Flow Mirror settings"
					helper="Image output controls mirrored from the image-generation source of truth. The Poster Builder Flow Mirror panel uses the same values."
					action={<SourceBadge source={s.flow_mirror.source} />}
				>
					<div className="grid gap-4 md:grid-cols-3">
						<div>
							<p className="text-[10px] font-bold uppercase text-slate-500">
								Aspect ratios
							</p>
							<p className="mt-1 text-sm text-slate-200">
								{s.flow_mirror.aspect_ratios.join("  ·  ")}
							</p>
							<p className="mt-1 text-[10px] text-slate-500">
								Default {s.flow_mirror.defaults.aspect_ratio}
							</p>
						</div>
						<div>
							<p className="text-[10px] font-bold uppercase text-slate-500">
								Counts
							</p>
							<p className="mt-1 text-sm text-slate-200">
								{s.flow_mirror.counts.map((c) => `${c}x`).join("  ·  ")}
							</p>
							<p className="mt-1 text-[10px] text-slate-500">
								Default {s.flow_mirror.defaults.count}x
							</p>
						</div>
						<div>
							<p className="text-[10px] font-bold uppercase text-slate-500">
								Image models
							</p>
							<ul className="mt-1 space-y-1">
								{s.flow_mirror.image_models.map((m) => (
									<li key={m.key} className="text-sm text-slate-200">
										{m.label}
										{m.pending ? (
											<Badge tone="warn" className="ml-2">
												pending id
											</Badge>
										) : null}
									</li>
								))}
							</ul>
							<p className="mt-1 text-[10px] text-slate-500">
								Default {s.flow_mirror.defaults.image_model}
							</p>
						</div>
					</div>
				</Section>
			</div>

			<div data-testid="cockpit-copy-components">
				<Section
					title="Copy components"
					helper="How copy is sourced for this workspace."
					action={<SourceBadge source={s.copy_components.source} />}
				>
					<div className="grid gap-3 text-xs text-slate-300 md:grid-cols-2">
						<p>
							<span className="text-slate-500">Routes: </span>
							{s.copy_components.routes.length
								? s.copy_components.routes.join("  ·  ")
								: "Not configured yet"}
						</p>
						<p>
							<span className="text-slate-500">Copy sets: </span>
							{s.copy_components.copy_sets_scope} scope
						</p>
						<p>
							<span className="text-slate-500">Copy landbank: </span>
							{s.copy_components.landbank_products > 0
								? `${s.copy_components.landbank_products} product(s) with a landbank`
								: "Not configured yet"}
						</p>
					</div>
					<details className="mt-3 text-[10px] text-slate-500">
						<summary className="cursor-pointer select-none">
							Technical detail
						</summary>
						<p className="mt-1">
							Copy-sets endpoint:{" "}
							<code className="text-slate-400">
								{s.copy_components.copy_sets_endpoint}
							</code>
						</p>
					</details>
				</Section>
			</div>

			<div data-testid="cockpit-ai-status">
				<Section
					title="AI assist status"
					helper="Whether AI copy assist is available. No API keys or secrets are shown."
					action={<SourceBadge source={s.ai_provider.source} />}
				>
					<div className="grid gap-3 text-xs text-slate-300 md:grid-cols-2">
						<p>
							<span className="text-slate-500">Copy lane: </span>
							{s.ai_provider.lane}
						</p>
						<p className="flex items-center gap-2">
							<span className="text-slate-500">Status: </span>
							<span data-testid="cockpit-ai-status-value">
								<Badge tone={s.ai_provider.configured ? "success" : "warn"}>
									{s.ai_provider.configured ? "configured" : "unavailable"}
								</Badge>
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
					<HelperText>
						AI copy generation is spent only on explicit operator action in the
						Poster Builder.
					</HelperText>
				</Section>
			</div>
		</div>
	);
}
