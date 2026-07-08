import { useEffect, useState } from "react";
import { getAPI } from "./client";
import type { PosterRecipe } from "../types/posterRecipe";

/** Read-only fetch of the poster recipe authority (GET /api/poster/recipes).
 * No mutation, no generation, no credit spend. */
export async function fetchPosterRecipes(): Promise<PosterRecipe[]> {
	const res = await getAPI<{ recipes: PosterRecipe[] }>("/api/poster/recipes");
	return res.recipes ?? [];
}

export function usePosterRecipes(): { recipes: PosterRecipe[]; error: string } {
	const [recipes, setRecipes] = useState<PosterRecipe[]>([]);
	const [error, setError] = useState("");
	useEffect(() => {
		let active = true;
		void fetchPosterRecipes()
			.then((r) => {
				if (active) setRecipes(r);
			})
			.catch((e: Error) => {
				if (active) setError(e.message || "Failed to load poster recipes.");
			});
		return () => {
			active = false;
		};
	}, []);
	return { recipes, error };
}
