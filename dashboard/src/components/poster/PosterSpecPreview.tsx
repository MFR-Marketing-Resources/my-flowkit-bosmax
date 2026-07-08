import type { OverlaySpec, PosterSpec } from "../../types/posterRecipe";

/** Structured poster_spec + overlay_spec preview (recipe path only). Overlay is a
 * deterministic layout foundation — NOT a rendered poster; the disclaimer makes
 * the Phase 2 compositor limitation explicit. */
export default function PosterSpecPreview({
	posterSpec,
	overlaySpec,
}: {
	posterSpec: PosterSpec | null | undefined;
	overlaySpec: OverlaySpec | null | undefined;
}) {
	if (!posterSpec && !overlaySpec) return null;
	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5"
			data-testid="poster-spec-preview"
		>
			<h3 className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
				Structured poster spec
			</h3>

			{posterSpec ? (
				<div className="mt-3 grid gap-2 text-xs text-slate-300 md:grid-cols-2">
					<div>
						Recipe: <span className="text-slate-100">{posterSpec.recipe_id}</span> ·{" "}
						{posterSpec.archetype}
					</div>
					<div>Layout: {posterSpec.layout_template}</div>
					<div className="md:col-span-2">Placement: {posterSpec.product_placement}</div>
					<div>Scene: {posterSpec.background_scene}</div>
					<div>Style: {posterSpec.visual_style}</div>
				</div>
			) : null}

			{overlaySpec ? (
				<>
					<div className="mt-4 overflow-x-auto">
						<table className="w-full min-w-[420px] text-left text-[11px] text-slate-400">
							<thead className="text-slate-500">
								<tr>
									<th className="py-1 pr-3">Zone</th>
									<th className="py-1 pr-3">Role</th>
									<th className="py-1 pr-3">x/y/w/h</th>
									<th className="py-1">Text</th>
								</tr>
							</thead>
							<tbody data-testid="poster-overlay-zones">
								{overlaySpec.zones.map((z) => (
									<tr key={z.zone_id} className="border-t border-slate-800/70">
										<td className="py-1 pr-3 text-slate-300">{z.zone_id}</td>
										<td className="py-1 pr-3">{z.role}</td>
										<td className="py-1 pr-3 tabular-nums">
											{z.x}/{z.y}/{z.w}/{z.h}
										</td>
										<td className="py-1 text-slate-200">{z.text}</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
					<p
						data-testid="poster-overlay-disclaimer"
						className="mt-3 text-[11px] text-amber-300"
					>
						overlay_spec is a deterministic layout foundation only. It does not
						render crisp final text until a Phase 2 compositor exists
						(renderer: {overlaySpec.renderer}).
					</p>
				</>
			) : null}
		</section>
	);
}
