import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Product, WorkspacePackageReadinessItem } from "../../types";

interface SearchableProductSelectProps {
	products: Product[];
	selectedProduct: Product | null;
	onSelect: (product: Product | null) => void;
	readinessByProductId?: Record<string, WorkspacePackageReadinessItem>;
}

export default function SearchableProductSelect({
	products,
	selectedProduct,
	onSelect,
	readinessByProductId = {},
}: SearchableProductSelectProps) {
	const [isOpen, setIsOpen] = useState(false);
	const [search, setSearch] = useState("");
	const containerRef = useRef<HTMLDivElement>(null);

	const filtered = products.filter((product) =>
		product.raw_product_title.toLowerCase().includes(search.toLowerCase()),
	);

	useEffect(() => {
		const handleClickOutside = (event: MouseEvent) => {
			if (
				containerRef.current &&
				!containerRef.current.contains(event.target as Node)
			) {
				setIsOpen(false);
			}
		};
		document.addEventListener("mousedown", handleClickOutside);
		return () => document.removeEventListener("mousedown", handleClickOutside);
	}, []);

	return (
		<div className="relative min-w-0" ref={containerRef}>
			<button
				type="button"
				onClick={() => setIsOpen(!isOpen)}
				className="flex w-full min-w-0 items-start justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 transition-all group hover:border-blue-500/50 cursor-pointer"
			>
				<div className="min-w-0 flex-1">
					{selectedProduct ? (
						<>
							<span className="bosmax-wrap-safe block text-sm font-bold text-slate-200">
								{selectedProduct.raw_product_title}
							</span>
							<span className="mt-2 inline-flex rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] text-emerald-200">
								{readinessByProductId[selectedProduct.id]?.readiness_status ??
									"READY"}
							</span>
						</>
					) : (
						<span className="bosmax-wrap-safe block text-sm text-slate-500">
							Search and select product...
						</span>
					)}
				</div>
				<ChevronDown
					size={18}
					className={`text-slate-500 group-hover:text-blue-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
				/>
			</button>

			{isOpen && (
				<div className="absolute z-50 mt-2 w-full min-w-0 overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl shadow-black/50 backdrop-blur-xl">
					<div className="p-3 border-bottom border-slate-800 bg-slate-950/50 flex items-center gap-2">
						<Search size={14} className="text-slate-500" />
						<input
							type="text"
							className="bg-transparent border-none outline-none text-xs text-slate-300 w-full"
							placeholder="Search by name..."
							value={search}
							onChange={(event) => setSearch(event.target.value)}
							onClick={(event) => event.stopPropagation()}
						/>
					</div>

					<div className="max-h-64 overflow-y-auto py-2">
						{filtered.length > 0 ? (
							filtered.map((product) => {
								const readiness = readinessByProductId[product.id];
								const readinessTone =
									readiness?.readiness_status === "READY"
										? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
										: "border-rose-500/30 bg-rose-500/10 text-rose-200";
								return (
									<button
										type="button"
										key={product.id}
										onClick={() => {
											onSelect(product);
											setIsOpen(false);
											setSearch("");
										}}
										className={`flex items-start justify-between gap-3 px-4 py-3 text-[11px] transition-colors cursor-pointer ${selectedProduct?.id === product.id ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`}
									>
										<div className="min-w-0 flex-1 pr-2">
											<span className="bosmax-wrap-safe block">
												{product.raw_product_title}
											</span>
											<span
												className={`mt-2 inline-flex rounded-full border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] ${readinessTone}`}
											>
												{readiness?.readiness_status ?? "READY"}
											</span>
										</div>
										{selectedProduct?.id === product.id ? (
											<Check size={14} />
										) : null}
									</button>
								);
							})
						) : (
							<div className="px-4 py-6 text-center text-xs text-slate-600 italic">
								No products match your search.
							</div>
						)}
					</div>

					<div className="p-2 border-t border-slate-800 bg-slate-950/20 text-right">
						<span className="text-[9px] text-slate-600 uppercase tracking-widest font-bold pr-2">
							{filtered.length} visible
						</span>
					</div>
				</div>
			)}
		</div>
	);
}
