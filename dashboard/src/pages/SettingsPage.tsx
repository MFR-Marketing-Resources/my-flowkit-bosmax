import { startTransition, useEffect, useState } from "react";
import { fetchAPI } from "../api/client";
import { useWebSocketContext } from "../contexts/WebSocketContext";
import type {
	AIProviderId,
	AIProviderLaneSetting,
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

export default function SettingsPage() {
	const [agentStatus, setAgentStatus] = useState<LocalAgentStatus | null>(null);
	const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null);
	const [providerRegistry, setProviderRegistry] =
		useState<AIProviderRegistry | null>(null);
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
	const { isConnected } = useWebSocketContext();

	const applyRegistry = (registry: AIProviderRegistry) => {
		startTransition(() => {
			setProviderRegistry(registry);
		});
	};

	const refreshStatus = async () => {
		try {
			const [status, tel, providers] = await Promise.all([
				fetchAPI<LocalAgentStatus>("/api/local-agent/status"),
				fetchAPI<TelemetrySummary>("/api/telemetry/summary"),
				fetchAPI<AIProviderRegistry>("/api/ai-providers"),
			]);
			startTransition(() => {
				setAgentStatus(status);
				setTelemetry(tel);
				setProviderRegistry(providers);
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

	const modelsForLane = (
		providerId: AIProviderId | null,
		lane: string,
	): AIProviderModelOption[] => {
		if (!providerId || !providerRegistry) return [];
		return (providerRegistry.model_catalog[providerId] || []).filter((model) =>
			model.lanes.includes(lane),
		);
	};

	const providersForLane = (lane: string): AIProviderSummary[] => {
		if (!providerRegistry) return [];
		return providerRegistry.providers.filter((provider) =>
			provider.supported_lanes.includes(lane),
		);
	};

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
	};

	const handleLaneProviderChange = async (
		lane: string,
		providerId: AIProviderId,
	) => {
		const models = modelsForLane(providerId, lane);
		const firstModel = models[0]?.model_id;
		if (!firstModel) {
			setBannerError(
				`${providerId.toUpperCase()} has no model that supports the ${lane} lane.`,
			);
			return;
		}
		await handleSaveLane(lane, providerId, firstModel);
	};

	const laneStatus = (setting: AIProviderLaneSetting) => {
		if (!setting.provider_id) {
			return {
				label: "NO PROVIDER",
				className: "border-slate-700 bg-slate-900 text-slate-400",
			};
		}
		const hasKey = providerRegistry?.providers.find(
			(provider) => provider.provider_id === setting.provider_id,
		)?.has_key;
		if (!hasKey) {
			return {
				label: "KEY MISSING",
				className: "border-amber-500/40 bg-amber-500/10 text-amber-300",
			};
		}
		if (!setting.configured) {
			return {
				label: "MODEL INVALID",
				className: "border-amber-500/40 bg-amber-500/10 text-amber-300",
			};
		}
		return setting.execution_enabled
			? {
					label: "ACTIVE",
					className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
				}
			: {
					label: "READY (DISABLED)",
					className: "border-slate-700 bg-slate-900 text-slate-400",
				};
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
											<div>{provider.current_capabilities.join(" • ")}</div>
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

										{(providerRegistry?.model_catalog?.[provider.provider_id]
											?.length ?? 0) > 0 ? (
											<div className="space-y-2">
												<label className="text-xs font-medium text-slate-400">
													Default Model
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
													{providerRegistry?.model_catalog?.[
														provider.provider_id
													]?.map((model) => (
														<option key={model.model_id} value={model.model_id}>
															{model.label}
														</option>
													))}
												</select>
												<div className="text-[11px] text-slate-500">
													Supported lanes:{" "}
													{provider.supported_lanes.length
														? provider.supported_lanes.join(", ")
														: "—"}
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
					above is a legacy runtime-wide selector. Lane Settings are what decide
					which provider/model each AI task actually uses. The{" "}
					<span className="font-semibold text-slate-200">Text Assist</span> lane
					powers <span className="font-semibold text-slate-200">AI Copy Assist</span>{" "}
					(candidate copy only — never the final deterministic prompt). The{" "}
					<span className="font-semibold text-slate-200">Vision</span> lane powers
					product-image vision tasks. A lane runs only when it has a stored key and
					its execution toggle is on.
				</div>
				<div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
					{providerRegistry?.lanes?.length
						? providerRegistry.lanes.map((setting) => {
								const status = laneStatus(setting);
								const laneBusy = mutatingProviderId === `lane:${setting.lane}`;
								const laneProviders = providersForLane(setting.lane);
								const laneModels = modelsForLane(
									setting.provider_id,
									setting.lane,
								);
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
												className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${status.className}`}
											>
												{status.label}
											</span>
										</div>

										<div className="space-y-3">
											<div className="space-y-2">
												<label className="text-xs font-medium text-slate-400">
													Provider
												</label>
												<select
													value={setting.provider_id || ""}
													onChange={(event) =>
														void handleLaneProviderChange(
															setting.lane,
															event.target.value as AIProviderId,
														)
													}
													disabled={laneBusy}
													className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
												>
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
													value={setting.model_id || ""}
													onChange={(event) =>
														setting.provider_id
															? void handleSaveLane(
																	setting.lane,
																	setting.provider_id,
																	event.target.value,
																)
															: undefined
													}
													disabled={laneBusy || !setting.provider_id}
													className="min-w-0 w-full rounded-lg border border-slate-800 bg-slate-950 px-4 py-2 text-sm text-slate-200 outline-none transition focus:border-blue-400/60 disabled:cursor-not-allowed disabled:opacity-60"
												>
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
													disabled={laneBusy || !setting.configured}
													className="h-4 w-4 cursor-pointer accent-emerald-500 disabled:cursor-not-allowed"
												/>
											</label>
											<div className="text-[11px] text-slate-500">
												{setting.lane === "text_assist"
													? "Consumed by AI Copy Assist candidate generation."
													: "Consumed by product-image vision tasks."}
											</div>
										</div>
									</div>
								);
							})
						: null}
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
