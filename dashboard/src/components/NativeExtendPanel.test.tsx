import '@testing-library/jest-dom/vitest';
import { StrictMode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const resolveMock = vi.fn();
const previewMock = vi.fn();
const lineageMock = vi.fn();
const authorizeMock = vi.fn();
const liveRunMock = vi.fn();
const candidatesMock = vi.fn();
const resolveSourceMock = vi.fn();
const lookupMock = vi.fn();
const planMock = vi.fn();
const authorizeJobMock = vi.fn();
const startJobMock = vi.fn();
const jobStatusMock = vi.fn();

vi.mock('../api/nativeExtend', () => ({
  resolveNativeExtend: (...a: unknown[]) => resolveMock(...a),
  previewNativeExtend: (...a: unknown[]) => previewMock(...a),
  fetchNativeExtendLineage: (...a: unknown[]) => lineageMock(...a),
  requestNativeExtendLiveAuthorization: (...a: unknown[]) => authorizeMock(...a),
  runNativeExtend: (...a: unknown[]) => liveRunMock(...a),
  fetchNativeExtendSourceCandidates: (...a: unknown[]) => candidatesMock(...a),
  resolveNativeExtendSource: (...a: unknown[]) => resolveSourceMock(...a),
  lookupVideoJob: (...a: unknown[]) => lookupMock(...a),
  planVideoJob: (...a: unknown[]) => planMock(...a),
  authorizeVideoJob: (...a: unknown[]) => authorizeJobMock(...a),
  startVideoJob: (...a: unknown[]) => startJobMock(...a),
  getVideoJobStatus: (...a: unknown[]) => jobStatusMock(...a),
}));

// Import SUT after mocks.
import NativeExtendPanel from './NativeExtendPanel';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  // Default: no finished clips — existing tests drive ids via props.
  candidatesMock.mockResolvedValue({ candidates: [], count: 0 });
  resolveSourceMock.mockResolvedValue({
    project_id: 'p',
    scene_id: 's',
    source_operation_id: 'op1',
    scene_display_name: 'S',
    verified: true,
  });
  lookupMock.mockResolvedValue({ found: false, logical_job_key: 'ljk_none' });
  planMock.mockResolvedValue(PLAN);
  authorizeJobMock.mockResolvedValue({
    job_id: 'vj_1', authorization_token: 'auth_x', expires_in_seconds: 600,
  });
  startJobMock.mockResolvedValue(STATUS('Generating video'));
  jobStatusMock.mockResolvedValue(STATUS('Generating video'));
});

const PLAN = {
  job_id: 'vj_1',
  status: 'CREATED',
  plan_fingerprint: 'fp_1',
  plan: {
    requested_seconds: 24,
    segment_count: 3,
    operation_counts: { initial_generation: 1, extend: 2, final_render: 1, total: 4 },
    credit_estimate: { initial_generation: 'credit_consuming', extend: 'credit_consuming', final_render: 'unknown', total: 'unknown' },
  },
};
function STATUS(stage: string, over: Record<string, unknown> = {}) {
  return {
    job_id: 'vj_1', status: stage, human_stage: stage, error_code: null,
    requested_duration_seconds: 24, product_name: 'MWTCB',
    plan: PLAN.plan, final_media_id: null, final_duration_s: null,
    complete: false, credit_summary: 'NOT_SPENT', no_credit_used: true, ...over,
  };
}

const READY = {
  route_id: 'GOOGLE_FLOW_NATIVE_EXTEND',
  transport_proven: true,
  duration_plan_authorized: true,
  block_plan: [8, 8, 8],
  parent_ready: true,
  project_ready: true,
  scene_ready: true,
  project_scene_ready: true,
  route_executable: true,
  final_concat_export_available: false,
  model_key: 'veo_3_1_extension_lite',
  block_duration_seconds: 8,
  planned_block_count: 2,
  planned_operation_count: 2,
  blockers: [] as string[],
};
const BLOCKED = {
  ...READY,
  parent_ready: false,
  project_scene_ready: false,
  route_executable: false,
  blockers: ['EXTEND_PARENT_MEDIA_ID_MISSING', 'EXTEND_PROJECT_CONTEXT_MISSING'],
};

function renderPanel(props: Record<string, unknown> = {}) {
  return render(
    <NativeExtendPanel
      projectId="p"
      sceneId="s"
      sourceOperationId="op1"
      productId="prod-1"
      productName="MWTCB"
      executionPackageId="wep_1"
      totalDurationSeconds={24}
      plannedBlocks={[
        { block_index: 2, position: 1, prompt: 'b2' },
        { block_index: 3, position: 2, prompt: 'b3', is_final: true },
      ]}
      {...props}
    />,
  );
}

describe('NativeExtendPanel', () => {
  it('renders the four distinct routes incl. final-concat disabled + ZIP-not-combined', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel();
    expect(
      await screen.findByTestId('route-GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('route-GOOGLE_FLOW_NATIVE_EXTEND')).toBeInTheDocument();
    const zip = screen.getByTestId('route-GOOGLE_FLOW_DOWNLOAD_PROJECT_ZIP');
    expect(zip).toHaveTextContent(/NOT a combined final video/);
    const concat = screen.getByTestId('route-GOOGLE_FLOW_FINAL_CONCAT_EXPORT');
    expect(concat).toHaveTextContent(/Final Timeline Render/);
    expect(concat).toHaveTextContent(/explicit confirmation/i);
  });

  it('shows the planned Extend operation count + final-concat unavailable', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel();
    expect(await screen.findByTestId('planned-op-count')).toHaveTextContent('2');
    expect(screen.getByTestId('final-concat-state')).toHaveTextContent(/READY \(execute-gated\)/);
  });

  it('renders blockers and disables preview when parent/project/scene missing', async () => {
    resolveMock.mockResolvedValue(BLOCKED);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel({ sourceOperationId: '' });
    expect(await screen.findByTestId('native-extend-blockers')).toHaveTextContent(
      'EXTEND_PARENT_MEDIA_ID_MISSING',
    );
    expect(screen.getByTestId('native-extend-preview-btn')).toBeDisabled();
  });

  it('requires explicit bounded confirmation before a live run can be authorized', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    previewMock.mockResolvedValue({
      dry_run: true,
      project_id: 'p',
      scene_id: 's',
      source_operation_id: 'op1',
      planned_operation_count: 2,
      block_count: 2,
      model_key: 'veo_3_1_extension_lite',
      blocks: [
        { block_index: 2, position: 1, parent_operation_id: 'op1', child_operation_id: null, polling_state: 'SOURCE_READY' },
        { block_index: 3, position: 2, parent_operation_id: null, child_operation_id: null, polling_state: 'SOURCE_READY' },
      ],
    });
    renderPanel();
    const btn = await screen.findByTestId('native-extend-preview-btn');
    await waitFor(() => expect(btn).not.toBeDisabled());
    fireEvent.click(btn);
    await waitFor(() => expect(previewMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId('preview-op-count')).toHaveTextContent('2');
    expect(screen.getByTestId('preview-block-2')).toBeInTheDocument();
    expect(screen.getByTestId('native-extend-live-btn')).toHaveTextContent('2');
    expect(screen.queryByTestId('native-extend-live-confirm')).toBeNull();

    authorizeMock.mockResolvedValue({
      authorization_token: 'one-shot-token',
      planned_operation_count: 2,
      expires_in_seconds: 300,
    });
    liveRunMock.mockResolvedValue({
      dry_run: false,
      planned_operation_count: 2,
      block_count: 2,
      blocks: [],
    });
    fireEvent.click(screen.getByTestId('native-extend-live-btn'));
    expect(await screen.findByTestId('native-extend-live-confirm')).toHaveTextContent('exactly 2');
    fireEvent.click(screen.getByTestId('native-extend-live-confirm-btn'));

    await waitFor(() => expect(authorizeMock).toHaveBeenCalledTimes(1));
    expect(liveRunMock).toHaveBeenCalledWith(expect.objectContaining({
      dry_run: false,
      confirm_live_credit_burn: true,
      confirmed_extend_operation_count: 2,
      live_authorization_token: 'one-shot-token',
    }));
  });

  it('renders lineage / polling status', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({
      lineage: [
        {
          extend_lineage_id: 'L1',
          block_index: 2,
          block_position: 1,
          parent_operation_id: 'op1',
          child_operation_id: 'c2',
          child_primary_media_id: 'c2',
          polling_state: 'EXTEND_SUCCEEDED',
        },
      ],
      count: 1,
    });
    renderPanel();
    expect(await screen.findByTestId('lineage-2')).toHaveTextContent('EXTEND_SUCCEEDED');
  });

  // ── SEV-0 current-run binding: NO history clip can silently become the source ──
  it('mount performs ZERO candidate lookups and ZERO resolve-source calls (SEV-0)', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    candidatesMock.mockResolvedValue({
      candidates: [
        {
          media_id: 'clip-old', job_id: 'j-old', project_id: 'proj-old',
          created_at: '2026-07-11T10:23:38Z', product_id: 'prod',
          product_name: 'Old clip', request_id: 'req',
          workspace_generation_package_id: null,
        },
      ],
      count: 1,
    });
    renderPanel({ projectId: '', sceneId: '', sourceOperationId: '' });
    await screen.findByTestId('native-extend-panel');
    // A newer-looking historical clip exists — it must NEVER be fetched, resolved,
    // or inherited on mount. The durable job owns its own Video 1.
    expect(candidatesMock).not.toHaveBeenCalled();
    expect(resolveSourceMock).not.toHaveBeenCalled();
    expect(planMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('project-input')).toHaveValue('');
    expect(screen.getByTestId('source-operation-input')).toHaveValue('');
  });

  it('candidates load only when Advanced Diagnostics is opened, never auto-applied', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    candidatesMock.mockResolvedValue({
      candidates: [
        {
          media_id: 'clip-old', job_id: 'j-old', project_id: 'proj-old',
          created_at: '2026-07-11T10:23:38Z', product_id: 'prod',
          product_name: 'Old clip', request_id: 'req',
          workspace_generation_package_id: null,
        },
      ],
      count: 1,
    });
    renderPanel({ projectId: '', sceneId: '', sourceOperationId: '' });
    const diagnostics = await screen.findByTestId('native-extend-advanced-diagnostics');
    (diagnostics as HTMLDetailsElement).open = true;
    fireEvent(diagnostics, new Event('toggle'));
    await waitFor(() => expect(candidatesMock).toHaveBeenCalledTimes(1));
    // Listed for the operator, but NOT auto-resolved into the Extend context.
    expect(resolveSourceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('project-input')).toHaveValue('');
    expect(screen.getByTestId('source-operation-input')).toHaveValue('');
  });

  it('shows a human prompt (not raw codes) when no product is selected', async () => {
    resolveMock.mockResolvedValue(BLOCKED);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    candidatesMock.mockResolvedValue({ candidates: [], count: 0 });
    renderPanel({ productId: undefined, projectId: '', sceneId: '', sourceOperationId: '' });

    expect(await screen.findByTestId('native-extend-waiting-source')).toHaveTextContent(
      /Select a product above/,
    );
    // No engineering blocker codes on the normal surface.
    expect(screen.queryByTestId('native-extend-blockers')).toBeNull();
    // Without an intent there is no Generate action, no plan call, no lookup.
    expect(screen.queryByTestId('generate-full-video-btn')).toBeNull();
    expect(planMock).not.toHaveBeenCalled();
    expect(lookupMock).not.toHaveBeenCalled();
  });

  // ── SEV-0 request lifecycle: plan gating, StrictMode, deterministic 422 ────
  it('an incomplete execution package produces ZERO plan and ZERO lookup calls', async () => {
    resolveMock.mockResolvedValue(BLOCKED);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel({
      executionPackageId: undefined,
      projectId: '', sceneId: '', sourceOperationId: '',
    });
    expect(await screen.findByTestId('native-extend-waiting-source')).toBeInTheDocument();
    expect(planMock).not.toHaveBeenCalled();
    expect(lookupMock).not.toHaveBeenCalled();
    expect(resolveSourceMock).not.toHaveBeenCalled();
  });

  it('StrictMode double-mount issues at most ONE read-only lookup and ZERO plans', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    render(
      <StrictMode>
        <NativeExtendPanel
          projectId="p"
          sceneId="s"
          sourceOperationId="op1"
          productId="prod-1"
          productName="MWTCB"
          executionPackageId="wep_1"
          totalDurationSeconds={24}
          plannedBlocks={[
            { block_index: 2, position: 1, prompt: 'b2' },
            { block_index: 3, position: 2, prompt: 'b3', is_final: true },
          ]}
        />
      </StrictMode>,
    );
    await screen.findByTestId('native-extend-panel');
    await waitFor(() => expect(lookupMock).toHaveBeenCalledTimes(1));
    expect(planMock).not.toHaveBeenCalled();
  });

  it('a deterministic 422 shows the exact rejection and is NEVER retried', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    planMock.mockRejectedValue(
      new Error(
        'API 422: {"detail":{"code":"INCOMPLETE_PRODUCTION_PLAN","detail":"missing production authority: initial_prompt_text"}}',
      ),
    );
    renderPanel();
    fireEvent.click(await screen.findByTestId('generate-full-video-btn'));
    const err = await screen.findByTestId('full-video-plan-error');
    expect(err).toHaveTextContent('INCOMPLETE_PRODUCTION_PLAN');
    expect(err).toHaveTextContent('initial_prompt_text');
    // exactly the ONE deliberate request — no automatic retry, no confirm dialog
    expect(planMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('full-video-confirm')).toBeNull();
    // still exactly one call after the UI settles
    await new Promise((r) => setTimeout(r, 50));
    expect(planMock).toHaveBeenCalledTimes(1);
  });

  it('switching products clears stale job authority (no cross-job reuse)', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    lookupMock.mockResolvedValue({
      found: true, job_id: 'vj_A', status: 'INITIAL_POLLING',
      plan_fingerprint: 'fp_A', plan: PLAN.plan, logical_job_key: 'ljk_A',
    });
    jobStatusMock.mockResolvedValue(STATUS('Generating video', { job_id: 'vj_A' }));
    const view = renderPanel({ productId: 'prod-A' });
    expect(await screen.findByTestId('full-video-progress')).toBeInTheDocument();

    // Product switch: job A's plan/status/output authority must NOT carry over.
    lookupMock.mockResolvedValue({ found: false, logical_job_key: 'ljk_B' });
    view.rerender(
      <NativeExtendPanel
        projectId="p"
        sceneId="s"
        sourceOperationId="op1"
        productId="prod-B"
        productName="Other"
        executionPackageId="wep_2"
        totalDurationSeconds={24}
        plannedBlocks={[
          { block_index: 2, position: 1, prompt: 'b2' },
          { block_index: 3, position: 2, prompt: 'b3', is_final: true },
        ]}
      />,
    );
    await waitFor(() =>
      expect(screen.queryByTestId('full-video-progress')).toBeNull(),
    );
    expect(screen.getByTestId('generate-full-video-btn')).toBeInTheDocument();
  });

  it('selecting a saved clip resolves and fills the Flow context (diagnostics only)', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    candidatesMock.mockResolvedValue({
      candidates: [
        {
          media_id: 'clip-a',
          job_id: 'ja',
          project_id: 'proj-a',
          created_at: '2026-07-11T09:00:00Z',
          product_id: null,
          product_name: 'Bosmax Oil 10 ML',
          request_id: null,
          workspace_generation_package_id: null,
        },
      ],
      count: 1,
    });
    resolveSourceMock.mockResolvedValue({
      project_id: 'proj-a',
      scene_id: 'scene-a',
      source_operation_id: 'clip-a',
      scene_display_name: null,
      verified: true,
    });
    renderPanel(); // manual selection requires opening Advanced Diagnostics first
    const diagnostics = await screen.findByTestId('native-extend-advanced-diagnostics');
    (diagnostics as HTMLDetailsElement).open = true;
    fireEvent(diagnostics, new Event('toggle'));
    await waitFor(() => expect(candidatesMock).toHaveBeenCalledTimes(1));
    const select = await screen.findByTestId('native-extend-source-select');
    fireEvent.change(select, { target: { value: 'clip-a' } });
    await waitFor(() =>
      expect(screen.getByTestId('source-operation-input')).toHaveValue('clip-a'),
    );
    expect(screen.getByTestId('project-input')).toHaveValue('proj-a');
    expect(screen.getByTestId('scene-input')).toHaveValue('scene-a');
  });

  it('keeps raw ids inside Advanced Diagnostics and the lane guide collapsed', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel();
    const advanced = await screen.findByTestId('native-extend-advanced');
    expect(advanced.tagName.toLowerCase()).toBe('details');
    expect(advanced).not.toHaveAttribute('open');
    const guide = screen.getByTestId('native-extend-lane-guide');
    expect(guide.tagName.toLowerCase()).toBe('details');
    expect(guide).not.toHaveAttribute('open');
    // The four lane cards remain available inside the guide.
    expect(screen.getByTestId('route-GOOGLE_FLOW_FINAL_CONCAT_EXPORT')).toBeInTheDocument();
  });

  it('restores ONE final video result from a completed durable job on mount (refresh-safe)', async () => {
    // Refresh scenario: the READ-ONLY lookup finds the existing job; status COMPLETE.
    lookupMock.mockResolvedValue({
      found: true, job_id: 'vj_1', status: 'COMPLETE',
      plan_fingerprint: 'fp_1', plan: PLAN.plan, logical_job_key: 'ljk_1',
    });
    jobStatusMock.mockResolvedValue(
      STATUS('Video ready', {
        status: 'COMPLETE', complete: true,
        final_media_id: 'final_vj_1', final_duration_s: 24.0,
      }),
    );
    renderPanel();

    const result = await screen.findByTestId('final-video-result');
    expect(result).toHaveTextContent(/Video ready/);
    expect(result).toHaveTextContent(/24/);
    expect(screen.getByTestId('final-preview')).toBeInTheDocument();     // one preview
    expect(screen.getByTestId('final-download')).toHaveAttribute(
      'href', '/api/flow/retrieved/final_vj_1');
    // it RESUMED read-only — never planned, never started a fresh job on load
    expect(planMock).not.toHaveBeenCalled();
    expect(startJobMock).not.toHaveBeenCalled();
    // no second result card
    expect(screen.getAllByTestId('final-video-result')).toHaveLength(1);
  });

    const BANNED_ON_NORMAL_SURFACE = [
    'Independent Block Plan',
    'Download Project ZIP',
    'Final Concatenated Export',
    'Flow project id',
    'Scene id',
    'Source clip operation id',
    'GOOGLE_FLOW_NATIVE_EXTEND',
    'veo_3_1_extension_lite',
    'EXTEND_PARENT_MEDIA_ID_MISSING',
    'AUTHORITY_MISSING',
    'Preview continuation plan',
  ];

  it('normal production surface exposes NO engineering strings (Mission 9)', async () => {
    resolveMock.mockResolvedValue(BLOCKED);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel({ sourceOperationId: '' });
    await screen.findByTestId('native-extend-panel');

    const diagnostics = screen.getByTestId('native-extend-advanced-diagnostics');
    expect(diagnostics.tagName.toLowerCase()).toBe('details');
    expect(diagnostics).not.toHaveAttribute('open'); // closed by default

    // Every occurrence of every technical string must live INSIDE diagnostics.
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const offenders: string[] = [];
    let node: Node | null = walker.nextNode();
    while (node) {
      const text = node.textContent ?? '';
      for (const banned of BANNED_ON_NORMAL_SURFACE) {
        if (text.includes(banned)) {
          const el = node.parentElement;
          if (!el?.closest('[data-testid="native-extend-advanced-diagnostics"]')) {
            offenders.push(`${banned} :: ${text.slice(0, 60)}`);
          }
        }
      }
      node = walker.nextNode();
    }
    expect(offenders).toEqual([]);
  });

  it('one Generate Video action runs the whole job behind ONE whole-plan confirmation (Mission 8)', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    startJobMock.mockResolvedValue(STATUS('Generating video'));
    renderPanel();

    const generate = await screen.findByTestId('generate-full-video-btn');
    await waitFor(() => expect(generate).not.toBeDisabled());
    fireEvent.click(generate);

    // ONE confirmation covering the ENTIRE requested video (initial + extend + final)
    const confirm = await screen.findByTestId('full-video-confirm');
    expect(confirm).toHaveTextContent(/Initial part: 1 operation/);
    expect(confirm).toHaveTextContent(/Continuation: 2 operations/);
    expect(confirm).toHaveTextContent(/Final video preparation: 1 operation/);
    expect(screen.getByTestId('full-video-plan-total')).toHaveTextContent('4');
    // honest credit: final render cost is 'unknown', not "credits once"
    expect(confirm).toHaveTextContent(/Final render credit cost is unknown/);
    expect(confirm).not.toHaveTextContent(/credits once/);

    fireEvent.click(screen.getByTestId('full-video-confirm-btn'));

    // one authorization for the whole reviewed plan, then one start (returns fast)
    await waitFor(() => expect(authorizeJobMock).toHaveBeenCalledWith('vj_1', 'fp_1'));
    expect(authorizeJobMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(startJobMock).toHaveBeenCalledWith('vj_1'));

    // simple human progress, no raw codes
    const progress = await screen.findByTestId('full-video-progress');
    expect(progress).toHaveTextContent(/Generating video/);
    expect(screen.queryByTestId('full-video-error')).toBeNull();
  });

    it('human failure copy + no-credit claim come from STRUCTURED backend state', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    // start returns a failed status with backend-proven no_credit_used
    startJobMock.mockResolvedValue(
      STATUS('The continuation could not be completed safely.', {
        status: 'EXTEND_FAILED', error_code: 'EXTEND_FAILED',
        credit_summary: 'NOT_SPENT', no_credit_used: true,
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByTestId('generate-full-video-btn'));
    fireEvent.click(await screen.findByTestId('full-video-confirm-btn'));

    const err = await screen.findByTestId('full-video-error');
    expect(err).toHaveTextContent('The continuation could not be completed safely.');
    expect(err).toHaveTextContent('No credit was used for the failed step.');
    // raw code lives only inside Advanced Diagnostics
    expect(screen.getByTestId('full-video-raw-error')).toHaveTextContent(/EXTEND_FAILED/);
    expect(
      screen.getByTestId('full-video-raw-error')
        .closest('[data-testid="native-extend-advanced-diagnostics"]'),
    ).not.toBeNull();
  });

  it('does NOT claim "no credit used" when the backend reports credit MAY_HAVE_SPENT', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    startJobMock.mockResolvedValue(
      STATUS('The final video could not be prepared.', {
        status: 'FINAL_RENDER_FAILED', error_code: 'FINAL_RENDER_FAILED',
        credit_summary: 'MAY_HAVE_SPENT', no_credit_used: false,
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByTestId('generate-full-video-btn'));
    fireEvent.click(await screen.findByTestId('full-video-confirm-btn'));
    const err = await screen.findByTestId('full-video-error');
    expect(err).toHaveTextContent('The final video could not be prepared.');
    expect(err).not.toHaveTextContent('No credit was used');
  });

  it('shows a human re-confirm (not a failure) when a not-yet-started step needs re-authorization', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    // On mount the READ-ONLY lookup finds a job whose status is AUTHORIZATION_EXPIRED.
    lookupMock.mockResolvedValue({
      found: true, job_id: 'vj_1', status: 'AUTHORIZATION_EXPIRED',
      plan_fingerprint: 'fp_1', plan: PLAN.plan, logical_job_key: 'ljk_1',
    });
    jobStatusMock.mockResolvedValue(
      STATUS('Please review and confirm the video again.', {
        status: 'AUTHORIZATION_EXPIRED', error_code: 'AUTHORIZATION_EXPIRED',
      }),
    );
    renderPanel();
    // it is a normal re-confirm state: the Generate action is offered, not a red error
    const reauth = await screen.findByTestId('full-video-reauth');
    expect(reauth).toHaveTextContent(/review and confirm the video again/i);
    expect(within(reauth).getByTestId('generate-full-video-btn')).toBeInTheDocument();
    expect(screen.queryByTestId('full-video-error')).toBeNull();
    // and the dead 501 stub message never surfaces anywhere
    expect(document.body.textContent).not.toMatch(/PENDING_OPERATOR_PROOF|501/);
  });
});
