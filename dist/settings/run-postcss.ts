import { type ChildProcess, execFile, spawn } from "node:child_process";
import { existsSync, mkdir, readFile, readFileSync, rm, rmSync, writeFile } from "node:fs";
import { promisify } from "node:util";
import { dirname, join } from "node:path";
import process from "node:process";
import { createSrcWatcher, DebouncedWorker, DEFAULT_AWF, DEFAULT_IGNORES } from "./utils.js";
import caspianConfig from "../caspian.config.json";

const mode: "watch" | "build" =
  process.argv[2] === "watch" ? "watch" : "build";
const watcherPidFile = join(process.cwd(), ".casp", "postcss-watch.pid");
const WATCH_PROCESS_ENV = {
  ...process.env,
  NO_COLOR: "1",
  FORCE_COLOR: "0",
  NODE_DISABLE_COLORS: "1",
};
const mkdirAsync = promisify(mkdir);
const readFileAsync = promisify(readFile);
const rmAsync = promisify(rm);
const writeFileAsync = promisify(writeFile);

const args: string[] = [
  "--max-old-space-size=6144",
  "./node_modules/postcss-cli/index.js",
  "src/app/globals.css",
  "-o",
  "public/css/styles.css",
];

const WATCH_IGNORES = [
  ...DEFAULT_IGNORES,
  "**/__pycache__/**",
  "**/*.pyc",
];

type ClosableWatcher = {
  close: () => Promise<void>;
};

function isValidPid(value: string): boolean {
  return /^\d+$/.test(value.trim());
}

function isProcessRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function killWindowsProcessTree(pid: number): Promise<void> {
  return new Promise((resolve) => {
    const killer = execFile(
      "taskkill",
      ["/F", "/T", "/PID", String(pid)],
      () => resolve(),
    );

    killer.on("error", () => resolve());
  });
}

async function killProcessTree(pid: number): Promise<void> {
  if (process.platform === "win32") {
    await killWindowsProcessTree(pid);
    return;
  }

  try {
    process.kill(pid, "SIGTERM");
  } catch {
    return;
  }
}

async function ensurePidDirectory(): Promise<void> {
  await mkdirAsync(dirname(watcherPidFile), { recursive: true });
}

async function clearPidFile(): Promise<void> {
  try {
    const storedPid = (await readFileAsync(watcherPidFile, "utf8")).trim();
    if (storedPid === String(process.pid)) {
      await rmAsync(watcherPidFile, { force: true });
    }
  } catch {}
}

function clearPidFileSync(): void {
  try {
    const storedPid = readFileSync(watcherPidFile, "utf8").trim();
    if (storedPid === String(process.pid)) {
      rmSync(watcherPidFile, { force: true });
    }
  } catch {}
}

async function cleanupStaleWatcher(): Promise<void> {
  if (mode !== "watch") {
    return;
  }

  await ensurePidDirectory();

  let storedPid = "";

  try {
    storedPid = (await readFileAsync(watcherPidFile, "utf8")).trim();
  } catch {
    return;
  }

  if (!isValidPid(storedPid)) {
    await rmAsync(watcherPidFile, { force: true });
    return;
  }

  const pid = Number(storedPid);

  if (pid === process.pid) {
    return;
  }

  if (!isProcessRunning(pid)) {
    await rmAsync(watcherPidFile, { force: true });
    return;
  }

  console.warn(
    `[tailwind] Found stale PostCSS watcher (PID ${pid}), stopping it before restart.`,
  );
  await killProcessTree(pid);
  await rmAsync(watcherPidFile, { force: true });
}

async function writePidFile(): Promise<void> {
  if (mode !== "watch") {
    return;
  }

  await ensurePidDirectory();
  await writeFileAsync(watcherPidFile, `${process.pid}\n`, "utf8");
}

function runPostcssBuild(): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      stdio: "inherit",
      windowsHide: true,
      env: {
        ...WATCH_PROCESS_ENV,
        PP_POSTCSS_MODE: mode,
      },
    });

    activeBuild = child;

    child.on("error", (error) => {
      if (activeBuild === child) {
        activeBuild = null;
      }

      reject(error);
    });

    child.on("exit", (code) => {
      if (activeBuild === child) {
        activeBuild = null;
      }

      resolve(code ?? 0);
    });
  });
}

function createWatchers(rebuildWorker: DebouncedWorker): ClosableWatcher[] {
  const scheduleRebuild = (
    _event: string,
    _absPath: string,
    relPath: string,
  ) => {
    rebuildWorker.schedule(relPath);
  };

  const watchers: ClosableWatcher[] = [
    createSrcWatcher(join(process.cwd(), "src", "**", "*"), {
      exts: [".css", ".html", ".js", ".py"],
      ignored: WATCH_IGNORES,
      awaitWriteFinish: DEFAULT_AWF,
      logPrefix: "tailwind:src",
      onEvent: scheduleRebuild,
    }),
    createSrcWatcher(join(process.cwd(), "postcss.config.js"), {
      exts: [".js"],
      ignored: WATCH_IGNORES,
      awaitWriteFinish: DEFAULT_AWF,
      logPrefix: "tailwind:config",
      onEvent: scheduleRebuild,
    }),
  ];

  const tsRoot = join(process.cwd(), "ts");
  if (caspianConfig.typescript && existsSync(tsRoot)) {
    watchers.push(
      createSrcWatcher(join(tsRoot, "**", "*"), {
        exts: [".js", ".jsx", ".ts", ".tsx"],
        ignored: WATCH_IGNORES,
        awaitWriteFinish: DEFAULT_AWF,
        logPrefix: "tailwind:ts",
        onEvent: scheduleRebuild,
      }),
    );
  }

  return watchers;
}

async function closeWatchers(): Promise<void> {
  await Promise.all(
    sourceWatchers.splice(0).map(async (watcher) => {
      try {
        await watcher.close();
      } catch {}
    }),
  );
}

async function runWatchMode(): Promise<void> {
  const rebuildWorker = new DebouncedWorker(async () => {
    try {
      const exitCode = await runPostcssBuild();

      if (exitCode !== 0) {
        console.error(
          `[tailwind] PostCSS exited with code ${exitCode}. Watching for the next change...`,
        );
      }
    } catch (error) {
      console.error(error);
    }
  }, 150, "tailwind");

  sourceWatchers.push(...createWatchers(rebuildWorker));

  try {
    const exitCode = await runPostcssBuild();

    if (exitCode !== 0) {
      console.error(
        `[tailwind] Initial PostCSS build exited with code ${exitCode}. Watching for the next change...`,
      );
    }
  } catch (error) {
    console.error(error);
  }
}

await cleanupStaleWatcher();
await writePidFile();

let shuttingDown = false;
let activeBuild: ChildProcess | null = null;
const sourceWatchers: ClosableWatcher[] = [];

if (mode === "watch") {
  await runWatchMode();
} else {
  try {
    const exitCode = await runPostcssBuild();
    process.exit(exitCode);
  } catch (error) {
    console.error(error);
    process.exit(1);
  }
}

async function shutdown(exitCode: number): Promise<void> {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;

  await closeWatchers();

  if (activeBuild?.pid && activeBuild.exitCode === null && !activeBuild.killed) {
    await killProcessTree(activeBuild.pid);
  }

  await clearPidFile();
  process.exit(exitCode);
}

process.once("SIGINT", () => {
  void shutdown(0);
});

process.once("SIGTERM", () => {
  void shutdown(0);
});

process.once("uncaughtException", (error) => {
  console.error(error);
  void shutdown(1);
});

process.once("unhandledRejection", (reason) => {
  console.error(reason);
  void shutdown(1);
});

process.once("exit", () => {
  clearPidFileSync();
});
