/**
 * Zero-dependency DOM simulation for findComposerReferenceContainer contract.
 * Mirrors extension/flow-ui-driver.js Phase-2D: FIRST matching ancestor wins.
 */
function label(el) {
	return (el.getAttribute("aria-label") || el.textContent || "").trim();
}

function composerAddButtonWithin(root) {
	for (const el of root.querySelectorAll("button, [role='button']")) {
		const l = label(el).toLowerCase();
		if (l === "add" || l.endsWith("add") || /\badd\b/.test(l)) return true;
	}
	return false;
}

function findComposerReferenceContainer(composer) {
	if (!composer) return null;
	let el = composer.parentElement;
	while (el && el !== document.body) {
		if (!el.contains(composer)) break;
		if (composerAddButtonWithin(el)) return el;
		el = el.parentElement;
	}
	return null;
}

function countComposerThumbs(container) {
	if (!container) return 0;
	let n = 0;
	for (const node of container.querySelectorAll("img, video, picture")) {
		if (node.closest("[data-project-card='1']")) continue;
		n += 1;
	}
	return n;
}

function run() {
	const doc = new DOMParser().parseFromString(
		`<div id="outer" data-testid="outer">
  <img src="outer-project.jpg" data-project-card="1"/>
  <div id="inner" data-testid="inner">
    <button aria-label="add">Add</button>
    <textarea id="composer">What do you want to create?</textarea>
    <img src="ref-thumb.jpg" width="48" height="48"/>
  </div>
  <div id="mid" data-testid="mid">
    <button aria-label="add">Add</button>
    <div id="wrap">
      <div id="inner2" data-testid="inner2">
        <button aria-label="add">Add</button>
        <textarea id="composer2">Composer</textarea>
      </div>
    </div>
  </div>
</div>`,
		"text/html",
	);

	const composer = doc.getElementById("composer");
	const container = findComposerReferenceContainer(composer);
	const inner = doc.getElementById("inner");
	const outer = doc.getElementById("outer");

	if (!container || container.id !== "inner") {
		console.error("FAIL: expected inner panel, got", container && container.id);
		process.exit(1);
	}
	if (container === outer) {
		console.error("FAIL: selected outer ancestor");
		process.exit(1);
	}
	const count = countComposerThumbs(container);
	if (count !== 1) {
		console.error("FAIL: expected 1 thumb in inner, got", count);
		process.exit(1);
	}
	const outerCount = countComposerThumbs(outer);
	if (outerCount < 2) {
		console.error("FAIL: outer should include project card image");
		process.exit(1);
	}

	const composer2 = doc.getElementById("composer2");
	const c2 = findComposerReferenceContainer(composer2);
	if (!c2 || c2.id !== "inner2") {
		console.error("FAIL: nested composer should pick inner2");
		process.exit(1);
	}

	console.log(JSON.stringify({
		ok: true,
		selected_container_id: container.id,
		inner_thumb_count: count,
		outer_thumb_count: outerCount,
		evidence: "first_ancestor_with_add_control",
	}));
}

if (typeof DOMParser === "undefined") {
	console.error("SKIP: DOMParser not available");
	process.exit(0);
}
run();