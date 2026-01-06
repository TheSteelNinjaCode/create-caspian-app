import { fileURLToPath } from "url";
import { dirname } from "path";
import chokidar, { FSWatcher } from "chokidar";
import { spawn, ChildProcess, execFile } from "child_process";
import { relative } from "path";

export const PUBLIC_DIR = "public";
export const SRC_DIR = "src";
export const APP_DIR = "src/app";

export function getFileMeta() {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  return { __filename, __dirname };
}

export type WatchEvent = "add" | "addDir" | "change" | "unlink" | "unlinkDir";

export const DEFAULT_IGNORES: (string | RegExp)[] = [
  /(^|[\/\\])\../,
  "**/node_modules/**",
  "**/vendor/**",
  "**/dist/**",
  "**/build/**",
  "**/.cache/**",
  "**/*.log",
  "**/*.tmp",
  "**/*.swp",
];

export const DEFAULT_AWF = { stabilityThreshold: 300, pollInterval: 100 };

export function createSrcWatcher(
  root: string,
  opts: {
    exts?: string[];
    onEvent: (event: WatchEvent, absPath: string, relPath: string) => void;
    ignored?: (string | RegExp)[];
    awaitWriteFinish?: { stabilityThreshold: number; pollInterval: number };
    logPrefix?: string;
    usePolling?: boolean;
    interval?: number;
  }
): FSWatcher {
  const {
    exts,
    onEvent,
    ignored = DEFAULT_IGNORES,
    awaitWriteFinish = DEFAULT_AWF,
    logPrefix = "watch",
    usePolling = true,
  } = opts;

  const watcher = chokidar.watch(root, {
    ignoreInitial: true,
    persistent: true,
    ignored,
    awaitWriteFinish,
    usePolling,
    interval: opts.interval ?? 1000,
  });

  watcher
    .on("ready", () => {
      console.log(`[${logPrefix}] Watching ${root.replace(/\\/g, "/")}/**/*`);
    })
    .on("all", (event: WatchEvent, filePath: string) => {
      if (exts && exts.length > 0) {
        const ok = exts.some((ext) => filePath.endsWith(ext));
        if (!ok) return;
      }
      const rel = relative(root, filePath).replace(/\\/g, "/");
      if (event === "add" || event === "change" || event === "unlink") {
        onEvent(event, filePath, rel);
      }
    })
    .on("error", (err) => console.error(`[${logPrefix}] Error:`, err));

  return watcher;
}

export class DebouncedWorker {
  private timer: NodeJS.Timeout | null = null;
  private running = false;
  private queued = false;

  constructor(
    private work: () => Promise<void> | void,
    private debounceMs = 350,
    private name = "worker"
  ) {}

  schedule(reason?: string) {
    if (reason) console.log(`[${this.name}] ${reason} → scheduled`);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.runNow().catch(() => {});
    }, this.debounceMs);
  }

  private async runNow() {
    if (this.running) {
      this.queued = true;
      return;
    }
    this.running = true;
    try {
      await this.work();
    } catch (err) {
      console.error(`[${this.name}] error:`, err);
    } finally {
      this.running = false;
      if (this.queued) {
        this.queued = false;
        this.runNow().catch(() => {});
      }
    }
  }
}

export function createRestartableProcess(spec: {
  name: string;
  cmd: string;
  args?: string[];
  stdio?: "inherit" | [any, any, any];
  gracefulSignal?: NodeJS.Signals;
  forceKillAfterMs?: number;
  windowsKillTree?: boolean;
  onStdout?: (buf: Buffer) => void;
  onStderr?: (buf: Buffer) => void;
}) {
  const {
    name,
    cmd,
    args = [],
    stdio = ["ignore", "pipe", "pipe"],
    gracefulSignal = "SIGINT",
    forceKillAfterMs = 2000,
    windowsKillTree = true,
    onStdout,
    onStderr,
  } = spec;

  let child: ChildProcess | null = null;

  function start() {
    console.log(`[${name}] Starting: ${cmd} ${args.join(" ")}`.trim());
    child = spawn(cmd, args, { stdio, windowsHide: true });

    child.stdout?.on("data", (buf: Buffer) => {
      if (onStdout) onStdout(buf);
      else process.stdout.write(`[${name}] ${buf.toString()}`);
    });

    child.stderr?.on("data", (buf: Buffer) => {
      if (onStderr) onStderr(buf);
      else process.stderr.write(`[${name}:err] ${buf.toString()}`);
    });

    child.on("close", (code) => {
      console.log(`[${name}] Exited with code ${code}`);
    });

    child.on("error", (err) => {
      console.error(`[${name}] Failed to start:`, err);
    });

    return child;
  }

  function killOnWindows(pid: number): Promise<void> {
    return new Promise((resolve) => {
      const cp = execFile("taskkill", ["/F", "/T", "/PID", String(pid)], () =>
        resolve()
      );
      cp.on("error", () => resolve());
    });
  }

  async function stop(): Promise<void> {
    if (!child || child.killed) return;
    const pid = child.pid!;
    console.log(`[${name}] Stopping…`);

    if (process.platform === "win32" && windowsKillTree) {
      await killOnWindows(pid);
      child = null;
      return;
    }

    await new Promise<void>((resolve) => {
      const done = () => resolve();
      child!.once("close", done).once("exit", done).once("disconnect", done);
      try {
        child!.kill(gracefulSignal);
      } catch {
        resolve();
      }
      setTimeout(() => {
        if (child && !child.killed) {
          try {
            process.kill(pid, "SIGKILL");
          } catch {}
        }
      }, forceKillAfterMs);
    });
    child = null;
  }

  async function restart(reason?: string) {
    if (reason) console.log(`[${name}] Restart requested: ${reason}`);
    await stop();
    return start();
  }

  function getChild() {
    return child;
  }

  return { start, stop, restart, getChild };
}

export function onExit(fn: () => Promise<void> | void) {
  const wrap = (sig: string) => async () => {
    console.log(`[proc] Received ${sig}, shutting down…`);
    try {
      await fn();
    } finally {
      process.exit(0);
    }
  };
  process.on("SIGINT", wrap("SIGINT"));
  process.on("SIGTERM", wrap("SIGTERM"));
  process.on("uncaughtException", async (err) => {
    console.error("[proc] Uncaught exception:", err);
    await wrap("uncaughtException")();
  });
}
