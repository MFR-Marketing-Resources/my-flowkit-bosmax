import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const resolveMock = vi.fn();
const previewMock = vi.fn();
const lineageMock = vi.fn();
const authorizeMock = vi.fn();
const liveRunMock = vi.fn();
const candidatesMock = vi.fn();
const resolveSourceMock = vi.fn();
const createJobMock = vi.fn();
const finalizeMock = vi.fn();

vi.mock('../api/nativeExtend', () => ({
  resolveNativeExtend: (...a: unknown[]) => resolveMock(...a),
  previewNativeExtend: (...a: unknown[]) => previewMock(...a),
  fetchNativeExtendLineage: (...a: unknown[]) => lineageMock(...a),
  requestNativeExtendLiveAuthorization: (...a: unknown[]) => authorizeMock(...a),
  runNativeExtend: (...a: unknown[]) => liveRunMock(...a),
  fetchNativeExtendSourceCandidates: (...a: unknown[]) => candidatesMock(...a),
  resolveNativeExtendSource: (...a: unknown[]) => resolveSourceMock(...a),
  createVideoJob: (...a: unknown[]) => createJobMock(...a),
  finalizeVideoJob: (...a: unknown[]) => finalizeMock(...a),
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
});

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

  it('auto-inherits the newest finished clip when the operator supplied nothing', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    candidatesMock.mockResolvedValue({
      candidates: [
        {
          media_id: 'clip-new',
          job_id: 'j2',
          project_id: 'proj-1',
          created_at: '2026-07-11T10:23:38Z',
          product_id: 'prod',
          product_name: 'Minyak Warisan Tok Cap Burung 25ml',
          request_id: 'req',
          workspace_generation_package_id: null,
        },
      ],
      count: 1,
    });
    resolveSourceMock.mockResolvedValue({
      project_id: 'proj-1',
      scene_id: 'scene-1',
      source_operation_id: 'clip-new',
      scene_display_name: 'Scene 1',
      verified: true,
    });
    renderPanel({ projectId: '', sceneId: '', sourceOperationId: '' });

    await waitFor(() =>
      expect(resolveSourceMock).toHaveBeenCalledWith({
        media_id: 'clip-new',
        project_id: 'proj-1',
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('project-input')).toHaveValue('proj-1'),
    );
    expect(screen.getByTestId('scene-input')).toHaveValue('scene-1');
    expect(screen.getByTestId('source-operation-input')).toHaveValue('clip-new');
    expect(screen.getByTestId('native-extend-source-note')).toHaveTextContent(/verified/i);
    // No raw-code blocker wall in the inherited flow.
    expect(screen.queryByTestId('native-extend-waiting-source')).toBeNull();
  });

  it('shows WAITING_FOR_SOURCE when no finished clip exists and nothing was supplied', async () => {
    resolveMock.mockResolvedValue(BLOCKED);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    candidatesMock.mockResolvedValue({ candidates: [], count: 0 });
    renderPanel({ projectId: '', sceneId: '', sourceOperationId: '' });

    expect(await screen.findByTestId('native-extend-waiting-source')).toHaveTextContent(
      /WAITING_FOR_SOURCE/,
    );
    // Raw blocker codes stay out of the empty-state surface.
    expect(screen.queryByTestId('native-extend-blockers')).toBeNull();
    expect(screen.getByTestId('native-extend-preview-btn')).toBeDisabled();
  });

  it('selecting a saved clip resolves and fills the Flow context', async () => {
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
    renderPanel(); // props supplied -> no auto-run; manual selection still works
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

  it('renders ONE final video result after prepare + gated render', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({
      lineage: [
        {
          extend_lineage_id: 'L1',
          block_index: 2,
          block_position: 1,
          parent_operation_id: 'op1',
          child_operation_id: 'child-1',
          child_primary_media_id: 'child-1',
          polling_state: 'EXTEND_SUCCEEDED',
        },
      ],
      count: 1,
    });
    createJobMock.mockResolvedValue({ job_id: 'vj_ui', status: 'TIMELINE_SEGMENTS_READY' });
    finalizeMock
      .mockResolvedValueOnce({
        dry_run: true,
        status: 'TIMELINE_SEGMENTS_READY',
        job_id: 'vj_ui',
        planned_render_operation_count: 1,
      })
      .mockResolvedValueOnce({
        dry_run: false,
        status: 'COMPLETE',
        job_id: 'vj_ui',
        final_media_id: 'final_vj_ui',
        measured_duration_s: 16.0,
        size_mb: 14.2,
      });
    renderPanel();

    const prepare = await screen.findByTestId('final-prepare-btn');
    fireEvent.click(prepare);
    await waitFor(() => expect(createJobMock).toHaveBeenCalledWith(
      expect.objectContaining({ source_media_id: 'op1', project_id: 'p' }),
    ));
    expect(await screen.findByTestId('final-plan')).toHaveTextContent('1 final render');

    fireEvent.click(screen.getByTestId('final-render-btn'));
    fireEvent.click(await screen.findByTestId('final-render-confirm-btn'));
    await waitFor(() => expect(finalizeMock).toHaveBeenLastCalledWith('vj_ui', {
      dry_run: false,
      confirm_live_credit_burn: true,
    }));

    const result = await screen.findByTestId('final-video-result');
    expect(result).toHaveTextContent(/Video ready/);
    expect(result).toHaveTextContent(/16/);
    const link = screen.getByTestId('final-download');
    expect(link).toHaveAttribute('href', '/api/flow/retrieved/final_vj_ui');
    // ONE deliverable: segment lineage is explicitly diagnostics
    expect(screen.getByTestId('native-extend-lineage')).toHaveTextContent(/diagnostics/i);
  });
});
