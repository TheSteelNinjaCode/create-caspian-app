import { readFileSync } from "node:fs";

// Tailwind is optional. The CSS pipeline is not: src/app/globals.css always
// compiles to public/css/styles.css. Tailwind, when enabled, is just one more
// plugin in that pipeline.
const { tailwindcss } = JSON.parse(
  readFileSync(new URL("./caspian.config.json", import.meta.url), "utf8"),
);

// Skip minification while watching so devtools shows readable CSS.
const isWatchMode = process.env.PP_POSTCSS_MODE === "watch";

export default {
  plugins: {
    ...(tailwindcss ? { "@tailwindcss/postcss": {} } : {}),
    ...(isWatchMode ? {} : { cssnano: {} }),
  },
};
