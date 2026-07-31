import { useNavigate } from "react-router-dom";
import { DataTable } from "../ui";
import type { DataTableColumn } from "../ui";
import type { ExceptionItem, ExceptionKind } from "../../api/reporting";

// Drill-down table for one exception kind. Wraps the shared DataTable and navigates to
// the product page on row click (query-param drill target — there is no /products/:id
// route). No aggregation here; it renders the rows the service already selected.

const PRODUCT_COLS: DataTableColumn<ExceptionItem>[] = [
	{
		key: "name",
		header: "Product",
		render: (r) => (
			<span className="font-medium text-slate-200">
				{r.product_display_name ?? r.product_id ?? "—"}
			</span>
		),
		sortValue: (r) => r.product_display_name ?? "",
	},
	{
		key: "cluster",
		header: "Cluster",
		render: (r) => r.cluster ?? "—",
		sortValue: (r) => r.cluster ?? "",
	},
	{
		key: "type",
		header: "Product Type",
		render: (r) => r.product_type_group ?? "—",
		sortValue: (r) => r.product_type_group ?? "",
	},
	{ key: "mapping", header: "Mapping", render: (r) => r.mapping_status ?? "—" },
	{ key: "prompt", header: "Prompt", render: (r) => r.prompt_readiness_status ?? "—" },
	{ key: "asset", header: "Image", render: (r) => r.asset_status ?? "—" },
];

const FAILED_COLS: DataTableColumn<ExceptionItem>[] = [
	{
		key: "name",
		header: "Product",
		render: (r) => (
			<span className="font-medium text-slate-200">
				{r.product_display_name ?? r.product_id ?? "—"}
			</span>
		),
		sortValue: (r) => r.product_display_name ?? "",
	},
	{ key: "mode", header: "Mode", render: (r) => r.mode ?? "—" },
	{
		key: "error",
		header: "Error",
		render: (r) => (
			<span className="text-red-300">{r.error_code ?? r.error_message ?? "—"}</span>
		),
	},
	{
		key: "failed",
		header: "Failed at",
		render: (r) => r.failed_at ?? r.created_at ?? "—",
		sortValue: (r) => r.failed_at ?? r.created_at ?? "",
	},
];

export interface ExceptionTableProps {
	kind: ExceptionKind;
	items: ExceptionItem[];
	loading?: boolean;
}

export function ExceptionTable({ kind, items, loading }: ExceptionTableProps) {
	const navigate = useNavigate();
	const cols = kind === "failed_generation" ? FAILED_COLS : PRODUCT_COLS;
	return (
		<DataTable<ExceptionItem>
			rows={items}
			columns={cols}
			getRowId={(r) => r.request_id ?? r.product_id ?? ""}
			searchText={(r) =>
				`${r.product_display_name ?? ""} ${r.cluster ?? ""} ${r.product_type_group ?? ""} ${r.error_code ?? ""}`
			}
			searchPlaceholder="Filter products…"
			onRowClick={(r) => {
				if (r.product_id)
					navigate(`/products?product=${encodeURIComponent(r.product_id)}`);
			}}
			emptyLabel={loading ? "Loading…" : "No records — nothing in this exception bucket."}
			pageSize={15}
		/>
	);
}
