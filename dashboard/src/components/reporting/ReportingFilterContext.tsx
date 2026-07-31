import {
	createContext,
	useContext,
	useMemo,
	useState,
	type ReactNode,
} from "react";
import type { LifecycleScope, ReportingFilters } from "../../api/reporting";

// Shared reporting filter state. Tier A wires only the lifecycle ACTIVE/ALL toggle;
// setCluster / setProductTypeGroup exist as the CROSS-FILTER SEAM (a chart onClick can
// call them later so every widget re-queries) but are not wired to any UI control yet.

interface ReportingFilterCtx extends ReportingFilters {
	setLifecycle: (s: LifecycleScope) => void;
	setCluster: (c: string | null) => void;
	setProductTypeGroup: (p: string | null) => void;
	clearDrillFilters: () => void;
}

const Ctx = createContext<ReportingFilterCtx | null>(null);

export function ReportingFilterProvider({ children }: { children: ReactNode }) {
	const [lifecycle_status, setLifecycle] = useState<LifecycleScope>("ACTIVE");
	const [cluster, setCluster] = useState<string | null>(null);
	const [product_type_group, setProductTypeGroup] = useState<string | null>(
		null,
	);
	const value = useMemo<ReportingFilterCtx>(
		() => ({
			lifecycle_status,
			cluster,
			product_type_group,
			setLifecycle,
			setCluster,
			setProductTypeGroup,
			clearDrillFilters: () => {
				setCluster(null);
				setProductTypeGroup(null);
			},
		}),
		[lifecycle_status, cluster, product_type_group],
	);
	return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useReportingFilters(): ReportingFilterCtx {
	const ctx = useContext(Ctx);
	if (!ctx)
		throw new Error(
			"useReportingFilters must be used within ReportingFilterProvider",
		);
	return ctx;
}

/** Narrow the context down to the plain filter payload sent to the API. */
export function asFilters(f: ReportingFilters): ReportingFilters {
	return {
		lifecycle_status: f.lifecycle_status,
		cluster: f.cluster,
		product_type_group: f.product_type_group,
	};
}
