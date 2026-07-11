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
  type NativeExtendResolution,
  type ExtendRunResult,
  type ExtendLineageRow,
  type ExtendBlockInput,
  type ExtendSourceCandidate,
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
  const [candidatesLoaded, setCandidatesLoaded] = useState(false);
  const [selectedSource, setSelectedSource] = useState('');
  const [sourceNote, setSourceNote] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const plannedBlockCount = plannedBlocks.length;

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
        setCandidatesLoaded(true);
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
      .catch(() => {
        if (!cancelled) setCandidatesLoaded(true);
      });
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

  return (
    <div
      data-testid="native-extend-panel"
      className="mt-4 rounded-lg border border-indigo-500/30 bg-indigo-500/5 p-4 text-sm text-slate-200"
    >
      <div className="mb-2 flex items-center justify-between">
        <h4 className="font-semibold text-indigo-200">Native Flow Extend</h4>
        <span className="text-xs text-slate-400">temporal continuation · uniform 8s blocks</span>
      </div>

      {/* Four distinct routes — collapsed lane guide (SEV-1: the default surface
          stays linear; the contrast cards are reference material, not workflow). */}
      <details data-testid="native-extend-lane-guide" className="mb-3">
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

      {/* Source clip — auto-inherited from finished Block-1 generations */}
      <div className="mb-3 grid gap-2">
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
              {candidates.length > 0
                ? 'Select a finished clip…'
                : 'No finished clips yet'}
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
        {candidatesLoaded &&
          candidates.length === 0 &&
          !projectId &&
          !sceneId &&
          !sourceOperationId && (
            <div
              data-testid="native-extend-waiting-source"
              className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-100"
            >
              WAITING_FOR_SOURCE — generate Block 1 first; the finished clip appears here
              automatically as the Extend source.
            </div>
          )}
      </div>

      {/* Raw Flow ids — Advanced Diagnostics only (never required in the normal flow) */}
      <details
        data-testid="native-extend-advanced"
        className="mb-3"
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer text-xs text-slate-500">
          Advanced Diagnostics — raw Flow ids (auto-filled; manual entry is a fallback)
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

      {/* Readiness + blockers + planned operation count + final-concat state */}
      {resolution && (
        <div data-testid="native-extend-readiness" className="mb-3 grid gap-1 text-xs">
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
            <span
              className={resolution.project_scene_ready ? 'text-emerald-300' : 'text-rose-300'}
            >
              {resolution.project_scene_ready ? 'READY' : 'MISSING'}
            </span>
          </div>
          <div data-testid="planned-op-count">
            Planned continuation blocks: {resolution.planned_block_count} · credit-consuming
            Extend operations: {resolution.planned_operation_count}
          </div>
          <div data-testid="final-concat-state" className="text-slate-400">
            Final concatenated 16s export:{' '}
            {finalConcatExportAvailable()
              ? 'available'
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

      {/* Dry-run preview — zero credits */}
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
            {preview?.planned_operation_count === 1 ? '' : 's'}; the final concatenated export remains unavailable.
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

      {/* Lineage + polling status */}
      {lineage.length > 0 && (
        <div data-testid="native-extend-lineage" className="mt-3 grid gap-1 text-xs">
          <div className="font-medium text-slate-300">Lineage &amp; polling status</div>
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
  );
}
