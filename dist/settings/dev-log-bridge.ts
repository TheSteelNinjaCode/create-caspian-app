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
 *
 * Terminal *and* file
 * -------------------
 * Printing to stdout only helps whoever owns that terminal. An AI agent working
 * in a separate session cannot see it, and starting a second `npm run dev` to
 * get its own copy would take different ports and orphan the browser tab. So
 * every event is also appended to `.casp/browser-log.jsonl`, which any process
 * can read. `npm run logs` renders it; see `settings/browser-log.py`.
 *
 * The log records successful page loads, not just failures. That is what makes
 * it trustworthy: without `load` events, a fixed error still sits in the file
 * forever (a clean reload writes nothing), and an empty file cannot be told
 * apart from "nobody opened the page". With them, a route's state is whatever
 * happened after its most recent load.
 */

import type { IncomingMessage, ServerResponse } from "http";
import { appendFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import chalk from "chalk";

export const DEV_LOG_PATH = "/__pp-devlog";
export const DEV_LOG_CLIENT_PATH = "/__pp-devlog.js";

const SETTINGS_DIR = dirname(fileURLToPath(import.meta.url));

/**
 * Session-scoped browser event log.
 *
 * Lives in `.casp/` because `settings/project-name.ts` deletes that directory at
 * the start of every `npm run dev`, so the log is truncated per dev session with
 * no cleanup code of its own -- and `.casp/` is already gitignored.
 */
export const BROWSER_LOG_FILE = join(SETTINGS_DIR, "..", ".casp", "browser-log.jsonl");

/**
 * Backstop cap. Compaction on every source change is what normally keeps the
 * file small; this only catches a pathological burst between two compactions.
 * Deliberately modest: at ~4 bytes per token, 256 KB is still ~64k tokens if
 * anything ever reads the raw file, and nothing should need more than that.
 */
const MAX_LOG_BYTES = 256 * 1024;
/** Events kept when trimming (the session header is always preserved). */
const TRIM_KEEP_EVENTS = 2000;

/**
 * An error reported within this long of its page load is treated as mount-phase.
 *
 * The distinction decides whether a clean reload is evidence of a fix. Mount
 * errors re-fire on every load, so a reload genuinely re-tests them. An error
 * from a click handler fires only when someone clicks, so a reload proves
 * nothing about it -- and reporting that route as CLEAN is a lie that sends
 * whoever reads it away from a live bug.
 */
const MOUNT_PHASE_MS = 2000;

/** Cap a single forwarded payload so a runaway logger cannot flood the terminal. */
const MAX_BODY_BYTES = 64 * 1024;
/** Identical repeated messages inside this window print once with a count. */
const DEDUPE_WINDOW_MS = 1000;

type ClientLogLevel = "error" | "warn" | "log";

type ClientLogEntry = {
  /** `load` marks a page render; anything else is forwarded console output. */
  type?: "load" | "console";
  level?: ClientLogLevel;
  message?: string;
  url?: string;
  stack?: string;
  /** Per-page-load id, so an error can be tied to the load that produced it. */
  page?: string;
};

/** One line of `.casp/browser-log.jsonl`. Keep in sync with `browser_log.py`. */
type LogEvent = {
  t: string;
  type: "session" | "session-end" | "load" | "error" | "warn" | "resolved" | "restart";
  route?: string;
  page?: string;
  message?: string;
  stack?: string[];
  pid?: number;
  port?: number;
  /** `resolved` only: how many earlier errors this clean load supersedes. */
  supersedes?: number;
  /** `session` only: tells anyone reading the raw file how to read it. */
  readme?: string;
  /** `error` only: whether a reload can re-test this. See MOUNT_PHASE_MS. */
  phase?: "mount" | "interaction" | "unknown";
  /** `error` only: milliseconds between the page load and the report. */
  afterMs?: number;
  /** Survived a compaction: it predates the current code and was not re-tested. */
  carried?: boolean;
};

const recentMessages = new Map<string, { at: number; count: number }>();

/**
 * Errors that are still standing, per route.
 *
 * This is the working set compaction preserves, so it must hold whole events
 * rather than counts. A load removes the route's mount-phase errors (that load
 * re-tested them); interaction errors stay, because nothing about a reload
 * exercises a click handler.
 *
 * In-memory state is safe here precisely because this process and the log file
 * have the same lifetime: the Python server restarts on every `.py` edit, but
 * BrowserSync (this module) does not, and the log is only reset by this module.
 */
const openErrors = new Map<string, LogEvent[]>();

/** Load time per page id, so an error can be placed in mount or interaction phase. */
const pageLoads = new Map<string, number>();

/** The session line, replayed as the header every time the log is compacted. */
let sessionHeader: LogEvent | null = null;

let logFileUsable = true;

/** Drop old events once the file grows past the cap, keeping the session header. */
function trimLogFile(): void {
  try {
    const lines = readFileSync(BROWSER_LOG_FILE, "utf-8").split("\n").filter(Boolean);
    const header = lines.find((line) => line.includes('"type":"session"'));
    const tail = lines.slice(-TRIM_KEEP_EVENTS);
    const kept = header && !tail.includes(header) ? [header, ...tail] : tail;
    writeFileSync(BROWSER_LOG_FILE, kept.join("\n") + "\n", "utf-8");
  } catch {
    // A trim failure is not worth taking the dev server down for.
  }
}

/**
 * Append one event to the session log.
 *
 * Synchronous on purpose: `appendFileSync` cannot interleave partial lines the
 * way concurrent async writes could, and dev-time volume is trivial. A logging
 * failure must never break the dev server, so every error is swallowed once and
 * the sink then disables itself.
 */
function appendEvent(event: LogEvent): void {
  if (!logFileUsable) return;
  try {
    let size = 0;
    try {
      size = statSync(BROWSER_LOG_FILE).size;
    } catch {
      mkdirSync(dirname(BROWSER_LOG_FILE), { recursive: true });
    }
    if (size > MAX_LOG_BYTES) trimLogFile();
    appendFileSync(BROWSER_LOG_FILE, JSON.stringify(event) + "\n", "utf-8");
  } catch {
    logFileUsable = false;
  }
}

/**
 * Open a new session log. Called by `bs-config.ts` once ports are settled.
 *
 * The header lets a reader decide whether the log is live or a leftover from a
 * dev server that has since exited -- the difference between "the app is clean"
 * and "nothing has been observed", which an agent must not confuse.
 */
export function startBrowserLogSession(port: number): void {
  openErrors.clear();
  pageLoads.clear();
  sessionHeader = {
    t: new Date().toISOString(),
    type: "session",
    pid: process.pid,
    port,
    // A reader who opens this file directly (an AI agent will) has no way to tell
    // a fixed error from a live one. Say so on line one rather than relying on
    // everyone knowing the format.
    readme:
      "History, not current state. An error is superseded by a later 'load' or " +
      "'resolved' for the same route -- except an error with phase 'interaction', " +
      "which a reload cannot re-test. Run `npm run logs` for current status.",
  };
  appendEvent(sessionHeader);
}

/**
 * Rewrite the log down to what is still open, and mark the code boundary.
 *
 * Called on every source change. Two problems it solves at once: the file would
 * otherwise grow for the whole life of a dev session that is never restarted,
 * and errors produced by code that has since been edited would keep reading as
 * current.
 *
 * What survives is deliberately narrow -- the session header, a `restart` marker,
 * and errors nobody has re-tested. Resolved history is dropped outright; it has
 * already done its job. Anything carried once is dropped on the next compaction,
 * so a stale interaction error cannot haunt the log forever.
 */
export function compactBrowserLog(reason: string): void {
  if (!logFileUsable || !sessionHeader) return;

  const carried: LogEvent[] = [];
  for (const [route, events] of [...openErrors]) {
    // Already carried once: the code has changed twice since, so stop reporting it.
    const survivors = events.filter((event) => !event.carried);
    if (survivors.length === 0) {
      openErrors.delete(route);
      continue;
    }
    const marked = survivors.map((event) => ({ ...event, carried: true }));
    openErrors.set(route, marked);
    carried.push(...marked);
  }

  // Page ids no longer resolve to a load event in the file; carried errors are
  // read by route instead, so drop the lookup table with them.
  pageLoads.clear();

  const restart: LogEvent = {
    t: new Date().toISOString(),
    type: "restart",
    message: `Source changed (${reason}); log compacted. Errors below predate the current code.`,
    supersedes: carried.length,
  };

  try {
    mkdirSync(dirname(BROWSER_LOG_FILE), { recursive: true });
    const lines = [sessionHeader, restart, ...carried]
      .map((event) => JSON.stringify(event))
      .join("\n");
    writeFileSync(BROWSER_LOG_FILE, lines + "\n", "utf-8");
  } catch {
    logFileUsable = false;
  }
}

/** Mark a clean shutdown so a reader knows the log is finished, not abandoned. */
export function endBrowserLogSession(): void {
  appendEvent({ t: new Date().toISOString(), type: "session-end" });
}

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

/** Keep the frames that name the failing template, not the whole runtime stack. */
function topFrames(stack: string | undefined, limit: number): string[] {
  if (!stack) return [];
  return stack
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("at "))
    .slice(0, limit);
}

function handleEntry(entry: ClientLogEntry): void {
  const route = formatRoute(entry.url);

  // A page load is a log-only event: it is the "this route rendered" marker the
  // reader needs to date errors against, but printing one per navigation would
  // bury the errors it exists to contextualise.
  if (entry.type === "load") {
    const page = entry.page ?? "";
    appendEvent({ t: new Date().toISOString(), type: "load", route, page });

    pageLoads.set(page, Date.now());
    if (pageLoads.size > 200) {
      // Long sessions accumulate page ids; the oldest can no longer receive
      // reports, so drop them rather than growing without bound.
      for (const key of [...pageLoads.keys()].slice(0, 100)) pageLoads.delete(key);
    }

    // This load re-ran mount, so any mount error from an earlier page has been
    // retested. Interaction errors have not: nothing here clicked anything.
    const standing = openErrors.get(route);
    if (standing) {
      const retested = standing.filter((event) => event.page !== page && event.phase !== "interaction");
      const remaining = standing.filter((event) => !retested.includes(event));
      if (retested.length > 0) {
        if (remaining.length > 0) openErrors.set(route, remaining);
        else openErrors.delete(route);
        // A clean reload would otherwise write nothing, leaving the error as the
        // last word on this route in the raw file. State the supersession.
        appendEvent({
          t: new Date().toISOString(),
          type: "resolved",
          route,
          page,
          supersedes: retested.length,
          message: `Route reloaded; ${retested.length} earlier mount error(s) on this route are historical.`,
        });
      }
    }
    return;
  }

  const level: ClientLogLevel = entry.level ?? "error";
  const message = (entry.message ?? "").trim();
  if (!message) return;

  // The file keeps every occurrence; only the terminal is deduplicated, so a
  // burst stays readable there without the log losing the true error count.
  const event: LogEvent = {
    t: new Date().toISOString(),
    type: level === "warn" ? "warn" : "error",
    route,
    page: entry.page,
    message,
    stack: topFrames(entry.stack, 5),
  };

  if (level === "error") {
    // Timing is the only signal available for whether a reload can re-test this:
    // mount work finishes in well under a second, so a report arriving much later
    // came from something a person did.
    const loadedAt = entry.page ? pageLoads.get(entry.page) : undefined;
    if (loadedAt === undefined) {
      event.phase = "unknown";
    } else {
      event.afterMs = Date.now() - loadedAt;
      event.phase = event.afterMs <= MOUNT_PHASE_MS ? "mount" : "interaction";
    }
    openErrors.set(route, [...(openErrors.get(route) ?? []), event]);
  }

  if (level === "error" || level === "warn") {
    appendEvent(event);
  }

  printEntry(entry, level, message, route);
}

function printEntry(
  entry: ClientLogEntry,
  level: ClientLogLevel,
  message: string,
  route: string,
): void {
  const { print, repeated } = shouldPrint(`${level}:${message}`);
  if (!print) return;

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

  // The first frames are the runtime's own internals; the useful location is
  // the compiled template expression, which the message already names.
  for (const frame of topFrames(entry.stack, 3)) {
    console.log(chalk.gray(`    ${frame}`));
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

  // Identifies this page load. Two POSTs can arrive out of order, so the reader
  // groups an error with its load by id rather than by arrival time -- that is
  // what makes "did this route reload clean?" answerable.
  var PAGE_ID = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

  function post(payload) {
    try {
      payload.url = location.href;
      payload.page = PAGE_ID;
      var body = JSON.stringify(payload);
      // keepalive lets the report survive a navigation triggered by the error.
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true
      }).catch(function () {});
    } catch (e) {}
  }

  function send(level, message, stack) {
    post({
      type: "console",
      level: level,
      message: String(message).slice(0, 8000),
      stack: stack ? String(stack).slice(0, 4000) : undefined
    });
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

  // Announce the load before anything can fail, so even a mount-time error has
  // a page record to attach to.
  post({ type: "load" });

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
        if (raw) handleEntry(JSON.parse(raw) as ClientLogEntry);
      } catch {
        // A malformed report must never take the dev server down.
      }
      res.writeHead(204).end();
    });
    return;
  }

  next();
}
