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
