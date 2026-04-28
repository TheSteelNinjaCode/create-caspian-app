import { execFile, spawn } from "node:child_process";
import { mkdir, readFile, readFileSync, rm, rmSync, writeFile } from "node:fs";
import { promisify } from "node:util";
import { dirname, join } from "node:path";
import process from "node:process";

const mode: "watch" | "build" =
  process.argv[2] === "watch" ? "watch" : "build";
const watcherPidFile = join(process.cwd(), ".casp", "postcss-watch.pid");
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

if (mode === "watch") {
  args.push("--watch");
}

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

await cleanupStaleWatcher();
await writePidFile();

const child = spawn(process.execPath, args, {
  stdio: "inherit",
  windowsHide: true,
  env: {
    ...process.env,
    PP_POSTCSS_MODE: mode,
  },
});

let shuttingDown = false;

child.on("error", (error) => {
  console.error(error);
  void shutdown(1);
});

async function shutdown(exitCode: number): Promise<void> {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;

  if (child.pid && child.exitCode === null && !child.killed) {
    await killProcessTree(child.pid);
  }

  await clearPidFile();
  process.exit(exitCode);
}

child.on("exit", async (code, signal) => {
  await clearPidFile();

  if (shuttingDown) {
    process.exit(code ?? 0);
    return;
  }

  if (signal) {
    try {
      process.kill(process.pid, signal);
    } catch {
      process.exit(1);
    }
    return;
  }

  process.exit(code ?? 0);
});

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
