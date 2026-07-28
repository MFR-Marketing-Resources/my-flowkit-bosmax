import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

export type VisualAssetPickerItem = {
	value: string;
	title: string;
	subtitle: string;
	previewUrl?: string | null;
	status?: string | null;
};

type VisualAssetPreviewProps = {
	title: string;
	subtitle?: string;
	previewUrl?: string | null;
	className?: string;
};

export function VisualAssetPreview({
	title,
	subtitle,
	previewUrl,
	className = "h-12",
}: VisualAssetPreviewProps) {
	const [failed, setFailed] = useState(false);
	const [open, setOpen] = useState(false);

	useEffect(() => {
		setFailed(false);
		setOpen(false);
	}, [previewUrl]);

	const resolvedPreview = Boolean(previewUrl && !failed);

	return (
		<>
			{resolvedPreview ? (
				<button
					aria-label={`Preview ${title}`}
					className="block w-full overflow-hidden rounded-lg bg-slate-950"
					onClick={(event) => {
						event.stopPropagation();
						setOpen(true);
					}}
					type="button"
				>
					<img
						alt={`Preview of ${title}`}
						className={`${className} w-full object-cover`}
						onError={() => setFailed(true)}
						src={previewUrl ?? undefined}
					/>
				</button>
			) : (
				<div
					className={`flex ${className} items-center justify-center rounded-lg bg-slate-800 px-1 text-center text-[9px] text-slate-400`}
					data-testid="visual-asset-fallback"
				>
					Preview unavailable
				</div>
			)}
			{open && resolvedPreview ? (
				<div
					aria-label="Image preview"
					aria-modal="true"
					className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-4"
					role="dialog"
				>
					<div className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 p-4 shadow-2xl">
						<img
							alt={title}
							className="max-h-[70vh] w-full rounded-lg object-contain"
							src={previewUrl ?? undefined}
						/>
						<div className="mt-3">
							<div className="font-semibold text-slate-100">{title}</div>
							{subtitle ? (
								<div className="text-xs text-slate-400">{subtitle}</div>
							) : null}
						</div>
						<button
							className="mt-3 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
							onClick={() => setOpen(false)}
							type="button"
						>
							Close preview
						</button>
					</div>
				</div>
			) : null}
		</>
	);
}

type VisualAssetPickerProps = {
	label: string;
	items: VisualAssetPickerItem[];
	value: string;
	onChange: (value: string) => void;
	isLoading?: boolean;
	error?: string | null;
	emptyMessage?: string;
	placeholder?: string;
	searchPlaceholder?: string;
};

export default function VisualAssetPicker({
	label,
	items,
	value,
	onChange,
	isLoading = false,
	error = null,
	emptyMessage = "No visual assets available.",
	placeholder = "Select a visual asset",
	searchPlaceholder = "Search name or code",
}: VisualAssetPickerProps) {
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const containerRef = useRef<HTMLDivElement>(null);
	const selected = items.find((item) => item.value === value) ?? null;
	const shown = useMemo(
		() =>
			items.filter((item) =>
				`${item.title} ${item.subtitle} ${item.status ?? ""}`
					.toLowerCase()
					.includes(query.toLowerCase()),
			),
		[items, query],
	);

	useEffect(() => {
		const closeOnOutsideClick = (event: MouseEvent) => {
			if (
				containerRef.current &&
				!containerRef.current.contains(event.target as Node)
			) {
				setOpen(false);
			}
		};
		document.addEventListener("mousedown", closeOnOutsideClick);
		return () => document.removeEventListener("mousedown", closeOnOutsideClick);
	}, []);

	return (
		<div className="relative mt-2" ref={containerRef}>
			<div
				aria-label={label}
				className="flex min-h-16 items-center gap-2 rounded-xl border border-slate-800 bg-slate-950 p-2"
			>
				{selected ? (
					<div className="w-16 shrink-0">
						<VisualAssetPreview
							previewUrl={selected.previewUrl}
							subtitle={selected.subtitle}
							title={selected.title}
						/>
					</div>
				) : (
					<div className="flex h-12 w-16 shrink-0 items-center justify-center rounded-lg bg-slate-800 text-[9px] text-slate-500">
						No selection
					</div>
				)}
				<button
					aria-controls={`${label.replace(/\s+/g, "-").toLowerCase()}-options`}
					aria-expanded={open}
					aria-haspopup="listbox"
					aria-label={`${label} visual combobox`}
					className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-slate-900"
					onClick={() => setOpen((current) => !current)}
					onKeyDown={(event) => {
						if (event.key === "Escape") setOpen(false);
					}}
					type="button"
				>
					<span className="min-w-0">
						<span className="block truncate text-xs font-semibold text-slate-100">
							{selected?.title ?? placeholder}
						</span>
						<span className="block truncate text-[10px] text-slate-400">
							{selected?.subtitle ?? `${items.length} option${items.length === 1 ? "" : "s"}`}
						</span>
					</span>
					<span className="flex shrink-0 items-center gap-2">
						{selected ? <Check aria-label="Selected" className="text-cyan-300" size={15} /> : null}
						<ChevronDown
							className={`text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
							size={16}
						/>
					</span>
				</button>
			</div>

			{open ? (
				<div
					className="absolute z-50 mt-2 w-full overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/50"
					id={`${label.replace(/\s+/g, "-").toLowerCase()}-options`}
				>
					<div className="flex items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-3 py-2">
						<Search className="shrink-0 text-slate-500" size={14} />
						<input
							aria-label={`${label} search`}
							className="w-full bg-transparent text-xs text-slate-200 outline-none placeholder:text-slate-600"
							onChange={(event) => setQuery(event.target.value)}
							placeholder={searchPlaceholder}
							value={query}
						/>
					</div>

					<div
						aria-label={`${label} options`}
						className="max-h-72 space-y-1 overflow-y-auto p-2"
						role="listbox"
					>
						{isLoading ? (
							<div className="p-3 text-xs text-slate-400">Loading visual assets…</div>
						) : error ? (
							<div className="p-3 text-xs text-rose-200">{error}</div>
						) : shown.length === 0 ? (
							<div className="p-3 text-xs text-slate-400">
								{query ? "No visual assets match this search." : emptyMessage}
							</div>
						) : (
							shown.map((item) => {
								const itemSelected = item.value === value;
								return (
									<div
										aria-selected={itemSelected}
										className={`flex items-center gap-2 rounded-lg border p-2 ${
											itemSelected
												? "border-cyan-400/70 bg-cyan-500/10"
												: "border-slate-800 bg-slate-950/50"
										}`}
										key={item.value}
										role="option"
									>
										<div className="w-16 shrink-0">
											<VisualAssetPreview
												previewUrl={item.previewUrl}
												subtitle={item.subtitle}
												title={item.title}
											/>
										</div>
										<div className="min-w-0 flex-1">
											<div className="truncate text-xs font-semibold text-slate-100">
												{item.title}
											</div>
											<div className="truncate text-[10px] text-slate-400">
												{item.subtitle}
											</div>
											{item.status ? (
												<div className="mt-1 inline-flex rounded-full border border-slate-700 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-300">
													{item.status}
												</div>
											) : null}
										</div>
										<button
											aria-label={`${itemSelected ? "Selected" : "Select"} ${item.title}`}
											className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${
												itemSelected
													? "border-cyan-400 bg-cyan-500/20 text-cyan-200"
													: "border-slate-700 text-slate-300 hover:border-cyan-500 hover:text-cyan-200"
											}`}
											onClick={() => {
												onChange(item.value);
												setOpen(false);
												setQuery("");
											}}
											type="button"
										>
											<Check size={16} />
										</button>
									</div>
								);
							})
						)}
					</div>
				</div>
			) : null}
		</div>
	);
}
