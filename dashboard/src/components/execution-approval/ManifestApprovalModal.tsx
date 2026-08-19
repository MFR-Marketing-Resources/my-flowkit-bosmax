import { useEffect, useState } from "react";
import {
  approveManifest,
  editManifestItem,
  getManifest,
} from "../../api/executionApproval";
import type {
  ApprovalManifest,
  ExecutionApprovalSnapshot,
} from "../../api/executionApproval";

export interface ManifestApprovalModalProps {
  /** An already-materialised REVIEW_REQUIRED manifest id (one review snapshot per
   * provider operation). The parent materialises it (e.g. montage
   * materialize-approval-manifest) and passes the id here. */
  manifestId: string;
  approvedBy: string;
  title?: string;
  /** Called with the APPROVED manifest. The parent then starts the run, which
   * resolves each operation's approved item by execution-envelope hash. */
  onApproved: (manifest: ApprovalManifest) => void;
  onCancel: () => void;
}

/**
 * Approved Generation Manifest review — the WYSIWYG step for a MULTI-operation run
 * (Montage scenes, Production Studio plan). Every per-operation final prompt is
 * shown; the operator may edit any item, then approves the WHOLE manifest at once.
 * What is approved here is exactly what each dispatch verifies by hash.
 */
export function ManifestApprovalModal({
  manifestId,
  approvedBy,
  title,
  onApproved,
  onCancel,
}: ManifestApprovalModalProps) {
  const [manifest, setManifest] = useState<ApprovalManifest | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    getManifest(manifestId)
      .then((m) => {
        if (cancelled) return;
        setManifest(m);
        setDrafts(Object.fromEntries(m.items.map((i) => [i.snapshot_id, i.final_prompt_text])));
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [manifestId]);

  const items = manifest?.items ?? [];
  const dirtyItem = (i: ExecutionApprovalSnapshot) => drafts[i.snapshot_id] !== i.final_prompt_text;
  const anyScanDirty = items.some((i) => i.scan_clean !== 1);
  const canApprove = !busy && manifest !== null && items.length > 0 && !anyScanDirty;

  async function handleSaveItem(item: ExecutionApprovalSnapshot) {
    const next = drafts[item.snapshot_id] ?? "";
    if (next === item.final_prompt_text) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await editManifestItem(manifestId, item.snapshot_id, next, approvedBy);
      setManifest(updated);
      setDrafts(Object.fromEntries(updated.items.map((i) => [i.snapshot_id, i.final_prompt_text])));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleApproveAll() {
    if (manifest === null) return;
    setBusy(true);
    setError(null);
    try {
      const approved = await approveManifest(manifestId, approvedBy);
      onApproved(approved);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
      data-testid="manifest-approval-overlay"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col gap-4 rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-100">
            {title ?? "Review every final prompt"}
          </h2>
          <p className="text-sm text-slate-400">
            These are the exact prompts that will be sent to the generator — one per
            operation. Review, edit any, then approve. What you approve is what gets
            dispatched; nothing generates until you approve.
          </p>
        </div>

        {error !== null && (
          <div
            className="rounded-lg border border-red-700 bg-red-950/50 p-2 text-sm text-red-300"
            data-testid="manifest-approval-error"
          >
            {error}
          </div>
        )}

        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          {items.map((item, idx) => (
            <div
              key={item.snapshot_id}
              className="rounded-lg border border-slate-700 bg-slate-950/60 p-3"
              data-testid="manifest-approval-item"
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-slate-300">
                  {item.manifest_item_key ?? `Operation ${idx + 1}`}
                  <span className="ml-2 text-slate-500">
                    {item.logical_mode} · {item.approval_state}
                  </span>
                </span>
                {dirtyItem(item) && (
                  <button
                    type="button"
                    className="rounded border border-slate-600 px-2 py-0.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                    onClick={() => void handleSaveItem(item)}
                    disabled={busy}
                  >
                    Save edit
                  </button>
                )}
              </div>
              <textarea
                className="h-28 w-full resize-none rounded border border-slate-700 bg-slate-950 p-2 font-mono text-xs leading-relaxed text-slate-200"
                value={drafts[item.snapshot_id] ?? ""}
                onChange={(e) =>
                  setDrafts((d) => ({ ...d, [item.snapshot_id]: e.target.value }))
                }
                disabled={busy}
                spellCheck={false}
              />
              {item.scan_clean !== 1 && !dirtyItem(item) && (
                <div className="mt-1 text-xs text-amber-400">
                  ⚠ This prompt failed the safety scan. Edit the flagged content
                  before the manifest can be approved.
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-slate-500">
            {items.length} operation{items.length === 1 ? "" : "s"}
            {anyScanDirty ? " · fix flagged prompts to approve" : ""}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              onClick={onCancel}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="button"
              data-testid="manifest-approve-all"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
              onClick={() => void handleApproveAll()}
              disabled={!canApprove}
            >
              {busy ? "Working…" : "Approve all & Generate"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
