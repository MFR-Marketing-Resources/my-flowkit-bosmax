import { startTransition, useEffect, useState } from "react";
import { fetchAPI } from "../api/client";
import { useWebSocketContext } from "../contexts/WebSocketContext";
import type {
	AIProviderCatalogEntry,
	AIProviderId,
	AIProviderLaneId,
	AIProviderLaneSetting,
	AIProviderLaneStatus,
	AIProviderModelOption,
	AIProviderRegistry,
	AIProviderSummary,
	LocalAgentStatus,
	TelemetrySummary,
} from "../types";

function DeploymentStatusCard({
	agentStatus,
}: {
	agentStatus: LocalAgentStatus | null;
}) {
	if (!agentStatus) return null;
	const deploymentTone = agentStatus.extension_connected
		? {
				label: "ONLINE",
				badgeClass: "bg-green-600/20 text-green-400",
				dotClass: "bg-green-500 animate-pulse",
			}
		: {
				label: "DEGRADED",
				badgeClass: "bg-amber-500/20 text-amber-300",
				dotClass: "bg-amber-400",
			};
	const ownershipLabel = agentStatus.auto_start_enabled
		? agentStatus.auto_start_mode.replaceAll("_", " ")
		: "MANUAL ONLY";
	return (
		<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6 shadow-xl backdrop-blur-md">
			<div className="mb-6 flex items-center justify-between">
				<h3 className="flex items-center gap-2 text-sm font-bold text-white">
					<span
						className={`h-2 w-2 rounded-full ${deploymentTone.dotClass}`}
					/>
					Deployment Status
				</h3>
				<div
					className={`rounded px-2 py-0.5 text-[10px] font-bold ${deploymentTone.badgeClass}`}
				>
					{deploymentTone.label}
				</div>
			</div>
			<div className="grid grid-cols-1 gap-4 md:grid-cols-4">
				<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
					<div className="mb-1 text-[10px] font-bold uppercase text-slate-500">
						Runtime Owner
					</div>
					<div className="text-sm font-bold text-slate-200">
						{ownershipLabel}
					</div>
					<div className="mt-1 text-[11px] text-slate-500">
						{agentStatus.task_name}
					</div>
				</div>
				<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
					<div className="mb-1 text-[10px] font-bold uppercase text-slate-500">
						Extension Bridge
					</div>
					<div
						className={`text-sm font-bold ${agentStatus.extension_connected ? "text-blue-400" : "text-amber-300"}`}
					>
						{agentStatus.extension_connected
							? `Connected / ${agentStatus.extension_state}`
							: `Disconnected / ${agentStatus.offline_reason || agentStatus.extension_state}`}
					</div>
				</div>
				<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
					<div className="mb-1 text-[10px] font-bold uppercase text-slate-500">
						Serving Mode
					</div>
					<div className="text-sm font-bold text-slate-200">
						{agentStatus.dashboard_serving_mode || "Local"}
					</div>
				</div>
				<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
					<div className="mb-1 text-[10px] font-bold uppercase text-slate-500">
						Last Heartbeat
					</div>
					<div className="font-mono text-sm text-slate-400">
						{agentStatus.last_health_check
							? new Date(agentStatus.last_health_check).toLocaleTimeString()
							: "—"}
					</div>
				</div>
			</div>
			{agentStatus.auto_start_warning ? (
				<div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
					Autostart warning: {agentStatus.auto_start_warning}
				</div>
			) : null}
		</div>
	);
}

const PROVIDER_ACCENT: Record<string, string> = {
	ACTIVE: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
	READY: "border-amber-500/40 bg-amber-500/10 text-amber-300",
	KEY_MISSING: "border-slate-700 bg-slate-900 text-slate-400",
};

const PROVIDER_LOADING_LABELS = [
	"Qwen",
	"Anthropic",
	"OpenAI",
	"Gemini",
	"DeepSeek",
];

function getProviderCardTone(provider: AIProviderSummary) {
	if (provider.is_active) {
		return "border-blue-500/30 bg-blue-500/5";
	}
	if (provider.has_key) {
		return "border-amber-500/20 bg-slate-900/40";
	}
	return "border-slate-800 bg-slate-900/30";
}

function getProviderInputPlaceholder(provider: AIProviderSummary) {
	if (provider.has_key) {
		return `Stored securely. Paste new ${provider.label} API key to replace.`;
	}
	return `Paste ${provider.label} API key`;
}

// --- defensive registry normalization ---------------------------------------
// The V3 SettingsPage dereferences V3-only fields (lane.status, provider.
// supported_lanes / current_capabilities, model.lanes, catalog entry.models).
// A stale (pre-#208) backend, a mid-migration state file, or a corrupt catalog
// can return an older or partial shape. Coercing every payload into the V3
// shape here means a single missing/mistyped field can NEVER unmount the whole
// page (the blank-screen incident). This is idempotent on a well-formed V3
// payload.

const asStringArray = (value: unknown): string[] =>
	Array.isArray(value)
		? value.filter((entry): entry is string => typeof entry === "string")
		: [];

const LANE_LABELS: Record<string, string> = {
	text_assist: "Text Assist",
	vision: "Vision",
};

function normalizeModelOption(raw: unknown): AIProviderModelOption | null {
	if (!raw || typeof raw !== "object") return null;
	const record = raw as Record<string, unknown>;
	const modelId = typeof record.model_id === "string" ? record.model_id : "";
	if (!modelId) return null;
	return {
		model_id: modelId,
		label:
			typeof record.label === "string" && record.label ? record.label : modelId,
		lanes: asStringArray(record.lanes),
		enabled: record.enabled === undefined ? true : Boolean(record.enabled),
		source: typeof record.source === "string" ? record.source : "seed",
	};
}

function normalizeCatalogEntry(raw: unknown): AIProviderCatalogEntry {
	// Old shape: model_catalog[provider] was an ARRAY of models. New shape:
	// { label, transport, enabled, supported_lanes, models }.
	const models = (
		Array.isArray(raw)
			? raw
			: raw && typeof raw === "object" && Array.isArray((raw as { models?: unknown }).models)
				? ((raw as { models: unknown[] }).models)
				: []
	)
		.map(normalizeModelOption)
		.filter((model): model is AIProviderModelOption => model !== null);
	const record =
		raw && typeof raw === "object" && !Array.isArray(raw)
			? (raw as Record<string, unknown>)
			: {};
	return {
		label: typeof record.label === "string" ? record.label : "",
		transport: typeof record.transport === "string" ? record.transport : "",
		enabled: record.enabled === undefined ? true : Boolean(record.enabled),
		supported_lanes: asStringArray(record.supported_lanes),
		models,
	};
}

function normalizeProvider(raw: unknown): AIProviderSummary | null {
	if (!raw || typeof raw !== "object") return null;
	const record = raw as Record<string, unknown>;
	if (typeof record.provider_id !== "string") return null;
	return {
		provider_id: record.provider_id as AIProviderId,
		label: typeof record.label === "string" ? record.label : record.provider_id,
		env_var: typeof record.env_var === "string" ? record.env_var : "",
		has_key: Boolean(record.has_key),
		masked_key: typeof record.masked_key === "string" ? record.masked_key : null,
		status: typeof record.status === "string" ? record.status : "KEY_MISSING",
		is_active: Boolean(record.is_active),
		updated_at: typeof record.updated_at === "string" ? record.updated_at : null,
		activated_at:
			typeof record.activated_at === "string" ? record.activated_at : null,
		activation_scope:
			typeof record.activation_scope === "string"
				? record.activation_scope
				: "REGISTRY_ONLY",
		current_capabilities: asStringArray(record.current_capabilities),
		default_model:
			typeof record.default_model === "string" ? record.default_model : null,
		supported_lanes: asStringArray(record.supported_lanes),
	};
}

function normalizeLane(raw: unknown): AIProviderLaneSetting | null {
	if (!raw || typeof raw !== "object") return null;
	const record = raw as Record<string, unknown>;
	if (typeof record.lane !== "string") return null;
	const providerId =
		typeof record.provider_id === "string"
			? (record.provider_id as AIProviderId)
			: null;
	const modelId = typeof record.model_id === "string" ? record.model_id : null;
	// Old shape carried `configured` but no explicit `status`; derive one so
	// `status.replaceAll(...)` in render can never throw.
	const status: AIProviderLaneStatus =
		typeof record.status === "string"
			? (record.status as AIProviderLaneStatus)
			: providerId && modelId
				? "READY"
				: "NOT_CONFIGURED";
	return {
		lane: record.lane as AIProviderLaneId,
		label:
			typeof record.label === "string"
				? record.label
				: LANE_LABELS[record.lane] || record.lane,
		provider_id: providerId,
		model_id: modelId,
		execution_enabled: Boolean(record.execution_enabled),
		configured_by_user:
			record.configured_by_user === undefined
				? Boolean(record.configured)
				: Boolean(record.configured_by_user),
		key_present: Boolean(record.key_present),
		model_valid: Boolean(record.model_valid),
		status,
		configured: Boolean(
			record.configured === undefined ? providerId && modelId : record.configured,
		),
	};
}

function normalizeRegistry(raw: unknown): {
	registry: AIProviderRegistry;
	catalogMalformed: boolean;
} {
	const record =
		raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
	const providers = (
		Array.isArray(record.providers) ? record.providers : []
	)
		.map(normalizeProvider)
		.filter((provider): provider is AIProviderSummary => provider !== null);

	const rawCatalog = record.model_catalog;
	const model_catalog: Record<string, AIProviderCatalogEntry> = {};
	let catalogMalformed = false;
	if (
		rawCatalog &&
		typeof rawCatalog === "object" &&
		!Array.isArray(rawCatalog)
	) {
		for (const [providerId, entry] of Object.entries(
			rawCatalog as Record<string, unknown>,
		)) {
			model_catalog[providerId] = normalizeCatalogEntry(entry);
		}
	} else if (rawCatalog !== undefined) {
		// present but wrong type (array / primitive) → unusable
		catalogMalformed = true;
	}

	const lanes = (Array.isArray(record.lanes) ? record.lanes : [])
		.map(normalizeLane)
		.filter((lane): lane is AIProviderLaneSetting => lane !== null);

	return {
		registry: {
			active_provider:
				typeof record.active_provider === "string"
					? (record.active_provider as AIProviderId)
					: null,
			providers,
			model_catalog,
			lanes,
		},
		catalogMalformed,
	};
}

export default function SettingsPage() {
	const [agentStatus, setAgentStatus] = useState<LocalAgentStatus | null>(null);
	const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null);
	const [providerRegistry, setProviderRegistry] =
		useState<AIProviderRegistry | null>(null);
	const [catalogMalformed, setCatalogMalformed] = useState(false);
	const [draftKeys, setDraftKeys] = useState<Record<AIProviderId, string>>({
		qwen: "",
		anthropic: "",
		openai: "",
		gemini: "",
		deepseek: "",
	});
	const [mutatingProviderId, setMutatingProviderId] = useState<string | null>(
		null,
	);
	const [bannerMessage, setBannerMessage] = useState<string | null>(null);
	const [bannerError, setBannerError] = useState<string | null>(null);
	// Pending (unsaved) lane provider selection: choosing a provider blanks the
	// model until the operator explicitly picks one (nothing is persisted yet).
	const [laneProviderDraft, setLaneProviderDraft] = useState<
		Record<string, string>
	>({});
	// Per-provider "add custom model" form drafts.
	const [customModelDraft, setCustomModelDraft] = useState<
		Record<string, { model_id: string; label: string; lanes: string[] }>
	>({});
	const { isConnected } = useWebSocketContext();

	const applyRegistry = (raw: unknown) => {
		const { registry, catalogMalformed: malformed } = normalizeRegistry(raw);
		startTransition(() => {
			setProviderRegistry(registry);
			setCatalogMalformed(malformed);
		});
	};

	const refreshStatus = async () => {
		try {
			const [status, tel, providers] = await Promise.all([
				fetchAPI<LocalAgentStatus>("/api/local-agent/status"),
				fetchAPI<TelemetrySummary>("/api/telemetry/summary"),
				fetchAPI<unknown>("/api/ai-providers"),
			]);
			const { registry, catalogMalformed: malformed } =
				normalizeRegistry(providers);
			startTransition(() => {
				setAgentStatus(status);
				setTelemetry(tel);
				setProviderRegistry(registry);
				setCatalogMalformed(malformed);
			});
		} catch (err) {
			console.error("Failed to fetch settings status", err);
			setBannerError(
				err instanceof Error ? err.message : "Failed to load AI provider settings.",
			);
		}
	};

	useEffect(() => {
		void refreshStatus();
		const timer = setInterval(() => {
			void refreshStatus();
		}, 10000);
		return () => clearInterval(timer);
	}, []);

	const setDraftValue = (providerId: AIProviderId, value: string) => {
		setDraftKeys((current) => ({ ...current, [providerId]: value }));
	};

	const runProviderMutation = async (
		providerId: string,
		task: () => Promise<AIProviderRegistry>,
		successMessage: string,
	) => {
		setMutatingProviderId(providerId);
		setBannerError(null);
		setBannerMessage(null);
		try {
			const payload = await task();
			applyRegistry(payload);
			setBannerMessage(successMessage);
		} catch (err) {
			setBannerError(
				err instanceof Error ? err.message : "Provider mutation failed.",
			);
		} finally {
			setMutatingProviderId(null);
		}
	};

	const handleSaveKey = async (providerId: AIProviderId) => {
		const apiKey = draftKeys[providerId]?.trim() || "";
		await runProviderMutation(
			providerId,
			async () =>
				fetchAPI<AIProviderRegistry>(`/api/ai-providers/${providerId}/key`, {
					method: "PUT",
					body: JSON.stringify({ api_key: apiKey }),
				}),
			`${providerId.toUpperCase()} key stored in local provider registry.`,
		);
		setDraftValue(providerId, "");
	};

	const handleActivate = async (provider: AIProviderSummary) => {
		const providerId = provider.provider_id;
		const pendingKey = draftKeys[providerId]?.trim() || "";

		await runProviderMutation(
			providerId,
			async () => {
				if (!provider.has_key && !pendingKey) {
					throw new Error("Paste an API key first, then activate the provider.");
				}
				if (!provider.has_key && pendingKey) {
					await fetchAPI<AIProviderRegistry>(
						`/api/ai-providers/${providerId}/key`,
						{
							method: "PUT",
							body: JSON.stringify({ api_key: pendingKey }),
						},
					);
				}
				return fetchAPI<AIProviderRegistry>(
					`/api/ai-providers/${providerId}/activate`,
					{
						method: "POST",
						body: JSON.stringify({}),
					},
				);
			},
			`${provider.label} is now the active AI provider.`,
		);
		setDraftValue(providerId, "");
	};

	const handleClearKey = async (providerId: AIProviderId) => {
		await runProviderMutation(
			providerId,
			async () =>
				fetchAPI<AIProviderRegistry>(`/api/ai-providers/${providerId}/key`, {
					method: "DELETE",
					body: JSON.stringify({}),
				}),
			`${providerId.toUpperCase()} key cleared from local provider registry.`,
		);
		setDraftValue(providerId, "");
	};

	const handleDeactivate = async () => {
		await runProviderMutation(
			"GLOBAL",
			async () =>
				fetchAPI<AIProviderRegistry>("/api/ai-providers/deactivate", {
					method: "POST",
					body: JSON.stringify({}),
				}),
			"Active AI provider cleared. Stored keys remain available in the registry.",
		);
	};

	const handleSaveModel = async (
		providerId: AIProviderId,
		modelId: string,
	) => {
		if (!modelId) return;
		await runProviderMutation(
			`model:${providerId}`,
			async () =>
				fetchAPI<AIProviderRegistry>(`/api/ai-providers/${providerId}/model`, {
					method: "PUT",
					body: JSON.stringify({ model_id: modelId }),
				}),
			`${providerId.toUpperCase()} default model set to ${modelId}.`,
		);
	};

	// --- mutable model catalog ------------------------------------------
	const catalogEntry = (providerId: string): AIProviderCatalogEntry | null =>
		providerRegistry?.model_catalog?.[providerId] ?? null;

	const laneAllowedForProvider = (providerId: string, lane: string): boolean => {
		const transport = catalogEntry(providerId)?.transport;
		if (lane === "vision") return transport === "anthropic_messages";
		return true; // text_assist supported by all implemented transports
	};

	const modelsForLane = (
		providerId: AIProviderId | null,
		lane: string,
	): AIProviderModelOption[] => {
		if (!providerId) return [];
		return (catalogEntry(providerId)?.models ?? []).filter(
			(model) => model.enabled && (model.lanes ?? []).includes(lane),
		);
	};

	const providersForLane = (lane: string): AIProviderSummary[] => {
		if (!providerRegistry) return [];
		return (providerRegistry.providers ?? []).filter((provider) =>
			(provider.supported_lanes ?? []).includes(lane),
		);
	};

	const handleUpsertModel = async (
		providerId: AIProviderId,
		modelId: string,
		label: string,
		lanes: string[],
		enabled: boolean,
		successMessage: string,
	) => {
		await runProviderMutation(
			`catalog:${providerId}:${modelId}`,
			async () =>
				fetchAPI<AIProviderRegistry>(
					`/api/ai-providers/model-catalog/${providerId}/models/${encodeURIComponent(modelId)}`,
					{
						method: "PUT",
						body: JSON.stringify({ label, lanes, enabled }),
					},
				),
			successMessage,
		);
	};

	const handleToggleModelEnabled = async (
		providerId: AIProviderId,
		model: AIProviderModelOption,
	) => {
		if (model.enabled) {
			await runProviderMutation(
				`catalog:${providerId}:${model.model_id}`,
				async () =>
					fetchAPI<AIProviderRegistry>(
						`/api/ai-providers/model-catalog/${providerId}/models/${encodeURIComponent(model.model_id)}/disable`,
						{ method: "PATCH", body: JSON.stringify({}) },
					),
				`${model.model_id} disabled.`,
			);
			return;
		}
		await handleUpsertModel(
			providerId,
			model.model_id,
			model.label,
			model.lanes,
			true,
			`${model.model_id} enabled.`,
		);
	};

	const handleAddCustomModel = async (providerId: AIProviderId) => {
		const draft = customModelDraft[providerId] || {
			model_id: "",
			label: "",
			lanes: [],
		};
		const modelId = draft.model_id.trim();
		if (!modelId) {
			setBannerError("Enter a model ID to add a custom model.");
			return;
		}
		const lanes = draft.lanes.length ? draft.lanes : ["text_assist"];
		await handleUpsertModel(
			providerId,
			modelId,
			draft.label.trim() || modelId,
			lanes,
			true,
			`Custom model ${modelId} added to ${providerId.toUpperCase()}.`,
		);
		setCustomModelDraft((current) => ({
			...current,
			[providerId]: { model_id: "", label: "", lanes: [] },
		}));
	};

	const handleResetSeedCatalog = async () => {
		await runProviderMutation(
			"catalog:reset",
			async () =>
				fetchAPI<AIProviderRegistry>("/api/ai-providers/model-catalog/reset-seed", {
					method: "POST",
					body: JSON.stringify({}),
				}),
			"Model catalog reset to built-in seed presets.",
		);
	};

	const setCustomDraftField = (
		providerId: string,
		patch: Partial<{ model_id: string; label: string; lanes: string[] }>,
	) =>
		setCustomModelDraft((current) => {
			const base = current[providerId] || {
				model_id: "",
				label: "",
				lanes: [],
			};
			return { ...current, [providerId]: { ...base, ...patch } };
		});

	const toggleCustomLane = (providerId: string, lane: string) =>
		setCustomModelDraft((current) => {
			const draft = current[providerId] || {
				model_id: "",
				label: "",
				lanes: [],
			};
			const lanes = draft.lanes.includes(lane)
				? draft.lanes.filter((entry) => entry !== lane)
				: [...draft.lanes, lane];
			return { ...current, [providerId]: { ...draft, lanes } };
		});

	// --- lane configuration ---------------------------------------------
	const handleSaveLane = async (
		lane: string,
		providerId: AIProviderId,
		modelId: string,
		executionEnabled?: boolean,
	) => {
		await runProviderMutation(
			`lane:${lane}`,
			async () =>
				fetchAPI<AIProviderRegistry>(`/api/ai-providers/lanes/${lane}`, {
					method: "PUT",
					body: JSON.stringify({
						provider_id: providerId,
						model_id: modelId,
						execution_enabled:
							executionEnabled === undefined ? null : executionEnabled,
					}),
				}),
			`${lane} lane set to ${providerId} / ${modelId}.`,
		);
		setLaneProviderDraft((current) => {
			const next = { ...current };
			delete next[lane];
			return next;
		});
	};

	const handleClearLane = async (lane: string) => {
		await runProviderMutation(
			`lane:${lane}`,
			async () =>
				fetchAPI<AIProviderRegistry>(`/api/ai-providers/lanes/${lane}`, {
					method: "DELETE",
					body: JSON.stringify({}),
				}),
			`${lane} lane cleared (NOT CONFIGURED).`,
		);
		setLaneProviderDraft((current) => {
			const next = { ...current };
			delete next[lane];
			return next;
		});
	};

	const LANE_STATUS_STYLE: Record<string, string> = {
		NOT_CONFIGURED: "border-slate-700 bg-slate-900 text-slate-400",
		MODEL_MISSING: "border-amber-500/40 bg-amber-500/10 text-amber-300",
		MODEL_DISABLED: "border-amber-500/40 bg-amber-500/10 text-amber-300",
		KEY_MISSING: "border-amber-500/40 bg-amber-500/10 text-amber-300",
		EXECUTION_DISABLED: "border-slate-700 bg-slate-900 text-slate-400",
		READY: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
	};

	const activeProviderLabel =
		providerRegistry?.providers.find((provider) => provider.is_active)?.label ||
		"None";

	return (
		<div className="mx-auto max-w-6xl space-y-8 p-8">
			<div>
				<h2 className="mb-2 text-2xl font-bold text-white">Engine Room</h2>
				<p className="text-sm text-slate-400">
					Configure backend pipelines, API connections, and operator-local AI
					provider activation.
				</p>
			</div>

			<DeploymentStatusCard
				agentStatus={agentStatus}
			/>

			{bannerMessage ? (
				<div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
					{bannerMessage}
				</div>
			) : null}
			{bannerError ? (
				<div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
					<div className="flex flex-wrap items-center justify-between gap-3">
						<span>{bannerError}</span>
						<button
							type="button"
							onClick={() => void refreshStatus()}
							className="shrink-0 rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-1.5 text-xs font-semibold text-red-100 hover:border-red-300"
						>
							Retry
						</button>
					</div>
				</div>
			) : null}
			{catalogMalformed ? (
				<div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
					Model catalog unavailable or malformed. Reset catalog or refresh.
				</div>
			) : null}

			<div className="grid grid-cols-1 gap-8 xl:grid-cols-[1.1fr_1.9fr]">
				<section className="space-y-4">
					<h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
						System Telemetry
					</h3>
					<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
						<div className="space-y-4">
							<div className="flex items-center justify-between text-sm">
								<span className="text-slate-400">Total Jobs (Today)</span>
								<span className="font-bold text-white">
									{telemetry?.total_today || 0}
								</span>
							</div>
							<div className="flex items-center justify-between text-sm">
								<span className="text-slate-400">Success Rate</span>
								<span className="font-bold text-green-400">
									{telemetry?.total_today
										? Math.round((telemetry.completed / telemetry.total_today) * 100)
										: 0}
									%
								</span>
							</div>
							<div className="flex items-center justify-between text-sm">
								<span className="text-slate-400">Worker Status</span>
								<span className="font-bold uppercase text-blue-400">
									{isConnected ? "Idle" : "Offline"}
								</span>
							</div>
							<div className="flex items-center justify-between text-sm">
								<span className="text-slate-400">Active AI Provider</span>
								<span className="font-bold text-white">{activeProviderLabel}</span>
							</div>
						</div>
						<div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-xs text-slate-400">
							`LIVE_NOW` providers can affect existing runtime lanes immediately.
							`REGISTRY_ONLY` providers are stored, activatable, and ready for the
							next module wave.
						</div>
						<div className="mt-4 flex flex-wrap gap-3">
							<button
								type="button"
								onClick={() => void refreshStatus()}
								className="rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-blue-400/50 hover:text-blue-200"
							>
								Refresh Snapshot
							</button>
							<button
								type="button"
								onClick={() => void handleDeactivate()}
								disabled={mutatingProviderId === "GLOBAL"}
								className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-200 hover:border-red-400 disabled:cursor-not-allowed disabled:opacity-60"
							>
								Deactivate Active Provider
							</button>
						</div>
					</div>
				</section>

				<section className="space-y-4">
					<div className="flex items-center justify-between">
						<h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
							AI Provider Registry
						</h3>
						<div className="text-xs text-slate-500">
							Route: <code>/api/ai-providers</code>
						</div>
					</div>
					<div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
						{providerRegistry?.providers.length ? providerRegistry.providers.map((provider) => {
							const isBusy = mutatingProviderId === provider.provider_id;
							const draftValue = draftKeys[provider.provider_id] || "";
							return (
								<div
									key={provider.provider_id}
									className={`min-w-0 rounded-2xl border p-5 shadow-lg ${getProviderCardTone(provider)}`}
								>
									<div className="mb-4 flex items-start justify-between gap-4">
										<div className="min-w-0">
											<div className="flex items-center gap-2">
												<h4 className="text-base font-bold text-white">
													{provider.label}
												</h4>
												<span
													className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${PROVIDER_ACCENT[provider.status] || PROVIDER_ACCENT.KEY_MISSING}`}
												>
													{provider.status}
												</span>
											</div>
											<div className="mt-1 break-all text-[11px] uppercase tracking-wide text-slate-500">
												Env var: {provider.env_var}
											</div>
										</div>
										<div className="min-w-0 text-right text-[11px] text-slate-400">
											<div>{provider.activation_scope}</div>
											<div>
												{provider.is_active
													? "Current active provider"
													: provider.has_key
														? "Stored but inactive"
														: "No key stored"}
											</div>
										</div>
									</div>

									<div className="space-y-3">
										<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300">
											<div className="mb-2 font-semibold text-slate-200">
												Current capability lane
											</div>
											<div>
									{(provider.current_capabilities ?? []).join(" • ") ||
										"No capabilities declared"}
								</div>
										</div>

										<div className="space-y-2">
											<label className="text-xs font-medium text-slate-400">
												API Key
											</label>
											<input
												type="password"
												value={draftValue}
												onChange={(event) =>
													setDraftValue(provider.provider_id, event.target.value)
												}
												placeholder={getProviderInputPlaceholder(provider)}
												className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition placeholder:text-slate-500 focus:border-blue-400/60"
											/>
											<div className="min-h-[1rem] text-[11px] text-slate-500">
												{provider.masked_key ? (
													<span className="block break-all">
														Stored key: {provider.masked_key}
													</span>
												) : null}
											</div>
										</div>

										{catalogEntry(provider.provider_id) ? (
											<div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/50 p-3">
												<div className="text-[11px] text-slate-500">
													Built-in models are starter presets. You can add/edit
													models as providers change their model IDs.
												</div>

												<div className="space-y-2">
													<label className="text-xs font-medium text-slate-400">
														Default Model{" "}
														<span className="text-[10px] text-slate-500">
															(provider convenience — does not select a lane)
														</span>
													</label>
													<select
														value={provider.default_model || ""}
														onChange={(event) =>
															void handleSaveModel(
																provider.provider_id,
																event.target.value,
															)
														}
														disabled={isBusy}
														className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
													>
														<option value="">Select model…</option>
														{(catalogEntry(provider.provider_id)?.models ?? [])
															.filter((model) => model.enabled)
															.map((model) => (
																<option key={model.model_id} value={model.model_id}>
																	{model.label}
																</option>
															))}
													</select>
													<div className="text-[11px] text-slate-500">
														Transport: {catalogEntry(provider.provider_id)?.transport}
														{" · "}Supported lanes:{" "}
														{(provider.supported_lanes ?? []).length
															? (provider.supported_lanes ?? []).join(", ")
															: "—"}
													</div>
												</div>

												<div className="space-y-1">
													<div className="text-xs font-semibold text-slate-300">
														Models
													</div>
													{(catalogEntry(provider.provider_id)?.models ?? []).map(
														(model) => (
															<div
																key={model.model_id}
																className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/70 px-2 py-1.5"
															>
																<div className="min-w-0">
																	<div className="flex items-center gap-1">
																		<span
																			className={`truncate text-[11px] font-semibold ${model.enabled ? "text-slate-200" : "text-slate-500 line-through"}`}
																		>
																			{model.label}
																		</span>
																		<span className="rounded bg-slate-800 px-1 text-[9px] uppercase text-slate-400">
																			{model.source}
																		</span>
																	</div>
																	<div className="truncate text-[10px] text-slate-500">
																		{model.model_id} ·{" "}
																		{(model.lanes ?? []).join(", ") || "no lanes"}
																	</div>
																</div>
																<button
																	type="button"
																	onClick={() =>
																		void handleToggleModelEnabled(
																			provider.provider_id,
																			model,
																		)
																	}
																	disabled={isBusy}
																	className={`shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold disabled:opacity-50 ${model.enabled ? "border-red-500/30 bg-red-500/10 text-red-200" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"}`}
																>
																	{model.enabled ? "Disable" : "Enable"}
																</button>
															</div>
														),
													)}
												</div>

												<div className="space-y-2 rounded-lg border border-dashed border-slate-700 p-2">
													<div className="text-xs font-semibold text-slate-300">
														Add custom model
													</div>
													<input
														value={
															customModelDraft[provider.provider_id]?.model_id || ""
														}
														onChange={(event) =>
															setCustomDraftField(provider.provider_id, {
																model_id: event.target.value,
															})
														}
														placeholder="model_id (e.g. deepseek-reasoner)"
														className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-blue-400/60"
													/>
													<input
														value={
															customModelDraft[provider.provider_id]?.label || ""
														}
														onChange={(event) =>
															setCustomDraftField(provider.provider_id, {
																label: event.target.value,
															})
														}
														placeholder="Label (optional)"
														className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-blue-400/60"
													/>
													<div className="flex flex-wrap gap-3 text-[11px] text-slate-400">
														{["text_assist", "vision"]
															.filter((lane) =>
																laneAllowedForProvider(provider.provider_id, lane),
															)
															.map((lane) => (
																<label
																	key={lane}
																	className="flex items-center gap-1"
																>
																	<input
																		type="checkbox"
																		checked={(
																			customModelDraft[provider.provider_id]?.lanes ||
																			[]
																		).includes(lane)}
																		onChange={() =>
																			toggleCustomLane(provider.provider_id, lane)
																		}
																		className="accent-blue-500"
																	/>
																	{lane}
																</label>
															))}
													</div>
													<button
														type="button"
														onClick={() =>
															void handleAddCustomModel(provider.provider_id)
														}
														disabled={isBusy}
														className="w-full rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-200 hover:border-blue-400 disabled:opacity-50"
													>
														Add custom model
													</button>
												</div>
											</div>
										) : null}

										<div className="grid grid-cols-3 gap-2">
											<button
												type="button"
												onClick={() => void handleSaveKey(provider.provider_id)}
												disabled={isBusy || !draftValue.trim()}
												className="rounded-lg border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-blue-400/50 hover:text-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
											>
												Save Key
											</button>
											<button
												type="button"
												onClick={() => void handleActivate(provider)}
												disabled={
													isBusy || (!provider.has_key && !draftValue.trim())
												}
												className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 hover:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
											>
												Activate
											</button>
											<button
												type="button"
												onClick={() => void handleClearKey(provider.provider_id)}
												disabled={isBusy || !provider.has_key}
												className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-200 hover:border-red-400 disabled:cursor-not-allowed disabled:opacity-50"
											>
												Clear
											</button>
										</div>

										<div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-[11px] text-slate-400 sm:grid-cols-2">
											<div className="min-w-0">
												<div className="mb-1 uppercase tracking-wide text-slate-500">
													Stored Key
												</div>
												<div className="break-all">
													{provider.masked_key || "Not stored"}
												</div>
											</div>
											<div className="min-w-0">
												<div className="mb-1 uppercase tracking-wide text-slate-500">
													Last Updated
												</div>
												<div className="break-words">
													{provider.updated_at
														? new Date(provider.updated_at).toLocaleString()
														: "Never"}
												</div>
											</div>
										</div>
									</div>
								</div>
							);
						}) : (
							PROVIDER_LOADING_LABELS.map((label) => (
								<div
									key={label}
									className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5 shadow-lg"
								>
									<div className="mb-3 text-base font-bold text-white">{label}</div>
									<div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/40 p-4 text-sm text-slate-400">
										Loading AI provider registry…
									</div>
								</div>
							))
						)}
					</div>
				</section>
			</div>

			<section className="space-y-4">
				<div className="flex items-center justify-between">
					<h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
						Lane Settings
					</h3>
					<div className="text-xs text-slate-500">
						Route: <code>/api/ai-providers/lanes/&#123;lane&#125;</code>
					</div>
				</div>
				<div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-xs text-slate-400">
					The <span className="font-semibold text-slate-200">global active provider</span>{" "}
					above is a legacy runtime-wide selector. Lane Settings decide which
					provider/model each AI task actually uses. The{" "}
					<span className="font-semibold text-slate-200">Text Assist</span> lane
					powers <span className="font-semibold text-slate-200">AI Copy Assist</span>{" "}
					(candidate copy only — never the final deterministic prompt). The{" "}
					<span className="font-semibold text-slate-200">Vision</span> lane powers
					product-image vision tasks. Lanes ship{" "}
					<span className="font-semibold text-slate-200">NOT CONFIGURED</span> — a lane
					is inactive until provider, model, key, and the execution toggle are all
					configured.
				</div>
				<div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
					{providerRegistry?.lanes?.length
						? providerRegistry.lanes.map((setting) => {
								const laneBusy = mutatingProviderId === `lane:${setting.lane}`;
								const laneProviders = providersForLane(setting.lane);
								const draftProvider = laneProviderDraft[setting.lane];
								const displayProvider =
									draftProvider !== undefined
										? draftProvider
										: setting.provider_id || "";
								const providerChanged =
									draftProvider !== undefined &&
									draftProvider !== (setting.provider_id || "");
								const modelValue = providerChanged
									? ""
									: setting.model_id || "";
								const laneModels = modelsForLane(
									(displayProvider || null) as AIProviderId | null,
									setting.lane,
								);
								const executionAllowed =
									setting.key_present && setting.model_valid;
								return (
									<div
										key={setting.lane}
										className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900/40 p-5 shadow-lg"
									>
										<div className="mb-4 flex items-center justify-between gap-3">
											<div>
												<h4 className="text-base font-bold text-white">
													{setting.label} Lane
												</h4>
												<div className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">
													Lane id: {setting.lane}
												</div>
											</div>
											<span
												className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${LANE_STATUS_STYLE[setting.status] || LANE_STATUS_STYLE.NOT_CONFIGURED}`}
											>
												{(setting.status ?? "NOT_CONFIGURED").replaceAll("_", " ")}
											</span>
										</div>

										<div className="space-y-3">
											<div className="space-y-2">
												<label className="text-xs font-medium text-slate-400">
													Provider
												</label>
												<select
													value={displayProvider}
													onChange={(event) =>
														setLaneProviderDraft((current) => ({
															...current,
															[setting.lane]: event.target.value,
														}))
													}
													disabled={laneBusy}
													className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
												>
													<option value="">Select provider…</option>
													{laneProviders.map((provider) => (
														<option
															key={provider.provider_id}
															value={provider.provider_id}
														>
															{provider.label}
														</option>
													))}
												</select>
											</div>

											<div className="space-y-2">
												<label className="text-xs font-medium text-slate-400">
													Model
												</label>
												<select
													value={modelValue}
													onChange={(event) =>
														displayProvider && event.target.value
															? void handleSaveLane(
																	setting.lane,
																	displayProvider as AIProviderId,
																	event.target.value,
																)
															: undefined
													}
													disabled={laneBusy || !displayProvider}
													className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
												>
													<option value="">Select model…</option>
													{laneModels.map((model) => (
														<option key={model.model_id} value={model.model_id}>
															{model.label}
														</option>
													))}
												</select>
											</div>

											<label className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-2 text-xs text-slate-300">
												<span>Execution enabled</span>
												<input
													type="checkbox"
													checked={setting.execution_enabled}
													onChange={(event) =>
														setting.provider_id && setting.model_id
															? void handleSaveLane(
																	setting.lane,
																	setting.provider_id,
																	setting.model_id,
																	event.target.checked,
																)
															: undefined
													}
													disabled={laneBusy || !executionAllowed}
													className="h-4 w-4 cursor-pointer accent-emerald-500 disabled:cursor-not-allowed"
												/>
											</label>

											<div className="flex items-center justify-between gap-2">
												<div className="text-[11px] text-slate-500">
													{setting.lane === "text_assist"
														? "Consumed by AI Copy Assist candidate generation."
														: "Consumed by product-image vision tasks."}
												</div>
												<button
													type="button"
													onClick={() => void handleClearLane(setting.lane)}
													disabled={laneBusy || !setting.configured_by_user}
													className="shrink-0 rounded border border-slate-700 bg-slate-950/70 px-2 py-1 text-[10px] font-semibold text-slate-300 hover:border-red-400/50 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-40"
												>
													Clear
												</button>
											</div>
										</div>
									</div>
								);
							})
						: null}
				</div>
				<div className="flex justify-end">
					<button
						type="button"
						onClick={() => void handleResetSeedCatalog()}
						disabled={mutatingProviderId === "catalog:reset"}
						className="rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-blue-400/50 hover:text-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
					>
						Reset models to seed
					</button>
				</div>
			</section>

			<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 text-xs text-blue-300">
				Local secrets are persisted under the Flow Kit local-agent state
				directory. No API key is written into tracked repo files. Activation is
				fail-closed: a provider cannot become active until a key is stored, and a
				lane cannot execute until its provider key + model are configured and its
				execution toggle is on.
			</div>
		</div>
	);
}
