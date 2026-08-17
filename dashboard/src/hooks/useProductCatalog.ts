import { useEffect, useState } from "react";
import {
	fetchProductCatalog,
	type ProductCatalogPurpose,
} from "../api/products";
import type { Product } from "../types";

type ProductCatalogState = {
	products: Product[];
	isLoadingProducts: boolean;
	productsError: string | null;
};

type ProductCatalogSnapshot = ProductCatalogState & { key: string };

export function useProductCatalog(
	limit = 50,
	purpose: ProductCatalogPurpose = "GENERATION",
): ProductCatalogState {
	const key = `${purpose}:${limit}`;
	const [state, setState] = useState<ProductCatalogSnapshot>(() => ({
		key,
		products: [],
		isLoadingProducts: true,
		productsError: null,
	}));

	useEffect(() => {
		let active = true;
		void fetchProductCatalog(limit, purpose)
			.then((response) => {
				if (!active) return;
				setState({
					key,
					products: response.items ?? [],
					isLoadingProducts: false,
					productsError: null,
				});
			})
			.catch((error: unknown) => {
				if (!active) return;
				setState({
					key,
					products: [],
					isLoadingProducts: false,
					productsError:
						error instanceof Error
							? error.message
							: "Failed to load product catalog.",
				});
			});
		return () => {
			active = false;
		};
	}, [key, limit, purpose]);

	if (state.key !== key) {
		return { products: [], isLoadingProducts: true, productsError: null };
	}
	return {
		products: state.products,
		isLoadingProducts: state.isLoadingProducts,
		productsError: state.productsError,
	};
}
