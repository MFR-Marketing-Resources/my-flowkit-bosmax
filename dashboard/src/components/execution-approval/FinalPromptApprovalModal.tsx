import { useEffect, useState } from "react";
import {
  approveSnapshot,
  createReviewSnapshot,
  editSnapshot,
  prepareDispatch,
} from "../../api/executionApproval";
import type {
  ExecutionApprovalSnapshot,
  PrepareDispatchRequest,
  ReviewEnvelope,
} from "../../api/executionApproval";

export interface FinalPromptApprovalModalProps {
  /** The provider-ready envelope to review. Mirror EXACTLY what the surface will
   * dispatch (same prompt + settings + resolved asset ids). Use this for
   * pass-through prompts (video). The parent renders this modal only when a
   * review is pending, with a stable envelope. */
  envelope?: ReviewEnvelope;
  /** Server-grounded review: the backend compiles the FINAL provider-ready prompt
   * (product-truth grounding for IMG happens BEFORE review) and freezes the
   * snapshot. Use this for any surface whose prompt is grounded/compiled
   * server-side (IMG / Poster Builder) — the operator then reviews the GROUNDED
   * prompt, never the raw one. Provide exactly one of ``envelope`` /
   * ``prepareRequest``. */
  prepareRequest?: PrepareDispatchRequest;
  approvedBy: string;
  /** Called with the APPROVED snapshot. The parent then dispatches using
   * ``snapshot.final_prompt_text`` (which reflects any edit) so the dispatch
   * envelope matches the approval. */
  onApproved: (snapshot: ExecutionApprovalSnapshot) => void;
  onCancel: () => void;
}

/**
 * Final Prompt Approval Gate — the WYSIWYG review step shown before a
 * credit-bearing generation. What the operator approves here is exactly what is
 * dispatched to the provider.
 */
export function FinalPromptApprovalModal({
  envelope,
  prepareRequest,
  approvedBy,
  onApproved,
  onCancel,
}: FinalPromptApprovalModalProps) {
  const [snapshot, setSnapshot] = useState<ExecutionApprovalSnapshot | null>(null);
  const [promptText, setPromptText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    // Server-grounded (IMG) vs client pass-through (video). Grounding runs BEFORE
    // review so the operator always approves the FINAL provider-ready prompt.
    const pending = prepareRequest
      ? prepareDispatch(prepareRequest)
      : createReviewSnapshot(envelope as ReviewEnvelope);
    pending
      .then((snap) => {
        if (cancelled) return;
        setSnapshot(snap);
        setPromptText(snap.final_prompt_text);
        setDirty(false);
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
  }, [envelope, prepareRequest]);

  const scanClean = snapshot?.scan_clean === 1;
  const canApprove = !busy && snapshot !== null && (dirty || scanClean);

  async function handleApproveAndGenerate() {
    if (snapshot === null) return;
    setBusy(true);
    setError(null);
    try {
      let current = snapshot;
      if (dirty && promptText !== snapshot.final_prompt_text) {
        current = await editSnapshot(snapshot.snapshot_id, promptText, approvedBy);
        setSnapshot(current);
        setDirty(false);
        if (current.scan_clean !== 1) {
          setError(
            "The edited prompt failed the safety scan. Fix the flagged content, then approve.",
          );
          setBusy(false);
          return;
        }
      }
      const approved = await approveSnapshot(current.snapshot_id, approvedBy);
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
      data-testid="final-prompt-approval-overlay"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-4 rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-slate-100">
            Review the final prompt
          </h2>
          <p className="text-sm text-slate-400">
            This is the exact prompt that will be sent to the generator. Review,
            edit if needed, then approve — what you approve is what gets dispatched.
          </p>
        </div>

        {error !== null && (
          <div
            className="rounded-lg border border-red-700 bg-red-950/50 p-2 text-sm text-red-300"
            data-testid="final-prompt-approval-error"
          >
            {error}
          </div>
        )}

        <textarea
          data-testid="final-prompt-approval-textarea"
          className="h-64 w-full flex-1 resize-none rounded-lg border border-slate-700 bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200"
          value={promptText}
          onChange={(e) => {
            setPromptText(e.target.value);
            setDirty(true);
          }}
          disabled={busy || snapshot === null}
          spellCheck={false}
        />

        {snapshot !== null && !scanClean && !dirty && (
          <div className="text-sm text-amber-400" data-testid="final-prompt-approval-scan-warning">
            ⚠ This prompt failed the safety scan. Edit the flagged content before
            it can be approved.
          </div>
        )}

        <div className="flex items-center justify-end gap-2">
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
            data-testid="final-prompt-approve-generate"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            onClick={() => {
              void handleApproveAndGenerate();
            }}
            disabled={!canApprove}
          >
            {busy ? "Working…" : "Approve & Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
