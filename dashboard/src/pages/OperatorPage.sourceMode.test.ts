import { describe, expect, it } from "vitest";
import { resolveOperatorSourceMode } from "./OperatorPage";

// ADR-008 canonical source_mode contract. This guards the FRAMES→HYBRID
// preview→final exec-package flip (de77a36): HYBRID and F2V must remain
// separate first-class source modes and never collapse into one another.
describe("resolveOperatorSourceMode (ADR-008 canonical source_mode)", () => {
	it("pins HYBRID surface to source_mode HYBRID", () => {
		expect(resolveOperatorSourceMode("HYBRID")).toBe("HYBRID");
	});

	it("pins F2V/Frames surface to source_mode FRAMES", () => {
		expect(resolveOperatorSourceMode("F2V")).toBe("FRAMES");
	});

	it("pins I2V surface to source_mode INGREDIENTS", () => {
		expect(resolveOperatorSourceMode("I2V")).toBe("INGREDIENTS");
	});

	it("pins IMG surface to source_mode IMAGES", () => {
		expect(resolveOperatorSourceMode("IMG")).toBe("IMAGES");
	});

	it("defaults T2V and any unknown surface to source_mode T2V", () => {
		expect(resolveOperatorSourceMode("T2V")).toBe("T2V");
		expect(resolveOperatorSourceMode("UNKNOWN_SURFACE")).toBe("T2V");
	});
});

// Owner Phase-1 (SEV-0 manual_faf40cf6): failure notices must identify the
// SOURCE mode; the shared transport is a diagnostic detail only.
import { noticeModeLabel } from "./OperatorPage";

describe("noticeModeLabel (Hybrid failure diagnostics)", () => {
	it("labels a HYBRID-surface failure as HYBRID with F2V transport detail", () => {
		expect(noticeModeLabel("HYBRID", "F2V")).toBe("HYBRID (transport: F2V)");
	});

	it("keeps a true Frames surface identified as Frames/F2V", () => {
		expect(noticeModeLabel("F2V", "F2V")).toBe("Frames/F2V");
	});

	it("identifies the Ingredients surface distinctly", () => {
		expect(noticeModeLabel("I2V", "I2V")).toBe("Ingredients/I2V");
	});

	it("passes T2V through unchanged (source == transport)", () => {
		expect(noticeModeLabel("T2V", "T2V")).toBe("T2V");
	});
});
