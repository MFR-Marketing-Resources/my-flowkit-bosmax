import { useCallback, useEffect, useRef, useState } from "react";

import {
	fetchProductMascot,
	removeProductMascot,
	setProductMascot,
	type ProductMascot,
} from "../../api/productMascot";

/**
 * Product Mascot Key Visual — a sibling of the Official Product Visual in the
 * VISUAL tab. Minimal operator controls: preview / upload / replace / remove.
 * No generation, no model/provider selection, no prompt editor, no job history.
 * The mascot is a creative derivative and NEVER the Official Product Visual.
 */
export default function ProductMascotKeyVisualPanel({
	productId,
}: {
	productId: string;
}) {
	const [mascot, setMascot] = useState<ProductMascot | null>(null);
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const fileRef = useRef<HTMLInputElement | null>(null);

	const load = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const res = await fetchProductMascot(productId);
			setMascot(res.mascot);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load mascot");
		} finally {
			setLoading(false);
		}
	}, [productId]);

	useEffect(() => {
		void load();
	}, [load]);

	const onFile = useCallback(
		async (file: File) => {
			setBusy(true);
			setError(null);
			try {
				const dataUrl = await new Promise<string>((resolve, reject) => {
					const reader = new FileReader();
					reader.onload = () => resolve(String(reader.result));
					reader.onerror = () => reject(new Error("Failed to read file"));
					reader.readAsDataURL(file);
				});
				const base64 = dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
				const res = await setProductMascot(productId, {
					image_base64: base64,
					file_name: file.name,
				});
				setMascot(res.mascot);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Upload failed");
			} finally {
				setBusy(false);
				if (fileRef.current) fileRef.current.value = "";
			}
		},
		[productId],
	);

	const onRemove = useCallback(async () => {
		setBusy(true);
		setError(null);
		try {
			await removeProductMascot(productId);
			setMascot(null);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Remove failed");
		} finally {
			setBusy(false);
		}
	}, [productId]);

	return (
		<section className="rounded-3xl border border-slate-800 bg-slate-950/60 p-6">
			<div>
				<h3 className="text-base font-semibold text-white">
					Product Mascot Key Visual
				</h3>
				<p className="mt-1 max-w-2xl text-sm text-slate-400">
					A creative-derivative character anchor for this product, used as the
					recurring visual identity in Mascot Montage. It is separate from the
					Official Product Visual and never replaces Product Truth. Generate the
					mascot externally in any tool, then upload the final image here.
				</p>
			</div>

			{error && (
				<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-300">
					{error}
				</div>
			)}

			<div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center">
				<div className="flex h-40 w-40 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-slate-800 bg-slate-900">
					{loading ? (
						<span className="text-xs text-slate-500">Loading…</span>
					) : mascot?.preview_url ? (
						<img
							src={mascot.preview_url}
							alt="Product mascot key visual"
							className="h-full w-full object-contain"
						/>
					) : (
						<span className="px-3 text-center text-xs text-slate-500">
							No mascot uploaded
						</span>
					)}
				</div>

				<div className="flex flex-1 flex-col gap-3">
					{mascot ? (
						<div className="text-sm text-slate-300">
							<div className="font-medium text-white">
								{mascot.display_name || "Product Mascot"}
							</div>
							<div className="text-xs text-slate-500">
								Updated {mascot.updated_at || "—"}
							</div>
						</div>
					) : (
						<div className="text-sm text-slate-400">
							Upload a PNG, JPG, or WebP image to set this product's mascot.
						</div>
					)}

					<div className="flex flex-wrap gap-2">
						<input
							ref={fileRef}
							type="file"
							accept="image/png,image/jpeg,image/webp"
							className="hidden"
							onChange={(event) => {
								const file = event.target.files?.[0];
								if (file) void onFile(file);
							}}
						/>
						<button
							type="button"
							disabled={busy || loading}
							onClick={() => fileRef.current?.click()}
							className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
						>
							{busy ? "Working…" : mascot ? "Replace" : "Upload"}
						</button>
						{mascot && (
							<button
								type="button"
								disabled={busy}
								onClick={() => void onRemove()}
								className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800 disabled:opacity-50"
							>
								Remove
							</button>
						)}
					</div>
				</div>
			</div>
		</section>
	);
}
