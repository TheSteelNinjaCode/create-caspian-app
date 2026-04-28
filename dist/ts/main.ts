import "/js/pp-reactive-v2.js";

// The following global names have already been declared elsewhere in the project:
// - pp: Used for the Reactive Core functionality.

// Imports goes here --Start

// Uncomment the following line if you need to use the createGlobalSingleton function in this file.
// import { createGlobalSingleton } from "./global-functions.js";
// import { myCustomFunction } from "./money.js";

// createGlobalSingleton("myCustomFunction", myCustomFunction);

// Imports goes here --End

const pp = (globalThis as any).pp;

if (document.readyState !== "loading") {
  pp?.mount?.();
} else {
  document.addEventListener("DOMContentLoaded", () => pp?.mount?.(), {
    once: true,
  });
}
