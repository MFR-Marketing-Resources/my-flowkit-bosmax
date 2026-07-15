import type { ChangeEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchAPI, patchAPI, postAPI, postMultipartAPI } from "../api/client";
import {
	fetchProductIntelligence,
	fetchProductIntelligenceProvenance,
	fetchProductIntelligenceSnapshots,
} from "../api/products";
import ProductIntelligenceReviewDraftPanel from "../components/product-intelligence/ProductIntelligenceReviewDraftPanel";
import { HelperText } from "../components/ui";
import type {
	FastMossImportBatchReport,
	Product,
	ProductCreativeBrief,
	ProductIntelligenceFieldProvenance,
	ProductIntelligenceLatestSnapshotResponse,
	ProductIntelligenceSnapshot,
	VariationPlan,
} from "../types";
import {
	formatCommissionDisplay,
	formatCommissionRateDisplay,
	formatCountDisplay,
	formatCurrencyDisplay,
	formatTaxonomyPath,
} from "../utils/productDisplay";

type ManualFormState = Partial<Product> & {
	image_base64?: string | null;
	image_filename?: string | null;
};

type TikTokFormState = {
	url: string;
	raw_product_title: string;
};

type UnsafeHandlingProduct = Product & {
	unsafe_handling_rules?: string[];
};

type ProductSortMode =
	| "PRODUCT_SOLD_VERIFIED_DESC"
	| "SHOP_TOTAL_SOLD_DESC"
	| "PRODUCT_NAME_ASC";
type LifecycleFilterMode = "ACTIVE_ONLY" | "INCLUDE_ARCHIVED" | "ARCHIVED_ONLY";
type LifecycleActionType =
	| "ARCHIVE"
	| "UNARCHIVE"
	| "DELETE_TEST_ROW"
	| "DELETE_PRODUCT";
type FastMossImportFieldKey =
	| "creator_search"
	| "export_ad_list"
	| "export_advertiser_list"
	| "shop_list"
	| "sales_rank"
	| "new_products_ranking"
	| "product_search_data"
	| "product_search_sales_rank"
	| "most_promoted_products_rank"
	| "video_product_list";

const FASTMOSS_IMPORT_FIELDS: Array<{
	key: FastMossImportFieldKey;
	label: string;
}> = [
	{ key: "creator_search", label: "Creator Search" },
	{ key: "export_ad_list", label: "Export Ad List" },
	{ key: "export_advertiser_list", label: "Export Advertiser List" },
	{ key: "shop_list", label: "Shop List" },
	{ key: "sales_rank", label: "Sales Rank" },
	{ key: "new_products_ranking", label: "New Products Ranking" },
	{ key: "product_search_data", label: "Product Search Data" },
	{ key: "product_search_sales_rank", label: "Product Search Sales Rank" },
	{ key: "most_promoted_products_rank", label: "Most Promoted Products Rank" },
	{ key: "video_product_list", label: "Video Product List" },
];

const PRODUCT_INTELLIGENCE_REQUIRED_FIELDS = [
	"product_description",
	"benefits_json",
	"usp_json",
	"usage_text",
	"ingredients_text",
	"warnings_text",
	"target_customer_text",
	"allowed_claims_json",
	"buyer_persona_snapshot_json",
	"copy_strategy_summary_json",
	"source_urls_json",
	"image_evidence_json",
	"claim_gate",
	"claim_risk_level",
] as const;

const PHYSICS_ENGINE_KEYWORD: Record<string, string> = {
	BEAUTY_BOTTLE_OR_TUBE:
		"EXACTLY beauty bottle or tube size. Fits naturally in one hand — hold upright with label facing camera.",
	SKINCARE_JAR_OR_TUBE:
		"EXACTLY skincare jar or tube size. Compact — hold in one hand with lid or label visible.",
	A: "EXACTLY perfume/fragrance bottle size. Small, elegant — display upright with nozzle and label visible.",
	SUPPLEMENT_BOTTLE:
		"EXACTLY supplement bottle size. Cylindrical, label-forward — hold upright in one hand.",
	TRADITIONAL_HERBAL_OIL_BOTTLE:
		"EXACTLY compact traditional herbal-oil bottle size. Small palm-size bottle in an adult hand — hold upright with label facing camera.",
	MEDICAL_TEST_KIT:
		"EXACTLY medical test kit size. Compact box or pouch — hold flat in one hand, label facing camera.",
	FOOD_PACK_OR_JAR:
		"EXACTLY food pack or jar size. Sealed — hold upright in one hand with label clearly visible.",
	B: "EXACTLY food jar or bottle size. Hold upright in one hand, label facing camera.",
	HOUSEHOLD_PACKAGED_GOODS:
		"EXACTLY household packaged goods size. Boxy or bottle-shaped — hold upright with branding facing camera.",
	LAUNDRY_LIQUID_REFILL:
		"EXACTLY laundry liquid refill pack size. Soft flexible pouch — hold upright with spout pointing up.",
	FABRIC_SOFTENER_LIQUID:
		"EXACTLY fabric softener bottle size. Hold upright in one hand, label facing camera.",
	RIGID_CONTAINER:
		"EXACTLY rigid container size. Firm, boxy or cylindrical — hold upright with label facing camera.",
	KITCHEN_TOOL:
		"EXACTLY kitchen tool size. Handle-forward — demonstrate grip naturally in one hand.",
	ELECTRONICS_SMALL_DEVICE:
		"EXACTLY small electronics device size. Compact — hold in one hand with screen or brand facing camera.",
	STATIONERY_PACK:
		"EXACTLY stationery pack size. Flat or slim — hold in one hand with label visible.",
	PAPER_GOODS:
		"EXACTLY paper goods pack size. Flat, rectangular — hold naturally with branding facing camera.",
	TOY_BOX_OR_PACK:
		"EXACTLY toy box or pack size. Boxy — hold upright with front panel facing camera.",
	SMALL_RIGID_DECOR:
		"EXACTLY small decorative item size. Display upright or flat in one hand with design visible.",
	FASHION_ACCESSORY_SMALL_OBJECT:
		"EXACTLY small fashion accessory size. Compact — hold or wear naturally, item clearly visible.",
	WIPES_SOFT_PACK:
		"EXACTLY wipes soft pack size. Flat, flexible pouch — hold in one hand with label facing camera.",
	SOFT_PACKAGED_GOODS:
		"EXACTLY soft-packaged goods size. Flexible pouch or sachet — hold upright in one hand.",
};

function getEngineKeywordPreview(
	physicsClass: string | null | undefined,
): string {
	if (!physicsClass)
		return "No physics class set — cannot preview engine keyword.";
	return (
		PHYSICS_ENGINE_KEYWORD[physicsClass] ??
		`No mapping defined for physics class: ${physicsClass}`
	);
}

function emptyManualForm(): ManualFormState {
	return {
		raw_product_title: "",
		product_short_name: "",
		brand: "",
		category: "",
		subcategory: "",
		type: "",
		price: undefined,
		currency: "MYR",
		commission_amount: undefined,
		commission_rate: "",
		image_url: "",
		source_url: "",
		product_type: "",
		silo: "",
		trigger_id: "",
		formula: "",
		copywriting_angle: "",
		claim_risk_level: "",
		physics_class: "",
		recommended_grip: "",
		hand_object_interaction: "",
		material_behavior: "",
		surface_behavior: "",
		unsafe_handling_rules: [],
		section_5_product_physics_prompt: "",
		image_base64: null,
		image_filename: null,
	};
}

function fieldValue(value: string | number | null | undefined) {
	if (value === null || value === undefined || value === "")
		return "NOT_AVAILABLE";
	return String(value);
}

function formatTimestamp(value: string | null | undefined) {
	if (!value) return "NOT_AVAILABLE";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return value;
	return date.toLocaleString("en-MY", {
		year: "numeric",
		month: "short",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
	});
}

function formatScore(value: number | null | undefined) {
	if (value === null || value === undefined || Number.isNaN(value))
		return "NOT_AVAILABLE";
	return value.toFixed(2);
}

function getSnapshotStatusTone(
	status: ProductIntelligenceSnapshot["status"] | null | undefined,
) {
	switch (status) {
		case "APPROVED":
			return "ready";
		case "DRAFT":
		case "SUPERSEDED":
			return "warn";
		case "REJECTED":
		case "ARCHIVED":
			return "risk";
		default:
			return "neutral";
	}
}

function getLatestSnapshotStatusTone(
	status:
		| ProductIntelligenceLatestSnapshotResponse["status"]
		| null
		| undefined,
) {
	return status === "APPROVED_SNAPSHOT_AVAILABLE" ? "ready" : "warn";
}

function getClaimRiskTone(value: string | null | undefined) {
	switch (value) {
		case "LOW":
			return "ready";
		case "MEDIUM":
			return "warn";
		case "HIGH":
			return "risk";
		default:
			return "neutral";
	}
}

function hasSnapshotValue(value: unknown) {
	if (value === null || value === undefined) return false;
	if (typeof value === "string") return value.trim().length > 0;
	if (Array.isArray(value)) return value.length > 0;
	if (typeof value === "object") return Object.keys(value).length > 0;
	return true;
}

function getSnapshotMissingFields(
	snapshot: ProductIntelligenceSnapshot | null,
) {
	if (!snapshot) return [...PRODUCT_INTELLIGENCE_REQUIRED_FIELDS];
	return PRODUCT_INTELLIGENCE_REQUIRED_FIELDS.filter((fieldName) => {
		const value = snapshot[fieldName];
		return !hasSnapshotValue(value);
	});
}

function formatNormalizedText(value: unknown) {
	if (value === null || value === undefined || value === "")
		return "NOT_AVAILABLE";
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
}

function summarizeRecord(record: Record<string, unknown>) {
	return Object.entries(record).filter(([, value]) => hasSnapshotValue(value));
}

function normalizeProductIntelligenceError(error: unknown) {
	const message =
		error instanceof Error
			? error.message
			: "Failed to load product intelligence snapshots";
	if (message.includes("PRODUCT_NOT_FOUND")) {
		return "PRODUCT_NOT_FOUND: selected product no longer exists in the catalog.";
	}
	return message;
}

function salesMetricScope(product: Product) {
	return (
		product.sold_count_metric_scope ||
		product.sales_metrics?.sold_count_metric_scope ||
		"UNKNOWN"
	);
}

function salesMetricTruthStatus(product: Product) {
	return (
		product.sold_count_truth_status ||
		product.sales_metrics?.sold_count_truth_status ||
		"NOT_VERIFIED"
	);
}

function productSoldCount(product: Product) {
	return (
		product.product_sold_count ??
		product.sales_metrics?.product_sold_count ??
		null
	);
}

function shopTotalSoldCount(product: Product) {
	return (
		product.shop_total_sold_count ??
		product.sales_metrics?.shop_total_sold_count ??
		null
	);
}

function salesMetricWarnings(product: Product) {
	return (
		product.sales_metric_warnings ||
		product.sales_metrics?.sales_metric_warnings ||
		[]
	);
}

function hasTextValue<T extends string>(
	value: T | null | undefined,
): value is T {
	return typeof value === "string" && value.trim().length > 0;
}

function lifecycleStatus(product: Product | null) {
	return product?.lifecycle_status || "ACTIVE";
}

function isArchivedProduct(product: Product | null) {
	return lifecycleStatus(product) === "ARCHIVED";
}

function isReferenceOnlyProduct(product: Product | null) {
	return Boolean(
		product?.reference_only || product?.source_lane === "FASTMOSS_REFERENCE",
	);
}

function isDeleteTestEligible(product: Product | null) {
	if (!product) return false;
	const titles = [
		product.raw_product_title,
		product.product_display_name,
		product.product_short_name,
	]
		.filter(
			(value): value is string =>
				typeof value === "string" && value.trim().length > 0,
		)
		.map((value) => value.trim().toUpperCase());
	return (
		product.source !== "FASTMOSS" &&
		titles.some((value) => value.endsWith("TEST_DO_NOT_USE"))
	);
}

function emptyFastMossImportState(): Record<
	FastMossImportFieldKey,
	File | null
> {
	return {
		creator_search: null,
		export_ad_list: null,
		export_advertiser_list: null,
		shop_list: null,
		sales_rank: null,
		new_products_ranking: null,
		product_search_data: null,
		product_search_sales_rank: null,
		most_promoted_products_rank: null,
		video_product_list: null,
	};
}

async function fileToBase64(file: File) {
	return await new Promise<string>((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => {
			const payload = reader.result;
			if (typeof payload !== "string") {
				reject(new Error("Failed to convert image file"));
				return;
			}
			resolve(payload);
		};
		reader.onerror = () =>
			reject(reader.error ?? new Error(`Failed to read ${file.name}`));
		reader.readAsDataURL(file);
	});
}

function StatBadge({
	label,
	tone = "neutral",
}: {
	label: string;
	tone?: "neutral" | "ready" | "warn" | "risk";
}) {
	const styles = {
		neutral: {
			background: "rgba(148,163,184,0.12)",
			color: "var(--text)",
			border: "1px solid rgba(148,163,184,0.2)",
		},
		ready: {
			background: "rgba(34,197,94,0.12)",
			color: "#86efac",
			border: "1px solid rgba(34,197,94,0.2)",
		},
		warn: {
			background: "rgba(245,158,11,0.12)",
			color: "#fcd34d",
			border: "1px solid rgba(245,158,11,0.2)",
		},
		risk: {
			background: "rgba(239,68,68,0.12)",
			color: "#fca5a5",
			border: "1px solid rgba(239,68,68,0.2)",
		},
	} as const;
	return (
		<span
			className="px-2 py-1 rounded text-[10px] font-semibold"
			style={styles[tone]}
		>
			{label}
		</span>
	);
}

function Panel({
	title,
	subtitle,
	children,
}: {
	title: string;
	subtitle?: string;
	children: React.ReactNode;
}) {
	return (
		<section
			className="min-w-0 rounded-2xl border p-4"
			style={{
				background:
					"linear-gradient(180deg, rgba(15,23,42,0.8), rgba(15,23,42,0.42))",
				borderColor: "var(--border)",
			}}
		>
			<div className="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div className="min-w-0">
					<h2 className="text-sm font-bold" style={{ color: "var(--text)" }}>
						{title}
					</h2>
					{subtitle ? (
						<div
							className="bosmax-wrap-safe mt-1 text-[11px]"
							style={{ color: "var(--muted)" }}
						>
							{subtitle}
						</div>
					) : null}
				</div>
			</div>
			{children}
		</section>
	);
}

function KV({
	label,
	value,
}: {
	label: string;
	value: string | number | null | undefined;
}) {
	return (
		<div className="bosmax-kv-row border-b border-[var(--border)] py-1 text-[11px] last:border-0 hover:bg-slate-800/50">
			<div
				style={{ color: "var(--muted)" }}
				className="bosmax-kv-label font-semibold"
			>
				{label}
			</div>
			<div style={{ color: "var(--text)" }} className="bosmax-kv-value">
				{fieldValue(value)}
			</div>
		</div>
	);
}

function imageStatusLabel(product: Product | null) {
	return product?.image_readiness_status || "IMAGE_NOT_AVAILABLE";
}

function imageStatusDetail(product: Product | null) {
	return product?.image_readiness_detail || product?.image_failure_detail || "";
}

function imageErrorLabel(product: Product | null) {
	if (product?.local_image_path) return imageStatusLabel(product);
	return "IMAGE_LOAD_FAILED";
}

function ImageFallback({
	src,
	alt,
	className,
	emptyLabel,
	errorLabel,
}: {
	src?: string | null;
	alt?: string;
	className?: string;
	emptyLabel?: string;
	errorLabel?: string;
}) {
	const [err, setErr] = useState(false);
	if (!src)
		return (
			<div
				className={`${className} flex items-center justify-center bg-slate-800 text-[10px] font-bold text-slate-500 text-center p-2`}
			>
				{emptyLabel || "IMAGE_NOT_AVAILABLE"}
			</div>
		);
	if (err)
		return (
			<div
				className={`${className} flex items-center justify-center bg-red-900/20 text-[10px] font-bold text-red-500/70 border border-red-900/50 text-center p-2`}
			>
				{errorLabel || "IMAGE_LOAD_FAILED"}
			</div>
		);
	return (
		<img
			src={src}
			alt={alt}
			className={className}
			onError={() => setErr(true)}
		/>
	);
}

const PAGE_SIZE_PRODUCTS = 20;

export default function ProductsSalesAnalyzerPage() {
	const [products, setProducts] = useState<Product[]>([]);
	const [searchParams] = useSearchParams();
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [search, setSearch] = useState("");
	const [sourceFilter, setSourceFilter] = useState("FASTMOSS");
	const [groupFilter, setGroupFilter] = useState("ALL");
	const [familyFilter, setFamilyFilter] = useState("ALL");
	const [copyRouteFilter, setCopyRouteFilter] = useState("ALL");
	const [claimGateFilter, setClaimGateFilter] = useState("ALL");
	const [confidenceFilter, setConfidenceFilter] = useState("ALL");
	const [lifecycleFilter, setLifecycleFilter] =
		useState<LifecycleFilterMode>("ACTIVE_ONLY");
	const [sortMode, setSortMode] = useState<ProductSortMode>("PRODUCT_NAME_ASC");
	const [readinessFilter] = useState("ALL");
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
	const [imageActionBusy, setImageActionBusy] = useState(false);
	const [imageMapImportBusy, setImageMapImportBusy] = useState(false);
	const [fastMossImportBusy, setFastMossImportBusy] = useState(false);
	const [fastMossImportFiles, setFastMossImportFiles] = useState<
		Record<FastMossImportFieldKey, File | null>
	>(emptyFastMossImportState);
	const [fastMossImportReport, setFastMossImportReport] =
		useState<FastMossImportBatchReport | null>(null);
	const [selectedImageUrl, setSelectedImageUrl] = useState("");
	const [manualForm, setManualForm] =
		useState<ManualFormState>(emptyManualForm);
	const [tikTokForm, setTikTokForm] = useState<TikTokFormState>({
		url: "",
		raw_product_title: "",
	});
	const [activeTab, setActiveTab] = useState<
		"DETAILS" | "INTELLIGENCE" | "BRIEF" | "VARIATIONS" | "PREVIEW" | "EDIT"
	>("DETAILS");
	const [editForm, setEditForm] = useState<Record<string, string>>({});
	const [editSaving, setEditSaving] = useState(false);
	const [editSuccess, setEditSuccess] = useState<string | null>(null);
	const [editError, setEditError] = useState<string | null>(null);
	const [intelligenceSummary, setIntelligenceSummary] =
		useState<ProductIntelligenceLatestSnapshotResponse | null>(null);
	const [intelligenceSnapshots, setIntelligenceSnapshots] = useState<
		ProductIntelligenceSnapshot[]
	>([]);
	const [intelligenceLoading, setIntelligenceLoading] = useState(false);
	const [intelligenceError, setIntelligenceError] = useState<string | null>(
		null,
	);
	const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(
		null,
	);
	const [snapshotProvenance, setSnapshotProvenance] = useState<
		ProductIntelligenceFieldProvenance[]
	>([]);
	const [provenanceLoading, setProvenanceLoading] = useState(false);
	const [provenanceError, setProvenanceError] = useState<string | null>(null);
	const [brief, setBrief] = useState<ProductCreativeBrief | null>(null);
	const [variations, setVariations] = useState<VariationPlan[]>([]);
	const [promptPreview, setPromptPreview] = useState<string | null>(null);
	const [previewLoading, setPreviewLoading] = useState(false);
	const [lifecycleModal, setLifecycleModal] = useState<{
		action: LifecycleActionType;
		product: Product;
		reason: string;
		confirmationPhrase: string;
		errorMessage?: string;
	} | null>(null);
	const [currentPageProducts, setCurrentPageProducts] = useState(1);

	const filterOptions = useMemo(() => {
		const values = {
			groups: Array.from(
				new Set(products.map((product) => product.group).filter(hasTextValue)),
			).sort(),
			families: Array.from(
				new Set(
					products
						.map((product) => product.bosmax_product_family)
						.filter(hasTextValue),
				),
			).sort(),
			copyRoutes: Array.from(
				new Set(
					products.map((product) => product.copy_route).filter(hasTextValue),
				),
			).sort(),
			claimGates: Array.from(
				new Set(
					products.map((product) => product.claim_gate).filter(hasTextValue),
				),
			).sort(),
			confidences: Array.from(
				new Set(
					products
						.map((product) => product.intelligence_confidence)
						.filter(hasTextValue),
				),
			).sort(),
		};
		return values;
	}, [products]);
	const filteredProducts = useMemo(() => {
		const filtered = products.filter((product) => {
			if (groupFilter !== "ALL" && product.group !== groupFilter) return false;
			if (
				familyFilter !== "ALL" &&
				product.bosmax_product_family !== familyFilter
			)
				return false;
			if (copyRouteFilter !== "ALL" && product.copy_route !== copyRouteFilter)
				return false;
			if (claimGateFilter !== "ALL" && product.claim_gate !== claimGateFilter)
				return false;
			if (
				confidenceFilter !== "ALL" &&
				product.intelligence_confidence !== confidenceFilter
			)
				return false;
			return true;
		});
		return filtered.sort((left, right) => {
			if (sortMode === "PRODUCT_NAME_ASC") {
				const leftName = (
					left.product_short_name ||
					left.raw_product_title ||
					""
				).toLowerCase();
				const rightName = (
					right.product_short_name ||
					right.raw_product_title ||
					""
				).toLowerCase();
				return leftName.localeCompare(rightName);
			}
			if (sortMode === "PRODUCT_SOLD_VERIFIED_DESC") {
				const leftSold = productSoldCount(left);
				const rightSold = productSoldCount(right);
				if (leftSold !== null && rightSold !== null)
					return rightSold - leftSold;
				if (leftSold !== null) return -1;
				if (rightSold !== null) return 1;
				const leftName = (
					left.product_short_name ||
					left.raw_product_title ||
					""
				).toLowerCase();
				const rightName = (
					right.product_short_name ||
					right.raw_product_title ||
					""
				).toLowerCase();
				return leftName.localeCompare(rightName);
			}
			const leftShopTotal = shopTotalSoldCount(left);
			const rightShopTotal = shopTotalSoldCount(right);
			if (leftShopTotal !== null && rightShopTotal !== null)
				return rightShopTotal - leftShopTotal;
			if (leftShopTotal !== null) return -1;
			if (rightShopTotal !== null) return 1;
			const leftName = (
				left.product_short_name ||
				left.raw_product_title ||
				""
			).toLowerCase();
			const rightName = (
				right.product_short_name ||
				right.raw_product_title ||
				""
			).toLowerCase();
			return leftName.localeCompare(rightName);
		});
	}, [
		products,
		groupFilter,
		familyFilter,
		copyRouteFilter,
		claimGateFilter,
		confidenceFilter,
		sortMode,
	]);
	const selectedProduct = useMemo(
		() => filteredProducts.find((product) => product.id === selectedId) || null,
		[filteredProducts, selectedId],
	);
	const selectedSnapshot = useMemo(() => {
		if (selectedSnapshotId) {
			const matched = intelligenceSnapshots.find(
				(snapshot) => snapshot.snapshot_id === selectedSnapshotId,
			);
			if (matched) return matched;
		}
		return (
			intelligenceSummary?.latest_snapshot || intelligenceSnapshots[0] || null
		);
	}, [intelligenceSnapshots, intelligenceSummary, selectedSnapshotId]);
	const snapshotMissingFields = useMemo(
		() => getSnapshotMissingFields(selectedSnapshot),
		[selectedSnapshot],
	);
	const groupedProvenance = useMemo(() => {
		const groups = new Map<string, ProductIntelligenceFieldProvenance[]>();
		for (const item of snapshotProvenance) {
			const existing = groups.get(item.field_name);
			if (existing) {
				existing.push(item);
			} else {
				groups.set(item.field_name, [item]);
			}
		}
		return Array.from(groups.entries()).sort(([left], [right]) =>
			left.localeCompare(right),
		);
	}, [snapshotProvenance]);
	const imageReadinessSummary = useMemo(() => {
		const summary = {
			READY: 0,
			CACHE_READY: 0,
			URL_MISSING: 0,
			DOWNLOAD_FAILED: 0,
			NOT_AVAILABLE: 0,
		};

		for (const product of filteredProducts) {
			switch (product.image_readiness_status) {
				case "IMAGE_READY":
					summary.READY += 1;
					break;
				case "IMAGE_CACHE_READY":
					summary.CACHE_READY += 1;
					break;
				case "IMAGE_DOWNLOAD_FAILED":
					summary.DOWNLOAD_FAILED += 1;
					break;
				case "IMAGE_NOT_AVAILABLE":
					summary.NOT_AVAILABLE += 1;
					break;
				default:
					summary.URL_MISSING += 1;
			}
		}
		return summary;
	}, [filteredProducts]);

	const reloadProductIntelligence = useCallback(
		async (preferredSnapshotId?: string | null) => {
			if (!selectedId) return;
			const productId = selectedId;
			setIntelligenceLoading(true);
			setIntelligenceError(null);
			try {
				const [summary, snapshots] = await Promise.all([
					fetchProductIntelligence(productId),
					fetchProductIntelligenceSnapshots(productId),
				]);
				setIntelligenceSummary(summary);
				setIntelligenceSnapshots(snapshots.items);
				setSelectedSnapshotId((current) => {
					if (
						preferredSnapshotId &&
						snapshots.items.some(
							(snapshot) => snapshot.snapshot_id === preferredSnapshotId,
						)
					) {
						return preferredSnapshotId;
					}
					if (
						current &&
						snapshots.items.some((snapshot) => snapshot.snapshot_id === current)
					) {
						return current;
					}
					return (
						summary.latest_snapshot?.snapshot_id ||
						snapshots.items[0]?.snapshot_id ||
						null
					);
				});
			} catch (err) {
				setIntelligenceError(normalizeProductIntelligenceError(err));
			} finally {
				setIntelligenceLoading(false);
			}
		},
		[selectedId],
	);

	useEffect(() => {
		if (
			selectedId &&
			filteredProducts.some((product) => product.id === selectedId)
		)
			return;
		setSelectedId(filteredProducts[0]?.id || null);
	}, [filteredProducts, selectedId]);

	// Deep-link bridge (from Smart Registration): ?tab=INTELLIGENCE opens the
	// Product Intelligence / AI Fill Missing tab; ?product=<id> preselects it.
	// Applied once after products load; never overrides later user navigation.
	const deepLinkApplied = useRef(false);
	useEffect(() => {
		if (deepLinkApplied.current || products.length === 0) return;
		const tabParam = searchParams.get("tab");
		const productParam = searchParams.get("product");
		if (productParam && products.some((product) => product.id === productParam)) {
			setSelectedId(productParam);
		}
		if (tabParam === "INTELLIGENCE") {
			setActiveTab("INTELLIGENCE");
		}
		deepLinkApplied.current = true;
	}, [products, searchParams]);

	useEffect(() => {
		setSelectedImageUrl(selectedProduct?.image_url || "");
		setBrief(null);
		setVariations([]);
		setPromptPreview(null);
		setIntelligenceSummary(null);
		setIntelligenceSnapshots([]);
		setIntelligenceError(null);
		setSelectedSnapshotId(null);
		setSnapshotProvenance([]);
		setProvenanceError(null);
		setEditSuccess(null);
		setEditError(null);
		if (selectedProduct) {
			setEditForm({
				product_short_name: selectedProduct.product_short_name || "",
				brand: selectedProduct.brand || "",
				price:
					selectedProduct.price != null ? String(selectedProduct.price) : "",
				commission_rate: selectedProduct.commission_rate || "",
				commission_amount:
					selectedProduct.commission_amount != null
						? String(selectedProduct.commission_amount)
						: "",
				physics_class: selectedProduct.physics_class || "",
				copywriting_angle: selectedProduct.copywriting_angle || "",
				silo: selectedProduct.silo || "",
				trigger_id: selectedProduct.trigger_id || "",
				formula: selectedProduct.formula || "",
				claim_risk_level: selectedProduct.claim_risk_level || "",
				category: selectedProduct.category || "",
				subcategory: selectedProduct.subcategory || "",
				type: selectedProduct.type || "",
			});
		}
	}, [selectedProduct]);

	useEffect(() => {
		async function fetchData() {
			if (!selectedId) return;
			if (selectedProduct && isReferenceOnlyProduct(selectedProduct)) return;
			if (activeTab === "BRIEF") {
				try {
					const res = await fetchAPI<ProductCreativeBrief>(
						`/api/products/${selectedId}/creative-brief`,
					);
					setBrief(res);
				} catch (err) {
					console.error("Failed to fetch brief", err);
				}
			} else if (activeTab === "VARIATIONS") {
				try {
					const res = await postAPI<VariationPlan[]>(
						`/api/products/${selectedId}/variation-plan`,
						{},
					);
					setVariations(res);
				} catch (err) {
					console.error("Failed to fetch variations", err);
				}
			}
		}
		fetchData();
	}, [selectedId, activeTab, selectedProduct]);

	useEffect(() => {
		if (activeTab !== "INTELLIGENCE" || !selectedId) return;
		let cancelled = false;

		async function loadProductIntelligence() {
			await reloadProductIntelligence();
			if (cancelled) return;
		}

		void loadProductIntelligence();
		return () => {
			cancelled = true;
		};
	}, [activeTab, selectedId, reloadProductIntelligence]);

	useEffect(() => {
		if (activeTab !== "INTELLIGENCE") return;
		if (!selectedSnapshotId) {
			setSnapshotProvenance([]);
			setProvenanceError(null);
			return;
		}
		const snapshotId = selectedSnapshotId;
		let cancelled = false;

		async function loadSnapshotProvenance() {
			setProvenanceLoading(true);
			setProvenanceError(null);
			try {
				const response = await fetchProductIntelligenceProvenance(snapshotId);
				if (cancelled) return;
				setSnapshotProvenance(response.items);
			} catch (err) {
				if (cancelled) return;
				setProvenanceError(
					err instanceof Error
						? err.message
						: "Failed to load field provenance evidence",
				);
			} finally {
				if (!cancelled) setProvenanceLoading(false);
			}
		}

		void loadSnapshotProvenance();
		return () => {
			cancelled = true;
		};
	}, [activeTab, selectedSnapshotId]);

	// Stale-response guard: only the LATEST request may write state. Typing in
	// the search box fires overlapping fetches; a slow broad-query response must
	// never overwrite a newer narrow-query result.
	const loadSequenceRef = useRef(0);

	const loadProducts = useCallback(async () => {
		const requestSeq = ++loadSequenceRef.current;
		setLoading(true);
		setError(null);
		try {
			const params = new URLSearchParams();
			if (search.trim()) params.set("q", search.trim());
			if (sourceFilter === "FASTMOSS_REFERENCE") {
				params.set("source_lane", "FASTMOSS_REFERENCE");
			} else if (sourceFilter !== "ALL") {
				params.set("source", sourceFilter);
			}
			if (readinessFilter !== "ALL") params.set("readiness", readinessFilter);
			if (lifecycleFilter === "INCLUDE_ARCHIVED")
				params.set("include_archived", "true");
			if (lifecycleFilter === "ARCHIVED_ONLY") {
				params.set("include_archived", "true");
				params.set("lifecycle_status", "ARCHIVED");
			}
			params.set("limit", "500");
			const query = params.toString();
			const res = await fetchAPI<{ items: Product[]; total_count: number }>(
				`/api/products${query ? `?${query}` : ""}`,
			);
			if (requestSeq !== loadSequenceRef.current) return; // stale response — discard
			// No more slice logic, it natively returns exactly what matches.
			const rows = res.items || [];
			setProducts(rows);
			setSelectedId((current) =>
				current && rows.some((row) => row.id === current)
					? current
					: rows[0]?.id || null,
			);
		} catch (err) {
			if (requestSeq !== loadSequenceRef.current) return;
			setError(err instanceof Error ? err.message : "Failed to load products");
		} finally {
			if (requestSeq === loadSequenceRef.current) setLoading(false);
		}
	}, [lifecycleFilter, readinessFilter, search, sourceFilter]);

	useEffect(() => {
		// Debounce: wait for typing to settle before fetching (search changes),
		// while filter changes still load promptly through the same timer.
		const timer = setTimeout(() => {
			void loadProducts();
		}, 300);
		return () => clearTimeout(timer);
	}, [loadProducts]);

	useEffect(() => {
		async function loadLatestFastMossImportReport() {
			try {
				const report = await fetchAPI<FastMossImportBatchReport>(
					"/api/fastmoss/import-batch/latest",
				);
				setFastMossImportReport(report);
			} catch {
				setFastMossImportReport(null);
			}
		}
		loadLatestFastMossImportReport();
	}, []);

	async function handleManualSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setSaving(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const payload = {
				...manualForm,
				price: manualForm.price === undefined ? null : Number(manualForm.price),
				commission_amount:
					manualForm.commission_amount === undefined
						? null
						: Number(manualForm.commission_amount),
			};
			const created = await postAPI<Product>("/api/products/manual", payload);
			setManualForm(emptyManualForm());
			await loadProducts();
			setSelectedId(created.id);
			setSaveSuccess(`Saved manually: ${created.id}`);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to create manual product",
			);
		} finally {
			setSaving(false);
		}
	}

	async function handleImageUpload(e: ChangeEvent<HTMLInputElement>) {
		const file = e.target.files?.[0];
		if (!file) return;
		try {
			const base64 = await fileToBase64(file);
			setManualForm((f) => ({
				...f,
				image_base64: base64,
				image_filename: file.name,
			}));
		} catch (_err) {
			alert("Failed to read image file");
		}
	}

	function handleFastMossFileChange(
		fieldKey: FastMossImportFieldKey,
		event: ChangeEvent<HTMLInputElement>,
	) {
		const file = event.target.files?.[0] || null;
		setFastMossImportFiles((current) => ({ ...current, [fieldKey]: file }));
	}

	async function handleFastMossImportSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFastMossImportBusy(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const formData = new FormData();
			for (const field of FASTMOSS_IMPORT_FIELDS) {
				const file = fastMossImportFiles[field.key];
				if (file) formData.append(field.key, file);
			}
			const report = await postMultipartAPI<FastMossImportBatchReport>(
				"/api/fastmoss/import-batch",
				formData,
			);
			setFastMossImportReport(report);
			setFastMossImportFiles(emptyFastMossImportState());
			setSaveSuccess(`FastMoss latest import batch parsed: ${report.batch_id}`);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to import FastMoss latest batch",
			);
		} finally {
			setFastMossImportBusy(false);
		}
	}

	async function handleTikTokSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setSaving(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const response = await postAPI<{
				product?: Product;
				error_code?: string;
				detail?: string;
			}>("/api/products/import-tiktokshop", tikTokForm);
			if (
				response.error_code === "TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED" ||
				response.detail?.includes("Not implemented")
			) {
				setError(
					"TikTok Shop extraction is NOT_IMPLEMENTED. Please use Manual Intake.",
				);
				return;
			}
			if (response.product) {
				setTikTokForm({ url: "", raw_product_title: "" });
				await loadProducts();
				setSelectedId(response.product.id);
				setSaveSuccess(`Imported Draft: ${response.product.id}`);
			}
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to register TikTok Shop product. NOT_IMPLEMENTED extraction.",
			);
		} finally {
			setSaving(false);
		}
	}

	async function updateSelectedProductImage(
		payload: Record<string, unknown>,
		successMessage: string,
	) {
		if (!selectedProduct) return;
		setImageActionBusy(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const updated = await patchAPI<Product>(
				`/api/products/${selectedProduct.id}`,
				payload,
			);
			await loadProducts();
			setSelectedId(updated.id);
			setSaveSuccess(successMessage);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to update selected product image state",
			);
		} finally {
			setImageActionBusy(false);
		}
	}

	async function handleSelectedImageUpload(e: ChangeEvent<HTMLInputElement>) {
		const file = e.target.files?.[0];
		if (!file || !selectedProduct) return;
		setImageActionBusy(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const base64 = await fileToBase64(file);
			const updated = await patchAPI<Product>(
				`/api/products/${selectedProduct.id}`,
				{
					image_base64: base64,
					image_filename: file.name,
					image_asset_status: "READY",
					image_failure_detail: "",
				},
			);
			await loadProducts();
			setSelectedId(updated.id);
			setSaveSuccess(
				"Uploaded image and cached it locally for the selected product",
			);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to upload image for selected product",
			);
		} finally {
			e.target.value = "";
			setImageActionBusy(false);
		}
	}

	async function handlePreviewPrompt(variant: VariationPlan) {
		if (!selectedId) return;
		setPreviewLoading(true);
		try {
			const res = await postAPI<{ prompt: string }>(
				`/api/products/${selectedId}/prompt-preview`,
				variant,
			);
			setPromptPreview(res.prompt);
			setActiveTab("PREVIEW");
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to generate preview",
			);
		} finally {
			setPreviewLoading(false);
		}
	}

	async function handlePasteImageUrl() {
		if (!selectedProduct || !selectedImageUrl.trim()) return;
		await updateSelectedProductImage(
			{
				image_url: selectedImageUrl.trim(),
				local_image_path: "",
				asset_status: "UNRESOLVED",
				image_asset_status: "UNRESOLVED",
				image_failure_detail: "",
			},
			"Updated image URL for the selected product",
		);
	}

	async function handleCacheSelectedImage() {
		if (!selectedProduct) return;
		setImageActionBusy(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const result = await postAPI<{
				status: string;
				detail?: string;
				local_image_path?: string;
			}>(`/api/products/${selectedProduct.id}/cache-image`, {});
			await loadProducts();
			setSelectedId(selectedProduct.id);
			setSaveSuccess(
				result.status === "success"
					? "Cached image successfully for the selected product"
					: result.detail ||
							"Image cache attempt completed with a non-ready result",
			);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to cache selected product image",
			);
		} finally {
			setImageActionBusy(false);
		}
	}

	async function handleMarkImageNotAvailable() {
		if (!selectedProduct) return;
		await updateSelectedProductImage(
			{
				image_url: "",
				local_image_path: "",
				asset_status: "UNRESOLVED",
				image_asset_status: "NOT_AVAILABLE",
				image_failure_detail: "Marked manually as image not available.",
			},
			"Marked the selected product image as not available",
		);
	}

	async function handleImageMapImport(e: ChangeEvent<HTMLInputElement>) {
		const file = e.target.files?.[0];
		if (!file) return;
		setImageMapImportBusy(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const formData = new FormData();
			formData.append("file", file);
			const response = await fetch("/api/products/import-image-map", {
				method: "POST",
				body: formData,
			});
			const payload = (await response.json()) as {
				imported?: number;
				total_rows?: number;
				warnings?: string[];
				detail?: string;
			};
			if (!response.ok) {
				throw new Error(payload.detail || "Failed to import image map");
			}
			await loadProducts();
			const warningSuffix = payload.warnings?.length
				? ` (${payload.warnings.length} warning${payload.warnings.length === 1 ? "" : "s"})`
				: "";
			setSaveSuccess(
				`Imported image map rows: ${payload.imported || 0}/${payload.total_rows || 0}${warningSuffix}`,
			);
			if (payload.warnings?.length) {
				setError(payload.warnings.slice(0, 5).join(" | "));
			}
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to import image map",
			);
		} finally {
			e.target.value = "";
			setImageMapImportBusy(false);
		}
	}

	async function handleEditFormSubmit(e: FormEvent) {
		e.preventDefault();
		if (!selectedProduct) return;
		setEditSaving(true);
		setEditError(null);
		setEditSuccess(null);
		try {
			const payload: Record<string, string | number | null> = {};
			for (const [key, val] of Object.entries(editForm)) {
				if (val === "") {
					payload[key] = null;
				} else if (key === "price" || key === "commission_amount") {
					const n = parseFloat(val);
					payload[key] = Number.isNaN(n) ? null : n;
				} else {
					payload[key] = val;
				}
			}
			await patchAPI(`/api/products/${selectedProduct.id}`, payload);
			await loadProducts();
			setEditSuccess("Product updated successfully.");
		} catch (err) {
			setEditError(
				err instanceof Error ? err.message : "Failed to save changes",
			);
		} finally {
			setEditSaving(false);
		}
	}

	function openLifecycleModal(action: LifecycleActionType, product: Product) {
		setLifecycleModal({
			action,
			product,
			reason: "",
			confirmationPhrase: "",
			errorMessage: "",
		});
	}

	async function handleLifecycleActionSubmit(
		event: FormEvent<HTMLFormElement>,
	) {
		event.preventDefault();
		if (!lifecycleModal) return;

		const expectedPhrase = lifecycleExpectedPhrase(lifecycleModal.action);
		if (lifecycleModal.confirmationPhrase.trim() !== expectedPhrase) {
			setLifecycleModal((current) =>
				current
					? {
							...current,
							errorMessage: `Archive confirmation phrase did not match. Required: ${expectedPhrase}.`,
						}
					: current,
			);
			return;
		}

		setSaving(true);
		setError(null);
		setSaveSuccess(null);
		try {
			const endpoint =
				lifecycleModal.action === "ARCHIVE"
					? `/api/products/${lifecycleModal.product.id}/archive`
					: lifecycleModal.action === "UNARCHIVE"
						? `/api/products/${lifecycleModal.product.id}/unarchive`
						: lifecycleModal.action === "DELETE_PRODUCT"
							? `/api/products/${lifecycleModal.product.id}/delete`
							: `/api/products/${lifecycleModal.product.id}/delete-test-row`;
			const response = await postAPI<{
				deleted?: boolean;
				lifecycle_status?: string;
			}>(endpoint, {
				reason: lifecycleModal.reason,
				confirmation_phrase: lifecycleModal.confirmationPhrase.trim(),
			});
			await loadProducts();
			if (
				lifecycleModal.action === "DELETE_TEST_ROW" ||
				lifecycleModal.action === "DELETE_PRODUCT"
			) {
				setSelectedId((current) =>
					current === lifecycleModal.product.id ? null : current,
				);
				setSaveSuccess(
					lifecycleModal.action === "DELETE_PRODUCT"
						? `Permanently deleted: ${lifecycleModal.product.id}`
						: `Deleted test row: ${lifecycleModal.product.id}`,
				);
			} else {
				setSelectedId((current) =>
					current === lifecycleModal.product.id &&
					lifecycleFilter === "ACTIVE_ONLY" &&
					response.lifecycle_status === "ARCHIVED"
						? null
						: current,
				);
				setSaveSuccess(
					lifecycleModal.action === "ARCHIVE"
						? `Archived product: ${lifecycleModal.product.id}`
						: `Unarchived product: ${lifecycleModal.product.id}`,
				);
			}
			setLifecycleModal(null);
		} catch (err) {
			let msg =
				err instanceof Error ? err.message : "Failed to apply lifecycle action";
			if (
				msg.includes("ARCHIVE_CONFIRMATION_REQUIRED") ||
				msg.includes("UNARCHIVE_CONFIRMATION_REQUIRED") ||
				msg.includes("CONFIRMATION_REQUIRED")
			) {
				msg = `Archive confirmation phrase did not match. Required: ${expectedPhrase}.`;
			}
			setLifecycleModal((current) =>
				current ? { ...current, errorMessage: msg } : current,
			);
		} finally {
			setSaving(false);
		}
	}

	function lifecycleExpectedPhrase(action: LifecycleActionType) {
		if (action === "ARCHIVE") return "ARCHIVE_PRODUCT";
		if (action === "UNARCHIVE") return "UNARCHIVE_PRODUCT";
		if (action === "DELETE_PRODUCT") return "DELETE_PRODUCT_PERMANENT";
		return "DELETE_TEST_ROW_ONLY";
	}

	const lifecycleCanSubmit = lifecycleModal
		? lifecycleModal.reason.trim().length > 0 &&
			lifecycleModal.confirmationPhrase.trim() ===
				lifecycleExpectedPhrase(lifecycleModal.action)
		: false;

	const totalPagesProducts = Math.ceil(
		filteredProducts.length / PAGE_SIZE_PRODUCTS,
	);
	const safePageProducts = Math.min(
		Math.max(1, currentPageProducts),
		totalPagesProducts || 1,
	);
	const paginatedProducts = filteredProducts.slice(
		(safePageProducts - 1) * PAGE_SIZE_PRODUCTS,
		safePageProducts * PAGE_SIZE_PRODUCTS,
	);

	return (
		<div className="grid min-h-full min-w-0 gap-4 p-4 md:p-6 lg:min-h-0 lg:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.45fr)] lg:overflow-hidden">
			{/* Left: Complete Catalog Browser */}
			<div
				className="flex min-w-0 flex-col overflow-hidden rounded-2xl border bg-slate-900/30 lg:min-h-0"
				style={{ borderColor: "var(--border)" }}
			>
				<div className="p-4 border-b" style={{ borderColor: "var(--border)" }}>
					<h2 className="text-sm font-bold mb-3">Products / Sales Analyzer</h2>
					<div className="bosmax-auto-fit-grid mb-3 text-[10px]">
						<div className="bosmax-wrap-safe rounded border border-emerald-500/20 bg-emerald-500/10 p-2 text-emerald-200">
							READY: {imageReadinessSummary.READY}
						</div>
						<div className="bosmax-wrap-safe rounded border border-sky-500/20 bg-sky-500/10 p-2 text-sky-200">
							CACHE_READY: {imageReadinessSummary.CACHE_READY}
						</div>
						<div className="bosmax-wrap-safe rounded border border-amber-500/20 bg-amber-500/10 p-2 text-amber-200">
							URL_MISSING: {imageReadinessSummary.URL_MISSING}
						</div>
						<div className="bosmax-wrap-safe rounded border border-rose-500/20 bg-rose-500/10 p-2 text-rose-200">
							DOWNLOAD_FAILED: {imageReadinessSummary.DOWNLOAD_FAILED}
						</div>
						<div className="bosmax-wrap-safe rounded border border-slate-500/20 bg-slate-500/10 p-2 text-slate-200">
							NOT_AVAILABLE: {imageReadinessSummary.NOT_AVAILABLE} | TOTAL:{" "}
							{filteredProducts.length}
						</div>
					</div>
					<div className="space-y-2">
						<input
							type="text"
							value={search}
							onChange={(e) => {
								setSearch(e.target.value);
								setCurrentPageProducts(1);
							}}
							placeholder="Search products..."
							className="w-full bg-slate-900 border text-xs px-3 py-2 rounded"
							style={{ borderColor: "var(--border)", color: "var(--text)" }}
							onKeyDown={(e) => e.key === "Enter" && loadProducts()}
						/>
						<div className="flex flex-col gap-2 sm:flex-row">
							<select
								value={sourceFilter}
								onChange={(e) => {
									setSourceFilter(e.target.value);
									setCurrentPageProducts(1);
								}}
								aria-label="Filter products by source"
								className="min-w-0 flex-1 bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="FASTMOSS">FastMoss</option>
								<option value="FASTMOSS_REFERENCE">FastMoss Reference</option>
								<option value="MANUAL">Manual</option>
								<option value="TIKTOKSHOP">TikTok Draft</option>
								<option value="TEST">Test / Fixture</option>
								<option value="ALL">All Sources</option>
							</select>
							<button
								type="button"
								onClick={loadProducts}
								className="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-1.5 rounded font-medium"
							>
								Search
							</button>
						</div>
						{/* Persistent Bulk Convert CTA — always visible above filter grid */}
						<a
							href="/product-registration?tab=bulk"
							className="flex items-center justify-center gap-2 w-full rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 text-xs font-bold text-indigo-300 hover:bg-indigo-500/20 hover:border-indigo-500/60 transition-colors"
						>
							<svg
								aria-hidden="true"
								className="w-3.5 h-3.5 shrink-0"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
								strokeWidth={2}
							>
								<path
									strokeLinecap="round"
									strokeLinejoin="round"
									d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
								/>
							</svg>
							Bulk Convert FastMoss
						</a>
						<div className="grid grid-cols-1 gap-2 md:grid-cols-2">
							<select
								value={groupFilter}
								onChange={(e) => {
									setGroupFilter(e.target.value);
									setCurrentPageProducts(1);
								}}
								aria-label="Filter products by group"
								className="bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="ALL">All Groups</option>
								{filterOptions.groups.map((value) => (
									<option key={value} value={value}>
										{value}
									</option>
								))}
							</select>
							<select
								value={familyFilter}
								onChange={(e) => setFamilyFilter(e.target.value)}
								aria-label="Filter products by family"
								className="bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="ALL">All Families</option>
								{filterOptions.families.map((value) => (
									<option key={value} value={value}>
										{value}
									</option>
								))}
							</select>
							<select
								value={copyRouteFilter}
								onChange={(e) => setCopyRouteFilter(e.target.value)}
								aria-label="Filter products by copy route"
								className="bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="ALL">All Copy Routes</option>
								{filterOptions.copyRoutes.map((value) => (
									<option key={value} value={value}>
										{value}
									</option>
								))}
							</select>
							<select
								value={claimGateFilter}
								onChange={(e) => setClaimGateFilter(e.target.value)}
								aria-label="Filter products by claim gate"
								className="bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="ALL">All Claim Gates</option>
								{filterOptions.claimGates.map((value) => (
									<option key={value} value={value}>
										{value}
									</option>
								))}
							</select>
							<select
								value={confidenceFilter}
								onChange={(e) => setConfidenceFilter(e.target.value)}
								aria-label="Filter products by intelligence confidence"
								className="col-span-2 bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="ALL">All Intelligence Confidence</option>
								{filterOptions.confidences.map((value) => (
									<option key={value} value={value}>
										{value}
									</option>
								))}
							</select>
							<select
								value={lifecycleFilter}
								onChange={(e) =>
									setLifecycleFilter(e.target.value as LifecycleFilterMode)
								}
								aria-label="Filter products by lifecycle status"
								className="col-span-2 bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="ACTIVE_ONLY">Active only</option>
								<option value="INCLUDE_ARCHIVED">Include archived</option>
								<option value="ARCHIVED_ONLY">Archived only</option>
							</select>
							<select
								value={sortMode}
								onChange={(e) => setSortMode(e.target.value as ProductSortMode)}
								aria-label="Sort products"
								className="col-span-2 bg-slate-900 border text-xs px-2 py-1.5 rounded"
								style={{ borderColor: "var(--border)", color: "var(--text)" }}
							>
								<option value="PRODUCT_NAME_ASC">Product Name A-Z</option>
								<option value="PRODUCT_SOLD_VERIFIED_DESC">
									Product Sold Verified
								</option>
								<option value="SHOP_TOTAL_SOLD_DESC">Shop Total Sold</option>
							</select>
						</div>
					</div>
				</div>

				<HelperText className="mb-2 px-2">
					Klik kad untuk butiran penuh. Guna butang{" "}
					<span className="font-semibold text-blue-300">Edit</span> /{" "}
					<span className="font-semibold text-amber-300">Archive</span> pada
					setiap kad untuk kemas kini maklumat atau nyah-aktif produk yang tidak
					digunakan — terus dari senarai.
				</HelperText>
				<div
					className="min-h-[280px] flex-1 overflow-y-auto p-2 lg:min-h-0"
					style={{ scrollbarWidth: "thin" }}
				>
					{loading && (
						<div
							className="text-center py-4 text-xs"
							style={{ color: "var(--muted)" }}
						>
							Loading catalog...
						</div>
					)}
					{!loading && filteredProducts.length === 0 && (
						<div
							className="text-center py-4 text-xs"
							style={{ color: "var(--muted)" }}
						>
							No products found
						</div>
					)}

					<div className="space-y-1">
						{paginatedProducts.map((product) => (
							<button
								key={product.id}
								type="button"
								onClick={() => setSelectedId(product.id)}
								className={`flex w-full min-w-0 gap-3 rounded border p-2 text-left transition-colors ${selectedId === product.id ? "border border-blue-500/50 bg-blue-900/30" : "border border-transparent hover:bg-slate-800"}`}
							>
								<div className="flex-shrink-0 w-16 h-16 rounded overflow-hidden bg-slate-800">
									<ImageFallback
										src={product.rendered_img_src}
										alt={product.product_short_name}
										className="w-full h-full object-cover"
										emptyLabel={imageStatusLabel(product)}
										errorLabel={imageErrorLabel(product)}
									/>
								</div>
								<div className="flex-1 min-w-0 flex flex-col justify-between py-0.5">
									<div className="flex items-center gap-2 min-w-0">
										<div
											className="bosmax-wrap-safe text-xs font-semibold text-slate-200"
											title={product.raw_product_title}
										>
											{product.product_short_name || product.raw_product_title}
										</div>
										<StatBadge
											label={
												product.source_label ||
												product.source_lane ||
												product.source
											}
											tone={
												isReferenceOnlyProduct(product) ? "warn" : "neutral"
											}
										/>
										{isArchivedProduct(product) ? (
											<StatBadge label="ARCHIVED" tone="warn" />
										) : null}
										{product.is_test_product ? (
											<StatBadge label="TEST" tone="risk" />
										) : null}
									</div>
									<div className="bosmax-wrap-safe mt-0.5 text-[10px] text-slate-400">
										{formatTaxonomyPath(
											product.category,
											product.subcategory,
											product.type,
										)}
									</div>
									<div className="bosmax-wrap-safe mt-0.5 text-[10px] text-sky-300">
										{product.group || "UNKNOWN_REVIEW_REQUIRED"} /{" "}
										{product.bosmax_product_family || "UNKNOWN_REVIEW_REQUIRED"}
									</div>
									<div className="bosmax-wrap-safe mt-0.5 text-[10px] text-slate-500">
										copy_route={product.copy_route || "NOT_FOUND"} | claim_gate=
										{product.claim_gate || "CLAIM_REVIEW_REQUIRED"} |
										confidence={product.intelligence_confidence || "LOW"}
									</div>
									<div className="bosmax-wrap-safe mt-0.5 text-[10px] text-slate-500">
										{imageStatusLabel(product)}
									</div>
									{isReferenceOnlyProduct(product) ? (
										<div className="bosmax-wrap-safe mt-0.5 text-[10px] text-amber-300">
											{product.catalog_visibility_reason ||
												"Reference-only FastMoss lane. Registration required before package load."}
										</div>
									) : null}
									<div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[10px]">
										<span className="bosmax-wrap-safe text-emerald-400">
											{formatCurrencyDisplay(product.price, product.currency)}
										</span>
										{salesMetricTruthStatus(product) ===
										"VERIFIED_PRODUCT_LEVEL" ? (
											<span className="bosmax-wrap-safe text-orange-300">
												Product sold:{" "}
												{formatCountDisplay(productSoldCount(product))}
											</span>
										) : salesMetricTruthStatus(product) ===
											"SHOP_LEVEL_AGGREGATE" ? (
											<span className="bosmax-wrap-safe text-orange-300">
												Shop total sold:{" "}
												{formatCountDisplay(shopTotalSoldCount(product))}
											</span>
										) : (
											<span className="bosmax-wrap-safe text-slate-400">
												Product sold: NOT_VERIFIED
											</span>
										)}
									</div>
									{salesMetricTruthStatus(product) ===
									"SHOP_LEVEL_AGGREGATE" ? (
										<div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[10px]">
											<span className="bosmax-wrap-safe text-slate-400">
												Product sold: NOT_VERIFIED
											</span>
											<StatBadge
												label="SHOP_LEVEL_METRIC_NOT_PRODUCT_SALES"
												tone="warn"
											/>
										</div>
									) : null}
									<div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[10px]">
										<span className="bosmax-wrap-safe text-cyan-300">
											Comm:{" "}
											{formatCommissionRateDisplay(product.commission_rate)}
										</span>
										<span className="bosmax-wrap-safe text-cyan-200">
											{formatCurrencyDisplay(
												product.commission_amount,
												product.currency,
											)}
										</span>
									</div>
									<div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-800 pt-2">
										<button
											type="button"
											onClick={(e) => {
												e.stopPropagation();
												setSelectedId(product.id);
												setActiveTab("EDIT");
											}}
											className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-[10px] font-semibold text-blue-200 hover:bg-blue-500/20"
										>
											Edit
										</button>
										{isArchivedProduct(product) ? (
											<button
												type="button"
												onClick={(e) => {
													e.stopPropagation();
													openLifecycleModal("UNARCHIVE", product);
												}}
												className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/20"
											>
												Unarchive
											</button>
										) : (
											<button
												type="button"
												onClick={(e) => {
													e.stopPropagation();
													openLifecycleModal("ARCHIVE", product);
												}}
												className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20"
											>
												Archive
											</button>
										)}
									</div>
								</div>
							</button>
						))}
					</div>

					{totalPagesProducts > 1 && (
						<div className="mt-3 flex items-center justify-between border-t border-slate-800 pt-3">
							<span className="text-[10px] text-slate-500">
								{(safePageProducts - 1) * PAGE_SIZE_PRODUCTS + 1}–
								{Math.min(
									safePageProducts * PAGE_SIZE_PRODUCTS,
									filteredProducts.length,
								)}{" "}
								of {filteredProducts.length}
							</span>
							<div className="flex items-center gap-1">
								<button
									type="button"
									disabled={safePageProducts <= 1}
									onClick={() => setCurrentPageProducts((p) => p - 1)}
									className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] font-bold text-slate-300 disabled:opacity-40"
								>
									← Prev
								</button>
								{Array.from(
									{ length: totalPagesProducts },
									(_, i) => i + 1,
								).map((n) => (
									<button
										key={n}
										type="button"
										onClick={() => setCurrentPageProducts(n)}
										className={`rounded border px-2 py-1 text-[10px] font-bold ${safePageProducts === n ? "border-blue-500/50 bg-blue-500/20 text-blue-300" : "border-slate-700 bg-slate-800 text-slate-400"}`}
									>
										{n}
									</button>
								))}
								<button
									type="button"
									disabled={safePageProducts >= totalPagesProducts}
									onClick={() => setCurrentPageProducts((p) => p + 1)}
									className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] font-bold text-slate-300 disabled:opacity-40"
								>
									Next →
								</button>
							</div>
						</div>
					)}
				</div>
			</div>

			{/* Right: Selected Detail / Forms */}
			<div
				className="min-w-0 rounded-2xl border bg-slate-900/20 p-4 md:p-6 lg:min-h-0 lg:overflow-y-auto"
				style={{ borderColor: "var(--border)", scrollbarWidth: "thin" }}
			>
				{error && (
					<div className="mb-4 bg-red-900/30 border border-red-500/30 text-red-400 p-3 rounded text-sm text-center">
						{error}
					</div>
				)}
				{saveSuccess && (
					<div className="mb-4 bg-emerald-900/30 border border-emerald-500/30 text-emerald-400 p-3 rounded text-sm text-center flex justify-between">
						<span>{saveSuccess}</span>
						<button type="button" onClick={() => setSaveSuccess(null)}>
							✕
						</button>
					</div>
				)}

				<div className="grid min-w-0 gap-6 items-start 2xl:grid-cols-[minmax(0,1fr)_300px]">
					<div className="space-y-6">
						{selectedProduct && (
							<div className="space-y-6">
								<div className="flex flex-wrap gap-1 border-b border-slate-800 pb-px">
									{(
										[
											"DETAILS",
											"INTELLIGENCE",
											"BRIEF",
											"VARIATIONS",
											"PREVIEW",
											"EDIT",
										] as const
									).map((tab) => (
										<button
											type="button"
											key={tab}
											onClick={() => setActiveTab(tab)}
											className={`px-4 py-2 text-[11px] font-bold transition-all border-b-2 ${activeTab === tab ? "border-blue-500 text-blue-400 bg-blue-500/5" : "border-transparent text-slate-500 hover:text-slate-300"}`}
										>
											{tab}
										</button>
									))}
								</div>

								{activeTab === "DETAILS" && (
									<>
										<Panel
											title="Database Record"
											subtitle={`ID: ${selectedProduct.id} | Source: ${selectedProduct.source_label || selectedProduct.source_lane || selectedProduct.source}`}
										>
											<div className="mb-4 flex flex-col gap-4 sm:flex-row">
												<div className="w-24 h-24 rounded border border-slate-700 overflow-hidden flex-shrink-0">
													<ImageFallback
														src={selectedProduct.rendered_img_src}
														alt="Product Thumbnail"
														className="w-full h-full object-cover"
														emptyLabel={imageStatusLabel(selectedProduct)}
														errorLabel={imageErrorLabel(selectedProduct)}
													/>
												</div>
												<div className="flex-1 min-w-0">
													<div className="bosmax-wrap-safe text-lg font-bold text-slate-100">
														{selectedProduct.product_short_name ||
															selectedProduct.raw_product_title}
													</div>
													<div className="bosmax-pre-wrap-safe mt-1 border-b border-slate-800 pb-2 text-xs text-slate-400">
														{selectedProduct.raw_product_title}
													</div>
													<div className="flex flex-wrap gap-2 mt-2">
														{selectedProduct.prompt_readiness_status ===
														"READY" ? (
															<StatBadge label="READY" tone="ready" />
														) : (
															<StatBadge
																label={
																	selectedProduct.prompt_readiness_status ||
																	"MISSING_FIELDS"
																}
																tone="warn"
															/>
														)}
														{selectedProduct.physics_class ? (
															<StatBadge
																label={`DNA: ${selectedProduct.physics_class}`}
																tone="ready"
															/>
														) : (
															<StatBadge label="DNA: NONE" tone="neutral" />
														)}
														<StatBadge
															label={`${selectedProduct.mapping_source} | ${selectedProduct.mapping_confidence}`}
															tone="neutral"
														/>
														<StatBadge
															label={
																selectedProduct.source_label ||
																selectedProduct.source_lane ||
																selectedProduct.source
															}
															tone={
																isReferenceOnlyProduct(selectedProduct)
																	? "warn"
																	: "neutral"
															}
														/>
														{isArchivedProduct(selectedProduct) ? (
															<StatBadge label="ARCHIVED" tone="warn" />
														) : (
															<StatBadge label="ACTIVE" tone="ready" />
														)}
														{selectedProduct.is_test_product ? (
															<StatBadge label="TEST" tone="risk" />
														) : null}
														{!isReferenceOnlyProduct(selectedProduct) ? (
															<button
																type="button"
																onClick={() =>
																	openLifecycleModal(
																		"DELETE_PRODUCT",
																		selectedProduct,
																	)
																}
																className="rounded border border-red-700/40 bg-red-900/20 px-3 py-1.5 text-[10px] font-bold text-red-400"
															>
																Delete Product
															</button>
														) : null}
													</div>
													{isReferenceOnlyProduct(selectedProduct) ? (
														<div className="mt-2 rounded border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200 flex items-start justify-between gap-3">
															<span>
																{selectedProduct.catalog_visibility_reason ||
																	"FastMoss reference is review-only. Convert eligible references through Bulk FastMoss Convert before workspace generation."}
															</span>
															<a
																href="/product-registration?tab=bulk"
																className="shrink-0 rounded bg-amber-500/20 border border-amber-500/30 px-2 py-1 text-[10px] font-bold text-amber-300 hover:bg-amber-500/30 transition-colors whitespace-nowrap"
															>
																Open Bulk FastMoss Convert
															</a>
														</div>
													) : null}
													<div className="mt-3 flex flex-wrap gap-2">
														{isReferenceOnlyProduct(
															selectedProduct,
														) ? null : isArchivedProduct(selectedProduct) ? (
															<button
																type="button"
																onClick={() =>
																	openLifecycleModal(
																		"UNARCHIVE",
																		selectedProduct,
																	)
																}
																className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-[10px] font-bold text-emerald-300"
															>
																Unarchive
															</button>
														) : (
															<button
																type="button"
																onClick={() =>
																	openLifecycleModal("ARCHIVE", selectedProduct)
																}
																className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[10px] font-bold text-amber-300"
															>
																Archive
															</button>
														)}
														{isDeleteTestEligible(selectedProduct) ? (
															<button
																type="button"
																onClick={() =>
																	openLifecycleModal(
																		"DELETE_TEST_ROW",
																		selectedProduct,
																	)
																}
																className="rounded border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-[10px] font-bold text-red-300"
															>
																Delete Test Row
															</button>
														) : null}
													</div>
												</div>
											</div>

											<div className="space-y-1 mt-4">
												<KV
													label="Lifecycle Status"
													value={lifecycleStatus(selectedProduct)}
												/>
												<KV
													label="Source Lane"
													value={
														selectedProduct.source_label ||
														selectedProduct.source_lane ||
														selectedProduct.source
													}
												/>
												<KV
													label="Archived At"
													value={selectedProduct.archived_at}
												/>
												<KV
													label="Archived Reason"
													value={selectedProduct.archived_reason}
												/>
												<KV
													label="Category Taxonomy"
													value={formatTaxonomyPath(
														selectedProduct.category,
														selectedProduct.subcategory,
														selectedProduct.type,
													)}
												/>
												<KV
													label="Price & Currency"
													value={formatCurrencyDisplay(
														selectedProduct.price,
														selectedProduct.currency,
													)}
												/>
												<KV
													label="Commission"
													value={formatCommissionDisplay(selectedProduct)}
												/>
												<KV
													label="Commission Amount"
													value={formatCurrencyDisplay(
														selectedProduct.commission_amount,
														selectedProduct.currency,
													)}
												/>
												<KV
													label="Commission Rate"
													value={formatCommissionRateDisplay(
														selectedProduct.commission_rate,
													)}
												/>
												<KV
													label="Product Type ID"
													value={selectedProduct.product_type}
												/>
												<KV label="Silo" value={selectedProduct.silo} />
												<KV
													label="Copywriting Angle"
													value={selectedProduct.copywriting_angle}
												/>
												<KV
													label="Trigger ID / Formula"
													value={`${selectedProduct.trigger_id} / ${selectedProduct.formula}`}
												/>
												<KV
													label="Claim Risk Level"
													value={selectedProduct.claim_risk_level}
												/>
											</div>
										</Panel>

										<Panel
											title="Product Handling / Physics DNA"
											subtitle="Resolved behavior properties"
										>
											<div className="space-y-1 mb-4">
												<KV label="Group" value={selectedProduct.group} />
												<KV
													label="Sub Group"
													value={selectedProduct.sub_group}
												/>
												<KV
													label="Type Of Product"
													value={selectedProduct.type_of_product}
												/>
												<KV
													label="BOSMAX Product Family"
													value={selectedProduct.bosmax_product_family}
												/>
												<KV
													label="Package Form"
													value={selectedProduct.package_form}
												/>
												<KV
													label="Physical State"
													value={selectedProduct.physical_state}
												/>
												<KV
													label="Product Scale Class"
													value={selectedProduct.product_scale_class}
												/>
												<KV
													label="Handling Profile"
													value={selectedProduct.handling_profile}
												/>
												<KV
													label="Scene Profile"
													value={selectedProduct.scene_profile}
												/>
												<KV
													label="Camera Profile"
													value={selectedProduct.camera_profile}
												/>
												<KV
													label="Copy Route"
													value={selectedProduct.copy_route}
												/>
												<KV
													label="Claim Gate"
													value={selectedProduct.claim_gate}
												/>
												<KV
													label="Claim Tokens"
													value={(selectedProduct.claim_tokens || []).join(
														", ",
													)}
												/>
												<KV
													label="Copy Formula"
													value={selectedProduct.copy_formula}
												/>
												<KV
													label="Intelligence Confidence"
													value={selectedProduct.intelligence_confidence}
												/>
												<KV
													label="Intelligence Status"
													value={selectedProduct.intelligence_status}
												/>
												<KV
													label="Taxonomy Conflict"
													value={
														selectedProduct.taxonomy_conflict ? "YES" : "NO"
													}
												/>
												<KV
													label="Taxonomy Conflict Reason"
													value={selectedProduct.taxonomy_conflict_reason}
												/>
												<KV
													label="Sales Metrics Source"
													value={
														selectedProduct.sales_metrics_source ||
														selectedProduct.sales_metrics
															?.sales_metrics_source ||
														selectedProduct.sales_metrics?.source_status
													}
												/>
												<KV
													label="Sales Metrics Batch ID"
													value={
														selectedProduct.sales_metrics_batch_id ||
														selectedProduct.sales_metrics
															?.sales_metrics_batch_id
													}
												/>
												<KV
													label="Matched File Type"
													value={
														selectedProduct.matched_file_type ||
														selectedProduct.sales_metrics?.matched_file_type
													}
												/>
												<KV
													label="Matched By"
													value={
														selectedProduct.matched_by ||
														selectedProduct.sales_metrics?.matched_by
													}
												/>
												<KV
													label="Raw Metric Column"
													value={
														selectedProduct.raw_metric_column ||
														selectedProduct.sales_metrics?.raw_metric_column
													}
												/>
												<KV
													label="Sold Count Metric Scope"
													value={salesMetricScope(selectedProduct)}
												/>
												<KV
													label="Sold Count Truth Status"
													value={salesMetricTruthStatus(selectedProduct)}
												/>
												<KV
													label="Product Sold Count"
													value={
														productSoldCount(selectedProduct) === null
															? "NOT_VERIFIED"
															: formatCountDisplay(
																	productSoldCount(selectedProduct),
																)
													}
												/>
												<KV
													label="Shop Total Sold Count"
													value={
														shopTotalSoldCount(selectedProduct) === null
															? "NOT_AVAILABLE"
															: formatCountDisplay(
																	shopTotalSoldCount(selectedProduct),
																)
													}
												/>
												<KV
													label="Shop Count"
													value={formatCountDisplay(selectedProduct.shop_count)}
												/>
												<KV
													label="Shop Names"
													value={(selectedProduct.shop_names || []).join(", ")}
												/>
												<KV
													label="Sales Metric Warnings"
													value={salesMetricWarnings(selectedProduct).join(
														"; ",
													)}
												/>
												<KV
													label="Sales Metric Provenance"
													value={(
														selectedProduct.sales_metric_provenance ||
														selectedProduct.sales_metrics
															?.sales_metric_provenance ||
														[]
													).join("; ")}
												/>
												<KV
													label="Image Analysis Status"
													value={selectedProduct.image_analysis_status}
												/>
												<KV
													label="Visual Confidence"
													value={
														selectedProduct.image_analysis?.visual_confidence
													}
												/>
												<KV
													label="Semantic Analysis Provider"
													value={selectedProduct.image_analysis?.provider}
												/>
											</div>
											<div className="space-y-1">
												<KV
													label="Physics Class"
													value={selectedProduct.physics_class}
												/>
												<KV
													label="Scale / Fragility"
													value={`${selectedProduct.product_scale} | Fragility: ${selectedProduct.fragility_level}`}
												/>
												<KV
													label="Recommended Grip"
													value={selectedProduct.recommended_grip}
												/>
												<KV
													label="Hand Interaction"
													value={selectedProduct.hand_object_interaction}
												/>
												<KV
													label="Material Behavior"
													value={selectedProduct.material_behavior}
												/>
												<KV
													label="Surface Behavior"
													value={selectedProduct.surface_behavior}
												/>
												<KV
													label="Air Gap Rule"
													value={selectedProduct.air_gap_rule}
												/>
												<KV
													label="Unsafe Constraints"
													value={(
														(selectedProduct as UnsafeHandlingProduct)
															.unsafe_handling_rules || []
													).join("; ")}
												/>
												<div className="mt-3 p-3 bg-slate-900/50 rounded border border-slate-800 text-xs font-mono text-purple-300 leading-relaxed">
													{selectedProduct.section_5_product_physics_prompt ||
														"No Section 5 prompt generated."}
												</div>
												<div className="mt-3">
													<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400 mb-1">
														Engine Keyword Preview (compiled)
													</div>
													<div className="p-3 bg-emerald-950/30 rounded border border-emerald-500/20 text-xs font-mono text-emerald-300 leading-relaxed">
														{getEngineKeywordPreview(
															selectedProduct.physics_class,
														)}
													</div>
												</div>
											</div>
										</Panel>

										<Panel
											title="Source & Maintenance"
											subtitle="Audit details"
										>
											<div className="space-y-1">
												<KV
													label="Source URL"
													value={
														selectedProduct.source_url ||
														selectedProduct.tiktok_product_url
													}
												/>
												<KV
													label="Image Source"
													value={selectedProduct.image_url}
												/>
												<KV
													label="Image Readiness"
													value={selectedProduct.image_readiness_status}
												/>
												<KV
													label="Image Readiness Detail"
													value={
														selectedProduct.image_readiness_detail ||
														selectedProduct.image_failure_detail
													}
												/>
												<KV
													label="Local Image Path"
													value={selectedProduct.local_image_path}
												/>
												<KV
													label="Detected Package"
													value={
														selectedProduct.image_analysis?.detected_package
													}
												/>
												<KV
													label="Detected Text"
													value={(
														selectedProduct.image_analysis?.detected_text || []
													).join(", ")}
												/>
												<KV
													label="Detected Size Text"
													value={
														selectedProduct.image_analysis?.detected_size_text
													}
												/>
												<KV
													label="Image Analysis Warnings"
													value={(
														selectedProduct.image_analysis?.warnings || []
													).join("; ")}
												/>
												<KV
													label="Rendered Image Src"
													value={selectedProduct.rendered_img_src}
												/>
												<KV
													label="Image HTTP Status"
													value={selectedProduct.image_http_status}
												/>
												<KV
													label="Catalog Label"
													value={selectedProduct.catalog_label}
												/>
												<KV
													label="Intelligence Warnings"
													value={(
														selectedProduct.intelligence_warnings || []
													).join("; ")}
												/>
												<KV
													label="Intelligence Provenance"
													value={(
														selectedProduct.intelligence_provenance || []
													).join("; ")}
												/>
											</div>

											{imageStatusDetail(selectedProduct) ? (
												<div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-300">
													{imageStatusDetail(selectedProduct)}
												</div>
											) : null}

											<div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 space-y-3">
												<div className="text-[11px] font-semibold text-slate-300">
													Image Actions
												</div>
												<div className="flex flex-col gap-2">
													<input
														type="text"
														value={selectedImageUrl}
														onChange={(e) =>
															setSelectedImageUrl(e.target.value)
														}
														aria-label="Selected product image URL"
														placeholder="Paste image URL"
														className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
													/>
													<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
														<button
															type="button"
															disabled={
																imageActionBusy || !selectedImageUrl.trim()
															}
															onClick={handlePasteImageUrl}
															className="bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 border border-blue-500/30 text-xs px-3 py-2 rounded disabled:opacity-50"
														>
															Paste Image URL
														</button>
														<button
															type="button"
															disabled={imageActionBusy}
															onClick={handleCacheSelectedImage}
															className="bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 border border-emerald-500/30 text-xs px-3 py-2 rounded disabled:opacity-50"
														>
															Cache Image
														</button>
														<label
															className={`bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 text-xs px-3 py-2 rounded text-center cursor-pointer ${imageActionBusy ? "opacity-50 cursor-not-allowed" : ""}`}
														>
															Upload Image
															<input
																type="file"
																accept="image/*"
																onChange={handleSelectedImageUpload}
																aria-label="Upload selected product image"
																className="hidden"
																disabled={imageActionBusy}
															/>
														</label>
														<button
															type="button"
															disabled={imageActionBusy}
															onClick={handleMarkImageNotAvailable}
															className="bg-amber-600/20 hover:bg-amber-600/40 text-amber-300 border border-amber-500/30 text-xs px-3 py-2 rounded disabled:opacity-50"
														>
															Mark Image Not Available
														</button>
													</div>
												</div>
											</div>

											<div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 space-y-3">
												<div className="text-[11px] font-semibold text-slate-300">
													Mode Readiness
												</div>
												<div className="space-y-2">
													{Object.entries(
														selectedProduct.mode_readiness || {},
													).map(([mode, readiness]) => (
														<div
															key={mode}
															className="rounded border border-slate-800 bg-slate-900/60 p-2"
														>
															<div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
																<span className="bosmax-wrap-safe font-semibold text-slate-200">
																	{mode}
																</span>
																<StatBadge
																	label={readiness.status}
																	tone={
																		readiness.status === "READY"
																			? "ready"
																			: readiness.status ===
																					"READY_OR_NEEDS_REVIEW"
																				? "warn"
																				: "risk"
																	}
																/>
															</div>
															<div className="bosmax-wrap-safe mt-1 text-[10px] text-slate-400">
																{readiness.detail}
															</div>
															{"asset_strategy" in readiness &&
															readiness.asset_strategy ? (
																<div className="bosmax-wrap-safe mt-1 text-[10px] text-slate-500">
																	Asset Strategy: {readiness.asset_strategy}
																</div>
															) : null}
														</div>
													))}
												</div>
											</div>
										</Panel>
									</>
								)}

								{activeTab === "INTELLIGENCE" && (
									<div className="space-y-6">
										{selectedProduct ? (
											<ProductIntelligenceReviewDraftPanel
												productId={selectedProduct.id}
												onApproved={async (snapshotId) => {
													await reloadProductIntelligence(snapshotId);
												}}
											/>
										) : null}
										<Panel
											title="Product Intelligence Snapshot Review"
											subtitle="Approved snapshot evidence surface backed by immutable product_intelligence_snapshot storage."
										>
											<div className="grid gap-4 lg:grid-cols-2">
												<div className="space-y-1">
													<KV
														label="Snapshot Availability"
														value={intelligenceSummary?.status || "LOADING"}
													/>
													<KV
														label="Total Snapshots"
														value={
															intelligenceSummary?.provenance_summary
																.total_snapshots
														}
													/>
													<KV
														label="Approved Snapshot Count"
														value={
															intelligenceSummary?.provenance_summary
																.approved_snapshot_count
														}
													/>
												</div>
												<div className="space-y-1">
													<KV
														label="Latest Approved Snapshot ID"
														value={
															intelligenceSummary?.provenance_summary
																.latest_approved_snapshot_id
														}
													/>
													<KV
														label="Latest Approved Version"
														value={
															intelligenceSummary?.provenance_summary
																.latest_approved_version
														}
													/>
													<KV
														label="Selected Snapshot ID"
														value={selectedSnapshot?.snapshot_id}
													/>
												</div>
											</div>
											<div className="mt-4 flex flex-wrap gap-2">
												<StatBadge
													label={
														intelligenceSummary?.status ||
														"NO_APPROVED_SNAPSHOT"
													}
													tone={getLatestSnapshotStatusTone(
														intelligenceSummary?.status,
													)}
												/>
												{selectedSnapshot ? (
													<StatBadge
														label={`Snapshot ${selectedSnapshot.version} • ${selectedSnapshot.status}`}
														tone={getSnapshotStatusTone(
															selectedSnapshot.status,
														)}
													/>
												) : null}
												{selectedSnapshot?.claim_risk_level ? (
													<StatBadge
														label={`Claim Risk: ${selectedSnapshot.claim_risk_level}`}
														tone={getClaimRiskTone(
															selectedSnapshot.claim_risk_level,
														)}
													/>
												) : null}
											</div>
											<div className="mt-4 rounded border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-[11px] text-sky-100">
												Operator Clarity: Approved Product Intelligence truth
												remains sidecar-only. The product row stays
												catalog/routing metadata only, approval creates
												immutable snapshots, and no dual-write or bulk AI
												enrichment path is exposed here.
											</div>
										</Panel>

										{intelligenceLoading ? (
											<Panel
												title="Product Intelligence Loading"
												subtitle="Fetching latest snapshot, snapshot history, and evidence."
											>
												<div className="py-12 text-center text-xs text-slate-500">
													Loading Product Intelligence snapshots...
												</div>
											</Panel>
										) : intelligenceError ? (
											<Panel
												title={
													intelligenceError.includes("PRODUCT_NOT_FOUND")
														? "Product Not Found"
														: "Product Intelligence Error"
												}
												subtitle={
													intelligenceError.includes("PRODUCT_NOT_FOUND")
														? "The selected product was removed or no longer resolves in the backend."
														: "Snapshot read-only APIs returned an error."
												}
											>
												<div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-3 text-[11px] text-red-300">
													{intelligenceError}
												</div>
											</Panel>
										) : intelligenceSnapshots.length === 0 &&
											!intelligenceSummary?.latest_snapshot ? (
											<Panel
												title="No Approved Snapshot"
												subtitle="This product has no stored approved Product Intelligence snapshot yet."
											>
												<div className="rounded border border-amber-500/20 bg-amber-500/10 px-4 py-4 text-[11px] leading-relaxed text-amber-100">
													No approved snapshot stored for this product yet.
													Reviewers can still create and validate Product
													Intelligence review drafts above, but no immutable
													approved snapshot has been created yet from that
													review pipeline.
												</div>
											</Panel>
										) : (
											<>
												{intelligenceSummary?.latest_snapshot ? (
													<Panel
														title="Latest Approved Snapshot Summary"
														subtitle={`Approved snapshot ${intelligenceSummary.latest_snapshot.version} for product ${intelligenceSummary.product_id}`}
													>
														<div className="grid gap-4 lg:grid-cols-2">
															<div className="space-y-1">
																<KV
																	label="Snapshot ID"
																	value={
																		intelligenceSummary.latest_snapshot
																			.snapshot_id
																	}
																/>
																<KV
																	label="Approved At"
																	value={formatTimestamp(
																		intelligenceSummary.latest_snapshot
																			.approved_at,
																	)}
																/>
																<KV
																	label="Approved By"
																	value={
																		intelligenceSummary.latest_snapshot
																			.approved_by
																	}
																/>
																<KV
																	label="Readiness Status"
																	value={
																		intelligenceSummary.latest_snapshot
																			.readiness_status
																	}
																/>
																<KV
																	label="Created From Review Draft"
																	value={
																		intelligenceSummary.latest_snapshot
																			.created_from_review_draft_id
																	}
																/>
															</div>
															<div className="space-y-1">
																<KV
																	label="Confidence Score"
																	value={formatScore(
																		intelligenceSummary.latest_snapshot
																			.confidence_score,
																	)}
																/>
																<KV
																	label="Completeness Score"
																	value={formatScore(
																		intelligenceSummary.latest_snapshot
																			.completeness_score,
																	)}
																/>
																<KV
																	label="Claim Gate"
																	value={
																		intelligenceSummary.latest_snapshot
																			.claim_gate
																	}
																/>
																<KV
																	label="Claim Risk Level"
																	value={
																		intelligenceSummary.latest_snapshot
																			.claim_risk_level
																	}
																/>
																<KV
																	label="Product Truth Lock"
																	value={
																		intelligenceSummary.latest_snapshot
																			.product_truth_lock
																	}
																/>
															</div>
														</div>
														<div className="mt-4 grid gap-4 lg:grid-cols-2">
															<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																	Benefits
																</div>
																<div className="flex flex-wrap gap-2">
																	{intelligenceSummary.latest_snapshot
																		.benefits_json.length > 0 ? (
																		intelligenceSummary.latest_snapshot.benefits_json.map(
																			(item) => (
																				<StatBadge
																					key={item}
																					label={item}
																					tone="neutral"
																				/>
																			),
																		)
																	) : (
																		<span className="text-[11px] text-slate-500">
																			NOT_AVAILABLE
																		</span>
																	)}
																</div>
															</div>
															<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																	USP
																</div>
																<div className="flex flex-wrap gap-2">
																	{intelligenceSummary.latest_snapshot.usp_json
																		.length > 0 ? (
																		intelligenceSummary.latest_snapshot.usp_json.map(
																			(item) => (
																				<StatBadge
																					key={item}
																					label={item}
																					tone="neutral"
																				/>
																			),
																		)
																	) : (
																		<span className="text-[11px] text-slate-500">
																			NOT_AVAILABLE
																		</span>
																	)}
																</div>
															</div>
														</div>
														<div className="mt-4 grid gap-4 lg:grid-cols-2">
															<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																	Summary Fields
																</div>
																<div className="space-y-1">
																	<KV
																		label="Size / Volume"
																		value={
																			intelligenceSummary.latest_snapshot
																				.size_or_volume
																		}
																	/>
																	<KV
																		label="Product Form Factor"
																		value={
																			intelligenceSummary.latest_snapshot
																				.product_form_factor
																		}
																	/>
																	<KV
																		label="Package Notes"
																		value={
																			intelligenceSummary.latest_snapshot
																				.package_notes
																		}
																	/>
																	<KV
																		label="Packaging Description"
																		value={
																			intelligenceSummary.latest_snapshot
																				.packaging_description
																		}
																	/>
																</div>
															</div>
															<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																	Approved Truth Narrative
																</div>
																<div className="space-y-2 text-[11px] text-slate-300">
																	<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-2">
																		{fieldValue(
																			intelligenceSummary.latest_snapshot
																				.product_description,
																		)}
																	</div>
																	<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-2">
																		Usage:{" "}
																		{fieldValue(
																			intelligenceSummary.latest_snapshot
																				.usage_text,
																		)}
																	</div>
																	<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-2">
																		Ingredients:{" "}
																		{fieldValue(
																			intelligenceSummary.latest_snapshot
																				.ingredients_text,
																		)}
																	</div>
																	<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-2">
																		Warnings:{" "}
																		{fieldValue(
																			intelligenceSummary.latest_snapshot
																				.warnings_text,
																		)}
																	</div>
																	<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-2">
																		Target Customer:{" "}
																		{fieldValue(
																			intelligenceSummary.latest_snapshot
																				.target_customer_text,
																		)}
																	</div>
																</div>
															</div>
														</div>
														<div className="mt-4 grid gap-4 lg:grid-cols-2">
															<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																	Buyer Persona Snapshot
																</div>
																<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-300">
																	{formatNormalizedText(
																		intelligenceSummary.latest_snapshot
																			.buyer_persona_snapshot_json,
																	)}
																</div>
															</div>
															<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																	Copy Strategy Summary
																</div>
																<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-300">
																	{formatNormalizedText(
																		intelligenceSummary.latest_snapshot
																			.copy_strategy_summary_json,
																	)}
																</div>
															</div>
														</div>
													</Panel>
												) : null}

												<div className="grid gap-6 xl:grid-cols-[minmax(260px,0.85fr)_minmax(0,1.15fr)]">
													<Panel
														title="Snapshot History"
														subtitle="Select a stored snapshot to inspect its evidence pack."
													>
														<div className="space-y-2">
															{intelligenceSnapshots.map((snapshot) => (
																<button
																	type="button"
																	key={snapshot.snapshot_id}
																	onClick={() =>
																		setSelectedSnapshotId(snapshot.snapshot_id)
																	}
																	className={`w-full rounded border px-3 py-3 text-left transition-colors ${
																		selectedSnapshot?.snapshot_id ===
																		snapshot.snapshot_id
																			? "border-blue-500/40 bg-blue-500/10"
																			: "border-slate-800 bg-slate-950/40 hover:border-slate-700 hover:bg-slate-900/70"
																	}`}
																>
																	<div className="flex flex-wrap items-center justify-between gap-2">
																		<div className="bosmax-wrap-safe text-[11px] font-semibold text-slate-100">
																			Snapshot v{snapshot.version}
																		</div>
																		<StatBadge
																			label={snapshot.status}
																			tone={getSnapshotStatusTone(
																				snapshot.status,
																			)}
																		/>
																	</div>
																	<div className="mt-1 text-[10px] text-slate-400">
																		{snapshot.snapshot_id}
																	</div>
																	<div className="mt-2 flex flex-wrap gap-2">
																		<StatBadge
																			label={`Readiness: ${snapshot.readiness_status || "NOT_AVAILABLE"}`}
																			tone="neutral"
																		/>
																		{intelligenceSummary?.latest_snapshot
																			?.snapshot_id === snapshot.snapshot_id ? (
																			<StatBadge
																				label="LATEST APPROVED"
																				tone="ready"
																			/>
																		) : null}
																	</div>
																	<div className="mt-2 grid gap-1 text-[10px] text-slate-500">
																		<div>
																			Created{" "}
																			{formatTimestamp(snapshot.created_at)}
																		</div>
																		<div>
																			Updated{" "}
																			{formatTimestamp(snapshot.updated_at)}
																		</div>
																		<div>
																			Approved{" "}
																			{formatTimestamp(snapshot.approved_at)}
																		</div>
																		<div>
																			Approved By{" "}
																			{fieldValue(snapshot.approved_by)}
																		</div>
																		<div>
																			Confidence{" "}
																			{formatScore(snapshot.confidence_score)}
																		</div>
																		<div>
																			Completeness{" "}
																			{formatScore(snapshot.completeness_score)}
																		</div>
																	</div>
																</button>
															))}
														</div>
													</Panel>

													<div className="space-y-6">
														<Panel
															title="Selected Snapshot Detail"
															subtitle={
																selectedSnapshot
																	? `Snapshot ${selectedSnapshot.snapshot_id}`
																	: "No snapshot selected."
															}
														>
															{selectedSnapshot ? (
																<div className="space-y-4">
																	<div className="flex flex-wrap gap-2">
																		<StatBadge
																			label={selectedSnapshot.status}
																			tone={getSnapshotStatusTone(
																				selectedSnapshot.status,
																			)}
																		/>
																		<StatBadge
																			label={`Claim Gate: ${selectedSnapshot.claim_gate || "NOT_AVAILABLE"}`}
																			tone="neutral"
																		/>
																		<StatBadge
																			label={`Claim Risk: ${selectedSnapshot.claim_risk_level || "NOT_AVAILABLE"}`}
																			tone={getClaimRiskTone(
																				selectedSnapshot.claim_risk_level,
																			)}
																		/>
																	</div>

																	<div className="grid gap-4 lg:grid-cols-2">
																		<div className="space-y-1">
																			<KV
																				label="Version"
																				value={selectedSnapshot.version}
																			/>
																			<KV
																				label="Created By"
																				value={selectedSnapshot.created_by}
																			/>
																			<KV
																				label="Created At"
																				value={formatTimestamp(
																					selectedSnapshot.created_at,
																				)}
																			/>
																			<KV
																				label="Approved At"
																				value={formatTimestamp(
																					selectedSnapshot.approved_at,
																				)}
																			/>
																			<KV
																				label="Approved By"
																				value={selectedSnapshot.approved_by}
																			/>
																		</div>
																		<div className="space-y-1">
																			<KV
																				label="Product Truth Lock"
																				value={
																					selectedSnapshot.product_truth_lock
																				}
																			/>
																			<KV
																				label="Confidence Score"
																				value={formatScore(
																					selectedSnapshot.confidence_score,
																				)}
																			/>
																			<KV
																				label="Completeness Score"
																				value={formatScore(
																					selectedSnapshot.completeness_score,
																				)}
																			/>
																			<KV
																				label="Size / Volume"
																				value={selectedSnapshot.size_or_volume}
																			/>
																			<KV
																				label="Product Form Factor"
																				value={
																					selectedSnapshot.product_form_factor
																				}
																			/>
																		</div>
																	</div>

																	<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																		<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																			Missing Required Snapshot Fields
																		</div>
																		<div className="flex flex-wrap gap-2">
																			{snapshotMissingFields.length > 0 ? (
																				snapshotMissingFields.map(
																					(fieldName) => (
																						<StatBadge
																							key={fieldName}
																							label={fieldName}
																							tone="warn"
																						/>
																					),
																				)
																			) : (
																				<StatBadge
																					label="All required snapshot fields present"
																					tone="ready"
																				/>
																			)}
																		</div>
																	</div>

																	<div className="grid gap-4 lg:grid-cols-2">
																		<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																			<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																				Claim Safety Fields
																			</div>
																			<div className="space-y-1">
																				<KV
																					label="Claim Gate"
																					value={selectedSnapshot.claim_gate}
																				/>
																				<KV
																					label="Claim Risk Level"
																					value={
																						selectedSnapshot.claim_risk_level
																					}
																				/>
																				<KV
																					label="Package Notes"
																					value={selectedSnapshot.package_notes}
																				/>
																				<KV
																					label="Packaging Description"
																					value={
																						selectedSnapshot.packaging_description
																					}
																				/>
																			</div>
																			<div className="mt-3 flex flex-wrap gap-2">
																				{selectedSnapshot.claim_tokens_json
																					.length > 0 ? (
																					selectedSnapshot.claim_tokens_json.map(
																						(token) => (
																							<StatBadge
																								key={token}
																								label={token}
																								tone="neutral"
																							/>
																						),
																					)
																				) : (
																					<span className="text-[11px] text-slate-500">
																						No claim tokens.
																					</span>
																				)}
																			</div>
																		</div>

																		<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																			<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																				Allowed / Blocked Claims
																			</div>
																			<div className="space-y-3">
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-emerald-300">
																						Allowed Claims
																					</div>
																					<div className="flex flex-wrap gap-2">
																						{selectedSnapshot
																							.allowed_claims_json.length >
																						0 ? (
																							selectedSnapshot.allowed_claims_json.map(
																								(item) => (
																									<StatBadge
																										key={item}
																										label={item}
																										tone="ready"
																									/>
																								),
																							)
																						) : (
																							<span className="text-[11px] text-slate-500">
																								NOT_AVAILABLE
																							</span>
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-red-300">
																						Blocked Claims
																					</div>
																					<div className="flex flex-wrap gap-2">
																						{selectedSnapshot
																							.blocked_claims_json.length >
																						0 ? (
																							selectedSnapshot.blocked_claims_json.map(
																								(item) => (
																									<StatBadge
																										key={item}
																										label={item}
																										tone="risk"
																									/>
																								),
																							)
																						) : (
																							<span className="text-[11px] text-slate-500">
																								NOT_AVAILABLE
																							</span>
																						)}
																					</div>
																				</div>
																			</div>
																		</div>
																	</div>

																	<div className="grid gap-4 lg:grid-cols-2">
																		<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																			<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																				Snapshot Narrative
																			</div>
																			<div className="space-y-3 text-[11px] text-slate-300">
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Product Description
																					</div>
																					<div className="bosmax-pre-wrap-safe">
																						{fieldValue(
																							selectedSnapshot.product_description,
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Usage Text
																					</div>
																					<div className="bosmax-pre-wrap-safe">
																						{fieldValue(
																							selectedSnapshot.usage_text,
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Warnings Text
																					</div>
																					<div className="bosmax-pre-wrap-safe">
																						{fieldValue(
																							selectedSnapshot.warnings_text,
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Ingredients Text
																					</div>
																					<div className="bosmax-pre-wrap-safe">
																						{fieldValue(
																							selectedSnapshot.ingredients_text,
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Target Customer Text
																					</div>
																					<div className="bosmax-pre-wrap-safe">
																						{fieldValue(
																							selectedSnapshot.target_customer_text,
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Paste Anything Summary
																					</div>
																					<div className="bosmax-pre-wrap-safe">
																						{fieldValue(
																							selectedSnapshot.paste_anything_summary,
																						)}
																					</div>
																				</div>
																			</div>
																		</div>

																		<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																			<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																				Evidence Summary
																			</div>
																			<div className="space-y-3 text-[11px] text-slate-300">
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Source URLs
																					</div>
																					<div className="space-y-1">
																						{summarizeRecord(
																							selectedSnapshot.source_urls_json,
																						).length > 0 ? (
																							summarizeRecord(
																								selectedSnapshot.source_urls_json,
																							).map(([key, value]) => (
																								<div
																									key={key}
																									className="bosmax-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-1"
																								>
																									<span className="font-semibold text-slate-400">
																										{key}:
																									</span>{" "}
																									{formatNormalizedText(value)}
																								</div>
																							))
																						) : (
																							<div className="text-slate-500">
																								NOT_AVAILABLE
																							</div>
																						)}
																					</div>
																				</div>
																				<div>
																					<div className="mb-1 text-[10px] font-semibold text-slate-400">
																						Image Evidence
																					</div>
																					<div className="space-y-1">
																						{summarizeRecord(
																							selectedSnapshot.image_evidence_json,
																						).length > 0 ? (
																							summarizeRecord(
																								selectedSnapshot.image_evidence_json,
																							).map(([key, value]) => (
																								<div
																									key={key}
																									className="bosmax-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-2 py-1"
																								>
																									<span className="font-semibold text-slate-400">
																										{key}:
																									</span>{" "}
																									{formatNormalizedText(value)}
																								</div>
																							))
																						) : (
																							<div className="text-slate-500">
																								NOT_AVAILABLE
																							</div>
																						)}
																					</div>
																				</div>
																			</div>
																		</div>
																	</div>

																	<div className="grid gap-4 lg:grid-cols-2">
																		<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																			<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																				Buyer Persona Snapshot
																			</div>
																			<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-300">
																				{formatNormalizedText(
																					selectedSnapshot.buyer_persona_snapshot_json,
																				)}
																			</div>
																		</div>

																		<div className="rounded border border-slate-800 bg-slate-950/60 p-3">
																			<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
																				Copy Strategy Summary
																			</div>
																			<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-300">
																				{formatNormalizedText(
																					selectedSnapshot.copy_strategy_summary_json,
																				)}
																			</div>
																		</div>
																	</div>
																</div>
															) : (
																<div className="py-8 text-center text-xs text-slate-500">
																	No snapshot selected.
																</div>
															)}
														</Panel>

														<Panel
															title="Snapshot Provenance Evidence"
															subtitle="Field-level evidence from product_intelligence_field_provenance."
														>
															{provenanceLoading ? (
																<div className="py-10 text-center text-xs text-slate-500">
																	Loading snapshot provenance evidence...
																</div>
															) : provenanceError ? (
																<div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-3 text-[11px] text-red-300">
																	{provenanceError}
																</div>
															) : groupedProvenance.length === 0 ? (
																<div className="rounded border border-slate-800 bg-slate-950/60 px-4 py-4 text-[11px] text-slate-400">
																	No field provenance evidence stored for this
																	snapshot.
																</div>
															) : (
																<div className="space-y-4">
																	{groupedProvenance.map(
																		([fieldName, items]) => (
																			<div
																				key={fieldName}
																				className="rounded border border-slate-800 bg-slate-950/60 p-3"
																			>
																				<div className="flex flex-wrap items-center justify-between gap-2">
																					<div className="bosmax-wrap-safe text-[11px] font-semibold text-slate-100">
																						{fieldName}
																					</div>
																					<StatBadge
																						label={`${items.length} evidence row${items.length === 1 ? "" : "s"}`}
																						tone="neutral"
																					/>
																				</div>
																				<div className="mt-3 space-y-3">
																					{items.map((item) => (
																						<div
																							key={item.provenance_id}
																							className="rounded border border-slate-800 bg-slate-900/70 p-3"
																						>
																							<div className="grid gap-3 lg:grid-cols-2">
																								<div className="space-y-1">
																									<KV
																										label="Source Type"
																										value={item.source_type}
																									/>
																									<KV
																										label="Source Lane"
																										value={item.source_lane}
																									/>
																									<KV
																										label="Evidence Kind"
																										value={item.evidence_kind}
																									/>
																									<KV
																										label="Extraction Method"
																										value={
																											item.extraction_method
																										}
																									/>
																								</div>
																								<div className="space-y-1">
																									<KV
																										label="Verification Status"
																										value={
																											item.verification_status
																										}
																									/>
																									<KV
																										label="Claim Risk Flag"
																										value={item.claim_risk_flag}
																									/>
																									<KV
																										label="Reviewer Decision"
																										value={
																											item.reviewer_decision
																										}
																									/>
																									<KV
																										label="Confidence Score"
																										value={formatScore(
																											item.confidence_score,
																										)}
																									/>
																								</div>
																							</div>
																							{item.source_url ? (
																								<a
																									href={item.source_url}
																									target="_blank"
																									rel="noreferrer"
																									className="mt-3 inline-block text-[11px] text-sky-300 underline underline-offset-2"
																								>
																									Open Evidence Source
																								</a>
																							) : null}
																							<div className="mt-3 grid gap-3 lg:grid-cols-2">
																								<div>
																									<div className="mb-1 text-[10px] font-semibold text-slate-400">
																										Declared Value
																									</div>
																									<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-950 px-3 py-2 text-[11px] text-slate-300">
																										{formatNormalizedText(
																											item.declared_value,
																										)}
																									</div>
																								</div>
																								<div>
																									<div className="mb-1 text-[10px] font-semibold text-slate-400">
																										Normalized Value
																									</div>
																									<div className="bosmax-pre-wrap-safe rounded border border-slate-800 bg-slate-950 px-3 py-2 text-[11px] text-slate-300">
																										{formatNormalizedText(
																											item.normalized_value,
																										)}
																									</div>
																								</div>
																							</div>
																							{item.reviewer_note ? (
																								<div className="mt-3 rounded border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
																									Reviewer Note:{" "}
																									{item.reviewer_note}
																								</div>
																							) : null}
																						</div>
																					))}
																				</div>
																			</div>
																		),
																	)}
																</div>
															)}
														</Panel>
													</div>
												</div>
											</>
										)}
									</div>
								)}

								{activeTab === "BRIEF" && brief && (
									<div className="space-y-6">
										<Panel
											title="Product Creative Brief"
											subtitle={`Brief ID: ${brief.brief_id}`}
										>
											<div className="grid gap-4 lg:grid-cols-2">
												<div className="space-y-4">
													<h3 className="text-xs font-bold text-slate-300">
														Readiness Status
													</h3>
													<div className="space-y-2">
														{Object.entries(brief.readiness).map(([k, v]) => (
															<div
																key={k}
																className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900/50 p-2 text-[11px]"
															>
																<span className="bosmax-wrap-safe text-slate-400">
																	{k}
																</span>
																<StatBadge
																	label={v as string}
																	tone={v === "READY" ? "ready" : "risk"}
																/>
															</div>
														))}
													</div>
													{brief.missing_fields.length > 0 && (
														<div className="bosmax-pre-wrap-safe rounded border border-red-500/20 bg-red-900/10 p-3 text-[10px] text-red-300">
															<strong>Missing Fields:</strong>{" "}
															{brief.missing_fields.join(", ")}
														</div>
													)}
												</div>
												<div className="space-y-4">
													<h3 className="text-xs font-bold text-slate-300">
														Copywriting Route
													</h3>
													<div className="space-y-1">
														<KV
															label="Silo"
															value={brief.copywriting_route.silo}
														/>
														<KV
															label="Formula"
															value={brief.copywriting_route.formula}
														/>
														<KV
															label="Trigger"
															value={brief.copywriting_route.trigger_id}
														/>
														<KV
															label="Risk Level"
															value={brief.copywriting_route.claim_risk_level}
														/>
													</div>
												</div>
											</div>
										</Panel>

										<Panel
											title="Physics DNA"
											subtitle="Biometric and material properties"
										>
											<div className="grid gap-4 lg:grid-cols-2">
												<div className="space-y-1">
													<KV
														label="Class"
														value={brief.physics_dna.physics_class}
													/>
													<KV
														label="Scale"
														value={brief.physics_dna.product_scale}
													/>
													<KV
														label="Interaction"
														value={brief.physics_dna.hand_object_interaction}
													/>
												</div>
												<div className="space-y-1">
													<KV
														label="Material"
														value={brief.physics_dna.material_behavior}
													/>
													<KV
														label="Surface"
														value={brief.physics_dna.surface_behavior}
													/>
												</div>
											</div>
											<div className="bosmax-pre-wrap-safe mt-4 rounded border border-slate-800 bg-slate-900/80 p-3 font-mono text-[10px] text-purple-300">
												{brief.physics_dna.section_5_product_physics_prompt}
											</div>
										</Panel>
									</div>
								)}

								{activeTab === "VARIATIONS" && (
									<Panel
										title="Variation Matrix"
										subtitle="Product-to-Concept expansion"
									>
										<div className="space-y-4">
											{variations.map((v) => (
												<div
													key={v.variant_id}
													className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 hover:bg-slate-900/60 transition-all"
												>
													<div className="mb-3 flex flex-wrap items-start justify-between gap-2">
														<div className="bosmax-wrap-safe text-xs font-bold text-blue-400">
															Variant #{v.variation_index}
														</div>
														<StatBadge
															label={v.readiness}
															tone={v.readiness === "READY" ? "ready" : "risk"}
														/>
													</div>
													<div className="mb-4 grid gap-x-6 gap-y-2 lg:grid-cols-2">
														<KV label="Hook Angle" value={v.hook_angle} />
														<KV label="Scene Context" value={v.scene_context} />
														<KV label="Camera Route" value={v.camera_route} />
														<KV label="Strategy" value={v.asset_strategy} />
													</div>
													<button
														type="button"
														onClick={() => handlePreviewPrompt(v)}
														className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-[10px] font-bold py-2 rounded uppercase tracking-wider border border-slate-700"
													>
														Preview 9-Section Prompt
													</button>
												</div>
											))}
											{variations.length === 0 && (
												<div className="text-center py-8 text-slate-500 text-xs">
													No variations generated.
												</div>
											)}
										</div>
									</Panel>
								)}

								{activeTab === "PREVIEW" && (
									<Panel
										title="9-Section Prompt Preview"
										subtitle="Clean compiled output for Google Flow"
									>
										{previewLoading ? (
											<div className="text-center py-12 text-slate-500 text-xs">
												Compiling prompt...
											</div>
										) : promptPreview ? (
											<div className="space-y-4">
												<div className="bosmax-pre-wrap-safe select-all rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-[11px] leading-relaxed text-slate-300">
													{promptPreview}
												</div>
												<div className="flex flex-wrap gap-2">
													<button
														type="button"
														onClick={() => {
															navigator.clipboard.writeText(promptPreview);
															setSaveSuccess("Prompt copied to clipboard");
														}}
														className="flex-1 bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 border border-blue-500/30 py-2 rounded text-xs font-bold"
													>
														Copy to Clipboard
													</button>
													<button
														type="button"
														onClick={() => setActiveTab("VARIATIONS")}
														className="px-6 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 py-2 rounded text-xs font-bold"
													>
														Back
													</button>
												</div>
											</div>
										) : (
											<div className="text-center py-12 text-slate-500 text-xs">
												Select a variant to preview prompt.
											</div>
										)}
									</Panel>
								)}

								{activeTab === "EDIT" && selectedProduct && (
									<form onSubmit={handleEditFormSubmit} className="space-y-4">
										<div
											className="text-xs font-semibold uppercase tracking-wide"
											style={{ color: "var(--muted)" }}
										>
											Edit Product Fields
										</div>
										{editSuccess && (
											<div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-300">
												{editSuccess}
											</div>
										)}
										{editError && (
											<div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">
												{editError}
											</div>
										)}
										<div className="grid grid-cols-2 gap-3">
											{[
												{ key: "product_short_name", label: "Short Name" },
												{ key: "brand", label: "Brand" },
												{ key: "price", label: "Price" },
												{ key: "commission_rate", label: "Commission Rate" },
												{
													key: "commission_amount",
													label: "Commission Amount",
												},
												{ key: "physics_class", label: "Physics Class" },
												{ key: "silo", label: "Silo" },
												{ key: "trigger_id", label: "Trigger ID" },
												{ key: "formula", label: "Formula" },
												{ key: "claim_risk_level", label: "Claim Risk Level" },
												{ key: "category", label: "Category" },
												{ key: "subcategory", label: "Subcategory" },
												{ key: "type", label: "Type" },
											].map(({ key, label }) => {
												const inputId = `edit-form-${key}`;
												return (
													<div key={key}>
														<label
															htmlFor={inputId}
															className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide"
															style={{ color: "var(--muted)" }}
														>
															{label}
														</label>
														<input
															id={inputId}
															value={editForm[key] ?? ""}
															onChange={(e) =>
																setEditForm((f) => ({
																	...f,
																	[key]: e.target.value,
																}))
															}
															className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
														/>
													</div>
												);
											})}
										</div>
										<div>
											<label
												htmlFor="edit-form-copywriting-angle"
												className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide"
												style={{ color: "var(--muted)" }}
											>
												Copywriting Angle
											</label>
											<textarea
												id="edit-form-copywriting-angle"
												value={editForm.copywriting_angle ?? ""}
												onChange={(e) =>
													setEditForm((f) => ({
														...f,
														copywriting_angle: e.target.value,
													}))
												}
												rows={3}
												className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
											/>
										</div>
										<div className="flex justify-end">
											<button
												type="submit"
												disabled={editSaving}
												className="rounded border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-[11px] font-bold text-blue-300 disabled:opacity-50"
											>
												{editSaving ? "Saving..." : "Save Changes"}
											</button>
										</div>
									</form>
								)}
							</div>
						)}
						{!selectedProduct && !loading && (
							<div className="p-8 text-center text-slate-500 border border-slate-800 rounded bg-slate-900/20">
								Select a product from the catalog to view details.
							</div>
						)}

						<div className="border-t border-slate-800 my-8 pt-8">
							<Panel
								title="Legacy Manual Intake / Admin Quick Patch"
								subtitle="Maintenance-only patch lane. Use Smart Registration for canonical product registration."
							>
								<div className="mb-4 rounded border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] leading-relaxed text-amber-200">
									Use Smart Registration for canonical product registration.
									This legacy panel is maintenance-only and may bypass the full
									review workflow.
								</div>
								<form onSubmit={handleManualSubmit} className="space-y-4">
									<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
										<div>
											<label
												htmlFor="manual-raw-title"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Raw Title (Platform name) *
											</label>
											<input
												id="manual-raw-title"
												required
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200 focus:border-blue-500"
												value={manualForm.raw_product_title || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														raw_product_title: e.target.value,
													}))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-short-name"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Short Name (Clean) *
											</label>
											<input
												id="manual-short-name"
												required
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200 focus:border-blue-500"
												value={manualForm.product_short_name || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														product_short_name: e.target.value,
													}))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-category"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Category *
											</label>
											<input
												id="manual-category"
												required
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
												value={manualForm.category || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														category: e.target.value,
													}))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-subcategory"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Subcategory *
											</label>
											<input
												id="manual-subcategory"
												required
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
												value={manualForm.subcategory || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														subcategory: e.target.value,
													}))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-type"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Type *
											</label>
											<input
												id="manual-type"
												required
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
												value={manualForm.type || ""}
												onChange={(e) =>
													setManualForm((f) => ({ ...f, type: e.target.value }))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-price"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Price (Native Value) *
											</label>
											<input
												id="manual-price"
												required
												type="number"
												step="0.01"
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
												value={manualForm.price || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														price: e.target.value
															? Number(e.target.value)
															: undefined,
													}))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-commission-rate"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Commission Rate (%)
											</label>
											<input
												id="manual-commission-rate"
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
												value={manualForm.commission_rate || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														commission_rate: e.target.value,
													}))
												}
											/>
										</div>
										<div>
											<label
												htmlFor="manual-source-url"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Source External URL
											</label>
											<input
												id="manual-source-url"
												className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
												value={manualForm.source_url || ""}
												onChange={(e) =>
													setManualForm((f) => ({
														...f,
														source_url: e.target.value,
													}))
												}
											/>
										</div>
										<div className="col-span-2">
											<label
												htmlFor="manual-image-url"
												className="block text-[11px] mb-1 text-slate-400"
											>
												Image Source (URL or Upload File)
											</label>
											<div className="flex flex-col gap-2 sm:flex-row sm:items-center">
												<input
													id="manual-image-url"
													type="text"
													placeholder="https://"
													className="flex-1 bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
													value={manualForm.image_url || ""}
													onChange={(e) =>
														setManualForm((f) => ({
															...f,
															image_url: e.target.value,
														}))
													}
												/>
												<span className="text-xs text-slate-500 text-center">
													OR
												</span>
												<input
													id="manual-image-file"
													type="file"
													accept="image/*"
													onChange={handleImageUpload}
													className="flex-1 text-xs file:bg-slate-800 file:border-0 file:rounded file:px-3 file:py-1 file:text-slate-300"
												/>
											</div>
											{manualForm.image_base64 && (
												<div className="mt-2 flex items-center gap-2">
													<img
														src={manualForm.image_base64}
														className="h-12 w-12 rounded object-cover border border-slate-700"
														alt="Preview"
													/>{" "}
													<span className="text-[10px] text-emerald-400">
														Image loaded for save
													</span>
												</div>
											)}
										</div>
									</div>
									<div className="pt-2 flex justify-end">
										<button
											type="submit"
											disabled={saving}
											className="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold flex items-center justify-center rounded px-4 py-2 text-xs shadow-md border-t border-emerald-400/50 disabled:opacity-50"
										>
											{saving
												? "Processing..."
												: "Save Manual Product & Parse Intelligence"}
										</button>
									</div>
								</form>
							</Panel>
						</div>
					</div>

					<div className="space-y-6 2xl:sticky 2xl:top-6">
						<Panel
							title="Image Acquisition"
							subtitle="Bulk import existing image/source URLs and commission metadata."
						>
							<label
								className={`flex items-center justify-center rounded border border-dashed border-slate-700 px-3 py-4 text-xs text-slate-300 ${imageMapImportBusy ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:border-sky-500/50 hover:text-sky-200"}`}
							>
								{imageMapImportBusy
									? "Importing image map..."
									: "Import Image Map CSV / JSON"}
								<input
									type="file"
									accept=".csv,.json"
									onChange={handleImageMapImport}
									aria-label="Import image map file"
									className="hidden"
									disabled={imageMapImportBusy}
								/>
							</label>
							<div className="mt-2 text-[10px] text-slate-500 leading-relaxed">
								Supported columns: product_id, raw_product_title,
								product_short_name, image_url, source_url, commission_amount,
								commission_rate.
							</div>
						</Panel>

						<Panel
							title="FastMoss Latest Import Refresh"
							subtitle="Upload the latest affiliate reference files as a read-only parse batch."
						>
							<div className="rounded border border-amber-500/20 bg-amber-500/10 p-3 text-[10px] leading-relaxed text-amber-200">
								FastMoss affiliate data is latest reference only. No
								weekly/growth analytics.
							</div>

							<form
								onSubmit={handleFastMossImportSubmit}
								className="mt-4 space-y-3"
							>
								{FASTMOSS_IMPORT_FIELDS.map((field) => (
									<div
										key={field.key}
										className="rounded border border-slate-800 bg-slate-950/60 p-3"
									>
										<label
											htmlFor={`fastmoss-import-${field.key}`}
											className="block text-[11px] font-semibold text-slate-200"
										>
											{field.label}
										</label>
										<input
											id={`fastmoss-import-${field.key}`}
											type="file"
											accept=".xlsx,.xls,.csv"
											onChange={(event) =>
												handleFastMossFileChange(field.key, event)
											}
											aria-label={`Upload ${field.label}`}
											className="mt-2 w-full text-[11px] file:mr-3 file:rounded file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-slate-300"
											disabled={fastMossImportBusy}
										/>
										<div className="mt-2 bosmax-wrap-safe text-[10px] text-slate-500">
											{fastMossImportFiles[field.key]?.name ||
												"No file selected"}
										</div>
									</div>
								))}

								<button
									type="submit"
									disabled={fastMossImportBusy}
									className="w-full rounded border border-fuchsia-500/30 bg-fuchsia-600/20 px-3 py-2 text-xs font-semibold text-fuchsia-200 disabled:opacity-50"
								>
									{fastMossImportBusy
										? "Parsing latest FastMoss batch..."
										: "Upload Latest FastMoss Batch"}
								</button>
							</form>

							{fastMossImportReport ? (
								<div className="mt-4 space-y-3 rounded border border-slate-800 bg-slate-950/60 p-3">
									<div className="text-[11px] font-semibold text-slate-200">
										Latest Import Report
									</div>
									<div className="space-y-1">
										<KV
											label="Batch ID"
											value={fastMossImportReport.batch_id}
										/>
										<KV
											label="Import Status"
											value={fastMossImportReport.import_status}
										/>
										<KV
											label="Write Back Status"
											value={fastMossImportReport.write_back_status}
										/>
										<KV
											label="Latest Reference Only"
											value={
												fastMossImportReport.latest_reference_only
													? "true"
													: "false"
											}
										/>
										<KV
											label="Growth Analytics Enabled"
											value={
												fastMossImportReport.growth_analytics_enabled
													? "true"
													: "false"
											}
										/>
										<KV
											label="Ready For Processing"
											value={
												fastMossImportReport.ready_for_processing
													? "true"
													: "false"
											}
										/>
										<KV
											label="Uploaded Files"
											value={fastMossImportReport.uploaded_files}
										/>
										<KV
											label="Recognized File Types"
											value={fastMossImportReport.recognized_file_types.join(
												", ",
											)}
										/>
										<KV
											label="Missing Expected File Types"
											value={fastMossImportReport.missing_expected_file_types.join(
												", ",
											)}
										/>
										<KV
											label="Duplicate File Types"
											value={fastMossImportReport.duplicate_file_types.join(
												", ",
											)}
										/>
										<KV
											label="Raw File Storage Path"
											value={fastMossImportReport.raw_file_storage_path}
										/>
									</div>

									<div>
										<div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
											Row Counts
										</div>
										<div className="space-y-1 text-[10px] text-slate-300">
											{Object.entries(
												fastMossImportReport.row_counts_by_file_type,
											).map(([fileType, rowCount]) => (
												<div
													key={fileType}
													className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-900/60 px-2 py-1"
												>
													<span className="bosmax-wrap-safe">{fileType}</span>
													<span>{formatCountDisplay(rowCount)}</span>
												</div>
											))}
										</div>
									</div>

									<div>
										<div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
											Column Validation
										</div>
										<div className="space-y-1">
											{Object.entries(
												fastMossImportReport.column_validation_by_file_type,
											).map(([fileType, validation]) => (
												<div
													key={fileType}
													className="rounded border border-slate-800 bg-slate-900/60 px-2 py-2 text-[10px] text-slate-300"
												>
													<div className="bosmax-wrap-safe font-semibold text-slate-200">
														{fileType}
													</div>
													<div className="bosmax-wrap-safe mt-1">
														status={validation.parse_status}
													</div>
													<div className="bosmax-wrap-safe mt-1">
														required=
														{validation.required_columns_present.join(", ") ||
															"NONE"}
													</div>
													<div className="bosmax-wrap-safe mt-1">
														missing=
														{validation.missing_required_columns.join(", ") ||
															"NONE"}
													</div>
												</div>
											))}
										</div>
									</div>

									<div>
										<div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
											Sales Metric Scope Summary
										</div>
										<div className="space-y-1">
											{fastMossImportReport.sales_metric_scope_report.map(
												(entry) => (
													<div
														key={`${entry.file_type_id}-${entry.source_column}-${entry.metric_name}-${entry.metric_scope}-${entry.truth_status}`}
														className="rounded border border-slate-800 bg-slate-900/60 px-2 py-2 text-[10px] text-slate-300"
													>
														<div className="bosmax-wrap-safe font-semibold text-slate-200">
															{entry.file_type_id} :: {entry.source_column}
														</div>
														<div className="bosmax-wrap-safe mt-1">
															{entry.metric_name} | scope={entry.metric_scope} |
															truth={entry.truth_status}
														</div>
														{entry.warning ? (
															<div className="bosmax-wrap-safe mt-1 text-amber-300">
																{entry.warning}
															</div>
														) : null}
													</div>
												),
											)}
										</div>
									</div>

									{fastMossImportReport.parse_warnings.length ? (
										<div className="rounded border border-amber-500/20 bg-amber-500/10 p-2 text-[10px] text-amber-200">
											{fastMossImportReport.parse_warnings.join(" | ")}
										</div>
									) : null}
									{fastMossImportReport.parse_errors.length ? (
										<div className="rounded border border-rose-500/20 bg-rose-500/10 p-2 text-[10px] text-rose-200">
											{fastMossImportReport.parse_errors.join(" | ")}
										</div>
									) : null}
								</div>
							) : null}
						</Panel>

						<Panel
							title="TikTok Shop Import"
							subtitle="Maintenance-only draft link lane. Prefer Smart Registration TikTok intake."
						>
							<div className="mb-3 rounded border border-sky-500/20 bg-sky-500/10 p-3 text-[10px] leading-relaxed text-sky-200">
								Use Smart Registration TikTok Intake for governed review-draft
								flow. This maintenance panel only creates a draft with
								NOT_IMPLEMENTED extraction when scraping is unavailable.
							</div>
							<form onSubmit={handleTikTokSubmit} className="space-y-3">
								<div>
									<label
										htmlFor="tiktok-shop-url"
										className="block text-[10px] mb-1 opacity-70"
									>
										Shop URL
									</label>
									<input
										id="tiktok-shop-url"
										type="url"
										required
										value={tikTokForm.url}
										onChange={(e) =>
											setTikTokForm((f) => ({ ...f, url: e.target.value }))
										}
										className="w-full bg-slate-950 border text-xs px-2 py-1.5 rounded"
										style={{
											borderColor: "var(--border)",
											color: "var(--text)",
										}}
										placeholder="https://shop.tiktok.com/..."
									/>
								</div>
								<div>
									<label
										htmlFor="tiktok-product-title"
										className="block text-[10px] mb-1 opacity-70"
									>
										Draft Product Title (Fallback)
									</label>
									<input
										id="tiktok-product-title"
										type="text"
										required
										value={tikTokForm.raw_product_title}
										onChange={(e) =>
											setTikTokForm((f) => ({
												...f,
												raw_product_title: e.target.value,
											}))
										}
										className="w-full bg-slate-950 border text-xs px-2 py-1.5 rounded"
										style={{
											borderColor: "var(--border)",
											color: "var(--text)",
										}}
									/>
								</div>
								<button
									type="submit"
									disabled={saving}
									className="w-full bg-blue-600/20 hover:bg-blue-600/40 text-blue-400 border border-blue-500/30 text-xs px-3 py-2 rounded font-medium disabled:opacity-50"
								>
									Register Draft Link
								</button>
								<div className="text-[10px] text-slate-500 px-1 leading-relaxed mt-2 text-center">
									If backend scraping is not implemented, this creates a draft
									record with NOT_IMPLEMENTED flag, requiring manual completion.
								</div>
							</form>
						</Panel>
					</div>
				</div>
			</div>

			{lifecycleModal ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4">
					<div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
						<div className="text-sm font-bold text-slate-100">
							{lifecycleModal.action === "ARCHIVE"
								? "Archive Product"
								: lifecycleModal.action === "UNARCHIVE"
									? "Unarchive Product"
									: lifecycleModal.action === "DELETE_PRODUCT"
										? "Delete Product Permanently"
										: "Delete Test Row"}
						</div>
						<div className="bosmax-wrap-safe mt-2 text-xs text-slate-400">
							Product:{" "}
							{lifecycleModal.product.product_short_name ||
								lifecycleModal.product.raw_product_title}
						</div>
						<div className="bosmax-wrap-safe mt-1 text-[11px] text-slate-500">
							Confirmation required:{" "}
							{lifecycleExpectedPhrase(lifecycleModal.action)}
						</div>
						<form
							onSubmit={handleLifecycleActionSubmit}
							className="mt-4 space-y-3"
						>
							<div>
								<label
									htmlFor="lifecycle-reason"
									className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-400"
								>
									Reason
								</label>
								<textarea
									id="lifecycle-reason"
									required
									value={lifecycleModal.reason}
									onChange={(event) =>
										setLifecycleModal((current) =>
											current
												? { ...current, reason: event.target.value }
												: current,
										)
									}
									className="min-h-[88px] w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
								/>
							</div>
							<div>
								<label
									htmlFor="lifecycle-confirmation-phrase"
									className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-400"
								>
									Confirmation Phrase
								</label>
								<input
									id="lifecycle-confirmation-phrase"
									required
									value={lifecycleModal.confirmationPhrase}
									onChange={(event) =>
										setLifecycleModal((current) =>
											current
												? {
														...current,
														confirmationPhrase: event.target.value,
														errorMessage: "",
													}
												: current,
										)
									}
									className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
									placeholder={lifecycleExpectedPhrase(lifecycleModal.action)}
								/>
								{lifecycleModal.confirmationPhrase.trim().length > 0 &&
									lifecycleModal.confirmationPhrase.trim() !==
										lifecycleExpectedPhrase(lifecycleModal.action) && (
										<div className="mt-1 text-[10px] text-red-400">
											Type {lifecycleExpectedPhrase(lifecycleModal.action)}{" "}
											exactly to continue.
										</div>
									)}
								{lifecycleModal.errorMessage && (
									<div className="mt-1 text-[10px] text-red-400 font-semibold">
										{lifecycleModal.errorMessage}
									</div>
								)}
								<div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-500">
									<span>Type the exact phrase above to unlock submit.</span>
									<div className="flex gap-2">
										<button
											type="button"
											onClick={() =>
												navigator.clipboard.writeText(
													lifecycleExpectedPhrase(lifecycleModal.action),
												)
											}
											className="rounded border border-slate-700 bg-slate-800 px-2 py-1 font-bold text-slate-300"
										>
											Copy Phrase
										</button>
										<button
											type="button"
											onClick={() =>
												setLifecycleModal((current) =>
													current
														? {
																...current,
																confirmationPhrase: lifecycleExpectedPhrase(
																	current.action,
																),
																errorMessage: "",
															}
														: current,
												)
											}
											className="rounded border border-slate-700 bg-slate-800 px-2 py-1 font-bold text-slate-300"
										>
											Use Expected Phrase
										</button>
									</div>
								</div>
							</div>
							<div className="flex flex-wrap justify-end gap-2">
								<button
									type="button"
									onClick={() => setLifecycleModal(null)}
									className="rounded border border-slate-700 bg-slate-800 px-3 py-2 text-[11px] font-bold text-slate-300"
								>
									Cancel
								</button>
								<button
									type="submit"
									disabled={saving || !lifecycleCanSubmit}
									className="rounded border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-[11px] font-bold text-blue-300 disabled:opacity-50 disabled:cursor-not-allowed"
								>
									Confirm
								</button>
							</div>
						</form>
					</div>
				</div>
			) : null}
		</div>
	);
}
