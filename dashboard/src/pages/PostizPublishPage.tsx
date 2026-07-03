import {
	AlertTriangle,
	CheckCircle2,
	Film,
	RefreshCw,
	Send,
	ShieldCheck,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type {
	PostizHealth,
	PostizIntegration,
	PostizPostType,
	PostizProviderTemplatesResponse,
	PostizPublishRecord,
	PostizPublishSuccess,
} from "../api/postiz";
import {
	getPostizHealth,
	getPostizIntegrations,
	getPostizProviderTemplates,
	getPostizPublishRecords,
	publishToPostiz,
} from "../api/postiz";

// POSTIZ PUBLISH — send a BOSMAX-generated artifact straight to Postiz
// (no manual re-upload). Fail-closed UX: if the backend health check is
// not OK, only the setup banner renders. Publishing defaults to draft —
// nothing goes public unless the operator explicitly chooses otherwise.

interface LibraryArtifact {
	media_id: string;
	mode: string | null;
	artifact_kind: "video" | "image";
	local_path?: string | null;
	size_mb: number | null;
	created_at: string;
}

const RECORD_STATUS_COLORS: Record<string, string> = {
	PENDING: "border-slate-700 bg-slate-800 text-slate-400",
	UPLOADED: "border-blue-500/40 bg-blue-500/15 text-blue-300",
	POST_CREATED: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
	FAILED: "border-red-500/40 bg-red-500/15 text-red-300",
};

const TIKTOK_PRIVACY_OPTIONS = [
	"SELF_ONLY",
	"PUBLIC_TO_EVERYONE",
	"MUTUAL_FOLLOW_FRIENDS",
	"FOLLOWER_OF_CREATOR",
] as const;

const DEFAULT_TIKTOK_PRIVACY = "SELF_ONLY";

function StatusBadge({ status }: { status: string }) {
	return (
		<span
			className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-widest whitespace-nowrap ${RECORD_STATUS_COLORS[status] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
		>
			{status}
		</span>
	);
}

function StepHeading({ step, title }: { step: string; title: string }) {
	return (
		<div className="flex items-center gap-2">
			<span className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-blue-500/40 bg-blue-500/10 text-[11px] font-bold text-blue-300">
				{step}
			</span>
			<span className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
				{title}
			</span>
		</div>
	);
}

export default function PostizPublishPage() {
	const [health, setHealth] = useState<PostizHealth | null>(null);
	const [healthError, setHealthError] = useState<string | null>(null);
	const [artifacts, setArtifacts] = useState<LibraryArtifact[]>([]);
	const [integrations, setIntegrations] = useState<PostizIntegration[]>([]);
	const [templates, setTemplates] =
		useState<PostizProviderTemplatesResponse | null>(null);
	const [records, setRecords] = useState<PostizPublishRecord[]>([]);
	const [loading, setLoading] = useState(true);

	// Form state
	const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(
		null,
	);
	const [selectedChannelIds, setSelectedChannelIds] = useState<string[]>([]);
	const [tiktokPrivacy, setTiktokPrivacy] = useState<Record<string, string>>(
		{},
	);
	const [content, setContent] = useState("");
	const [postType, setPostType] = useState<PostizPostType>("draft");
	const [scheduleAtLocal, setScheduleAtLocal] = useState("");

	// Action state
	const [busy, setBusy] = useState(false);
	const [dryRunPayload, setDryRunPayload] = useState<unknown>(null);
	const [dryRunNote, setDryRunNote] = useState<string | null>(null);
	const [publishResult, setPublishResult] =
		useState<PostizPublishSuccess | null>(null);
	const [publishError, setPublishError] = useState<string | null>(null);

	const loadRecords = useCallback(async () => {
		try {
			const resp = await getPostizPublishRecords();
			setRecords(resp.records ?? []);
		} catch {
			// audit trail is best-effort; publish errors surface elsewhere
		}
	}, []);

	const loadAll = useCallback(async () => {
		setLoading(true);
		setHealthError(null);
		try {
			const h = await getPostizHealth();
			setHealth(h);
			if (h.ok) {
				const [artResp, intResp, tplResp] = await Promise.all([
					fetch("/api/flow/artifacts?limit=50").then(async (r) => {
						if (!r.ok) throw new Error(`HTTP ${r.status}`);
						return r.json() as Promise<{ artifacts?: LibraryArtifact[] }>;
					}),
					getPostizIntegrations(),
					getPostizProviderTemplates(),
				]);
				setArtifacts(
					Array.isArray(artResp.artifacts) ? artResp.artifacts : [],
				);
				setIntegrations(intResp.integrations ?? []);
				setTemplates(tplResp);
				await loadRecords();
			}
		} catch (e) {
			setHealthError(String(e));
		} finally {
			setLoading(false);
		}
	}, [loadRecords]);

	useEffect(() => {
		void loadAll();
	}, [loadAll]);

	const channelsByProvider = useMemo(() => {
		const groups: Record<string, PostizIntegration[]> = {};
		for (const ch of integrations) {
			const key = ch.provider || "unknown";
			(groups[key] ??= []).push(ch);
		}
		return groups;
	}, [integrations]);

	const toggleChannel = (id: string, selectable: boolean) => {
		if (!selectable) return;
		setSelectedChannelIds((prev) =>
			prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
		);
	};

	// provider_settings[channelId] = {...template} (+ privacy_level for tiktok)
	const buildProviderSettings = useCallback(():
		| Record<string, Record<string, unknown>>
		| undefined => {
		if (!templates) return undefined;
		const settings: Record<string, Record<string, unknown>> = {};
		for (const id of selectedChannelIds) {
			const channel = integrations.find((c) => c.id === id);
			if (!channel) continue;
			const template = templates.templates[channel.provider];
			if (!template) continue;
			if (channel.provider === "tiktok") {
				settings[id] = {
					...template,
					privacy_level: tiktokPrivacy[id] ?? DEFAULT_TIKTOK_PRIVACY,
				};
			} else {
				settings[id] = { ...template };
			}
		}
		return Object.keys(settings).length > 0 ? settings : undefined;
	}, [templates, selectedChannelIds, integrations, tiktokPrivacy]);

	const buildRequest = useCallback(
		(dryRun: boolean) => {
			let scheduleAtIso: string | undefined;
			if (postType === "schedule" && scheduleAtLocal) {
				scheduleAtIso = new Date(scheduleAtLocal).toISOString();
			}
			return {
				artifact_media_id: selectedArtifactId ?? "",
				integration_ids: selectedChannelIds,
				post_type: postType,
				schedule_at: scheduleAtIso,
				content,
				provider_settings: buildProviderSettings(),
				dry_run: dryRun,
			};
		},
		[
			selectedArtifactId,
			selectedChannelIds,
			postType,
			scheduleAtLocal,
			content,
			buildProviderSettings,
		],
	);

	const canSubmit =
		!busy &&
		Boolean(selectedArtifactId) &&
		selectedChannelIds.length > 0 &&
		(postType !== "schedule" || Boolean(scheduleAtLocal));

	const handleDryRun = async () => {
		setBusy(true);
		setPublishError(null);
		setPublishResult(null);
		setDryRunPayload(null);
		setDryRunNote(null);
		try {
			const resp = await publishToPostiz(buildRequest(true));
			if ("dry_run" in resp && resp.dry_run) {
				setDryRunPayload(resp.payload);
				setDryRunNote(resp.note);
			}
		} catch (e) {
			setPublishError(String(e));
		} finally {
			setBusy(false);
		}
	};

	const handlePublish = async () => {
		setBusy(true);
		setPublishError(null);
		setPublishResult(null);
		setDryRunPayload(null);
		setDryRunNote(null);
		try {
			const resp = await publishToPostiz(buildRequest(false));
			if ("ok" in resp) {
				setPublishResult(resp);
			}
			await loadRecords();
		} catch (e) {
			setPublishError(String(e));
			await loadRecords();
		} finally {
			setBusy(false);
		}
	};

	const healthOk = health?.ok === true;

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			{/* Header */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="flex items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							POSTIZ PUBLISH
						</div>
						<div className="mt-1 text-xs text-slate-400">
							Send a BOSMAX-generated artifact to Postiz without manual
							re-upload. Defaults to draft — nothing goes public unless you
							explicitly choose otherwise.
						</div>
					</div>
					<button
						type="button"
						onClick={() => void loadAll()}
						className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200 transition-colors"
					>
						<RefreshCw size={13} className={loading ? "animate-spin" : ""} />
						Refresh
					</button>
				</div>
				{healthError && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{healthError}
					</div>
				)}
			</section>

			{/* Health banner — fail-closed: setup box only when not OK */}
			{health && !healthOk && (
				<section className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-5 space-y-3">
					<div className="flex items-center gap-2">
						<AlertTriangle size={16} className="text-amber-300" />
						<span className="text-xs font-bold uppercase tracking-[0.18em] text-amber-200">
							Postiz is not ready — setup required
						</span>
					</div>
					{health.problems?.length > 0 && (
						<ul className="space-y-1">
							{health.problems.map((p) => (
								<li
									key={p}
									className="text-[11px] text-amber-200/90 font-mono flex items-start gap-2"
								>
									<span>•</span>
									<span className="min-w-0">{p}</span>
								</li>
							))}
						</ul>
					)}
					<div className="text-[11px] text-amber-200/80">
						See{" "}
						<span className="font-mono text-amber-100">
							docs/integrations/postiz/OPERATOR_GUIDE.md
						</span>{" "}
						for setup instructions (enable the flag, base URL, API key).
					</div>
				</section>
			)}

			{healthOk && (
				<>
					{/* STEP 1 — ARTIFACT */}
					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5 space-y-4">
						<StepHeading step="1" title="Artifact" />
						<div className="text-[11px] text-slate-400">
							Pick one generated artifact from the 48h Library.
						</div>
						{artifacts.length === 0 ? (
							<div className="py-8 text-center text-sm text-slate-500">
								No artifacts in the 48h retention window. Generate something
								first, then come back.
							</div>
						) : (
							<div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
								{artifacts.map((item) => {
									const selected = selectedArtifactId === item.media_id;
									return (
										<button
											type="button"
											key={item.media_id}
											onClick={() =>
												setSelectedArtifactId(
													selected ? null : item.media_id,
												)
											}
											className={`group rounded-xl border p-2 text-left transition-colors ${selected ? "border-blue-400/70 bg-blue-500/10" : "border-slate-800 bg-slate-950/60 hover:border-slate-600"}`}
										>
											{item.artifact_kind === "video" ? (
												<video
													src={`/api/flow/retrieved/${item.media_id}`}
													muted
													playsInline
													preload="metadata"
													className="aspect-[9/16] w-full rounded-lg bg-black object-contain"
												/>
											) : (
												<img
													src={`/api/flow/retrieved/${item.media_id}`}
													alt={item.mode ?? "artifact"}
													loading="lazy"
													className="aspect-[9/16] w-full rounded-lg bg-black object-contain"
												/>
											)}
											<div className="mt-2 flex items-center justify-between text-[10px] text-slate-400">
												<span className="inline-flex items-center gap-1 font-semibold text-slate-300">
													<Film size={11} />
													{item.mode ?? "?"} · {item.artifact_kind}
												</span>
												<span>
													{item.size_mb != null ? `${item.size_mb}MB` : ""}
												</span>
											</div>
											<div className="mt-1 font-mono text-[9px] text-slate-500 truncate">
												{item.media_id}
											</div>
										</button>
									);
								})}
							</div>
						)}
					</section>

					{/* STEP 2 — CHANNELS */}
					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5 space-y-4">
						<StepHeading step="2" title="Channels" />
						<div className="text-[11px] text-slate-400">
							Select one or more connected Postiz channels —
							multiple accounts of the same provider are supported
							(selection is per channel id).
						</div>
						{integrations.length === 0 ? (
							<div className="py-8 text-center text-sm text-slate-500">
								No channels connected in Postiz yet. Connect accounts inside
								Postiz first.
							</div>
						) : (
							<div className="space-y-4">
								{Object.entries(channelsByProvider).map(
									([provider, channels]) => {
										const warnings = templates?.warnings?.[provider] ?? [];
										const template = templates?.templates?.[provider];
										const anySelected = channels.some((c) =>
											selectedChannelIds.includes(c.id),
										);
										return (
											<div
												key={provider}
												className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 space-y-2"
											>
												<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
													{provider}
												</div>
												<div className="space-y-1.5">
													{channels.map((ch) => {
														const unusable =
															ch.disabled === true ||
															ch.refresh_needed === true;
														const checked = selectedChannelIds.includes(
															ch.id,
														);
														return (
															<div key={ch.id} className="space-y-2">
																<label
																	className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${unusable ? "cursor-not-allowed border-slate-800 bg-slate-950/40 opacity-50" : "cursor-pointer border-slate-800 bg-slate-950/60 hover:border-slate-600"} ${checked ? "border-blue-400/60 bg-blue-500/10" : ""}`}
																>
																	<input
																		type="checkbox"
																		checked={checked}
																		disabled={unusable}
																		onChange={() =>
																			toggleChannel(ch.id, !unusable)
																		}
																		className="accent-blue-500"
																	/>
																	<span className="px-2 py-0.5 rounded border border-slate-700 bg-slate-800 text-[10px] font-bold uppercase tracking-widest text-slate-300">
																		{ch.provider}
																	</span>
																	<span className="text-xs text-slate-200 truncate">
																		{ch.name}
																	</span>
																	{ch.disabled === true && (
																		<span className="px-2 py-0.5 rounded border border-red-500/40 bg-red-500/15 text-[10px] font-bold uppercase text-red-300">
																			disabled
																		</span>
																	)}
																	{ch.refresh_needed === true && (
																		<span className="px-2 py-0.5 rounded border border-amber-500/40 bg-amber-500/15 text-[10px] font-bold uppercase text-amber-300">
																			refresh needed
																		</span>
																	)}
																</label>
																{checked && template && (
																	<div className="ml-6 rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-2">
																		<div className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
																			Settings ({provider} template)
																		</div>
																		<div className="flex flex-wrap gap-1.5">
																			{Object.entries(template)
																				.filter(
																					([k]) =>
																						!(
																							provider === "tiktok" &&
																							k === "privacy_level"
																						),
																				)
																				.map(([k, v]) => (
																					<span
																						key={k}
																						className="rounded border border-slate-700 bg-slate-800 px-2 py-0.5 font-mono text-[10px] text-slate-300"
																					>
																						{k}={String(v)}
																					</span>
																				))}
																		</div>
																		{provider === "tiktok" && (
																			<label className="flex items-center gap-2 text-[11px] text-slate-300">
																				privacy_level
																				<select
																					value={
																						tiktokPrivacy[ch.id] ??
																						DEFAULT_TIKTOK_PRIVACY
																					}
																					onChange={(e) =>
																						setTiktokPrivacy((prev) => ({
																							...prev,
																							[ch.id]: e.target.value,
																						}))
																					}
																					className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100"
																				>
																					{TIKTOK_PRIVACY_OPTIONS.map(
																						(opt) => (
																							<option key={opt} value={opt}>
																								{opt}
																							</option>
																						),
																					)}
																				</select>
																			</label>
																		)}
																	</div>
																)}
															</div>
														);
													})}
												</div>
												{anySelected && warnings.length > 0 && (
													<div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 space-y-1">
														{warnings.map((w) => (
															<div
																key={w}
																className="flex items-start gap-1.5 text-[11px] text-amber-200"
															>
																<AlertTriangle
																	size={11}
																	className="mt-0.5 flex-shrink-0"
																/>
																<span className="min-w-0">{w}</span>
															</div>
														))}
													</div>
												)}
											</div>
										);
									},
								)}
							</div>
						)}
					</section>

					{/* STEP 3 — POST */}
					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5 space-y-4">
						<StepHeading step="3" title="Post" />
						<label className="block space-y-1.5">
							<span className="text-[11px] font-semibold text-slate-300">
								Caption / content
							</span>
							<textarea
								value={content}
								onChange={(e) => setContent(e.target.value)}
								rows={4}
								placeholder="Caption for the post (optional)…"
								className="w-full rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600"
							/>
						</label>

						<div className="flex flex-wrap items-center gap-4">
							{(
								[
									["draft", "Draft (safe)"],
									["schedule", "Schedule"],
									["now", "Post now"],
								] as [PostizPostType, string][]
							).map(([value, label]) => (
								<label
									key={value}
									className="flex cursor-pointer items-center gap-2 text-xs text-slate-200"
								>
									<input
										type="radio"
										name="postiz-post-type"
										value={value}
										checked={postType === value}
										onChange={() => setPostType(value)}
										className="accent-blue-500"
									/>
									{label}
								</label>
							))}
							{postType === "schedule" && (
								<input
									type="datetime-local"
									value={scheduleAtLocal}
									onChange={(e) => setScheduleAtLocal(e.target.value)}
									className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-100"
								/>
							)}
						</div>

						<div className="flex flex-wrap items-center gap-2">
							<button
								type="button"
								disabled={!canSubmit}
								onClick={() => void handleDryRun()}
								className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20 transition-colors disabled:opacity-40"
							>
								<ShieldCheck size={12} />
								Preview Payload (dry run)
							</button>
							<button
								type="button"
								disabled={!canSubmit}
								onClick={() => void handlePublish()}
								className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-4 py-2 text-[11px] font-bold text-emerald-100 hover:bg-emerald-500/25 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
							>
								<Send size={12} />
								Send to Postiz
							</button>
						</div>

						{publishError && (
							<div className="flex items-start gap-2 rounded-xl border border-red-500/40 bg-red-500/10 p-3">
								<XCircle size={14} className="mt-0.5 flex-shrink-0 text-red-300" />
								<div className="min-w-0 text-[11px] text-red-200 break-all">
									{publishError}
								</div>
							</div>
						)}

						{publishResult && (
							<div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 space-y-1">
								<div className="flex items-center gap-2 text-xs font-bold text-emerald-200">
									<CheckCircle2 size={14} />
									Sent to Postiz — {publishResult.post_type}
								</div>
								<div className="font-mono text-[11px] text-emerald-200/90">
									record_id={publishResult.record_id}
								</div>
								<div className="font-mono text-[11px] text-emerald-200/90">
									postiz_media_id={publishResult.postiz_media?.id ?? "—"}
								</div>
								<div className="font-mono text-[11px] text-emerald-200/70">
									channels={publishResult.integration_ids.join(", ")}
								</div>
							</div>
						)}

						{dryRunPayload != null && (
							<div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-3 space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-300">
									Dry-run payload {dryRunNote ? `— ${dryRunNote}` : ""}
								</div>
								<pre className="overflow-x-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[10px] text-slate-300">
									{JSON.stringify(dryRunPayload, null, 2)}
								</pre>
							</div>
						)}
					</section>

					{/* AUDIT TRAIL */}
					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 overflow-hidden">
						<div className="border-b border-slate-800 px-5 py-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
							Audit Trail — publish records
						</div>
						{records.length === 0 ? (
							<div className="py-8 text-center text-sm text-slate-500">
								No publish records yet.
							</div>
						) : (
							<div className="overflow-x-auto">
								<table className="w-full">
									<thead className="border-b border-slate-800">
										<tr className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
											<th className="py-2.5 px-3 text-left">Record</th>
											<th className="py-2.5 px-3 text-left">Artifact</th>
											<th className="py-2.5 px-3 text-left">Type</th>
											<th className="py-2.5 px-3 text-left">Status</th>
											<th className="py-2.5 px-3 text-left">Error</th>
											<th className="py-2.5 px-3 text-left">Created</th>
										</tr>
									</thead>
									<tbody>
										{records.map((rec) => (
											<tr
												key={rec.record_id}
												className="border-b border-slate-800 last:border-0"
											>
												<td className="py-2 px-3 font-mono text-xs text-slate-400 max-w-[160px] truncate">
													{rec.record_id}
												</td>
												<td className="py-2 px-3 font-mono text-xs text-slate-400 max-w-[160px] truncate">
													{rec.artifact_media_id}
												</td>
												<td className="py-2 px-3 text-xs text-slate-300 uppercase">
													{rec.post_type}
												</td>
												<td className="py-2 px-3">
													<StatusBadge status={rec.status} />
												</td>
												<td className="py-2 px-3 text-[11px] text-red-300 max-w-[220px] truncate">
													{rec.error || "—"}
												</td>
												<td className="py-2 px-3 text-xs text-slate-500 whitespace-nowrap">
													{rec.created_at?.slice(0, 16).replace("T", " ") ??
														"—"}
												</td>
											</tr>
										))}
									</tbody>
								</table>
							</div>
						)}
					</section>
				</>
			)}
		</div>
	);
}
