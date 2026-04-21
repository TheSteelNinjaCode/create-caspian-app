import { existsSync } from "fs";
import { join } from "path";
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

function buildArgs(serverSpec: string): string[] {
  const args = ["run", serverSpec, "--no-banner"];
  const transport = process.env.MCP_TRANSPORT?.trim();
  const host = process.env.MCP_HOST?.trim();
  const port = process.env.MCP_PORT?.trim();
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

const handleMcpOutput = createMcpOutputHandler();

const runner = createRestartableProcess({
  name: "mcp",
  cmd: fastMcpCommand,
  args: buildArgs(serverSpec),
  startMessage: "[mcp] Starting MCP server...",
  onStdout: createLineHandler(handleMcpOutput),
  onStderr: createLineHandler(handleMcpOutput),
});

runner.start();
onExit(() => runner.stop());
