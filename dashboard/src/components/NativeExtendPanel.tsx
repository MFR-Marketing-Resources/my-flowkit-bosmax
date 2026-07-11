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
import { useEffect, useState } from 'react';
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
  createVideoJob,
  finalizeVideoJob,
  type NativeExtendResolution,
  type ExtendRunResult,
  type ExtendLineageRow,
  type ExtendBlockInput,
  type ExtendSourceCandidate,
  type FinalizeResult,
} from '../api/nativeExtend';

export interface NativeExtendPanelProps {
  projectId?: string | null;
  sceneId?: string | null;
  sourceOperationId?: string | null;
  totalDurationSeconds?: number | null;
  plannedBlocks?: ExtendBlockInput[];
  aspectRatio?: string;
}

export default function NativeExtendPanel({
  projectId: projectIdProp,
  sceneId: sceneIdProp,
  sourceOperationId: sourceProp,
  totalDurationSeconds,
  plannedBlocks = [],
  aspectRatio = 'VIDEO_ASPECT_RATIO_PORTRAIT',
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
  // ONE logical full-video job: the user deliverable is a single full-duration MP4.
  const [finalJobId, setFinalJobId] = useState<string | null>(null);
  const [finalPlan, setFinalPlan] = useState<FinalizeResult | null>(null);
  const [finalResult, setFinalResult] = useState<FinalizeResult | null>(null);
  const [finalBusy, setFinalBusy] = useState(false);
  const [finalConfirm, setFinalConfirm] = useState(false);
  const [finalError, setFinalError] = useState<string | null>(null);
  // ONE-action full-video orchestration (normal mode)
  const [fullConfirm, setFullConfirm] = useState(false);
  const [fullStage, setFullStage] = useState<string | null>(null);
  const [fullError, setFullError] = useState<string | null>(null);
  const [fullRawError, setFullRawError] = useState<string | null>(null);

  const plannedBlockCount = plannedBlocks.length;
  const requestedSeconds = totalDurationSeconds ?? (plannedBlockCount + 1) * 8;
  const extendSucceeded = lineage.some(
    (row) => row.polling_state === 'EXTEND_SUCCEEDED' && row.child_operation_id,
  );

  const prepareFinal = async () => {
    if (!projectId || !sourceOperationId) return;
    setFinalBusy(true);
    setFinalError(null);
    try {
      const job = await createVideoJob({
        source_media_id: sourceOperationId,
        project_id: projectId,
        requested_total_duration_seconds: requestedSeconds,
      });
      setFinalJobId(job.job_id);
      const plan = await finalizeVideoJob(job.job_id, { dry_run: true });
      setFinalPlan(plan);
    } catch (e) {
      setFinalError(e instanceof Error ? e.message : String(e));
    } finally {
      setFinalBusy(false);
    }
  };

  const renderFinal = async () => {
    if (!finalJobId) return;
    setFinalBusy(true);
    setFinalError(null);
    try {
      const result = await finalizeVideoJob(finalJobId, {
        dry_run: false,
        confirm_live_credit_burn: true,
      });
      setFinalResult(result);
      setFinalConfirm(false);
    } catch (e) {
      setFinalError(e instanceof Error ? e.message : String(e));
    } finally {
      setFinalBusy(false);
    }
  };

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

  useEffect(() => {
    let cancelled = false;
    fetchNativeExtendSourceCandidates()
      .then((r) => {
        if (cancelled) return;
        setCandidates(r.candidates);
        // Auto-inherit the newest finished clip when the operator has supplied nothing.
        if (
          r.candidates.length > 0 &&
          !(projectIdProp ?? '') &&
          !(sceneIdProp ?? '') &&
          !(sourceProp ?? '')
        ) {
          void applyCandidate(r.candidates[0]);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
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

  // Pre-submit gate codes: failing on these provably spends nothing.
  const NO_SPEND_CODES = [
    'LIVE_CREDIT_CONFIRMATION_REQUIRED',
    'NATIVE_EXTEND_DISABLED',
    'FINAL_TIMELINE_DISABLED',
    'EXTEND_SOURCE_NOT_RESOLVABLE',
    'need >=2 segment',
  ];

  const humanFailure = (stage: string, raw: string): string => {
    const base =
      stage === 'Extending video'
        ? 'The continuation could not be completed safely.'
        : stage === 'Preparing final video'
          ? 'The final video could not be prepared.'
          : 'The video could not be started.';
    const noSpend = NO_SPEND_CODES.some((c) => raw.includes(c));
    return noSpend ? `${base} No credit was used for the failed step.` : base;
  };

  const runFullVideo = async () => {
    if (!projectId || !sceneId || !sourceOperationId || plannedBlockCount === 0) return;
    setBusy(true);
    setFullError(null);
    setFullRawError(null);
    let stage = 'Preparing video';
    setFullStage(stage);
    try {
      const liveInput = {
        project_id: projectId,
        scene_id: sceneId,
        source_operation_id: sourceOperationId,
        blocks: plannedBlocks,
        aspect_ratio: aspectRatio,
        dry_run: false,
        confirm_live_credit_burn: true,
      };
      const plan = await previewNativeExtend({
        project_id: projectId,
        scene_id: sceneId,
        source_operation_id: sourceOperationId,
        blocks: plannedBlocks,
        aspect_ratio: aspectRatio,
      });
      stage = 'Extending video';
      setFullStage(stage);
      const authorization = await requestNativeExtendLiveAuthorization({
        ...liveInput,
        confirmed_extend_operation_count: plan.planned_operation_count,
      });
      await runNativeExtend({
        ...liveInput,
        confirmed_extend_operation_count: authorization.planned_operation_count,
        live_authorization_token: authorization.authorization_token,
      });
      stage = 'Preparing final video';
      setFullStage(stage);
      const job = await createVideoJob({
        source_media_id: sourceOperationId,
        project_id: projectId,
        requested_total_duration_seconds: requestedSeconds,
      });
      setFinalJobId(job.job_id);
      await finalizeVideoJob(job.job_id, { dry_run: true });
      const done = await finalizeVideoJob(job.job_id, {
        dry_run: false,
        confirm_live_credit_burn: true,
      });
      setFinalResult(done);
      setFullStage('Video ready');
      fetchNativeExtendLineage(projectId)
        .then((r) => setLineage(r.lineage))
        .catch(() => {});
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setFullRawError(raw);
      setFullError(humanFailure(stage, raw));
      setFullStage(null);
    } finally {
      setBusy(false);
      setFullConfirm(false);
    }
  };

  const idsReady = Boolean(projectId && sceneId && sourceOperationId);
  const canGenerateFull =
    idsReady && plannedBlockCount > 0 && !!resolution?.route_executable &&
    !busy && !finalResult && !finalBusy;

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
      {!idsReady && !finalResult && (
        <div
          data-testid="native-extend-waiting-source"
          className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-100"
        >
          Waiting for the first part — generate the video above; it links here
          automatically.
        </div>
      )}

      {idsReady && !finalResult && !fullStage && !fullConfirm && (
        <div className="grid gap-2">
          <div data-testid="full-video-ready" className="text-xs text-slate-300">
            Ready to complete the full {requestedSeconds}s video
            {plannedBlockCount > 0
              ? ` (${plannedBlockCount + 1} parts, joined automatically).`
              : '.'}
          </div>
          <button
            type="button"
            data-testid="generate-full-video-btn"
            className="w-fit rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!canGenerateFull}
            onClick={() => setFullConfirm(true)}
          >
            Generate Video
          </button>
        </div>
      )}

      {fullConfirm && !finalResult && (
        <div
          data-testid="full-video-confirm"
          className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100"
        >
          <p className="font-medium">Generate the complete {requestedSeconds}-second video?</p>
          <ul className="mt-1 list-inside list-disc text-amber-100/90">
            <li>Continuation: {plannedBlockCount} operation{plannedBlockCount === 1 ? '' : 's'}</li>
            <li>Final video preparation: 1 operation</li>
            <li>Uses Google Flow credits once, for this reviewed plan only.</li>
          </ul>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              data-testid="full-video-confirm-btn"
              className="rounded bg-indigo-600 px-3 py-1.5 font-medium text-white disabled:opacity-40"
              disabled={busy}
              onClick={runFullVideo}
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

      {fullStage && fullStage !== 'Video ready' && (
        <div
          data-testid="full-video-progress"
          className="mt-2 rounded border border-indigo-400/30 bg-indigo-400/10 px-3 py-2 text-xs text-indigo-100"
        >
          {fullStage}…
        </div>
      )}

      {fullError && (
        <div data-testid="full-video-error" className="mt-2 text-xs text-rose-300">
          {fullError}
        </div>
      )}

      {finalResult && (
        <div data-testid="final-video-result" className="mt-3 rounded border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">
          <div className="font-semibold text-emerald-200">Video ready</div>
          <div className="mt-1 text-xs text-slate-300">
            One final video · {finalResult.measured_duration_s?.toFixed?.(1) ?? finalResult.measured_duration_s}s
            {finalResult.size_mb ? ` · ${finalResult.size_mb} MB` : ''}
          </div>
          {finalResult.final_media_id && (
            <>
              <video
                data-testid="final-preview"
                className="mt-2 max-h-64 rounded"
                src={`/api/flow/retrieved/${finalResult.final_media_id}`}
                controls
              />
              <a
                data-testid="final-download"
                className="mt-2 inline-block rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white"
                href={`/api/flow/retrieved/${finalResult.final_media_id}`}
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
          {fullRawError && (
            <div data-testid="full-video-raw-error" className="mt-2 text-xs text-rose-300">
              raw: {fullRawError}
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

          {extendSucceeded && !finalResult && (
            <div data-testid="final-video-section" className="mt-3 rounded border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs">
              <div className="font-medium text-emerald-200">
                Final video — render the {requestedSeconds}s timeline into ONE MP4
              </div>
              {!finalPlan ? (
                <button
                  type="button"
                  data-testid="final-prepare-btn"
                  className="mt-2 rounded bg-emerald-700 px-3 py-1.5 font-medium text-white disabled:opacity-40"
                  disabled={finalBusy}
                  onClick={prepareFinal}
                >
                  Prepare final video (dry-run · no credits)
                </button>
              ) : (
                <div className="mt-2 grid gap-1">
                  <div data-testid="final-plan">
                    Planned: {finalPlan.planned_render_operation_count ?? 1} final render
                    operation → one {requestedSeconds}s MP4
                  </div>
                  {!finalConfirm ? (
                    <button
                      type="button"
                      data-testid="final-render-btn"
                      className="rounded bg-emerald-600 px-3 py-1.5 font-medium text-white disabled:opacity-40"
                      disabled={finalBusy}
                      onClick={() => setFinalConfirm(true)}
                    >
                      Render final video
                    </button>
                  ) : (
                    <div data-testid="final-render-confirm" className="rounded border border-rose-500/50 bg-rose-500/10 p-2 text-rose-100">
                      <p>Confirm final render: exactly 1 render operation for the reviewed
                      {' '}{requestedSeconds}s timeline.</p>
                      <div className="mt-2 flex gap-2">
                        <button
                          type="button"
                          data-testid="final-render-confirm-btn"
                          className="rounded bg-rose-600 px-3 py-1.5 font-medium text-white disabled:opacity-40"
                          disabled={finalBusy}
                          onClick={renderFinal}
                        >
                          Confirm &amp; render
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-500 px-3 py-1.5"
                          disabled={finalBusy}
                          onClick={() => setFinalConfirm(false)}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {finalError && (
                <div data-testid="final-error" className="mt-1 text-rose-300">{finalError}</div>
              )}
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
