import { spawn, ChildProcess } from "child_process";
import { platform } from "os";
import { existsSync } from "fs";
import { join } from "path";
import { Socket } from "net";
import { randomBytes } from "crypto";

let pythonProcess: ChildProcess | null = null;
let pythonControlToken: string | null = null;
let isRestarting = false;
const GRACEFUL_SHUTDOWN_TIMEOUT_MS = 7000;

function isWindows(): boolean {
  return platform() === "win32";
}

function getVenvPythonPath(): string {
  const venvPython = isWindows()
    ? join(".venv", "Scripts", "python.exe")
    : join(".venv", "bin", "python");

  if (!existsSync(venvPython)) {
    console.warn("Warning: Virtual environment not found, using system python");
    return isWindows() ? "python" : "python3";
  }
  return venvPython;
}

export function waitForPort(port: number, timeout = 10000): Promise<boolean> {
  const start = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      if (Date.now() - start > timeout) {
        resolve(false);
        return;
      }
      const socket = new Socket();
      socket.setTimeout(200);
      socket.on("connect", () => {
        socket.destroy();
        resolve(true);
      });
      socket.on("timeout", () => {
        socket.destroy();
        setTimeout(check, 100);
      });
      socket.on("error", () => {
        socket.destroy();
        setTimeout(check, 100);
      });
      socket.connect(port, "127.0.0.1");
    };
    check();
  });
}

export function waitForPortRelease(
  port: number,
  timeout = 5000,
): Promise<boolean> {
  const start = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      if (Date.now() - start > timeout) {
        resolve(false);
        return;
      }
      const socket = new Socket();
      socket.setTimeout(200);
      socket.on("connect", () => {
        socket.destroy();
        setTimeout(check, 100);
      });
      socket.on("timeout", () => {
        socket.destroy();
        resolve(true);
      });
      socket.on("error", (err: any) => {
        socket.destroy();
        if (err.code === "ECONNREFUSED") {
          resolve(true);
        } else {
          setTimeout(check, 100);
        }
      });
      socket.connect(port, "127.0.0.1");
    };
    check();
  });
}

async function killProcessTree(child: ChildProcess): Promise<void> {
  if (!child || child.exitCode !== null) return;
  const pid = child.pid;
  if (!pid) return;

  if (isWindows()) {
    try {
      await new Promise<void>((resolve) => {
        const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
          stdio: "ignore",
          shell: true,
          windowsHide: true,
        });
        killer.on("exit", () => resolve());
        killer.on("error", () => resolve());
      });
    } catch (e) {}
  } else {
    try {
      process.kill(-pid, "SIGKILL");
    } catch {
      try {
        child.kill("SIGKILL");
      } catch {}
    }
  }
}

export function requestGracefulShutdown(
  child: ChildProcess,
  controlToken: string | null,
  timeout = GRACEFUL_SHUTDOWN_TIMEOUT_MS,
): Promise<boolean> {
  if (child.exitCode !== null) return Promise.resolve(true);
  const stdin = child.stdin;
  if (!controlToken || !stdin?.writable) return Promise.resolve(false);

  return new Promise((resolve) => {
    let settled = false;
    const finish = (stopped: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.off("exit", onExit);
      child.off("close", onExit);
      resolve(stopped);
    };
    const onExit = () => finish(true);
    const timer = setTimeout(() => finish(false), timeout);

    child.once("exit", onExit);
    child.once("close", onExit);
    stdin.write(`shutdown:${controlToken}\n`, (error) => {
      if (error) finish(false);
    });
  });
}

async function stopPythonProcess(
  child: ChildProcess,
  controlToken: string | null,
): Promise<void> {
  const stoppedGracefully = await requestGracefulShutdown(child, controlToken);
  if (stoppedGracefully) return;

  console.warn(
    "Warning: Python server did not stop gracefully; forcing process termination.",
  );
  await killProcessTree(child);
}

function spawnPython(port: number, browserSyncPort?: number): ChildProcess {
  const pythonPath = getVenvPythonPath();
  const args = ["-u", "main.py"];

  console.log(`-> Starting Python server on port ${port}...`);

  pythonControlToken = randomBytes(32).toString("hex");
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    PORT: String(port),
    CASPIAN_DEV_CONTROL_TOKEN: pythonControlToken,
    ...(browserSyncPort
      ? { CASPIAN_BROWSER_SYNC_PORT: String(browserSyncPort) }
      : {}),
  };

  const child = spawn(pythonPath, args, {
    stdio: ["pipe", "inherit", "inherit"],
    shell: false,
    detached: !isWindows(),
    env,
  });

  child.on("error", (err) => console.error("Failed to start Python:", err));
  return child;
}

export function startPythonServer(
  port: number,
  browserSyncPort?: number,
): void {
  if (pythonProcess && pythonProcess.exitCode === null) return;
  pythonProcess = spawnPython(port, browserSyncPort);
}

export async function restartPythonServer(
  port: number,
  browserSyncPort?: number,
): Promise<void> {
  if (isRestarting) return;
  isRestarting = true;

  try {
    console.log("-> Restarting Python server...");
    const prev = pythonProcess;
    const prevControlToken = pythonControlToken;
    pythonProcess = null;
    pythonControlToken = null;

    if (prev) {
      await stopPythonProcess(prev, prevControlToken);
      await waitForPortRelease(port);
    }

    pythonProcess = spawnPython(port, browserSyncPort);
  } finally {
    isRestarting = false;
  }
}

export async function stopPythonServer(): Promise<void> {
  const prev = pythonProcess;
  const prevControlToken = pythonControlToken;
  pythonProcess = null;
  pythonControlToken = null;
  if (prev) await stopPythonProcess(prev, prevControlToken);
}

export async function waitForHttpHealth(
  port: number,
  timeout = 15000,
): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt <= timeout) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`, {
        cache: "no-store",
        signal: AbortSignal.timeout(1000),
      });

      if (response.ok) return true;
    } catch {}

    await new Promise((resolve) => setTimeout(resolve, 150));
  }

  return false;
}
