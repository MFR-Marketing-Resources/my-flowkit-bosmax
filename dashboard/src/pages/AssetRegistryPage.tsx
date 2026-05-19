import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
	checkAssetCompatibility,
	fetchAssetCatalog,
	fetchAssetDetail,
	fetchAssetsByType,
	resolveAssetSelection,
} from "../api/assetRegistry";
import AssetCatalogSummary from "../components/asset-registry/AssetCatalogSummary";
import AssetCompatibilityPanel from "../components/asset-registry/AssetCompatibilityPanel";
import AssetDetailPanel from "../components/asset-registry/AssetDetailPanel";
import AssetOptionsTable from "../components/asset-registry/AssetOptionsTable";
import AssetSelectionResolverPanel from "../components/asset-registry/AssetSelectionResolverPanel";
import type {
	AssetCatalogEntry,
	AssetCatalogResponse,
	AssetCompatibilityResponse,
	AssetDetailResponse,
	AssetOption,
	AssetOptionsResponse,
	AssetSelectionResponse,
} from "../types";

async function loadAllListings(entries: AssetCatalogEntry[]) {
	const pairs = await Promise.all(
		entries.map(
			async (entry) =>
				[entry.asset_type, await fetchAssetsByType(entry.asset_type)] as const,
		),
	);
	return Object.fromEntries(pairs) as Record<string, AssetOptionsResponse>;
}

export default function AssetRegistryPage() {
	const location = useLocation();
	const [catalog, setCatalog] = useState<AssetCatalogResponse | null>(null);
	const [selectedAssetType, setSelectedAssetType] = useState("CHARACTER");
	const [listingsByType, setListingsByType] = useState<
		Record<string, AssetOptionsResponse>
	>({});
	const [selectedAsset, setSelectedAsset] = useState<AssetOption | null>(null);
	const [detail, setDetail] = useState<AssetDetailResponse | null>(null);
	const [selections, setSelections] = useState<Record<string, string>>({});
	const [selectionResult, setSelectionResult] =
		useState<AssetSelectionResponse | null>(null);
	const [compatibilityResult, setCompatibilityResult] =
		useState<AssetCompatibilityResponse | null>(null);
	const [loading, setLoading] = useState(true);
	const [detailLoading, setDetailLoading] = useState(false);
	const [selectionLoading, setSelectionLoading] = useState(false);
	const [compatibilityLoading, setCompatibilityLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		async function load() {
			setLoading(true);
			setError(null);
			try {
				const nextCatalog = await fetchAssetCatalog();
				setCatalog(nextCatalog);
				const nextListings = await loadAllListings(nextCatalog.catalog);
				setListingsByType(nextListings);
				if (nextCatalog.catalog.length > 0) {
					setSelectedAssetType(nextCatalog.catalog[0].asset_type);
				}
			} catch (err) {
				setError(
					err instanceof Error ? err.message : "Failed to load asset registry",
				);
			} finally {
				setLoading(false);
			}
		}
		load();
	}, []);

	useEffect(() => {
		if (!selectedAsset) {
			setDetail(null);
			return;
		}
		setDetailLoading(true);
		fetchAssetDetail(selectedAsset.asset_id)
			.then(setDetail)
			.catch((err) =>
				setError(
					err instanceof Error ? err.message : "Failed to load asset detail",
				),
			)
			.finally(() => setDetailLoading(false));
	}, [selectedAsset]);

	const activeListing = listingsByType[selectedAssetType] || null;
	const supportedTypes = useMemo(
		() => catalog?.catalog.map((entry) => entry.asset_type).join(", ") || "",
		[catalog],
	);
	const creativeLibraryRoute =
		new URLSearchParams(location.search).get("portal") === "side"
			? "/assets/creative-library?portal=side"
			: "/assets/creative-library";

	function handleSelectionChange(assetType: string, assetId: string) {
		setSelections((current) => ({ ...current, [assetType]: assetId }));
	}

	async function handleResolve() {
		setSelectionLoading(true);
		try {
			const selectedAssets = Object.fromEntries(
				Object.entries(selections).filter(([, value]) => Boolean(value)),
			);
			const result = await resolveAssetSelection({
				selected_assets: selectedAssets,
			});
			setSelectionResult(result);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to resolve selections",
			);
		} finally {
			setSelectionLoading(false);
		}
	}

	async function handleCompatibilityCheck() {
		setCompatibilityLoading(true);
		try {
			const selectedAssets = Object.fromEntries(
				Object.entries(selections).filter(([, value]) => Boolean(value)),
			);
			const result = await checkAssetCompatibility({
				selected_assets: selectedAssets,
			});
			setCompatibilityResult(result);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to check compatibility",
			);
		} finally {
			setCompatibilityLoading(false);
		}
	}

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
					Asset Registry
				</div>
				<div className="bosmax-wrap-safe mt-2 max-w-4xl text-sm text-slate-300">
					This screen is read-only. Unverified assets are not canonical truth.
					Empty registries are not bugs; they mean repo-verified datasets do not
					exist yet. No Google Flow execution, no Chrome extension execution,
					and no batch execution are exposed here.
				</div>
				<div className="bosmax-pre-wrap-safe mt-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-3 text-[11px] text-slate-400">
					Supported asset types: {supportedTypes || "Loading..."}
				</div>
				<div className="mt-3 flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-3 text-[11px] text-slate-300 md:flex-row md:items-center md:justify-between">
					<div className="bosmax-wrap-safe">
						Asset Registry is read-only. To upload reusable Character, Scene
						Context, Style/Mood, or Composite Frame images, open Creative
						Library.
					</div>
					<Link
						to={creativeLibraryRoute}
						className="inline-flex items-center justify-center rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-200"
					>
						Open Creative Library
					</Link>
				</div>
				{error ? (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				) : null}
			</section>

			{loading ? (
				<div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-6 text-sm text-slate-400">
					Loading asset registry catalog...
				</div>
			) : catalog ? (
				<>
					<AssetCatalogSummary
						entries={catalog.catalog}
						selectedAssetType={selectedAssetType}
						onSelect={(assetType) => {
							setSelectedAssetType(assetType);
							setSelectedAsset(null);
						}}
					/>

					<div className="grid min-w-0 gap-6 2xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.95fr)]">
						<AssetOptionsTable
							listing={activeListing}
							selectedAssetId={selectedAsset?.asset_id || null}
							onSelect={(asset) => setSelectedAsset(asset)}
						/>
						{detailLoading ? (
							<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-400">
								Loading asset detail...
							</div>
						) : (
							<AssetDetailPanel detail={detail} />
						)}
					</div>

					<div className="grid gap-6 xl:grid-cols-2">
						<AssetSelectionResolverPanel
							listingsByType={listingsByType}
							selections={selections}
							onChange={handleSelectionChange}
							onResolve={handleResolve}
							result={selectionResult}
							loading={selectionLoading}
						/>
						<AssetCompatibilityPanel
							listingsByType={listingsByType}
							selections={selections}
							onChange={handleSelectionChange}
							onCheck={handleCompatibilityCheck}
							result={compatibilityResult}
							loading={compatibilityLoading}
						/>
					</div>
				</>
			) : null}
		</div>
	);
}
