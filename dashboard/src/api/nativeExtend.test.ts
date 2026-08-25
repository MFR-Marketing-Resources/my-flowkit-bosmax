import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getAPI, postAPI } = vi.hoisted(() => ({
  getAPI: vi.fn(),
  postAPI: vi.fn(),
}));

vi.mock('./client', () => ({ getAPI, postAPI }));

import * as nativeExtend from './nativeExtend';

describe('native Extend API retirement boundary', () => {
  beforeEach(() => {
    getAPI.mockReset();
    postAPI.mockReset();
  });

  it('keeps the sole extend-run wrapper hard-bound to provider-free dry-run', async () => {
    postAPI.mockResolvedValue({ dry_run: true, planned_operation_count: 1, blocks: [] });

    await nativeExtend.previewNativeExtend({
      project_id: 'project-preview',
      scene_id: 'scene-preview',
      source_operation_id: 'operation-preview',
      blocks: [{ block_index: 2, position: 1, prompt: 'Continue the scene.' }],
      aspect_ratio: 'VIDEO_ASPECT_RATIO_PORTRAIT',
    });

    expect(postAPI).toHaveBeenCalledTimes(1);
    expect(postAPI).toHaveBeenCalledWith(
      '/api/flow/extend-run',
      expect.objectContaining({ dry_run: true }),
    );
    expect(nativeExtend).not.toHaveProperty('runNativeExtend');
    expect(nativeExtend).not.toHaveProperty('requestNativeExtendLiveAuthorization');
  });
});
