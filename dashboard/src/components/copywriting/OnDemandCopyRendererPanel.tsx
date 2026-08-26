// On-Demand Copy Renderer panel (Round 2) — Benefit → Duration → Generate 5
// suggestions → lock/regenerate to target → finalize → prepare N READY packages.
// SYSTEM OWNS STRUCTURE; AI ONLY STITCHES. This is a DISTINCT copy authority
// (BENEFIT_COPY_RENDER_V1) — it never claims or writes a Copy Register V2 binding.
import { useCallback, useState } from 'react'
import { Check, Lock, RefreshCw, Sparkles } from 'lucide-react'
import {
  createSession,
  finalizeSession,
  generateSuggestions,
  lockCandidate,
  newRequestId,
  prepareSelected,
  unlockCandidate,
  type CopyRenderCandidate,
  type CopyRenderLane,
  type CopyRenderSession,
  type PrepareResult,
} from '../../api/copyRender'

export interface OnDemandCopyRendererPanelProps {
  productId: string
  benefitId: string
  durationSeconds: number
  lane: CopyRenderLane
  targetLanguage?: string
  defaultTarget?: number
  maxTarget?: number
  className?: string
  /** Called after the selection is finalized (and packages prepared) so the host
   * page can mark its neutral copyReady state and record the selected source. */
  onCopySelected?: (result: { session: CopyRenderSession; prepared: PrepareResult }) => void
}

export function OnDemandCopyRendererPanel(props: OnDemandCopyRendererPanelProps) {
  const { productId, benefitId, durationSeconds, lane, targetLanguage = 'BM_MS', className = '' } = props
  const [session, setSession] = useState<CopyRenderSession | null>(null)
  const [target, setTarget] = useState<number>(props.defaultTarget ?? 5)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async (label: string, fn: () => Promise<void>) => {
    setBusy(label)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [])

  const onGenerate = useCallback(() => run('generate', async () => {
    let sid = session?.session_id
    if (!sid || session?.status === 'STALE') {
      const created = await createSession({
        product_id: productId, benefit_id: benefitId, lane,
        target_count: target, duration_seconds: durationSeconds, target_language: targetLanguage,
      })
      sid = created.session_id
    }
    setSession(await generateSuggestions(sid!, newRequestId()))
  }), [run, session, productId, benefitId, lane, target, durationSeconds, targetLanguage])

  const onToggleLock = useCallback((c: CopyRenderCandidate) => run('lock', async () => {
    setSession(c.status === 'LOCKED' ? await unlockCandidate(c.candidate_id) : await lockCandidate(c.candidate_id))
  }), [run])

  const onProceed = useCallback(() => run('proceed', async () => {
    if (!session) return
    const finalized = await finalizeSession(session.session_id)
    const prepared = await prepareSelected(session.session_id)
    setSession(finalized)
    props.onCopySelected?.({ session: finalized, prepared })
  }), [run, session, props])

  const candidates = session?.candidates.filter((c) => c.status === 'SHOWN' || c.status === 'LOCKED') ?? []
  const locked = session?.locked_count ?? 0
  const tgt = session?.target_count ?? target
  const atTarget = locked >= tgt
  const isFinalized = session?.status === 'FINALIZED'

  return (
    <div
      className={`space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`}
      data-testid="on-demand-copy-renderer"
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-emerald-200">
          <Sparkles size={16} />
          <span>On-Demand Copy Renderer</span>
        </div>
        <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-300">
          {lane} · {durationSeconds}s · {targetLanguage}
        </span>
      </div>

      {!session && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="cr-target" className="text-xs text-slate-300">How many final scripts?</label>
          <input
            id="cr-target" type="number" min={1} max={props.maxTarget ?? 200} value={target}
            onChange={(e) => setTarget(Math.max(1, Number(e.target.value) || 1))}
            className="w-16 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-200"
          />
          <button
            type="button" disabled={!!busy} onClick={onGenerate} data-testid="cr-generate"
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-40"
          >
            {busy === 'generate' ? 'Generating…' : 'Generate 5 Suggestions'}
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200" role="alert">
          {error}
        </div>
      )}

      {session?.status === 'STALE' && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-100">
          The product truth or atom build changed. Start again to render fresh copy.
          <button
            type="button" onClick={() => setSession(null)}
            className="ml-2 rounded border border-amber-500/40 px-2 py-0.5 font-semibold text-amber-200 hover:bg-amber-500/20"
          >
            Start over
          </button>
        </div>
      )}

      {session && session.status !== 'STALE' && (
        <>
          <div className="flex items-center justify-between text-[11px]">
            <span className="rounded bg-slate-800 px-2 py-0.5 font-semibold text-slate-200" data-testid="cr-progress">
              Selected {locked}/{tgt}
            </span>
            <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-400">
              ≤ {session.word_budget} words · {session.formula_id}
            </span>
          </div>

          {candidates.map((c) => {
            const isLocked = c.status === 'LOCKED'
            return (
              <label
                key={c.candidate_id} data-testid="cr-candidate"
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-xs transition-colors ${
                  isLocked ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-slate-800 bg-slate-950/70 hover:border-slate-700'
                } ${isFinalized ? 'cursor-default' : ''}`}
              >
                <input
                  type="checkbox" checked={isLocked} disabled={!!busy || isFinalized}
                  onChange={() => onToggleLock(c)} aria-label={`Lock suggestion ${c.candidate_id}`}
                  className="mt-0.5"
                />
                <span className="flex-1">
                  <span className="whitespace-pre-wrap text-slate-100">{c.full_copy_text}</span>
                  <span className="ml-2 inline-flex items-center gap-1 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                    {isLocked ? <Lock size={10} /> : null}{c.word_count} words
                  </span>
                </span>
              </label>
            )
          })}

          {!isFinalized && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button" disabled={!!busy || !session.regenerate_enabled} onClick={onGenerate}
                data-testid="cr-regenerate"
                title={session.regenerate_enabled ? '' : 'Target reached — unlock a script to regenerate'}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:border-slate-500 disabled:opacity-40"
              >
                <RefreshCw size={13} className={busy === 'generate' ? 'animate-spin' : ''} />
                {busy === 'generate' ? 'Regenerating…' : 'Regenerate 5'}
              </button>
              <button
                type="button" disabled={!!busy || !atTarget} onClick={onProceed} data-testid="cr-proceed"
                className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-40"
              >
                {busy === 'proceed' ? 'Preparing…' : 'Proceed with Selected Scripts'}
              </button>
            </div>
          )}

          {isFinalized && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs font-semibold text-emerald-200" data-testid="cr-finalized">
              <Check size={14} />
              {tgt} script{tgt === 1 ? '' : 's'} finalized and prepared as READY packages.
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default OnDemandCopyRendererPanel
