(() => {
	const FLOWKIT_SELECTOR_REGISTRY_VERSION = "2026-05-24-phase1c-selector-registry";

	function freezeEntry(entry) {
		const next = {
			...entry,
			selectors: Array.isArray(entry.selectors)
				? Object.freeze([...entry.selectors])
				: Object.freeze([]),
		};
		return Object.freeze(next);
	}

	const FLOWKIT_SELECTOR_REGISTRY = Object.freeze({
		version: FLOWKIT_SELECTOR_REGISTRY_VERSION,
		entries: Object.freeze({
			flow_config_launcher_compact: freezeEntry({
				id: "flow_config_launcher_compact",
				surface: "mode_config",
				verification_status: "PROVEN",
				requires_shadow_piercing: false,
				evidence_source:
					"ui_contract:test_extension_side_panel_ui_contract.py|phase1a_phase1b_mainline",
				fallback_policy:
					"prefer composer-scoped compact chips before global compact chip fallback",
				selectors: [
					"button",
					"[role=\"button\"]",
					"[role=\"tab\"]",
					"[aria-haspopup]",
					"span",
					"div",
				],
			}),
			flow_config_surface_portal: freezeEntry({
				id: "flow_config_surface_portal",
				surface: "mode_config",
				verification_status: "PROVEN",
				requires_shadow_piercing: false,
				evidence_source:
					"ui_contract:test_extension_side_panel_ui_contract.py|flow_config_debug_snapshot",
				fallback_policy:
					"accept only visible listbox/dialog/menu/portal surfaces with model or aspect tokens",
				selectors: [
					"[role=\"listbox\"]",
					"[role=\"dialog\"]",
					"[role=\"menu\"]",
					"[data-floating-ui-portal] > *",
					"[data-radix-popper-content-wrapper] > *",
					"[data-radix-portal] > *",
				],
			}),
			f2v_collapsed_config_launcher: freezeEntry({
				id: "f2v_collapsed_config_launcher",
				surface: "mode_config",
				verification_status: "PROVEN",
				requires_shadow_piercing: false,
				evidence_source:
					"ui_contract:test_extension_side_panel_ui_contract.py|f2v_harness_checkpoint",
				fallback_policy:
					"match only compact F2V launcher tokens that include Video plus count/aspect markers",
				selectors: ['button[aria-haspopup="menu"]'],
			}),
			generate_button_composer_scoped: freezeEntry({
				id: "generate_button_composer_scoped",
				surface: "composer_generate",
				verification_status: "PROVEN",
				requires_shadow_piercing: false,
				evidence_source:
					"ui_contract:test_extension_side_panel_ui_contract.py|composer_targeting_harness",
				fallback_policy:
					"prefer composer-scoped visible buttons; reject excluded create-shell controls",
				selectors: ["button", "[role=\"button\"]"],
			}),
			generate_button_icon_path_fallback: freezeEntry({
				id: "generate_button_icon_path_fallback",
				surface: "composer_generate",
				verification_status: "DEPRECATED",
				requires_shadow_piercing: false,
				evidence_source:
					"legacy_dom_diagnostic_only|use_only_after_composer_scope_exhausted",
				fallback_policy:
					"last-resort fallback only after composer-scoped and text-based candidates fail",
				selectors: ["path"],
			}),
			upload_slot_label_scan: freezeEntry({
				id: "upload_slot_label_scan",
				surface: "upload_slot",
				verification_status: "UNSTABLE",
				requires_shadow_piercing: false,
				evidence_source:
					"playwright_harness:test-f2v-playwright-persistent-context.js|asset_picker_modal_jsdom",
				fallback_policy:
					"label scan may be reused only with explicit slot label and visible upload markers",
				selectors: [
					"label",
					"span",
					"div",
					"p",
					"button",
					"[role=\"button\"]",
				],
			}),
			asset_picker_modal_surface: freezeEntry({
				id: "asset_picker_modal_surface",
				surface: "upload_modal",
				verification_status: "UNSTABLE",
				requires_shadow_piercing: true,
				evidence_source:
					"playwright_harness:test-f2v-playwright-persistent-context.js|asset_picker_modal_jsdom",
				fallback_policy:
					"shadow/modal scan is allowed only with diagnostic evidence and programmable targets",
				selectors: [
					"[role=\"dialog\"]",
					"[aria-modal=\"true\"]",
					"dialog",
					"[data-floating-ui-portal] > *",
					"[data-radix-portal] > *",
					"[data-radix-popper-content-wrapper] > *",
				],
			}),
			upload_acceptance_preview_evidence: freezeEntry({
				id: "upload_acceptance_preview_evidence",
				surface: "upload_acceptance",
				verification_status: "UNSTABLE",
				requires_shadow_piercing: true,
				evidence_source:
					"playwright_harness:test-f2v-playwright-persistent-context.js|start_slot_preview_confirmation",
				fallback_policy:
					"preview acceptance requires explicit preview delta or modal-close plus preview evidence",
				selectors: [
					"img",
					"canvas",
					"video",
					"picture",
					"[role=\"img\"]",
					"[style*=\"background-image\"]",
				],
			}),
			upload_fixed_overlay_scan: freezeEntry({
				id: "upload_fixed_overlay_scan",
				surface: "upload_modal",
				verification_status: "DEPRECATED",
				requires_shadow_piercing: true,
				evidence_source: "legacy_modal_scan_diagnostic_only",
				fallback_policy:
					"diagnostic-only fallback; never treat fixed overlays as proven upload selectors",
				selectors: ["div", "section", "aside", "article", "dialog"],
			}),
		}),
	});

	function getEntry(id) {
		return FLOWKIT_SELECTOR_REGISTRY.entries[id] || null;
	}

	function getSelectorList(id) {
		const entry = getEntry(id);
		return entry ? [...entry.selectors] : [];
	}

	function getSelectorQuery(id) {
		return getSelectorList(id).join(", ");
	}

	function buildEvidencePointer(id) {
		const entry = getEntry(id);
		return entry
			? `selector-registry:${FLOWKIT_SELECTOR_REGISTRY_VERSION}:${entry.id}`
			: null;
	}

	window.__FLOWKIT_SELECTOR_REGISTRY__ = FLOWKIT_SELECTOR_REGISTRY;
	window.__FLOWKIT_SELECTOR_REGISTRY_HELPERS__ = Object.freeze({
		getEntry,
		getSelectorList,
		getSelectorQuery,
		buildEvidencePointer,
	});
})();
