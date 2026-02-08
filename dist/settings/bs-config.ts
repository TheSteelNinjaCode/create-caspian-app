import { writeFileSync, existsSync, mkdirSync, readFileSync } from "fs";
import browserSync, { BrowserSyncInstance } from "browser-sync";
import { generateFileListJson } from "./files-list.js";
import { join, dirname, relative } from "path";
import { getFileMeta, PUBLIC_DIR, SRC_DIR } from "./utils.js";
import { DebouncedWorker, createSrcWatcher, DEFAULT_AWF } from "./utils.js";
import {
  startPythonServer,
  restartPythonServer,
  waitForPort,
} from "./python-server.js";
import { componentMap } from "./component-map.js";
import { createServer } from "net";
import chalk from "chalk";

const { __dirname } = getFileMeta();
const bs: BrowserSyncInstance = browserSync.create();

const PUBLIC_IGNORE_DIRS = [""];
let previousRouteFiles: string[] = [];
let lastChangedFile: string | null = null;

let pythonPort = 0;
let bsPort = 0;

function getAvailablePort(startPort: number): Promise<number> {
  return new Promise((resolve) => {
    const server = createServer();
    server.listen(startPort, () => {
      server.close(() => resolve(startPort));
    });
    server.on("error", () => {
      resolve(getAvailablePort(startPort + 1));
    });
  });
}

const pipeline = new DebouncedWorker(
  async () => {
    const changedFile = lastChangedFile;
    lastChangedFile = null;

    await generateFileListJson();
    await componentMap();

    const needsPythonRestart =
      changedFile &&
      changedFile.endsWith(".py") &&
      !changedFile.includes("__pycache__");

    if (needsPythonRestart) {
      await restartPythonServer(pythonPort);
      updateRouteFilesCache();

      const isReady = await waitForPort(pythonPort);
      if (isReady && bs.active) {
        bs.reload();
      } else {
        console.error(chalk.red("⚠ Server failed to start or timed out."));
      }
      return;
    }

    if (
      changedFile &&
      (changedFile.endsWith(".pyc") || changedFile.includes("__pycache__"))
    )
      return;

    const filesListPath = join(__dirname, "files-list.json");
    if (existsSync(filesListPath)) {
      const filesList = JSON.parse(readFileSync(filesListPath, "utf-8"));
      const routeFiles = filesList.filter(
        (f: string) =>
          f.startsWith("./src/") && (f.endsWith(".py") || f.endsWith(".html")),
      );

      const routesChanged =
        previousRouteFiles.length !== routeFiles.length ||
        !routeFiles.every((f: string) => previousRouteFiles.includes(f));

      if (previousRouteFiles.length > 0 && routesChanged) {
        console.log(
          chalk.yellow(
            "→ Structure changed (New/Deleted file), restarting Python server...",
          ),
        );
        await restartPythonServer(pythonPort);
        const isReady = await waitForPort(pythonPort);
        if (isReady && bs.active) bs.reload();
      } else if (bs.active) {
        bs.reload();
      }
      previousRouteFiles = routeFiles;
    } else if (bs.active) {
      bs.reload();
    }
  },
  350,
  "bs-pipeline",
);

function updateRouteFilesCache() {
  const filesListPath = join(__dirname, "files-list.json");
  if (existsSync(filesListPath)) {
    const filesList = JSON.parse(readFileSync(filesListPath, "utf-8"));
    previousRouteFiles = filesList.filter(
      (f: string) =>
        f.startsWith("./src/") && (f.endsWith(".py") || f.endsWith(".html")),
    );
  }
}

const publicPipeline = new DebouncedWorker(
  async () => {
    console.log(chalk.cyan("→ Public directory changed, reloading browser..."));
    if (bs.active) bs.reload();
  },
  350,
  "bs-public-pipeline",
);

(async () => {
  bsPort = await getAvailablePort(5090);
  pythonPort = await getAvailablePort(bsPort + 10);

  updateRouteFilesCache();

  createSrcWatcher(join(SRC_DIR, "**", "*"), {
    onEvent: (_ev, _abs, rel) => {
      if (rel.includes("__pycache__") || rel.endsWith(".pyc")) return;
      lastChangedFile = rel;
      pipeline.schedule(rel);
    },
    awaitWriteFinish: DEFAULT_AWF,
    logPrefix: "watch-src",
    usePolling: true,
    interval: 1000,
  });

  createSrcWatcher(join(PUBLIC_DIR, "**", "*"), {
    onEvent: (_ev, abs, _) => {
      const relFromPublic = relative(PUBLIC_DIR, abs);
      const normalized = relFromPublic.replace(/\\/g, "/");
      if (PUBLIC_IGNORE_DIRS.includes(normalized.split("/")[0])) return;
      publicPipeline.schedule(relFromPublic);
    },
    awaitWriteFinish: DEFAULT_AWF,
    logPrefix: "watch-public",
    usePolling: true,
    interval: 1000,
  });

  const viteFlagFile = join(__dirname, "..", ".casp", ".vite-build-complete");
  mkdirSync(dirname(viteFlagFile), { recursive: true });
  if (!existsSync(viteFlagFile)) writeFileSync(viteFlagFile, "0");

  createSrcWatcher(viteFlagFile, {
    onEvent: (ev) => {
      if (ev === "change" && bs.active) {
        bs.reload();
      }
    },
    awaitWriteFinish: { stabilityThreshold: 100, pollInterval: 50 },
    logPrefix: "watch-vite",
    usePolling: true,
    interval: 500,
  });

  createSrcWatcher(join(__dirname, "..", "utils", "**", "*.py"), {
    onEvent: async (_ev, _abs, _) => {
      if (_abs.includes("__pycache__")) return;
      await restartPythonServer(pythonPort);
      const isReady = await waitForPort(pythonPort);
      if (isReady && bs.active) bs.reload();
    },
    awaitWriteFinish: DEFAULT_AWF,
    logPrefix: "watch-utils",
    usePolling: true,
    interval: 1000,
  });

  createSrcWatcher(join(__dirname, "..", "main.py"), {
    onEvent: async (_ev, _abs, _) => {
      if (_abs.includes("__pycache__")) return;
      await restartPythonServer(pythonPort);
      const isReady = await waitForPort(pythonPort);
      if (isReady && bs.active) bs.reload();
    },
    awaitWriteFinish: DEFAULT_AWF,
    logPrefix: "watch-main",
    usePolling: true,
    interval: 1000,
  });

  startPythonServer(pythonPort);

  bs.init(
    {
      proxy: `http://localhost:${pythonPort}`,
      port: bsPort,
      middleware: [
        (_req, res, next) => {
          res.setHeader("Cache-Control", "no-cache, no-store, must-revalidate");
          res.setHeader("Pragma", "no-cache");
          res.setHeader("Expires", "0");
          next();
        },
      ],
      notify: false,
      open: false,
      ghostMode: false,
      codeSync: true,
      logLevel: "silent",
    },
    (err, bsInstance) => {
      if (err) {
        console.error(chalk.red("BrowserSync failed to start:"), err);
        return;
      }

      const urls = bsInstance.getOption("urls");
      const localUrl = urls.get("local");
      const externalUrl = urls.get("external");
      const uiUrl = urls.get("ui");
      const uiExtUrl = urls.get("ui-external");

      console.log("");
      console.log(chalk.green.bold("✔ Ports Configured:"));
      console.log(
        `  ${chalk.blue.bold("Frontend (BrowserSync):")} ${chalk.magenta(localUrl)}`,
      );
      console.log(
        `  ${chalk.yellow.bold("Backend (Python):")}       ${chalk.magenta(
          `http://localhost:${pythonPort}`,
        )}`,
      );
      console.log(chalk.gray(" ------------------------------------"));

      if (externalUrl) {
        console.log(
          `    ${chalk.bold("External:")} ${chalk.magenta(externalUrl)}`,
        );
      }

      if (uiUrl) {
        console.log(`          ${chalk.bold("UI:")} ${chalk.magenta(uiUrl)}`);
      }

      const out = {
        local: localUrl,
        external: externalUrl,
        ui: uiUrl,
        uiExternal: uiExtUrl,
        backend: `http://localhost:${pythonPort}`,
      };

      writeFileSync(
        join(__dirname, "bs-config.json"),
        JSON.stringify(out, null, 2),
      );

      console.log(`\n${chalk.gray("Press Ctrl+C to stop.")}\n`);
    },
  );
})();
