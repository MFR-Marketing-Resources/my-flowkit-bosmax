import type { PosterRecipe } from "../../types/posterRecipe";

/** Recipe-first entry point: the operator picks a poster archetype BEFORE any
 * copy editing. Cards surface the recipe's structure (archetype, layout, allowed
 * text density, slot summary) so the choice drives the rest of the flow. */
export default function PosterRecipeSelector({
	recipes,
	selectedRecipeId,
	onSelect,
	error,
}: {
	recipes: PosterRecipe[];
	selectedRecipeId: string;
	onSelect: (recipeId: string) => void;
	error?: string;
}) {
	return (
		<section
			className="rounded-2xl border border-blue-500/30 bg-blue-950/20 p-5"
			data-testid="poster-recipe-selector"
		>
			<h3 className="text-sm font-bold text-blue-100">1. Choose a poster recipe</h3>
			<p className="mt-1 text-xs text-slate-400">
				Pick the poster archetype first — it defines the layout, scene, and which
				copy slots you fill. Copy comes after the recipe, not before.
			</p>

			{error ? (
				<p className="mt-3 text-sm text-rose-200" data-testid="poster-recipe-error">
					{error}
				</p>
			) : null}

			<div className="mt-4 grid gap-3 md:grid-cols-3">
				{recipes.map((r) => {
					const active = r.recipe_id === selectedRecipeId;
					return (
						<button
							key={r.recipe_id}
							type="button"
							data-testid={`poster-recipe-card-${r.recipe_id}`}
							aria-pressed={active}
							onClick={() => onSelect(r.recipe_id)}
							className={`rounded-xl border p-4 text-left transition ${
								active
									? "border-blue-400 bg-blue-600/20"
									: "border-slate-800 bg-slate-900/50 hover:border-blue-500/40"
							}`}
						>
							<div className="flex items-center justify-between gap-2">
								<span className="text-sm font-semibold text-slate-100">{r.label}</span>
								{active ? (
									<span className="rounded border border-blue-400/50 px-1.5 py-0.5 text-[9px] uppercase text-blue-100">
										Selected
									</span>
								) : null}
							</div>
							<span className="mt-1 block text-[9px] uppercase tracking-[0.14em] text-slate-500">
								{r.archetype}
							</span>
							<p className="mt-2 text-xs text-slate-400">{r.description}</p>
							<dl className="mt-3 space-y-1 text-[10px] text-slate-500">
								<div>
									Layout: <span className="text-slate-300">{r.layout_template}</span>
								</div>
								<div>
									Text density:{" "}
									<span className="text-slate-300">
										{r.allowed_text_density.join(" / ") || "—"}
									</span>
								</div>
								<div>
									Slots:{" "}
									<span className="text-slate-300">
										{r.zones.length} zones · {r.chip_slots.length} chips
									</span>
								</div>
							</dl>
						</button>
					);
				})}
			</div>

			{recipes.length === 0 && !error ? (
				<p className="mt-4 text-sm text-slate-500">Loading recipes…</p>
			) : null}
		</section>
	);
}
