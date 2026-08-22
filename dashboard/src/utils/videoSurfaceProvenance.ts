export const ACTIVE_VIDEO_SURFACE_LANES = [
	"HYBRID",
	"FACELESS",
	"MONTAGE",
	"PRODUCTION_STUDIO_P6",
] as const;

export type ActiveVideoSurfaceLane = (typeof ACTIVE_VIDEO_SURFACE_LANES)[number];

export const ACTIVE_VIDEO_SURFACE_LABELS: Record<ActiveVideoSurfaceLane, string> = {
	HYBRID: "Hybrid",
	FACELESS: "Faceless Video",
	MONTAGE: "Montage",
	PRODUCTION_STUDIO_P6: "Production Studio / P6",
};

const ALIASES: Record<string, ActiveVideoSurfaceLane> = {
	P6: "PRODUCTION_STUDIO_P6",
	PRODUCTION_STUDIO: "PRODUCTION_STUDIO_P6",
	PRODUCTION_STUDIO_P6: "PRODUCTION_STUDIO_P6",
	FACELESS_VIDEO: "FACELESS",
};

export function normalizeVideoSurfaceLane(value: unknown): ActiveVideoSurfaceLane | null {
	const token = String(value ?? "").trim().toUpperCase().replaceAll("-", "_");
	const canonical = ALIASES[token] ?? token;
	return (ACTIVE_VIDEO_SURFACE_LANES as readonly string[]).includes(canonical)
		? (canonical as ActiveVideoSurfaceLane)
		: null;
}

export function videoSurfaceLabel(value: unknown): string | null {
	const lane = normalizeVideoSurfaceLane(value);
	return lane ? ACTIVE_VIDEO_SURFACE_LABELS[lane] : null;
}

export function surfaceDisplayLabel(
	surfaceLane: unknown,
	transportMode?: unknown,
	legacyMode?: unknown,
): string {
	return (
		videoSurfaceLabel(surfaceLane) ??
		(String(transportMode ?? legacyMode ?? "").trim() ? "Legacy/Internal" : "Unknown Surface")
	);
}
