import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterRecipe } from "../../types/posterRecipe";

const COPY_FIELDS = new Set<keyof PosterBuilderDraft>([
	"hook",
	"subhook",
	"usp_1",
	"usp_2",
	"usp_3",
	"cta",
]);

/** Recipe-defined copy slots. The zones of the SELECTED recipe define which
 * fields appear (role, max_chars, placeholder) — not a fixed Hook/Subhook/USP/CTA
 * form. Editable slots map back onto the canonical copy fields so existing backend
 * copy validation is unchanged. Zones without a source field (e.g. footer) are
 * shown read-only (filled by the recipe/compositor, Phase 2). */
export default function PosterRecipeSlotEditor({
	recipe,
	draft,
	onDraftChange,
}: {
	recipe: PosterRecipe;
	draft: PosterBuilderDraft;
	onDraftChange: (d: PosterBuilderDraft) => void;
}) {
	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5"
			data-testid="poster-recipe-slot-editor"
		>
			<h3 className="text-sm font-bold text-slate-100">3. Recipe copy slots</h3>
			<p className="mt-1 text-xs text-slate-500">
				Fill only the slots this recipe defines. Each slot has its own poster-fit
				length limit.
			</p>
			<div className="mt-4 grid gap-3 md:grid-cols-2">
				{recipe.zones.map((zone) => {
					const field = zone.source_field as keyof PosterBuilderDraft;
					const editable = COPY_FIELDS.has(field);
					if (!editable) {
						return (
							<div
								key={zone.zone_id}
								data-testid={`slot-readonly-${zone.zone_id}`}
								className="rounded-lg border border-slate-800 bg-slate-950/40 p-3"
							>
								<span className="text-[10px] font-bold uppercase text-slate-500">
									{zone.role} · {zone.zone_id}
								</span>
								<p className="mt-1 text-[11px] text-slate-500">
									{zone.placeholder} — auto/recipe slot (Phase 2 compositor).
								</p>
							</div>
						);
					}
					const value = String(draft[field] ?? "");
					const len = value.trim().length;
					const over = len > zone.max_chars;
					return (
						<label key={zone.zone_id} data-testid={`slot-${zone.zone_id}`}>
							<div className="flex items-center justify-between">
								<span className="text-[10px] font-bold uppercase text-slate-500">
									{zone.role} · {zone.zone_id}
								</span>
								<span
									data-testid={`slot-count-${zone.zone_id}`}
									className={`text-[9px] ${over ? "text-rose-300" : "text-slate-500"}`}
								>
									{len}/{zone.max_chars}
								</span>
							</div>
							<input
								data-testid={`slot-field-${zone.source_field}`}
								maxLength={zone.max_chars}
								placeholder={zone.placeholder}
								className={`mt-1 w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm text-slate-200 ${over ? "border-rose-500/60" : "border-slate-800"}`}
								value={value}
								onChange={(e) =>
									onDraftChange({
										...draft,
										[field]: e.target.value,
										// A slot edit is operator-authored copy (re-enters governance).
										copy_source: "manual",
										copy_set_id: "",
										copy_fallback_confirmed: false,
									})
								}
							/>
							{over ? (
								<p
									data-testid={`slot-over-${zone.zone_id}`}
									className="mt-1 text-[10px] text-rose-300"
								>
									Terlalu panjang — pendekkan supaya muat slot ({zone.max_chars}).
								</p>
							) : null}
						</label>
					);
				})}
			</div>
		</section>
	);
}
