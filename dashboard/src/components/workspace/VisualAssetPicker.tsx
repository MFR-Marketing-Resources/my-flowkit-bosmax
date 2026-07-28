import { useMemo, useState } from "react";

export type VisualAssetPickerItem = {
	value: string;
	title: string;
	subtitle: string;
	previewUrl?: string | null;
};

type VisualAssetPickerProps = {
	label: string;
	items: VisualAssetPickerItem[];
	value: string;
	onChange: (value: string) => void;
};

export default function VisualAssetPicker({
	label,
	items,
	value,
	onChange,
}: VisualAssetPickerProps) {
	const [query, setQuery] = useState("");
	const [preview, setPreview] = useState<VisualAssetPickerItem | null>(null);
	const shown = useMemo(
		() =>
			items.filter((item) =>
				`${item.title} ${item.subtitle}`
					.toLowerCase()
					.includes(query.toLowerCase()),
			),
		[items, query],
	);

	return (
		<div className="mt-2 space-y-2" aria-label={label}>
			<input
				aria-label={`${label} search`}
				className="w-full rounded border border-slate-800 bg-slate-950 px-2 py-1 text-xs"
				onChange={(event) => setQuery(event.target.value)}
				placeholder="Search name or code"
				value={query}
			/>
			<div className="grid grid-cols-2 gap-2">
				{shown.map((item) => (
					<div
						className={`rounded border p-2 text-left text-xs ${
							value === item.value
								? "border-cyan-400 bg-cyan-500/10"
								: "border-slate-800"
						}`}
						key={item.value}
					>
						{item.previewUrl ? (
							<button
								aria-label={`Preview ${item.title}`}
								className="block w-full"
								onClick={() => setPreview(item)}
								type="button"
							>
								<img
									alt={`Preview of ${item.title}`}
									className="h-16 w-full object-cover"
									src={item.previewUrl}
								/>
							</button>
						) : (
							<div className="flex h-16 items-center justify-center bg-slate-800 text-slate-400">
								Preview unavailable
							</div>
						)}
						<button
							aria-pressed={value === item.value}
							className="mt-1 w-full text-left"
							onClick={() => onChange(item.value)}
							type="button"
						>
							<div>{item.title}</div>
							<div className="text-slate-400">{item.subtitle}</div>
						</button>
					</div>
				))}
			</div>
			{preview?.previewUrl ? (
				<div
					aria-label="Image preview"
					className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4"
					role="dialog"
				>
					<div className="max-w-lg rounded bg-slate-900 p-3">
						<img alt={preview.title} className="max-h-[70vh]" src={preview.previewUrl} />
						<button
							className="mt-2 rounded border px-3 py-1"
							onClick={() => setPreview(null)}
							type="button"
						>
							Close preview
						</button>
					</div>
				</div>
			) : null}
		</div>
	);
}
