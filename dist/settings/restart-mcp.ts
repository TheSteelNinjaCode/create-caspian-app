import { existsSync, readFileSync } from "fs";
import { isAbsolute, join } from "path";
import { createServer } from "net";
import caspianConfig from "../caspian.config.json";
import { createRestartableProcess, onExit } from "./utils.js";

const projectRoot = process.cwd();
const localFastMcp =
  process.platform === "win32"
    ? join(projectRoot, ".venv", "Scripts", "fastmcp.exe")
    : join(projectRoot, ".venv", "bin", "fastmcp");

const fastMcpCommand = existsSync(localFastMcp) ? localFastMcp : "fastmcp";

const suppressedLinePatterns = [
  /AuthlibDeprecationWarning/,
  /^It will be compatible before version 2\.0\.0\.$/,
  /^from authlib\.jose import /,
  /^INFO:\s+Started server process/,
  /^INFO:\s+Waiting for application startup\.$/,
  /^INFO:\s+Application startup complete\.$/,
];

function getServerSpec(): string | null {
  const explicitSpec = process.env.MCP_SERVER_SPEC?.trim();
  if (explicitSpec) {
    return explicitSpec;
  }

  const defaultSpecs = ["src/lib/mcp/fastmcp.json", "fastmcp.json", "mcp.json"];
  for (const relativeSpec of defaultSpecs) {
    if (existsSync(join(projectRoot, relativeSpec))) {
      return relativeSpec;
    }
  }

  return null;
}

function getServerSpecPath(serverSpec: string): string | null {
  if (serverSpec.startsWith("http://") || serverSpec.startsWith("https://")) {
    return null;
  }

  return isAbsolute(serverSpec) ? serverSpec : join(projectRoot, serverSpec);
}

function readDeploymentConfig(serverSpec: string): Record<string, unknown> {
  const serverSpecPath = getServerSpecPath(serverSpec);
  if (!serverSpecPath || !existsSync(serverSpecPath)) {
    return {};
  }

  try {
    const rawConfig = JSON.parse(readFileSync(serverSpecPath, "utf-8"));
    if (rawConfig && typeof rawConfig === "object") {
      const deployment = rawConfig.deployment;
      if (deployment && typeof deployment === "object") {
        return deployment as Record<string, unknown>;
      }
    }
  } catch {
    // Ignore malformed specs and allow FastMCP to validate them.
  }

  return {};
}

function getPreferredHost(serverSpec: string): string {
  return (
    process.env.MCP_HOST?.trim() ||
    String(readDeploymentConfig(serverSpec).host || "").trim() ||
    "127.0.0.1"
  );
}

function getPreferredPort(serverSpec: string): number | null {
  const rawPort =
    process.env.MCP_PORT?.trim() ||
    String(readDeploymentConfig(serverSpec).port || "").trim();

  if (!rawPort) {
    return null;
  }

  const port = Number(rawPort);
  if (!Number.isInteger(port) || port <= 0) {
    return null;
  }

  return port;
}

function findAvailablePort(startPort: number, host: string): Promise<number> {
  return new Promise((resolve) => {
    const server = createServer();

    server.listen(startPort, host, () => {
      server.close(() => resolve(startPort));
    });

    server.on("error", () => {
      resolve(findAvailablePort(startPort + 1, host));
    });
  });
}

function buildArgs(serverSpec: string, portOverride?: string): string[] {
  const args = ["run", serverSpec, "--no-banner"];
  const transport = process.env.MCP_TRANSPORT?.trim();
  const host = process.env.MCP_HOST?.trim();
  const port = portOverride || process.env.MCP_PORT?.trim();
  const path = process.env.MCP_PATH?.trim();
  const logLevel = process.env.MCP_LOG_LEVEL?.trim();

  if (transport) args.push("--transport", transport);
  if (host) args.push("--host", host);
  if (port) args.push("--port", port);
  if (path) args.push("--path", path);
  if (logLevel) args.push("--log-level", logLevel);

  return args;
}

function createLineHandler(handleLine: (line: string) => void) {
  let buffer = "";

  return (chunk: Buffer) => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      handleLine(line);
    }
  };
}

function createMcpOutputHandler() {
  let waitingForReadyUrl = false;
  let readyReported = false;

  return (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }

    if (suppressedLinePatterns.some((pattern) => pattern.test(trimmed))) {
      return;
    }

    if (trimmed.includes("Starting MCP server")) {
      waitingForReadyUrl = true;
      return;
    }

    if (trimmed.includes("transport '") && trimmed.endsWith(" on")) {
      waitingForReadyUrl = true;
      return;
    }

    const urlMatch = trimmed.match(/https?:\/\/\S+/);
    if (
      urlMatch &&
      (waitingForReadyUrl || trimmed.includes("Uvicorn running on"))
    ) {
      waitingForReadyUrl = false;
      if (!readyReported) {
        console.log(`[mcp] Ready at ${urlMatch[0]}`);
        readyReported = true;
      }
      return;
    }

    if (trimmed.startsWith("INFO:")) {
      return;
    }

    waitingForReadyUrl = false;

    if (/traceback|exception|error/i.test(trimmed)) {
      console.error(`[mcp] ${trimmed}`);
      return;
    }

    console.log(`[mcp] ${trimmed}`);
  };
}

if (!caspianConfig.mcp) {
  console.log("[mcp] Disabled in caspian.config.json, skipping MCP startup.");
  process.exit(0);
}

const serverSpec = getServerSpec();

if (!serverSpec) {
  console.log(
    "[mcp] Enabled, but no FastMCP server spec was found. Create src/lib/mcp/fastmcp.json or set MCP_SERVER_SPEC to a FastMCP config, file, or URL.",
  );
  process.exit(0);
}

const preferredHost = getPreferredHost(serverSpec);
const preferredPort = getPreferredPort(serverSpec);
const resolvedPort = preferredPort
  ? await findAvailablePort(preferredPort, preferredHost)
  : null;

if (preferredPort && resolvedPort && preferredPort !== resolvedPort) {
  console.log(
    `[mcp] Port ${preferredPort} is unavailable on ${preferredHost}, using ${resolvedPort} instead.`,
  );
}

const handleMcpOutput = createMcpOutputHandler();

const runner = createRestartableProcess({
  name: "mcp",
  cmd: fastMcpCommand,
  args: buildArgs(serverSpec, resolvedPort ? String(resolvedPort) : undefined),
  startMessage: "[mcp] Starting MCP server...",
  onStdout: createLineHandler(handleMcpOutput),
  onStderr: createLineHandler(handleMcpOutput),
});

runner.start();
onExit(() => runner.stop());
