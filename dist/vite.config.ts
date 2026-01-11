import { defineConfig, Plugin } from "vite";
import path from "path";
import fg from "fast-glob";
import { writeFileSync } from "fs";
import { generateGlobalTypes } from "./settings/vite-plugins/generate-global-types.js";

const entries = Object.fromEntries(
  fg.sync("ts/**/*.ts", { ignore: ["**/*.test.ts"] }).map((f) => {
    const rel = f.replace(/^ts\//, "").replace(/\.ts$/, "");
    return [rel, path.resolve(__dirname, f)];
  })
);

const VITE_WATCH_EXCLUDE = [
  "public/js/**",
  "node_modules/**",
  ".venv/**",
  ".casp/**",
];

function browserSyncNotify(): Plugin {
  const flagFile = path.resolve(__dirname, ".casp", ".vite-build-complete");

  return {
    name: "browsersync-notify",
    writeBundle() {
      writeFileSync(flagFile, Date.now().toString());
    },
  };
}

export default defineConfig(({ command, mode }) => ({
  publicDir: false,
  build: {
    outDir: "public/js",
    emptyOutDir: false,
    minify: "esbuild",
    sourcemap: false,
    chunkSizeWarningLimit: 1000,
    watch:
      command === "build" && mode === "development"
        ? { exclude: VITE_WATCH_EXCLUDE }
        : undefined,
    rollupOptions: {
      input: entries,
      external: [/^\/js\/.*/],
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
        manualChunks(id) {
          if (id.includes("node_modules")) {
            return id
              .toString()
              .split("node_modules/")[1]
              .split("/")[0]
              .toString();
          }
        },
      },
    },
  },
  plugins: [
    generateGlobalTypes(),
    ...(command === "build" && mode === "development"
      ? [browserSyncNotify()]
      : []),
  ],
  esbuild: { legalComments: "none" },
  define: { "process.env.NODE_ENV": '"production"' },
}));
