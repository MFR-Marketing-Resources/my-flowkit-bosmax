import { describe, it, expect } from 'vitest';
import {
  NATIVE_EXTEND_ROUTES,
  isRouteSelectable,
  finalConcatExportAvailable,
} from './nativeExtendCapability';

describe('nativeExtendCapability', () => {
  it('exposes four distinct routes', () => {
    const labels = NATIVE_EXTEND_ROUTES.map((r) => r.label);
    expect(labels).toContain('Independent Block Plan');
    expect(labels).toContain('Native Flow Extend');
    expect(labels).toContain('Download Project ZIP');
    expect(labels.some((l) => l.startsWith('Final Timeline Render'))).toBe(true);
    expect(new Set(NATIVE_EXTEND_ROUTES.map((r) => r.id)).size).toBe(4);
  });

  it('labels Download Project ZIP as NOT a combined final video', () => {
    const zip = NATIVE_EXTEND_ROUTES.find(
      (r) => r.id === 'GOOGLE_FLOW_DOWNLOAD_PROJECT_ZIP',
    )!;
    expect(zip.description).toMatch(/NOT a combined final video/);
    expect(zip.authority).toBe('AUTHORIZED');
  });

  it('final timeline render is authorized (captured contract) but execute-gated in copy', () => {
    const concat = NATIVE_EXTEND_ROUTES.find(
      (r) => r.id === 'GOOGLE_FLOW_FINAL_CONCAT_EXPORT',
    )!;
    expect(concat.authority).toBe('AUTHORIZED');
    expect(concat.disabled).toBe(false);
    expect(isRouteSelectable(concat)).toBe(true);
    expect(finalConcatExportAvailable()).toBe(true);
    // the copy must keep the confirmation gate + never offer the ZIP as substitute
    expect(concat.description).toMatch(/explicit confirmation/i);
    expect(concat.description).toMatch(/not a substitute/i);
  });

  it('native extend + independent block are both selectable', () => {
    for (const id of ['GOOGLE_FLOW_NATIVE_EXTEND', 'GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS']) {
      const r = NATIVE_EXTEND_ROUTES.find((x) => x.id === id)!;
      expect(isRouteSelectable(r)).toBe(true);
    }
  });
});
