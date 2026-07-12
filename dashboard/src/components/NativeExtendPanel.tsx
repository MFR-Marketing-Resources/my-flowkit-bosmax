// NativeExtendPanel — the operator surface for native Google Flow Extend.
//
// It makes the four options unambiguous (independent blocks / native Extend /
// Download-Project ZIP / final-concat-export-UNAVAILABLE), resolves live readiness +
// blockers through the ONE backend resolver, previews the continuation plan as a
// zero-credit dry-run, shows parent→child lineage + polling status, and surfaces the
// exact number of credit-consuming Extend operations a live run would perform.
//
// Live execution requires an explicit confirmation after dry-run. The backend grants
// a process-local, single-use authorization bound to the exact reviewed chain and
// planned operation count; /extend-run remains the only execution path.
import { useEffect, useRef, useState } from 'react';
import {
  NATIVE_EXTEND_ROUTES,
  finalConcatExportAvailable,
} from '../utils/nativeExtendCapability';
import {
  resolveNativeExtend,
  previewNativeExtend,
  fetchNativeExtendLineage,
  fetchNativeExtendSourceCandidates,
  resolveNativeExtendSource,
  requestNativeExtendLiveAuthorization,
  runNativeExtend,
  lookupVideoJob,
  planVideoJob,
  authorizeVideoJob,
  startVideoJob,
  getVideoJobStatus,
  type NativeExtendResolution,
  type ExtendRunResult,
  type ExtendLineageRow,
  type ExtendBlockInput,
  type ExtendSourceCandidate,
  type VideoJobPlan,
  type VideoJobStatus,
} from '../api/nativeExtend';

export interface NativeExtendPanelProps {
  projectId?: string | null;
  sceneId?: string | null;
  sourceOperationId?: string | null;
  totalDurationSeconds?: number | null;
  plannedBlocks?: ExtendBlockInput[];
  aspectRatio?: string;
  // Production intent — lets the ONE job own the whole lifecycle (create-before-initial).
  productId?: string | null;
  productName?: string | null;
  executionPackageId?: string | null;
  approvedAssetSha256?: string | null;
}

export default function NativeExtendPanel({
  projectId: projectIdProp,
  sceneId: sceneIdProp,
  sourceOperationId: sourceProp,
  totalDurationSeconds,
  plannedBlocks = [],
  aspectRatio = 'VIDEO_ASPECT_RATIO_PORTRAIT',
  productId,
  productName,
  executionPackageId,
  approvedAssetSha256,
}: NativeExtendPanelProps) {
  // Flow runtime ids the operator supplies (seeded from props when available).
  const [projectId, setProjectId] = useState(projectIdProp ?? '');
  const [sceneId, setSceneId] = useState(sceneIdProp ?? '');
  const [sourceOperationId, setSourceOperationId] = useState(sourceProp ?? '');
  const [resolution, setResolution] = useState<NativeExtendResolution | null>(null);
  const [preview, setPreview] = useState<ExtendRunResult | null>(null);
  const [lineage, setLineage] = useState<ExtendLineageRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmLive, setConfirmLive] = useState(false);
  const [liveResult, setLiveResult] = useState<ExtendRunResult | null>(null);
  // SEV-1 UX repair: finished Block-1 clips auto-inherit into the Extend context —
  // the operator selects a clip, never pastes raw project/scene/operation ids.
  const [candidates, setCandidates] = useState<ExtendSourceCandidate[]>([]);
  const [selectedSource, setSelectedSource] = useState('');
  const [sourceNote, setSourceNote] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // ONE durable, server-owned full-video job (normal mode)
  const [durablePlan, setDurablePlan] = useState<VideoJobPlan | null>(null);
  const [durableStatus, setDurableStatus] = useState<VideoJobStatus | null>(null);
  const [fullConfirm, setFullConfirm] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  // StrictMode-safe single-flight: one read-only lookup per intent key.
  const lookupKeyRef = useRef<string | null>(null);

  const plannedBlockCount = plannedBlocks.length;
  const requestedSeconds = totalDurationSeconds ?? (plannedBlockCount + 1) * 8;
  // Deterministic production intent: the SAME configuration resolves to the SAME
  // logical job, so a refresh reuses it (no localStorage, no duplicate job).
  // FULL client-side authority is required before ANY plan traffic exists —
  // product + execution package + a multi-block duration (SEV-0: no premature 422s).
  const intentReady = Boolean(productId && executionPackageId && requestedSeconds > 8);
  const jobInFlight =
    !!durableStatus &&
    !durableStatus.complete &&
    !(durableStatus.error_code);
  // Re-authorization is a normal state (a not-yet-started step needs a fresh
  // confirmation), not a failure — surfaced with the Generate action, not an error.
  const isAuthExpired = durableStatus?.status === 'AUTHORIZATION_EXPIRED';

  const planIntent = () => ({
    product_id: productId ?? null,
    product_name: productName ?? null,
    execution_package_id: executionPackageId ?? null,
    approved_asset_sha256: approvedAssetSha256 ?? null,
    requested_total_duration_seconds: requestedSeconds,
    aspect_ratio: aspectRatio,
    execution_mode: 'HYBRID_EXTEND',
  });

  // Mount / intent-change restore is READ-ONLY (SEV-0 lifecycle contract):
  // clear any stale job authority from a previous product/package, then look up
  // the existing logical job WITHOUT creating or planning anything. The ONE
  // plan POST happens only on the deliberate Generate action below.
  useEffect(() => {
    // Switching products/packages/durations must never carry another job's
    // plan, status, or output authority forward.
    setDurablePlan(null);
    setDurableStatus(null);
    setFullConfirm(false);
    setPlanError(null);
    if (!intentReady) return;
    const key = `${productId}|${executionPackageId}|${requestedSeconds}|${aspectRatio}`;
    const alreadyIssued = lookupKeyRef.current === key;
    lookupKeyRef.current = key;
    if (alreadyIssued) return; // StrictMode double-invoke guard: ONE lookup per key
    lookupVideoJob(planIntent())
      .then(async (found) => {
        // Apply only while this intent is still current (stale lookups dropped).
        if (lookupKeyRef.current !== key || !found.found || !found.job_id) return;
        setDurablePlan({
          job_id: found.job_id,
          status: found.status ?? 'CREATED',
          plan_fingerprint: found.plan_fingerprint ?? '',
          reused: true,
          plan: found.plan ?? undefined,
        } as VideoJobPlan);
        if (found.status && found.status !== 'CREATED') {
          const st = await getVideoJobStatus(found.job_id).catch(() => null);
          if (lookupKeyRef.current === key && st) setDurableStatus(st);
        }
      })
      .catch(() => {
        /* restore is advisory and read-only; never retried automatically */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId, executionPackageId, requestedSeconds]);

  // Poll a running job (never starts one) — refresh/restart safe.
  useEffect(() => {
    if (!jobInFlight || !durableStatus) return;
    const id = durableStatus.job_id;
    const t = setInterval(() => {
      getVideoJobStatus(id)
        .then((st) => setDurableStatus(st))
        .catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [jobInFlight, durableStatus?.job_id]);


  const applyCandidate = async (candidate: ExtendSourceCandidate) => {
    setSelectedSource(candidate.media_id);
    setSourceNote('Resolving scene context…');
    try {
      const ctx = await resolveNativeExtendSource({
        media_id: candidate.media_id,
        project_id: candidate.project_id,
      });
      setProjectId(ctx.project_id);
      setSceneId(ctx.scene_id);
      setSourceOperationId(ctx.source_operation_id);
      setSourceNote(
        `Source verified — ${candidate.product_name ?? candidate.media_id.slice(0, 8)} · scene ${
          ctx.scene_display_name ?? ctx.scene_id.slice(0, 8)
        }`,
      );
    } catch (e) {
      setSourceNote(
        `Could not auto-resolve this clip (${e instanceof Error ? e.message : String(e)}). ` +
          'Open Advanced Diagnostics to enter ids manually.',
      );
      setAdvancedOpen(true);
    }
  };

  // SEV-0 current-run binding: history candidates are a DIAGNOSTICS-ONLY manual
  // fallback. They are fetched only when the operator opens Advanced Diagnostics
  // and are NEVER auto-applied — no old/project-history clip can silently become
  // the Extend source, and no resolve-source request exists on mount.
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const candidatesLoadedRef = useRef(false);
  useEffect(() => {
    if (!diagnosticsOpen || candidatesLoadedRef.current) return;
    candidatesLoadedRef.current = true;
    fetchNativeExtendSourceCandidates()
      .then((r) => setCandidates(r.candidates))
      .catch(() => {});
  }, [diagnosticsOpen]);

  useEffect(() => {
    // Readiness resolution is a diagnostics aid for the manual lane — nothing to
    // resolve (and no request) until some Flow context actually exists.
    if (!projectId && !sceneId && !sourceOperationId) return;
    let cancelled = false;
    resolveNativeExtend({
      project_id: projectId || null,
      scene_id: sceneId || null,
      source_operation_id: sourceOperationId || null,
      planned_block_count: plannedBlockCount,
      total_duration_seconds: totalDurationSeconds ?? null,
    })
      .then((r) => {
        if (!cancelled) setResolution(r);
      })
      .catch(() => {
        /* readiness is advisory; ignore transient errors */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, sceneId, sourceOperationId, plannedBlockCount, totalDurationSeconds]);

  useEffect(() => {
    if (!projectId) return;
    fetchNativeExtendLineage(projectId)
      .then((r) => setLineage(r.lineage))
      .catch(() => {});
  }, [projectId, preview]);

  const canPreview =
    !!projectId && !!sceneId && !!sourceOperationId && plannedBlockCount > 0 && !busy;

  const runPreview = async () => {
    if (!canPreview) return;
    setBusy(true);
    setError(null);
    try {
      const r = await previewNativeExtend({
        project_id: projectId,
        scene_id: sceneId,
        source_operation_id: sourceOperationId,
        blocks: plannedBlocks,
        aspect_ratio: aspectRatio,
      });
      setPreview(r);
      setConfirmLive(false);
      setLiveResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const canStartLive =
    !!preview &&
    preview.planned_operation_count > 0 &&
    !!resolution?.route_executable &&
    !busy;

  const runLive = async () => {
    if (!preview || !canStartLive) return;
    const input = {
      project_id: projectId,
      scene_id: sceneId,
      source_operation_id: sourceOperationId,
      blocks: plannedBlocks,
      aspect_ratio: aspectRatio,
      dry_run: false,
      confirm_live_credit_burn: true,
      confirmed_extend_operation_count: preview.planned_operation_count,
    };
    setBusy(true);
    setError(null);
    try {
      const authorization = await requestNativeExtendLiveAuthorization(input);
      if (authorization.planned_operation_count !== preview.planned_operation_count) {
        throw new Error('EXTEND_CONFIRMATION_COUNT_MISMATCH');
      }
      const result = await runNativeExtend({
        ...input,
        live_authorization_token: authorization.authorization_token,
      });
      setLiveResult(result);
      setConfirmLive(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // "API 422: {"detail":{"code":…,"detail":…}}" → human-readable structured detail.
  const describePlanError = (e: unknown): string => {
    const raw = e instanceof Error ? e.message : String(e);
    const jsonStart = raw.indexOf('{');
    if (jsonStart >= 0) {
      try {
        const parsed = JSON.parse(raw.slice(jsonStart));
        const detail = parsed?.detail;
        if (detail && typeof detail === 'object') {
          return `${detail.code ?? 'PLAN_REJECTED'}: ${detail.detail ?? ''}`.trim();
        }
        if (typeof detail === 'string') return detail;
      } catch {
        /* fall through to raw */
      }
    }
    return raw;
  };

  const openGenerateConfirm = async () => {
    // THE one deliberate plan action: exactly one POST per click, never retried.
    // A structured 422 (missing/invalid authority) is shown verbatim — the
    // operator fixes the input; the request is not replayed automatically.
    setPlanError(null);
    setBusy(true);
    try {
      const plan = await planVideoJob(planIntent());
      setDurablePlan(plan);
      setFullConfirm(true);
    } catch (e) {
      setPlanError(describePlanError(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmAndGenerate = async () => {
    if (!durablePlan) return;
    setBusy(true);
    try {
      await authorizeVideoJob(durablePlan.job_id, durablePlan.plan_fingerprint);
      const st = await startVideoJob(durablePlan.job_id); // returns immediately
      setDurableStatus(st);
      setFullConfirm(false);
    } catch (e) {
      setDurableStatus({
        job_id: durablePlan.job_id,
        status: 'ERROR',
        human_stage: 'The video could not be started.',
        error_code: e instanceof Error ? e.message : String(e),
        complete: false,
        credit_summary: 'NOT_SPENT',
        no_credit_used: true,
      });
      setFullConfirm(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="native-extend-panel"
      className="mt-4 rounded-lg border border-indigo-500/30 bg-indigo-500/5 p-4 text-sm text-slate-200"
    >
      <div className="mb-2 flex items-center justify-between">
        <h4 className="font-semibold text-indigo-200">Full Video</h4>
        <span className="text-xs text-slate-400">
          {requestedSeconds}s · generated in parts automatically
        </span>
      </div>

      {/* ── NORMAL MODE: one job, one action, one result ─────────────────── */}
      {!durableStatus?.complete && (
        <>
          {!intentReady && (
            <div
              data-testid="native-extend-waiting-source"
              className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-100"
            >
              Select a product above to generate the full {requestedSeconds}s video.
            </div>
          )}

          {intentReady && !durableStatus && !fullConfirm && (
            <div className="grid gap-2">
              <div data-testid="full-video-ready" className="text-xs text-slate-300">
                {productName ? `${productName} — ` : ''}one {requestedSeconds}s video,
                generated in parts automatically.
              </div>
              <button
                type="button"
                data-testid="generate-full-video-btn"
                className="w-fit rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                disabled={busy}
                onClick={openGenerateConfirm}
              >
                Generate Video
              </button>
              {planError && (
                <div data-testid="full-video-plan-error" className="text-xs text-rose-300">
                  The video plan was rejected — {planError}
                </div>
              )}
            </div>
          )}

          {fullConfirm && durablePlan && (
            <div
              data-testid="full-video-confirm"
              className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100"
            >
              <p className="font-medium">
                Generate the complete {durablePlan.plan.requested_seconds}-second video?
              </p>
              <ul className="mt-1 list-inside list-disc text-amber-100/90">
                <li>
                  Initial part: {durablePlan.plan.operation_counts.initial_generation} operation
                </li>
                <li>
                  Continuation: {durablePlan.plan.operation_counts.extend} operation
                  {durablePlan.plan.operation_counts.extend === 1 ? '' : 's'}
                </li>
                <li>
                  Final video preparation: {durablePlan.plan.operation_counts.final_render} operation
                </li>
                <li data-testid="full-video-plan-total">
                  Total operations authorized: {durablePlan.plan.operation_counts.total}
                </li>
                <li>
                  One confirmation authorizes the operations listed above. Final render
                  credit cost is {durablePlan.plan.credit_estimate.final_render}.
                </li>
              </ul>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  data-testid="full-video-confirm-btn"
                  className="rounded bg-indigo-600 px-3 py-1.5 font-medium text-white disabled:opacity-40"
                  disabled={busy}
                  onClick={confirmAndGenerate}
                >
                  Confirm &amp; generate
                </button>
                <button
                  type="button"
                  className="rounded border border-slate-500 px-3 py-1.5"
                  disabled={busy}
                  onClick={() => setFullConfirm(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {durableStatus && !durableStatus.error_code && (
            <div
              data-testid="full-video-progress"
              className="mt-2 rounded border border-indigo-400/30 bg-indigo-400/10 px-3 py-2 text-xs text-indigo-100"
            >
              {durableStatus.human_stage}…
            </div>
          )}

          {/* Re-authorization is a normal, non-error state: only a not-yet-started
              step needs a fresh confirmation. Already-running work is never lost. */}
          {isAuthExpired && (
            <div
              data-testid="full-video-reauth"
              className="mt-2 grid gap-2 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100"
            >
              <div>{durableStatus?.human_stage}</div>
              <button
                type="button"
                data-testid="generate-full-video-btn"
                className="w-fit rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={busy}
                onClick={openGenerateConfirm}
              >
                Generate Video
              </button>
            </div>
          )}

          {durableStatus?.error_code && !isAuthExpired && (
            <div data-testid="full-video-error" className="mt-2 text-xs text-rose-300">
              {durableStatus.human_stage}
              {durableStatus.no_credit_used
                ? ' No credit was used for the failed step.'
                : ''}
            </div>
          )}
        </>
      )}

      {durableStatus?.complete && (
        <div data-testid="final-video-result" className="mt-3 rounded border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">
          <div className="font-semibold text-emerald-200">Video ready</div>
          <div className="mt-1 text-xs text-slate-300">
            One final video · {durableStatus.final_duration_s?.toFixed?.(1) ?? durableStatus.final_duration_s}s
          </div>
          {durableStatus.final_media_id && (
            <>
              <video
                data-testid="final-preview"
                className="mt-2 max-h-64 rounded"
                src={`/api/flow/retrieved/${durableStatus.final_media_id}`}
                controls
              />
              <a
                data-testid="final-download"
                className="mt-2 inline-block rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white"
                href={`/api/flow/retrieved/${durableStatus.final_media_id}`}
              >
                Download final video
              </a>
            </>
          )}
        </div>
      )}

      {/* ── ADVANCED DIAGNOSTICS: every technical control, closed by default ── */}
      <details
        data-testid="native-extend-advanced-diagnostics"
        className="mt-4 border-t border-slate-700/60 pt-2"
        onToggle={(e) => setDiagnosticsOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer text-xs text-slate-500">
          Advanced Diagnostics
        </summary>
        <div className="mt-3 grid gap-3">

        <details data-testid="native-extend-lane-guide">
          <summary className="cursor-pointer text-xs text-slate-400">
            Lane guide — what runs where (independent blocks · native Extend · ZIP · final export)
          </summary>
          <div data-testid="native-extend-routes" className="mt-2 grid gap-1">
            {NATIVE_EXTEND_ROUTES.map((route) => (
              <div
                key={route.id}
                data-testid={`route-${route.id}`}
                className={`rounded border px-2 py-1 ${
                  route.disabled
                    ? 'border-slate-600/40 bg-slate-700/20 opacity-60'
                    : 'border-indigo-400/30 bg-indigo-400/5'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{route.label}</span>
                  {route.disabled && (
                    <span data-testid="route-disabled" className="text-xs text-rose-300">
                      unavailable
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400">{route.description}</p>
              </div>
            ))}
          </div>
        </details>

        <div className="grid gap-2">
          <label className="text-xs text-slate-400">
            Source clip (finished Block-1 — auto-inherited)
            <select
              data-testid="native-extend-source-select"
              className="mt-1 w-full rounded bg-slate-800 px-2 py-1 text-slate-100"
              value={selectedSource}
              onChange={(e) => {
                const candidate = candidates.find((c) => c.media_id === e.target.value);
                if (candidate) void applyCandidate(candidate);
              }}
            >
              <option value="">
                {candidates.length > 0 ? 'Select a finished clip…' : 'No finished clips yet'}
              </option>
              {candidates.map((c) => (
                <option key={c.media_id} value={c.media_id}>
                  {(c.product_name ?? 'clip')} · {c.created_at ?? ''} · {c.media_id.slice(0, 8)}…
                </option>
              ))}
            </select>
          </label>
          {sourceNote && (
            <div data-testid="native-extend-source-note" className="text-xs text-slate-400">
              {sourceNote}
            </div>
          )}
        </div>

        <details
          data-testid="native-extend-advanced"
          open={advancedOpen}
          onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}
        >
          <summary className="cursor-pointer text-xs text-slate-500">
            Raw Flow ids (auto-filled; manual entry is a fallback)
          </summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <label className="text-xs text-slate-400">
              Flow project id
              <input
                data-testid="project-input"
                className="mt-1 w-full rounded bg-slate-800 px-2 py-1 text-slate-100"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                placeholder="project id"
              />
            </label>
            <label className="text-xs text-slate-400">
              Scene id
              <input
                data-testid="scene-input"
                className="mt-1 w-full rounded bg-slate-800 px-2 py-1 text-slate-100"
                value={sceneId}
                onChange={(e) => setSceneId(e.target.value)}
                placeholder="scene id"
              />
            </label>
            <label className="text-xs text-slate-400">
              Source clip operation id
              <input
                data-testid="source-operation-input"
                className="mt-1 w-full rounded bg-slate-800 px-2 py-1 text-slate-100"
                value={sourceOperationId}
                onChange={(e) => setSourceOperationId(e.target.value)}
                placeholder="finished Block-1 operation id"
              />
            </label>
          </div>
        </details>

        {resolution && (
          <div data-testid="native-extend-readiness" className="grid gap-1 text-xs">
            <div>
              Route: <span className="font-mono">{resolution.route_id}</span> · Model:{' '}
              <span className="font-mono">{resolution.model_key}</span> · Block duration:{' '}
              {resolution.block_duration_seconds}s
            </div>
            <div>
              Parent source:{' '}
              <span className={resolution.parent_ready ? 'text-emerald-300' : 'text-rose-300'}>
                {resolution.parent_ready ? 'READY' : 'MISSING'}
              </span>{' '}
              · Project/Scene:{' '}
              <span className={resolution.project_scene_ready ? 'text-emerald-300' : 'text-rose-300'}>
                {resolution.project_scene_ready ? 'READY' : 'MISSING'}
              </span>
            </div>
            <div data-testid="planned-op-count">
              Planned continuation blocks: {resolution.planned_block_count} · credit-consuming
              Extend operations: {resolution.planned_operation_count}
            </div>
            <div data-testid="final-concat-state" className="text-slate-400">
              Final timeline render:{' '}
              {finalConcatExportAvailable()
                ? 'READY (execute-gated) — renders ONE full-duration MP4'
                : 'UNAVAILABLE — fails closed (the Download Project ZIP is NOT a substitute)'}
            </div>
            {resolution.blockers.length > 0 &&
              Boolean(projectId || sceneId || sourceOperationId) && (
                <div
                  data-testid="native-extend-blockers"
                  className="mt-1 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-rose-200"
                >
                  Blocked: {resolution.blockers.join(', ')}
                </div>
              )}
          </div>
        )}

        <div>
          <button
            type="button"
            data-testid="native-extend-preview-btn"
            className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!canPreview || !resolution?.route_executable}
            onClick={runPreview}
          >
            Preview continuation plan (dry-run · no credits)
          </button>

          {error && (
            <div data-testid="native-extend-error" className="mt-2 text-xs text-rose-300">
              {error}
            </div>
          )}
          {durableStatus?.error_code && (
            <div data-testid="full-video-raw-error" className="mt-2 text-xs text-rose-300">
              raw: {durableStatus.error_code}
            </div>
          )}

          {preview && (
            <div data-testid="native-extend-preview" className="mt-3 grid gap-1 text-xs">
              <div data-testid="preview-op-count" className="font-medium">
                Planned Extend operations: {preview.planned_operation_count} of{' '}
                {preview.block_count} blocks
              </div>
              {preview.blocks.map((b) => (
                <div key={b.block_index} data-testid={`preview-block-${b.block_index}`}>
                  Block {b.block_index} (pos {b.position}) → {b.polling_state}
                  {b.parent_operation_id
                    ? ` · parent ${b.parent_operation_id}`
                    : ' · parent resolved at run time'}
                </div>
              ))}
            </div>
          )}

          {canStartLive && (
            <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-100">
              <p data-testid="native-extend-live-warning">
                Live test spends Google Flow credits. This authorizes exactly{' '}
                {preview?.planned_operation_count} Extend operation
                {preview?.planned_operation_count === 1 ? '' : 's'}; the final render is a separate gated step.
              </p>
              <button
                type="button"
                data-testid="native-extend-live-btn"
                className="mt-2 rounded bg-amber-600 px-3 py-1.5 font-medium text-white"
                onClick={() => setConfirmLive(true)}
              >
                Run live test ({preview?.planned_operation_count} credit-consuming operation
                {preview?.planned_operation_count === 1 ? '' : 's'})
              </button>
            </div>
          )}

          {confirmLive && preview && (
            <div
              data-testid="native-extend-live-confirm"
              className="mt-3 rounded border border-rose-500/50 bg-rose-500/10 p-3 text-xs text-rose-100"
            >
              <p>
                Confirm live Native Extend: Google Flow will be asked to run exactly{' '}
                {preview.planned_operation_count} credit-consuming operation
                {preview.planned_operation_count === 1 ? '' : 's'} for this reviewed plan.
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  data-testid="native-extend-live-confirm-btn"
                  className="rounded bg-rose-600 px-3 py-1.5 font-medium text-white disabled:opacity-40"
                  disabled={busy}
                  onClick={runLive}
                >
                  Confirm &amp; run live
                </button>
                <button
                  type="button"
                  className="rounded border border-slate-500 px-3 py-1.5"
                  disabled={busy}
                  onClick={() => setConfirmLive(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {liveResult && (
            <div data-testid="native-extend-live-result" className="mt-3 text-xs text-emerald-300">
              Live request accepted by the authoritative Extend orchestrator. Polling and lineage status are shown below.
            </div>
          )}

          {lineage.length > 0 && (
            <div data-testid="native-extend-lineage" className="mt-3 grid gap-1 text-xs">
              <div className="font-medium text-slate-300">Segment lineage (diagnostics — the deliverable is the ONE final video)</div>
              {lineage.map((row) => (
                <div key={row.extend_lineage_id} data-testid={`lineage-${row.block_index}`}>
                  Block {row.block_index}: {row.parent_operation_id ?? '—'} →{' '}
                  {row.child_operation_id ?? '—'}{' '}
                  <span className="font-mono text-slate-400">[{row.polling_state}]</span>
                </div>
              ))}
            </div>
          )}
        </div>
        </div>
      </details>
    </div>
  );
}
