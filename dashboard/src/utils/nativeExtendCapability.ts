// Native Google Flow Extend — operator-facing route/capability distinctions.
//
// Keeps FOUR distinct things unambiguous so an operator never confuses them:
//   1. Independent Block Plan        — separate 8s blocks, NOT a continuation.
//   2. Native Flow Extend            — each block continues the previous clip.
//   3. Download Project ZIP          — client-side ZIP of per-workflow media.
//   4. Final Concatenated Export     — the single combined video (UNAVAILABLE).
//
// Authority mirrors the backend capability registry (extend_route_planner):
// native-extend transport is AUTHORIZED (captured 2026-07-11), but the final
// concatenated export stays AUTHORITY_MISSING and MUST render disabled — the
// Download Project ZIP is NOT a substitute for it.

export type ExtendCapabilityAuthority = 'AUTHORIZED' | 'AUTHORITY_MISSING';

export interface ExtendRouteOption {
  id: string;
  label: string;
  description: string;
  authority: ExtendCapabilityAuthority;
  disabled: boolean;
}

export const FINAL_CONCAT_EXPORT_AUTHORITY_MISSING =
  'FINAL_CONCAT_EXPORT_AUTHORITY_MISSING';

export const NATIVE_EXTEND_ROUTES: ExtendRouteOption[] = [
  {
    id: 'GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS',
    label: 'Independent Block Plan',
    description:
      'Separate 8-second blocks, each generated independently. Not a temporal continuation of the previous clip.',
    authority: 'AUTHORIZED',
    disabled: false,
  },
  {
    id: 'GOOGLE_FLOW_NATIVE_EXTEND',
    label: 'Native Flow Extend',
    description:
      'Each block continues the previous clip via videoInput.mediaId + frame window (veo_3_1_extension_lite). Uniform 8-second blocks.',
    authority: 'AUTHORIZED',
    disabled: false,
  },
  {
    id: 'GOOGLE_FLOW_DOWNLOAD_PROJECT_ZIP',
    label: 'Download Project ZIP',
    description:
      'Client-side ZIP of the per-workflow media (e.g. block-1 mp4 + a poster image). It is NOT a combined final video and consumes no generation credit.',
    authority: 'AUTHORIZED',
    disabled: false,
  },
  {
    id: 'GOOGLE_FLOW_FINAL_CONCAT_EXPORT',
    label: 'Final Concatenated Export (unavailable)',
    description:
      'The single combined 16s video. Runtime contract not captured — fails closed (AUTHORITY_MISSING). Do not substitute the Download Project ZIP.',
    authority: 'AUTHORITY_MISSING',
    disabled: true,
  },
];

export function isRouteSelectable(route: ExtendRouteOption): boolean {
  return route.authority === 'AUTHORIZED' && !route.disabled;
}

export function finalConcatExportAvailable(): boolean {
  const route = NATIVE_EXTEND_ROUTES.find(
    (r) => r.id === 'GOOGLE_FLOW_FINAL_CONCAT_EXPORT',
  );
  return !!route && route.authority === 'AUTHORIZED';
}
