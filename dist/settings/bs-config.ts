import { writeFileSync, existsSync, mkdirSync, readFileSync } from "fs";
import browserSync, { BrowserSyncInstance } from "browser-sync";
import { execFile } from "child_process";
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
import { Socket } from "net";
import chalk from "chalk";
import { networkInterfaces, platform } from "os";
import { promisify } from "util";
import caspianConfig from "../caspian.config.json";

const { __dirname } = getFileMeta();
const bs: BrowserSyncInstance = browserSync.create();

const WORKSPACE_ROOT = join(__dirname, "..");
const PUBLIC_ROOT = join(WORKSPACE_ROOT, PUBLIC_DIR);
const PUBLIC_IGNORE_DIRS = ["uploads"];
let previousRouteFiles: string[] = [];
let lastChangedFile: string | null = null;

let pythonPort = 0;
let bsPort = 0;
const execFileAsync = promisify(execFile);
const PORT_PROBE_HOST = "127.0.0.1";

function isWindows(): boolean {
  return platform() === "win32";
}

function getReservedPorts(): Set<number> {
  const reservedPorts = new Set<number>();

  if (!caspianConfig.mcp) {
    return reservedPorts;
  }

  const mcpSpecPath = join(
    __dirname,
    "..",
    "src",
    "lib",
    "mcp",
    "fastmcp.json",
  );
  if (!existsSync(mcpSpecPath)) {
    return reservedPorts;
  }

  try {
    const mcpSpec = JSON.parse(readFileSync(mcpSpecPath, "utf-8"));
    const reservedPort = Number(mcpSpec?.deployment?.port);

    if (Number.isInteger(reservedPort) && reservedPort > 0) {
      reservedPorts.add(reservedPort);
    }
  } catch {
    // Ignore malformed local MCP config and fall back to dynamic allocation.
  }

  return reservedPorts;
}

function hasLoopbackListener(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new Socket();
    socket.setTimeout(250);

    socket.on("connect", () => {
      socket.destroy();
      resolve(true);
    });

    socket.on("timeout", () => {
      socket.destroy();
      resolve(false);
    });

    socket.on("error", () => {
      socket.destroy();
      resolve(false);
    });

    socket.connect(port, PORT_PROBE_HOST);
  });
}

async function hasWindowsTcpListener(port: number): Promise<boolean> {
  try {
    const { stdout } = await execFileAsync("netstat", ["-ano", "-p", "TCP"], {
      windowsHide: true,
    });

    return stdout.split(/\r?\n/).some((line) => {
      const parts = line.trim().split(/\s+/);
      return (
        parts.length >= 4 &&
        parts[0].toUpperCase() === "TCP" &&
        parts[1].endsWith(`:${port}`) &&
        parts[3].toUpperCase() === "LISTENING"
      );
    });
  } catch {
    return false;
  }
}

async function isPortAvailable(
  port: number,
  reservedPorts: Set<number>,
): Promise<boolean> {
  if (reservedPorts.has(port)) {
    return false;
  }

  if (isWindows() && (await hasWindowsTcpListener(port))) {
    return false;
  }

  return !(await hasLoopbackListener(port));
}

async function getAvailablePort(
  startPort: number,
  reservedPorts: Set<number> = new Set(),
): Promise<number> {
  let port = startPort;

  while (!(await isPortAvailable(port, reservedPorts))) {
    port += 1;
  }

  return port;
}

function getExternalIP(): string | null {
  const nets = networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name]!) {
      if (net.family === "IPv4" && !net.internal) {
        return net.address;
      }
    }
  }
  return null;
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
      await restartPythonServer(pythonPort, bsPort);
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
        await restartPythonServer(pythonPort, bsPort);
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

function isIgnoredPublicPath(absPath: string): boolean {
  const normalizedPath = relative(PUBLIC_ROOT, absPath).replace(/\\/g, "/");

  return PUBLIC_IGNORE_DIRS.some(
    (dir) => normalizedPath === dir || normalizedPath.startsWith(`${dir}/`),
  );
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
  const reservedPorts = getReservedPorts();

  bsPort = await getAvailablePort(5090, reservedPorts);
  pythonPort = await getAvailablePort(5200, reservedPorts);

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
      const relFromPublic = relative(PUBLIC_ROOT, abs).replace(/\\/g, "/");
      if (isIgnoredPublicPath(abs)) return;
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
      await restartPythonServer(pythonPort, bsPort);
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
      await restartPythonServer(pythonPort, bsPort);
      const isReady = await waitForPort(pythonPort);
      if (isReady && bs.active) bs.reload();
    },
    awaitWriteFinish: DEFAULT_AWF,
    logPrefix: "watch-main",
    usePolling: true,
    interval: 1000,
  });

  startPythonServer(pythonPort, bsPort);

  bs.init(
    {
      proxy: `http://localhost:${pythonPort}`,
      port: bsPort,
      online: true,
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
      const localUrl = urls.get("local") || `http://localhost:${bsPort}`;
      const externalIP = getExternalIP();
      const externalUrl =
        urls.get("external") ||
        (externalIP ? `http://${externalIP}:${bsPort}` : null);
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
