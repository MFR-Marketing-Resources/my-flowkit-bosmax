import { startTransition, useEffect, useEffectEvent, useState } from "react";
import { fetchAPI } from "../api/client";
import { useWebSocketContext } from "../contexts/WebSocketContext";
import type {
	AIExecutionMode,
	AILaneId,
	AIModelCatalog,
	AIProviderId,
	AIProviderRegistry,
	AIProviderSummary,
	AIRoutingLane,
	AIRoutingProviderId,
	AIRoutingRegistry,
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
					<span className={`h-2 w-2 rounded-full ${deploymentTone.dotClass}`} />
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
const ROUTING_MODE_OPTIONS: AIExecutionMode[] = [
	"disabled",
	"registry_only",
	"live",
];
const ROUTING_MODE_ACCENT: Record<AIExecutionMode, string> = {
	disabled: "border-slate-700 bg-slate-900 text-slate-400",
	registry_only: "border-amber-500/40 bg-amber-500/10 text-amber-300",
	live: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
};
type RoutingDraft = {
	provider_id: AIRoutingProviderId;
	model_id: string;
	enabled: boolean;
	execution_mode: AIExecutionMode;
};

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

function createEmptyRoutingDrafts(): Record<AILaneId, RoutingDraft> {
	return {
		product_image_analysis: {
			provider_id: "anthropic",
			model_id: "",
			enabled: false,
			execution_mode: "registry_only",
		},
		copywriting_assist: {
			provider_id: "qwen",
			model_id: "",
			enabled: false,
			execution_mode: "registry_only",
		},
		angle_hook_subhook_expansion: {
			provider_id: "deepseek",
			model_id: "",
			enabled: false,
			execution_mode: "registry_only",
		},
		claim_risk_qa: {
			provider_id: "openai",
			model_id: "",
			enabled: false,
			execution_mode: "registry_only",
		},
		product_truth_extraction: {
			provider_id: "gemini",
			model_id: "",
			enabled: false,
			execution_mode: "registry_only",
		},
		video_review: {
			provider_id: "anthropic",
			model_id: "",
			enabled: false,
			execution_mode: "registry_only",
		},
		final_prompt_compiler: {
			provider_id: "deterministic",
			model_id: "bosmax-canonical-compiler",
			enabled: true,
			execution_mode: "live",
		},
	};
}

function buildRoutingDrafts(
	registry: AIRoutingRegistry,
): Record<AILaneId, RoutingDraft> {
	const nextDrafts = createEmptyRoutingDrafts();
	for (const lane of registry.lanes) {
		nextDrafts[lane.lane_id] = {
			provider_id: lane.provider_id,
			model_id: lane.model_id,
			enabled: lane.enabled,
			execution_mode: lane.execution_mode,
		};
	}
	return nextDrafts;
}

function getRoutingCardTone(lane: AIRoutingLane) {
	if (lane.locked) {
		return "border-purple-500/30 bg-purple-500/5";
	}
	if (lane.is_executable_now) {
		return "border-emerald-500/30 bg-emerald-500/5";
	}
	if (lane.provider_has_key) {
		return "border-amber-500/20 bg-slate-900/40";
	}
	return "border-slate-800 bg-slate-900/30";
}

export default function SettingsPage() {
	const [agentStatus, setAgentStatus] = useState<LocalAgentStatus | null>(null);
	const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null);
	const [providerRegistry, setProviderRegistry] =
		useState<AIProviderRegistry | null>(null);
	const [modelCatalog, setModelCatalog] = useState<AIModelCatalog | null>(null);
	const [routingRegistry, setRoutingRegistry] =
		useState<AIRoutingRegistry | null>(null);
	const [draftKeys, setDraftKeys] = useState<Record<AIProviderId, string>>({
		qwen: "",
		anthropic: "",
		openai: "",
		gemini: "",
		deepseek: "",
	});
	const [routingDrafts, setRoutingDrafts] = useState<
		Record<AILaneId, RoutingDraft>
	>(createEmptyRoutingDrafts());
	const [mutatingProviderId, setMutatingProviderId] = useState<string | null>(
		null,
	);
	const [mutatingLaneId, setMutatingLaneId] = useState<string | null>(null);
	const [bannerMessage, setBannerMessage] = useState<string | null>(null);
	const [bannerError, setBannerError] = useState<string | null>(null);
	const { isConnected } = useWebSocketContext();

	const applyRegistry = (registry: AIProviderRegistry) => {
		startTransition(() => {
			setProviderRegistry(registry);
		});
	};

	const applyRouting = (routing: AIRoutingRegistry) => {
		startTransition(() => {
			setRoutingRegistry(routing);
			setRoutingDrafts(buildRoutingDrafts(routing));
		});
	};

	const refreshStatus = async () => {
		try {
			const [status, tel, providers, catalog, routing] = await Promise.all([
				fetchAPI<LocalAgentStatus>("/api/local-agent/status"),
				fetchAPI<TelemetrySummary>("/api/telemetry/summary"),
				fetchAPI<AIProviderRegistry>("/api/ai-providers"),
				fetchAPI<AIModelCatalog>("/api/ai-model-catalog"),
				fetchAPI<AIRoutingRegistry>("/api/ai-routing"),
			]);
			startTransition(() => {
				setAgentStatus(status);
				setTelemetry(tel);
				setProviderRegistry(providers);
				setModelCatalog(catalog);
				setRoutingRegistry(routing);
				setRoutingDrafts(buildRoutingDrafts(routing));
			});
		} catch (err) {
			console.error("Failed to fetch settings status", err);
			setBannerError(
				err instanceof Error
					? err.message
					: "Failed to load AI provider settings.",
			);
		}
	};

	const handleRefreshStatus = useEffectEvent(() => {
		void refreshStatus();
	});

	useEffect(() => {
		handleRefreshStatus();
		const timer = setInterval(() => {
			handleRefreshStatus();
		}, 10000);
		return () => clearInterval(timer);
	}, []);

	const setDraftValue = (providerId: AIProviderId, value: string) => {
		setDraftKeys((current) => ({ ...current, [providerId]: value }));
	};

	const runProviderMutation = async (
		providerId: AIProviderId | "GLOBAL",
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

	const runRoutingMutation = async (
		laneId: AILaneId | "GLOBAL",
		task: () => Promise<AIRoutingRegistry>,
		successMessage: string,
	) => {
		setMutatingLaneId(laneId);
		setBannerError(null);
		setBannerMessage(null);
		try {
			const payload = await task();
			applyRouting(payload);
			setBannerMessage(successMessage);
		} catch (err) {
			setBannerError(
				err instanceof Error ? err.message : "Routing mutation failed.",
			);
		} finally {
			setMutatingLaneId(null);
		}
	};

	const getCompatibleModels = (
		laneId: AILaneId,
		providerId: AIRoutingProviderId,
	) => {
		const providerEntry = modelCatalog?.providers.find(
			(provider) => provider.provider_id === providerId,
		);
		return (
			providerEntry?.models.filter(
				(model) =>
					model.recommended_lanes.includes(laneId) ||
					model.default_for_lanes.includes(laneId),
			) || []
		);
	};

	const getRoutingProvidersForLane = (laneId: AILaneId) =>
		modelCatalog?.providers.filter(
			(provider) =>
				getCompatibleModels(laneId, provider.provider_id).length > 0,
		) || [];

	const setRoutingDraftValue = (
		laneId: AILaneId,
		nextValue: Partial<RoutingDraft>,
	) => {
		setRoutingDrafts((current) => ({
			...current,
			[laneId]: {
				...current[laneId],
				...nextValue,
			},
		}));
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
					throw new Error(
						"Paste an API key first, then activate the provider.",
					);
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

	const handleRoutingProviderChange = (
		laneId: AILaneId,
		providerId: AIRoutingProviderId,
	) => {
		const compatibleModels = getCompatibleModels(laneId, providerId);
		const nextModelId =
			compatibleModels.find((model) => model.default_for_lanes.includes(laneId))
				?.model_id ||
			compatibleModels[0]?.model_id ||
			"";
		setRoutingDraftValue(laneId, {
			provider_id: providerId,
			model_id: nextModelId,
		});
	};

	const handleRoutingSave = async (laneId: AILaneId) => {
		const draft = routingDrafts[laneId];
		await runRoutingMutation(
			laneId,
			async () =>
				fetchAPI<AIRoutingRegistry>(`/api/ai-routing/${laneId}`, {
					method: "PUT",
					body: JSON.stringify(draft),
				}),
			`${laneId} routing saved.`,
		);
	};

	const handleRoutingReset = async () => {
		await runRoutingMutation(
			"GLOBAL",
			async () =>
				fetchAPI<AIRoutingRegistry>("/api/ai-routing/reset", {
					method: "POST",
					body: JSON.stringify({}),
				}),
			"AI model routing reset to repo-safe defaults.",
		);
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

			<DeploymentStatusCard agentStatus={agentStatus} />

			{bannerMessage ? (
				<div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
					{bannerMessage}
				</div>
			) : null}
			{bannerError ? (
				<div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
					{bannerError}
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
										? Math.round(
												(telemetry.completed / telemetry.total_today) * 100,
											)
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
								<span className="font-bold text-white">
									{activeProviderLabel}
								</span>
							</div>
						</div>
						<div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-xs text-slate-400">
							`LIVE_NOW` providers can affect existing runtime lanes
							immediately. `REGISTRY_ONLY` providers are stored, activatable,
							and ready for the next module wave.
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
						{providerRegistry?.providers.length
							? providerRegistry.providers.map((provider) => {
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
													<div>{provider.current_capabilities.join(" • ")}</div>
												</div>

												<div className="space-y-2">
													<label
														htmlFor={`provider-key-${provider.provider_id}`}
														className="text-xs font-medium text-slate-400"
													>
														API Key
													</label>
													<input
														id={`provider-key-${provider.provider_id}`}
														type="password"
														value={draftValue}
														onChange={(event) =>
															setDraftValue(
																provider.provider_id,
																event.target.value,
															)
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

												<div className="grid grid-cols-3 gap-2">
													<button
														type="button"
														onClick={() =>
															void handleSaveKey(provider.provider_id)
														}
														disabled={isBusy || !draftValue.trim()}
														className="rounded-lg border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-blue-400/50 hover:text-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
													>
														Save Key
													</button>
													<button
														type="button"
														onClick={() => void handleActivate(provider)}
														disabled={
															isBusy ||
															(!provider.has_key && !draftValue.trim())
														}
														className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 hover:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
													>
														Activate
													</button>
													<button
														type="button"
														onClick={() =>
															void handleClearKey(provider.provider_id)
														}
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
								})
							: PROVIDER_LOADING_LABELS.map((label) => (
									<div
										key={label}
										className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5 shadow-lg"
									>
										<div className="mb-3 text-base font-bold text-white">
											{label}
										</div>
										<div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/40 p-4 text-sm text-slate-400">
											Loading AI provider registry…
										</div>
									</div>
								))}
					</div>
				</section>
			</div>

			<section className="space-y-4">
				<div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
					<div>
						<h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
							AI Model Routing
						</h3>
						<div className="mt-1 text-xs text-slate-500">
							Routes: <code>/api/ai-model-catalog</code> ·{" "}
							<code>/api/ai-routing</code>
						</div>
					</div>
					<button
						type="button"
						onClick={() => void handleRoutingReset()}
						disabled={mutatingLaneId === "GLOBAL"}
						className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 hover:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
					>
						Reset AI Routing
					</button>
				</div>

				<div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
					{routingRegistry?.lanes.length ? (
						routingRegistry.lanes.map((lane) => {
							const isBusy = mutatingLaneId === lane.lane_id;
							const draft = routingDrafts[lane.lane_id];
							const providerOptions = getRoutingProvidersForLane(lane.lane_id);
							const modelOptions = getCompatibleModels(
								lane.lane_id,
								draft.provider_id,
							);

							return (
								<div
									key={lane.lane_id}
									className={`rounded-2xl border p-5 shadow-lg ${getRoutingCardTone(lane)}`}
								>
									<div className="mb-4 flex items-start justify-between gap-4">
										<div className="min-w-0">
											<div className="flex flex-wrap items-center gap-2">
												<h4 className="text-base font-bold text-white">
													{lane.label}
												</h4>
												<span
													className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${ROUTING_MODE_ACCENT[lane.execution_mode]}`}
												>
													{lane.execution_mode.toUpperCase()}
												</span>
												{lane.locked ? (
													<span className="rounded-full border border-purple-500/40 bg-purple-500/10 px-2 py-0.5 text-[10px] font-bold text-purple-200">
														LOCKED
													</span>
												) : null}
											</div>
											<div className="mt-1 text-sm text-slate-400">
												{lane.description}
											</div>
										</div>
										<div className="text-right text-[11px] text-slate-400">
											<div>
												{lane.is_executable_now
													? "EXECUTION READY"
													: "FAIL-CLOSED"}
											</div>
											<div>Key: {lane.provider_key_status}</div>
										</div>
									</div>

									<div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-4 md:grid-cols-2">
										<div className="space-y-2">
											<label
												htmlFor={`routing-provider-${lane.lane_id}`}
												className="text-xs font-medium text-slate-400"
											>
												Provider
											</label>
											<select
												id={`routing-provider-${lane.lane_id}`}
												value={draft.provider_id}
												onChange={(event) =>
													handleRoutingProviderChange(
														lane.lane_id,
														event.target.value as AIRoutingProviderId,
													)
												}
												disabled={lane.locked || isBusy}
												className="w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
											>
												{providerOptions.map((provider) => (
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
											<label
												htmlFor={`routing-model-${lane.lane_id}`}
												className="text-xs font-medium text-slate-400"
											>
												Model
											</label>
											<select
												id={`routing-model-${lane.lane_id}`}
												value={draft.model_id}
												onChange={(event) =>
													setRoutingDraftValue(lane.lane_id, {
														model_id: event.target.value,
													})
												}
												disabled={lane.locked || isBusy}
												className="w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
											>
												{modelOptions.map((model) => (
													<option key={model.model_id} value={model.model_id}>
														{model.label}
													</option>
												))}
											</select>
										</div>
										<div className="space-y-2">
											<label
												htmlFor={`routing-enabled-${lane.lane_id}`}
												className="text-xs font-medium text-slate-400"
											>
												Enabled
											</label>
											<label className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200">
												<input
													id={`routing-enabled-${lane.lane_id}`}
													type="checkbox"
													checked={draft.enabled}
													onChange={(event) =>
														setRoutingDraftValue(lane.lane_id, {
															enabled: event.target.checked,
														})
													}
													disabled={lane.locked || isBusy}
												/>
												<span>
													{draft.enabled ? "Lane enabled" : "Lane disabled"}
												</span>
											</label>
										</div>
										<div className="space-y-2">
											<label
												htmlFor={`routing-mode-${lane.lane_id}`}
												className="text-xs font-medium text-slate-400"
											>
												Execution Mode
											</label>
											<select
												id={`routing-mode-${lane.lane_id}`}
												value={draft.execution_mode}
												onChange={(event) =>
													setRoutingDraftValue(lane.lane_id, {
														execution_mode: event.target
															.value as AIExecutionMode,
														enabled:
															event.target.value === "disabled"
																? false
																: draft.enabled,
													})
												}
												disabled={lane.locked || isBusy}
												className="w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
											>
												{ROUTING_MODE_OPTIONS.map((mode) => (
													<option key={mode} value={mode}>
														{mode}
													</option>
												))}
											</select>
										</div>
									</div>

									<div className="mt-4 grid grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-4 text-[11px] text-slate-400 md:grid-cols-3">
										<div>
											<div className="mb-1 uppercase tracking-wide text-slate-500">
												Saved Route
											</div>
											<div className="text-slate-200">
												{lane.provider_label} / {lane.model_label}
											</div>
										</div>
										<div>
											<div className="mb-1 uppercase tracking-wide text-slate-500">
												Execution Status
											</div>
											<div className="text-slate-200">
												{lane.is_executable_now
													? "Executable now"
													: "Not executable"}
											</div>
										</div>
										<div>
											<div className="mb-1 uppercase tracking-wide text-slate-500">
												Last Updated
											</div>
											<div className="text-slate-200">
												{lane.updated_at
													? new Date(lane.updated_at).toLocaleString()
													: "System default"}
											</div>
										</div>
									</div>

									{lane.warnings.length ? (
										<div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
											Validation warning: {lane.warnings.join(" • ")}
										</div>
									) : null}

									<div className="mt-4 flex flex-wrap gap-3">
										<button
											type="button"
											onClick={() => void handleRoutingSave(lane.lane_id)}
											disabled={lane.locked || isBusy || !draft.model_id}
											className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-200 hover:border-blue-400 disabled:cursor-not-allowed disabled:opacity-50"
										>
											Update Route
										</button>
										{lane.locked ? (
											<div className="rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-2 text-xs font-semibold text-purple-200">
												Deterministic compiler locked to
												`bosmax-canonical-compiler`
											</div>
										) : null}
									</div>
								</div>
							);
						})
					) : (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5 shadow-lg text-sm text-slate-400">
							Loading AI model routing…
						</div>
					)}
				</div>
			</section>

			<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 text-xs text-blue-300">
				Local secrets are persisted under the Flow Kit local-agent state
				directory. No API key is written into tracked repo files. Activation is
				fail-closed: a provider cannot become active until a key is stored.
			</div>
		</div>
	);
}
