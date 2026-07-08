import { useEffect, useState } from "react";
import { getAPI } from "./client";

// Shared copywriting-readiness contract — consumed by every generation surface
// (video / IMG / poster) so readiness is checked in one place, not re-derived.
export interface CopywritingReadiness {
	product_id: string;
	product_intelligence_status: string;
	has_approved_snapshot: boolean;
	product_knowledge_ready: boolean;
	customer_avatar_ready: boolean;
	recommended_formula: string;
	selected_copy_set_id: string | null;
	approved_copy_set_count: number;
	formula_validation_status: string;
	sales_clarity_status: string;
	copy_applicable: boolean;
	ready_for_generation: boolean;
	blocking_reasons: string[];
	recommended_next_action: string;
}

export async function fetchCopywritingReadiness(
	productId: string,
): Promise<CopywritingReadiness> {
	return getAPI<CopywritingReadiness>(
		`/api/copywriting/readiness/${encodeURIComponent(productId)}`,
	);
}

export function useCopywritingReadiness(productId: string | null | undefined): {
	readiness: CopywritingReadiness | null;
	loading: boolean;
	error: string;
	reload: () => void;
} {
	const [readiness, setReadiness] = useState<CopywritingReadiness | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");
	const [tick, setTick] = useState(0);
	useEffect(() => {
		if (!productId) {
			setReadiness(null);
			return;
		}
		let active = true;
		setLoading(true);
		setError("");
		void fetchCopywritingReadiness(productId)
			.then((r) => {
				if (active) setReadiness(r);
			})
			.catch((e) => {
				if (active)
					setError(
						e instanceof Error ? e.message : "Failed to load copywriting readiness",
					);
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId, tick]);
	return { readiness, loading, error, reload: () => setTick((t) => t + 1) };
}
