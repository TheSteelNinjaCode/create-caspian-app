/**
 * Browser console -> dev terminal bridge (development only).
 *
 * Why this exists
 * ---------------
 * PulsePoint reports every runtime problem through `console.error` with a
 * `[PP-ERROR]` / `[PP-WARN]` prefix. Those never reached the `npm run dev`
 * terminal, so a broken route looked identical to a working one unless someone
 * happened to have DevTools open. An agent editing templates had no feedback
 * signal at all.
 *
 * This wires the browser back to the terminal that is already running:
 * BrowserSync proxies every request, so a middleware on `POST /__pp-devlog`
 * costs no extra port.
 *
 * The `<script src="/__pp-devlog.js">` tag is added by `_inject_dev_console_bridge`
 * in `main.py`, gated on `CASPIAN_BROWSER_SYNC_PORT` -- the variable
 * `settings/python-server.ts` sets only when the dev stack spawns the server.
 * BrowserSync's own `snippetOptions` injection does not fire against this app's
 * proxied responses (its client snippet is absent from them entirely), so the
 * tag has to come from the render pipeline rather than from the proxy.
 *
 * Transport choice: plain HTTP, not the BrowserSync socket. The errors worth
 * catching fire during `pp.mount()` at page load, which is often *before* the
 * BrowserSync client socket finishes connecting -- a socket bridge would drop
 * exactly the messages this exists to surface. A POST works from the first
 * millisecond of page life.
 *
 * This file is only imported by `settings/bs-config.ts`, which runs solely
 * under `npm run dev`. Nothing here ships to production.
 */

import type { IncomingMessage, ServerResponse } from "http";
import chalk from "chalk";

export const DEV_LOG_PATH = "/__pp-devlog";
export const DEV_LOG_CLIENT_PATH = "/__pp-devlog.js";

/** Cap a single forwarded payload so a runaway logger cannot flood the terminal. */
const MAX_BODY_BYTES = 64 * 1024;
/** Identical repeated messages inside this window print once with a count. */
const DEDUPE_WINDOW_MS = 1000;

type ClientLogLevel = "error" | "warn" | "log";

type ClientLogEntry = {
  level?: ClientLogLevel;
  message?: string;
  url?: string;
  stack?: string;
};

const recentMessages = new Map<string, { at: number; count: number }>();

function shouldPrint(signature: string): { print: boolean; repeated: number } {
  const now = Date.now();
  const previous = recentMessages.get(signature);

  if (previous && now - previous.at < DEDUPE_WINDOW_MS) {
    previous.count += 1;
    previous.at = now;
    return { print: false, repeated: previous.count };
  }

  const repeated = previous?.count ?? 0;
  recentMessages.set(signature, { at: now, count: 1 });

  // Keep the map from growing without bound during a long dev session.
  if (recentMessages.size > 200) {
    const cutoff = now - DEDUPE_WINDOW_MS * 10;
    for (const [key, value] of recentMessages) {
      if (value.at < cutoff) recentMessages.delete(key);
    }
  }

  return { print: true, repeated };
}

function formatRoute(rawUrl: string | undefined): string {
  if (!rawUrl) return "";
  try {
    const parsed = new URL(rawUrl);
    return parsed.pathname + parsed.search;
  } catch {
    return rawUrl;
  }
}

function printEntry(entry: ClientLogEntry): void {
  const level: ClientLogLevel = entry.level ?? "error";
  const message = (entry.message ?? "").trim();
  if (!message) return;

  const { print, repeated } = shouldPrint(`${level}:${message}`);
  if (!print) return;

  const route = formatRoute(entry.url);
  const badge =
    level === "error"
      ? chalk.bgRed.black.bold(" BROWSER ERROR ")
      : level === "warn"
        ? chalk.bgYellow.black.bold(" BROWSER WARN  ")
        : chalk.bgBlue.black.bold(" BROWSER LOG   ");

  const suppressed =
    repeated > 1 ? chalk.gray(`  (${repeated} identical suppressed)`) : "";

  console.log("");
  console.log(`${badge} ${route ? chalk.cyan(route) : ""}${suppressed}`);

  for (const line of message.split("\n")) {
    console.log(`  ${level === "error" ? chalk.red(line) : chalk.yellow(line)}`);
  }

  if (entry.stack) {
    // The first frames are the runtime's own internals; the useful location is
    // the compiled template expression, which the message already names.
    const frames = entry.stack
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.startsWith("at "))
      .slice(0, 3);
    for (const frame of frames) {
      console.log(chalk.gray(`    ${frame}`));
    }
  }
  console.log("");
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let size = 0;
    const chunks: Buffer[] = [];

    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        req.destroy();
        resolve("");
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", () => resolve(""));
  });
}

/**
 * Client script served at `/__pp-devlog.js`.
 *
 * Forwards only PulsePoint-prefixed console output plus genuine uncaught
 * errors, so ordinary `console.log` debugging stays in the browser where it
 * belongs and the terminal keeps signal high.
 */
const CLIENT_SCRIPT = `(() => {
  if (window.__ppDevLogInstalled) return;
  window.__ppDevLogInstalled = true;

  var ENDPOINT = ${JSON.stringify(DEV_LOG_PATH)};
  var PP_PREFIX = /^\\[PP-(ERROR|WARN)\\]/;

  function send(level, message, stack) {
    try {
      var body = JSON.stringify({
        level: level,
        message: String(message).slice(0, 8000),
        stack: stack ? String(stack).slice(0, 4000) : undefined,
        url: location.href
      });
      // keepalive lets the report survive a navigation triggered by the error.
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true
      }).catch(function () {});
    } catch (e) {}
  }

  function format(args) {
    return Array.prototype.map
      .call(args, function (arg) {
        if (arg instanceof Error) return arg.message;
        if (typeof arg === "string") return arg;
        try {
          return JSON.stringify(arg);
        } catch (e) {
          return String(arg);
        }
      })
      .join(" ");
  }

  function hook(name, level) {
    var original = console[name];
    console[name] = function () {
      var text = format(arguments);
      // Only PulsePoint runtime diagnostics are forwarded; app console noise
      // stays in the browser.
      if (PP_PREFIX.test(text)) {
        var stack;
        for (var i = 0; i < arguments.length; i++) {
          if (arguments[i] instanceof Error) {
            stack = arguments[i].stack;
            break;
          }
        }
        send(level, text, stack);
      }
      return original.apply(console, arguments);
    };
  }

  hook("error", "error");
  hook("warn", "warn");

  window.addEventListener("error", function (event) {
    if (!event) return;
    var error = event.error;
    send(
      "error",
      "Uncaught " + (error && error.message ? error.message : event.message),
      error && error.stack
    );
  });

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event && event.reason;
    send(
      "error",
      "Unhandled promise rejection: " +
        (reason && reason.message ? reason.message : String(reason)),
      reason && reason.stack
    );
  });
})();`;

/**
 * BrowserSync middleware pair: serves the client hook and receives its reports.
 *
 * Returned as a connect-style middleware; anything that is not one of the two
 * dev-log paths falls straight through to the proxy.
 */
export function devLogMiddleware(
  req: IncomingMessage,
  res: ServerResponse,
  next: () => void,
): void {
  const url = (req.url || "").split("?")[0];

  if (url === DEV_LOG_CLIENT_PATH) {
    res.writeHead(200, {
      "Content-Type": "application/javascript; charset=utf-8",
      "Cache-Control": "no-store",
    });
    res.end(CLIENT_SCRIPT);
    return;
  }

  if (url === DEV_LOG_PATH && req.method === "POST") {
    void readBody(req).then((raw) => {
      try {
        if (raw) printEntry(JSON.parse(raw) as ClientLogEntry);
      } catch {
        // A malformed report must never take the dev server down.
      }
      res.writeHead(204).end();
    });
    return;
  }

  next();
}
