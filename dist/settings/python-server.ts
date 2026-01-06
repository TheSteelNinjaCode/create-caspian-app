import { spawn, ChildProcess } from "child_process";
import { platform } from "os";
import { existsSync } from "fs";
import { join } from "path";
import { Socket } from "net";

let pythonProcess: ChildProcess | null = null;
let isRestarting = false;

function isWindows(): boolean {
  return platform() === "win32";
}

function getVenvPythonPath(): string {
  const venvPython = isWindows()
    ? join(".venv", "Scripts", "python.exe")
    : join(".venv", "bin", "python");

  if (!existsSync(venvPython)) {
    console.warn(`⚠ Virtual environment not found, using system python`);
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
  timeout = 5000
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

function spawnPython(port: number): ChildProcess {
  const pythonPath = getVenvPythonPath();
  const args = ["-u", "main.py"];

  console.log(`→ Starting Python server on port ${port}...`);

  const child = spawn(pythonPath, args, {
    stdio: "inherit",
    shell: false,
    detached: !isWindows(),
    env: { ...process.env, PYTHONUNBUFFERED: "1", PORT: String(port) },
  });

  child.on("error", (err) => console.error("Failed to start Python:", err));
  return child;
}

export function startPythonServer(port: number): void {
  if (pythonProcess && pythonProcess.exitCode === null) return;
  pythonProcess = spawnPython(port);
}

export async function restartPythonServer(port: number): Promise<void> {
  if (isRestarting) return;
  isRestarting = true;

  try {
    console.log("→ Restarting Python server...");
    const prev = pythonProcess;
    pythonProcess = null;

    if (prev) {
      await killProcessTree(prev);
      await waitForPortRelease(port);
    }

    pythonProcess = spawnPython(port);
  } finally {
    isRestarting = false;
  }
}

export function stopPythonServer(): void {
  const prev = pythonProcess;
  pythonProcess = null;
  if (prev) killProcessTree(prev);
}

process.on("exit", () => stopPythonServer());
process.on("SIGINT", () => {
  stopPythonServer();
  process.exit(0);
});
process.on("SIGTERM", () => {
  stopPythonServer();
  process.exit(0);
});
