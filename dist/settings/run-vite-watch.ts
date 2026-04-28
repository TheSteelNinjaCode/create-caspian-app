import { spawn } from "node:child_process";
import process from "node:process";
import { join } from "node:path";

const viteBin = join(process.cwd(), "node_modules", "vite", "bin", "vite.js");

const child = spawn(
  process.execPath,
  [viteBin, "build", "--watch", "--clearScreen", "false"],
  {
    stdio: "inherit",
    windowsHide: true,
    env: {
      ...process.env,
      NO_COLOR: "1",
      FORCE_COLOR: "0",
    },
  },
);

child.on("error", (error) => {
  console.error(error);
  process.exit(1);
});

child.on("exit", (code, signal) => {
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