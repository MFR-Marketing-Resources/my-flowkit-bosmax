export const DEACTIVATED_SURFACE_REDIRECTS = {
	"/operator/t2v": "/operator/hybrid",
	"/operator/f2v": "/operator/hybrid",
	"/operator/i2v": "/operator/hybrid",
	"/operator/img": "/creative/poster-builder",
	"/assets/img-cockpit": "/creative/poster-builder",
	"/assets/img-fastlane": "/creative/poster-builder",
} as const;

export type DeactivatedSurfacePath = keyof typeof DEACTIVATED_SURFACE_REDIRECTS;

export function isDeactivatedSurfacePath(path: string): path is DeactivatedSurfacePath {
	return path in DEACTIVATED_SURFACE_REDIRECTS;
}

export function resolveActiveSurfacePath(path: string): string {
	return isDeactivatedSurfacePath(path)
		? DEACTIVATED_SURFACE_REDIRECTS[path]
		: path;
}
