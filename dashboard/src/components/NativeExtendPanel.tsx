// NativeExtendPanel — the operator surface for native Google Flow Extend.
//
// It makes the four options unambiguous (independent blocks / native Extend /
// Download-Project ZIP / final-concat-export-UNAVAILABLE), resolves live readiness +
// blockers through the ONE backend resolver, previews the continuation plan as a
// zero-credit dry-run, shows parent→child lineage + polling status, and surfaces the
// exact number of credit-consuming Extend operations a live run would perform.
//
// It deliberately exposes NO live-run button: a live chain runs only server-side
// through the authoritative orchestrator (POST /api/flow/extend-run) with
// NATIVE_EXTEND_ENABLED=1 and a bounded confirmed operation count. Nothing here can
// spend credits.
import { useEffect, useState } from 'react';
import {
  NATIVE_EXTEND_ROUTES,
  finalConcatExportAvailable,
} from '../utils/nativeExtendCapability';
import {
  resolveNativeExtend,
  previewNativeExtend,
  fetchNativeExtendLineage,
  type NativeExtendResolution,
  type ExtendRunResult,
  type ExtendLineageRow,
  type ExtendBlockInput,
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

  const plannedBlockCount = plannedBlocks.length;

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

      {/* Four distinct routes — no ambiguity between them */}
      <div data-testid="native-extend-routes" className="mb-3 grid gap-1">
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

      {/* Flow context inputs */}
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
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
          {resolution.blockers.length > 0 && (
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

      {/* Live execution is NOT a button here — orchestrator-only, never a bypass */}
      <div
        data-testid="native-extend-live-note"
        className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200"
      >
        Live execution is not available from this panel. A live chain runs only through the
        authoritative orchestrator (POST /api/flow/extend-run) with NATIVE_EXTEND_ENABLED=1 and an
        explicit confirmed operation count equal to the planned count above. No control here spends
        credits.
      </div>

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
