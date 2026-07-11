import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const resolveMock = vi.fn();
const previewMock = vi.fn();
const lineageMock = vi.fn();
const authorizeMock = vi.fn();
const liveRunMock = vi.fn();

vi.mock('../api/nativeExtend', () => ({
  resolveNativeExtend: (...a: unknown[]) => resolveMock(...a),
  previewNativeExtend: (...a: unknown[]) => previewMock(...a),
  fetchNativeExtendLineage: (...a: unknown[]) => lineageMock(...a),
  requestNativeExtendLiveAuthorization: (...a: unknown[]) => authorizeMock(...a),
  runNativeExtend: (...a: unknown[]) => liveRunMock(...a),
}));

// Import SUT after mocks.
import NativeExtendPanel from './NativeExtendPanel';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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
    expect(concat).toHaveTextContent(/unavailable/i);
  });

  it('shows the planned Extend operation count + final-concat unavailable', async () => {
    resolveMock.mockResolvedValue(READY);
    lineageMock.mockResolvedValue({ lineage: [], count: 0 });
    renderPanel();
    expect(await screen.findByTestId('planned-op-count')).toHaveTextContent('2');
    expect(screen.getByTestId('final-concat-state')).toHaveTextContent(/UNAVAILABLE/);
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
});
