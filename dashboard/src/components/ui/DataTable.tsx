import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { HelperText } from "./HelperText";

export interface DataTableColumn<T> {
	key: string;
	header: ReactNode;
	/** Cell renderer. */
	render: (row: T) => ReactNode;
	/** If provided, the column header becomes a sort toggle; return the
	 * comparable value (string or number). */
	sortValue?: (row: T) => string | number;
	className?: string;
	headerClassName?: string;
}

export interface DataTableFilter<T> {
	key: string;
	label: string;
	options: { value: string; label: string }[];
	/** Return the row's value for this filter, compared to the selected option. */
	value: (row: T) => string;
}

export interface DataTableProps<T> {
	rows: T[];
	columns: DataTableColumn<T>[];
	getRowId: (row: T) => string;
	/** Rows per page (default 20). */
	pageSize?: number;
	/** Enable the search box; return the searchable haystack text for a row. */
	searchText?: (row: T) => string;
	searchPlaceholder?: string;
	/** Dropdown filters rendered next to the search box. */
	filters?: DataTableFilter<T>[];
	/** Rightmost per-row action cell (edit / archive / delete buttons). */
	rowActions?: (row: T) => ReactNode;
	onRowClick?: (row: T) => void;
	/** Highlight the currently-selected row. */
	selectedRowId?: string | null;
	emptyLabel?: string;
	initialSort?: { key: string; dir: "asc" | "desc" };
	/** Minimum table width before horizontal scroll kicks in. */
	minWidthClassName?: string;
	className?: string;
}

/**
 * The standard list surface for the whole dashboard: sortable column headers,
 * a search box, dropdown filters, Prev/Next pagination, a horizontal scroll
 * container, per-row actions and an empty state — all client-side, all in one
 * place so every list page behaves identically.
 */
export function DataTable<T>({
	rows,
	columns,
	getRowId,
	pageSize = 20,
	searchText,
	searchPlaceholder = "Search…",
	filters,
	rowActions,
	onRowClick,
	selectedRowId,
	emptyLabel = "No items.",
	initialSort,
	minWidthClassName = "min-w-[640px]",
	className,
}: DataTableProps<T>) {
	const [query, setQuery] = useState("");
	const [filterState, setFilterState] = useState<Record<string, string>>({});
	const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(
		initialSort ?? null,
	);
	const [page, setPage] = useState(1);

	const columnByKey = useMemo(() => {
		const map: Record<string, DataTableColumn<T>> = {};
		for (const column of columns) map[column.key] = column;
		return map;
	}, [columns]);

	const processed = useMemo(() => {
		let out = rows;
		const q = query.trim().toLowerCase();
		if (q && searchText) {
			out = out.filter((row) => searchText(row).toLowerCase().includes(q));
		}
		if (filters) {
			for (const filter of filters) {
				const selected = filterState[filter.key];
				if (selected) out = out.filter((row) => filter.value(row) === selected);
			}
		}
		if (sort) {
			const column = columnByKey[sort.key];
			if (column?.sortValue) {
				const dir = sort.dir === "asc" ? 1 : -1;
				out = [...out].sort((a, b) => {
					const av = column.sortValue!(a);
					const bv = column.sortValue!(b);
					if (av < bv) return -1 * dir;
					if (av > bv) return 1 * dir;
					return 0;
				});
			}
		}
		return out;
	}, [rows, query, searchText, filters, filterState, sort, columnByKey]);

	const totalPages = Math.max(1, Math.ceil(processed.length / pageSize));
	const safePage = Math.min(page, totalPages);
	const pageRows = processed.slice(
		(safePage - 1) * pageSize,
		safePage * pageSize,
	);
	const colSpan = columns.length + (rowActions ? 1 : 0);

	const toggleSort = (key: string) => {
		setPage(1);
		setSort((current) => {
			if (!current || current.key !== key) return { key, dir: "asc" };
			if (current.dir === "asc") return { key, dir: "desc" };
			return null; // third click clears the sort
		});
	};

	const hasControls = Boolean(searchText) || Boolean(filters?.length);

	return (
		<div className={`space-y-3${className ? ` ${className}` : ""}`}>
			{hasControls && (
				<div className="flex flex-wrap items-center gap-2">
					{searchText && (
						<input
							value={query}
							onChange={(event) => {
								setQuery(event.target.value);
								setPage(1);
							}}
							placeholder={searchPlaceholder}
							className="min-w-[180px] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
						/>
					)}
					{filters?.map((filter) => (
						<select
							key={filter.key}
							value={filterState[filter.key] ?? ""}
							onChange={(event) => {
								setFilterState((state) => ({
									...state,
									[filter.key]: event.target.value,
								}));
								setPage(1);
							}}
							className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
						>
							<option value="">{filter.label}: All</option>
							{filter.options.map((option) => (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							))}
						</select>
					))}
				</div>
			)}

			<div className="overflow-x-auto rounded-xl border border-slate-800">
				<table
					className={`w-full ${minWidthClassName} text-left text-xs`}
				>
					<thead className="bg-slate-950/60 text-[10px] uppercase tracking-[0.12em] text-slate-500">
						<tr>
							{columns.map((column) => (
								<th
									key={column.key}
									className={`px-4 py-3 font-semibold ${column.headerClassName ?? ""}`}
								>
									{column.sortValue ? (
										<button
											type="button"
											onClick={() => toggleSort(column.key)}
											className="inline-flex items-center gap-1 hover:text-slate-300"
										>
											{column.header}
											<span className="text-[9px]">
												{sort?.key === column.key
													? sort.dir === "asc"
														? "▲"
														: "▼"
													: "↕"}
											</span>
										</button>
									) : (
										column.header
									)}
								</th>
							))}
							{rowActions && (
								<th className="px-4 py-3 text-right font-semibold">Actions</th>
							)}
						</tr>
					</thead>
					<tbody className="divide-y divide-slate-800/70">
						{pageRows.length === 0 ? (
							<tr>
								<td
									colSpan={colSpan}
									className="px-4 py-8 text-center text-slate-500"
								>
									{emptyLabel}
								</td>
							</tr>
						) : (
							pageRows.map((row) => {
								const id = getRowId(row);
								const selected = selectedRowId != null && id === selectedRowId;
								return (
									<tr
										key={id}
										onClick={onRowClick ? () => onRowClick(row) : undefined}
										className={`${onRowClick ? "cursor-pointer " : ""}${selected ? "bg-blue-500/5 " : ""}hover:bg-slate-900/50`}
									>
										{columns.map((column) => (
											<td
												key={column.key}
												className={`px-4 py-3 ${column.className ?? ""}`}
											>
												{column.render(row)}
											</td>
										))}
										{rowActions && (
											<td
												className="px-4 py-3 text-right"
												onClick={(event) => event.stopPropagation()}
											>
												{rowActions(row)}
											</td>
										)}
									</tr>
								);
							})
						)}
					</tbody>
				</table>
			</div>

			<div className="flex items-center justify-between gap-2">
				<HelperText>
					{processed.length === 0
						? "0 items"
						: `${(safePage - 1) * pageSize + 1}–${Math.min(
								safePage * pageSize,
								processed.length,
							)} of ${processed.length}`}
				</HelperText>
				{totalPages > 1 && (
					<div className="flex items-center gap-1">
						<button
							type="button"
							onClick={() => setPage((current) => Math.max(1, current - 1))}
							disabled={safePage === 1}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
						>
							Prev
						</button>
						<span className="px-2 text-xs text-slate-400">
							{safePage} / {totalPages}
						</span>
						<button
							type="button"
							onClick={() =>
								setPage((current) => Math.min(totalPages, current + 1))
							}
							disabled={safePage === totalPages}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
						>
							Next
						</button>
					</div>
				)}
			</div>
		</div>
	);
}
