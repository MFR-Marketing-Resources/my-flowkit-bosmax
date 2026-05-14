import type { AssetSourceStatus } from "../../types";

const STATUS_STYLE: Record<AssetSourceStatus | string, string> = {
	REPO_VERIFIED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
	INPUT_SLOT_ONLY: "border-amber-500/30 bg-amber-500/10 text-amber-200",
	EXTERNAL_OPERATOR_PACK_NOT_VERIFIED:
		"border-red-500/30 bg-red-500/10 text-red-200",
	EMPTY_NOT_VERIFIED: "border-slate-500/30 bg-slate-500/10 text-slate-200",
	DERIVED_FROM_PRODUCT_DATA: "border-sky-500/30 bg-sky-500/10 text-sky-200",
};

export default function AssetSourceStatusBadge({
	status,
}: {
	status: AssetSourceStatus | string;
}) {
	const style =
		STATUS_STYLE[status] || "border-slate-700 bg-slate-900 text-slate-200";
	return (
		<span
			className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${style}`}
		>
			{status}
		</span>
	);
}
