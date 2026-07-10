/**
 * Video capability resolver (frontend mirror of the backend operator-policy
 * matrix). ALL types and options are derived from the payload delivered by
 * `GET /api/flow/video-capability-matrix` — there is no parallel hard-coded
 * engine/model/duration list in the UI. The pure helpers below implement the
 * Step-1 state-transition laws deterministically so they can be unit-tested
 * without rendering.
 */

export interface CapabilityModel {
	key: string;
	ui_label: string;
	allowed_durations_s: number[];
	default_duration_s: number;
}

export interface CapabilityEngine {
	id: string;
	label: string;
	supported: boolean;
	unsupported_reason: string | null;
	transport: string | null;
	description: string;
	single_duration_policy: number[];
	default_single_duration: number;
	models: CapabilityModel[];
	single_models_by_duration: Record<string, string[]>;
	default_model_by_duration: Record<string, string | null>;
}

export interface VideoCapabilityMatrix {
	capability_matrix_version: string;
	engines: CapabilityEngine[];
	default_engine: string;
}

/** A fully-resolved, valid SINGLE selection tuple. */
export interface SingleSelection {
	engineId: string;
	model: string; // ui_label (the identity the execute payload + registry use)
	durationSeconds: number;
	/** true when the resolver had to change the incoming model/duration to stay valid */
	adjusted: boolean;
	adjustmentReason: string | null;
}

/** True only for a structurally-valid matrix payload (guards test/stub stubs). */
export function isCapabilityMatrix(
	matrix: unknown,
): matrix is VideoCapabilityMatrix {
	return (
		!!matrix &&
		typeof matrix === "object" &&
		Array.isArray((matrix as VideoCapabilityMatrix).engines)
	);
}

export function getEngine(
	matrix: VideoCapabilityMatrix | null,
	engineId: string | null | undefined,
): CapabilityEngine | null {
	if (!isCapabilityMatrix(matrix) || !engineId) return null;
	return matrix.engines.find((e) => e.id === engineId) ?? null;
}

export function defaultEngine(
	matrix: VideoCapabilityMatrix | null,
): CapabilityEngine | null {
	if (!isCapabilityMatrix(matrix)) return null;
	return (
		getEngine(matrix, matrix.default_engine) ??
		matrix.engines.find((e) => e.supported) ??
		matrix.engines[0] ??
		null
	);
}

/** Operator-policy SINGLE durations for the engine (already policy-limited). */
export function singleDurations(engine: CapabilityEngine | null): number[] {
	return engine ? [...engine.single_duration_policy] : [];
}

/** Model rows selectable for (engine, duration) = policy ∩ registry. */
export function modelsForSingle(
	engine: CapabilityEngine | null,
	durationSeconds: number,
): CapabilityModel[] {
	if (!engine || !engine.supported) return [];
	const keys = engine.single_models_by_duration[String(durationSeconds)] ?? [];
	const byKey = new Map(engine.models.map((m) => [m.key, m]));
	const out: CapabilityModel[] = [];
	for (const k of keys) {
		const m = byKey.get(k);
		if (m) out.push(m);
	}
	return out;
}

/** Deterministic default model (ui_label) for (engine, duration), or null. */
export function defaultModelLabelForSingle(
	engine: CapabilityEngine | null,
	durationSeconds: number,
): string | null {
	if (!engine) return null;
	const key = engine.default_model_by_duration[String(durationSeconds)] ?? null;
	if (!key) return null;
	return engine.models.find((m) => m.key === key)?.ui_label ?? null;
}

function modelSupports(
	engine: CapabilityEngine,
	modelLabel: string | null,
	durationSeconds: number,
): boolean {
	if (!modelLabel) return false;
	return modelsForSingle(engine, durationSeconds).some(
		(m) => m.ui_label === modelLabel,
	);
}

/**
 * Resolve a valid SINGLE selection for an engine, preserving the operator's
 * prior model/duration where still valid and deterministically repairing what
 * is not. Encodes the ENGINE / MODEL / DURATION change laws:
 *  - keep the previous duration if it is in the engine policy, else the
 *    engine default duration;
 *  - keep the previous model if it still supports the resolved duration, else
 *    the deterministic default model for that duration.
 * `adjusted`/`adjustmentReason` report any repair so the UI can explain it.
 */
export function resolveSingleSelection(
	engine: CapabilityEngine | null,
	prevModel: string | null,
	prevDuration: number | null,
): SingleSelection | null {
	if (!engine || !engine.supported) return null;
	const policy = engine.single_duration_policy;
	if (policy.length === 0) return null;

	let adjusted = false;
	let reason: string | null = null;

	// Duration: keep if in policy, else engine default.
	let duration =
		prevDuration != null && policy.includes(prevDuration)
			? prevDuration
			: engine.default_single_duration;
	if (prevDuration != null && duration !== prevDuration) {
		adjusted = true;
		reason = "Duration adjusted to match the selected engine.";
	}

	// Model: keep if it supports the resolved duration, else default.
	let model = prevModel;
	if (!modelSupports(engine, model, duration)) {
		model = defaultModelLabelForSingle(engine, duration);
		if (prevModel != null && prevModel !== model) {
			adjusted = true;
			reason = "Model adjusted to match the selected engine and duration.";
		}
	}

	if (!model) return null;
	return {
		engineId: engine.id,
		model,
		durationSeconds: duration,
		adjusted,
		adjustmentReason: reason,
	};
}

/** Resolve a valid selection after only the DURATION changed (engine kept). */
export function resolveDurationChange(
	engine: CapabilityEngine | null,
	prevModel: string | null,
	nextDuration: number,
): SingleSelection | null {
	if (!engine || !engine.supported) return null;
	if (!engine.single_duration_policy.includes(nextDuration)) return null;
	let adjusted = false;
	let reason: string | null = null;
	let model = prevModel;
	if (!modelSupports(engine, model, nextDuration)) {
		model = defaultModelLabelForSingle(engine, nextDuration);
		if (prevModel != null && prevModel !== model) {
			adjusted = true;
			reason = "Model adjusted to match the selected duration.";
		}
	}
	if (!model) return null;
	return {
		engineId: engine.id,
		model,
		durationSeconds: nextDuration,
		adjusted,
		adjustmentReason: reason,
	};
}
