import "/js/pp-reactive-v2.js";

const pp = (globalThis).pp;

if (document.readyState !== "loading") {
	pp?.mount?.();
} else {
	document.addEventListener(
		"DOMContentLoaded",
		() => pp?.mount?.(),
		{ once: true },
	);
}