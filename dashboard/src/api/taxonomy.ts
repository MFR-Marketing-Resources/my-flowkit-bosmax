import { fetchAPI } from "./client";

export interface CopywritingTaxonomyTreeRecord {
  copywriting_angle: string;
  product_type_code: string;
  cluster: string;
  display_name: string;
  category: string;
  subcategory: string;
  type: string;
}

export interface CopywritingTaxonomyTree {
  categories: string[];
  subcategoriesByCategory: Record<string, string[]>;
  typesBySubcategory: Record<string, string[]>;
  recordByType: Record<string, CopywritingTaxonomyTreeRecord>;
}

export interface CopywritingTaxonomyResolution {
  product_id: string;
  product_display_name: string;
  match_status:
    | "EXACT_CODE"
    | "EXACT_TAXONOMY"
    | "AMBIGUOUS"
    | "UNMATCHED"
    | "NEEDS_RECONCILIATION";
  matched_by: string | null;
  product_fields: Record<string, string | null>;
  needs_reconciliation: boolean;
  current: Record<string, string | null>;
  match: CopywritingTaxonomyTreeRecord | Record<string, unknown> | null;
  nearest_match:
    | CopywritingTaxonomyTreeRecord
    | Record<string, unknown>
    | null;
  candidates: Array<CopywritingTaxonomyTreeRecord | Record<string, unknown>>;
}

export function fetchCopywritingTaxonomyTree(): Promise<CopywritingTaxonomyTree> {
  return fetchAPI<CopywritingTaxonomyTree>("/api/taxonomy/tree");
}

export function fetchProductCopywritingTaxonomy(
  productId: string,
): Promise<CopywritingTaxonomyResolution> {
  return fetchAPI<CopywritingTaxonomyResolution>(
    `/api/taxonomy/product/${encodeURIComponent(productId)}`,
  );
}
