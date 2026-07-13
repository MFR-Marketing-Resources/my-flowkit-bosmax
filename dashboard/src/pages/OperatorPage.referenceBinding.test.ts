import { describe, expect, it } from "vitest";
import { EMPTY_BINDING } from "../components/workspace/CanonicalReferenceBindingControls";
import { referenceBindingBlocker } from "./OperatorPage";

// Canonical per-mode reference-binding gate (PR#337/#338 regression repair).
// Mirrors the server contract: HYBRID needs NO manual pick (the approved
// package supplies the product anchor automatically) · FRAMES requires an
// explicit start frame · INGREDIENTS requires character + scene context roles.
describe("referenceBindingBlocker (canonical reference contract)", () => {
	it("HYBRID passes with no manual pick (automatic package product anchor)", () => {
		expect(referenceBindingBlocker("HYBRID", EMPTY_BINDING)).toBeNull();
	});

	it("HYBRID passes with an explicit product reference override", () => {
		expect(
			referenceBindingBlocker("HYBRID", {
				...EMPTY_BINDING,
				productReferenceAssetId: "ca_pick",
			}),
		).toBeNull();
	});

	it("F2V blocks without a start frame", () => {
		expect(referenceBindingBlocker("F2V", EMPTY_BINDING)).toMatch(
			/start frame/i,
		);
	});

	it("F2V passes with a start frame and optional end frame", () => {
		expect(
			referenceBindingBlocker("F2V", {
				...EMPTY_BINDING,
				startFrameAssetId: "ca_start",
			}),
		).toBeNull();
		expect(
			referenceBindingBlocker("F2V", {
				...EMPTY_BINDING,
				startFrameAssetId: "ca_start",
				endFrameAssetId: "ca_end",
			}),
		).toBeNull();
	});

	it("I2V blocks when the required recipe roles are incomplete (role-based, not count-based)", () => {
		// character + style is TWO references but still violates the default
		// recipe (scene context required, style optional).
		expect(
			referenceBindingBlocker("I2V", {
				...EMPTY_BINDING,
				characterReferenceAssetId: "ca_character",
				styleReferenceAssetId: "ca_style",
			}),
		).toMatch(/scene context/i);
	});

	it("I2V passes with character + scene context (style optional)", () => {
		expect(
			referenceBindingBlocker("I2V", {
				...EMPTY_BINDING,
				characterReferenceAssetId: "ca_character",
				sceneContextReferenceAssetId: "ca_scene",
			}),
		).toBeNull();
	});

	it("T2V and IMG never require reference bindings", () => {
		expect(referenceBindingBlocker("T2V", EMPTY_BINDING)).toBeNull();
		expect(referenceBindingBlocker("IMG", EMPTY_BINDING)).toBeNull();
	});
});
