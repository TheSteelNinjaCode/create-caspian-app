/**
 * Dev-stack reload hold.
 *
 * The file watcher cannot tell an agent's write from a human's save — chokidar
 * sees an inode change, not a writer. So the agent declares itself instead: a
 * hold file marks "an agent is mid-run", and while it is active the change
 * coordinator in `bs-config.ts` keeps queueing changes without restarting the
 * Python server or reloading the browser. Releasing the hold drains the whole
 * run as ONE restart and ONE reload.
 *
 * Why this matters: the coordinator batches on a 1500 ms quiet period, which is
 * tuned for a human's burst-save. An agent's gap between two edits is a tool
 * round-trip — always wider than that window — so without a hold every single
 * edit costs a full process restart plus a reload of every open tab, and each
 * reload re-runs the route's Prisma queries against a pool that was just
 * discarded. Against a remote database that is the churn this file prevents.
 *
 * The signal is set by Claude Code hooks (`PreToolUse` acquires and refreshes,
 * `Stop`/`SessionEnd` release), so it does not depend on a model remembering to
 * call anything. The manual escape hatches are `npm run dev:hold`,
 * `npm run dev:resume`, and `npm run dev:hold:status`.
 *
 * This module is deliberately dependency-free and written in erasable-only
 * TypeScript so Node can run it directly (`node settings/dev-hold.ts acquire`)
 * with a cold start fast enough to sit in front of every agent edit.
 */

import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * A hold that stops being refreshed is treated as abandoned. This is the valve
 * that keeps a crashed agent or a killed session from freezing the dev stack:
 * the worst case degrades to today's behaviour, never to a dead server.
 */
export const STALE_HOLD_MS = 120_000;

/**
 * Even a continuously refreshed hold drains eventually, so a very long agent run
 * still gets periodic restarts instead of none at all.
 */
export const MAX_HOLD_MS = 600_000;

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));

/** Resolved from this file, not from `cwd`, so hook shells cannot misplace it. */
export const WORKSPACE_ROOT = join(MODULE_DIR, "..");

/**
 * Lives in `.casp/` on purpose: `npm run dev` deletes that directory at startup,
 * so a fresh dev stack can never inherit a stale hold from a previous session.
 *
 * Resolved per call rather than at import so `CASPIAN_DEV_HOLD_PATH` can point a
 * test (or a second stack) at its own file instead of the live one.
 */
export function getHoldPath(): string {
  return (
    process.env.CASPIAN_DEV_HOLD_PATH ||
    join(WORKSPACE_ROOT, ".casp", "dev-hold.json")
  );
}

export type DevHold = {
  /** Who asked for the hold, for the terminal message only. */
  owner: string;
  /** Process that acquired it, for debugging a hold nobody expected. */
  pid: number;
  /** First acquire — drives the absolute cap. */
  acquiredAt: number;
  /** Most recent acquire — drives the stale check. */
  touchedAt: number;
  /** How many edits this run has queued, so the terminal can show progress. */
  edits: number;
};

export type DevHoldStatus =
  | { active: false; reason: "none"; hold: null }
  | { active: false; reason: "stale" | "expired"; hold: DevHold }
  | { active: true; reason: "held"; hold: DevHold };

function isDevHold(value: unknown): value is DevHold {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<DevHold>;
  return (
    typeof candidate.owner === "string" &&
    typeof candidate.pid === "number" &&
    typeof candidate.acquiredAt === "number" &&
    typeof candidate.touchedAt === "number" &&
    typeof candidate.edits === "number"
  );
}

/** Returns the parsed hold, or null when absent or unreadable. */
export function readDevHold(): DevHold | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(getHoldPath(), "utf-8"));
    return isDevHold(parsed) ? parsed : null;
  } catch {
    // Missing, half-written, or corrupt all mean the same thing to a caller:
    // there is no hold it can trust, so fall through to normal reloading.
    return null;
  }
}

/**
 * Decide whether the coordinator should defer. Both expiry rules fail open —
 * an unreadable, stale, or over-long hold reports inactive rather than blocking
 * the dev stack forever.
 */
export function evaluateDevHold(now: number = Date.now()): DevHoldStatus {
  const hold = readDevHold();
  if (!hold) return { active: false, reason: "none", hold: null };

  if (now - hold.touchedAt > STALE_HOLD_MS) {
    return { active: false, reason: "stale", hold };
  }

  if (now - hold.acquiredAt > MAX_HOLD_MS) {
    return { active: false, reason: "expired", hold };
  }

  return { active: true, reason: "held", hold };
}

/** True when reloads should be deferred right now. */
export function isDevHoldActive(now: number = Date.now()): boolean {
  return evaluateDevHold(now).active;
}

/**
 * Create the hold, or refresh an existing one. Refreshing keeps `acquiredAt` so
 * the absolute cap measures the whole run rather than restarting on every edit.
 *
 * A capped-out hold is deliberately still carried over. If a new edit started a
 * fresh window instead, an agent editing steadily would re-hold before the
 * coordinator's next 1500 ms tick and the cap would reset forever without ever
 * forcing a drain. Carrying it keeps the run expired — so reloads resume — until
 * an explicit release ends the run. A stale hold is a different case: nothing
 * refreshed it, so its owner is gone and the next edit legitimately starts over.
 */
export function acquireDevHold(
  owner: string = "agent",
  now: number = Date.now(),
): DevHold {
  const previous = evaluateDevHold(now);
  const carryOver =
    previous.reason === "held" || previous.reason === "expired"
      ? previous.hold
      : null;

  const hold: DevHold = {
    owner,
    pid: process.pid,
    acquiredAt: carryOver ? carryOver.acquiredAt : now,
    touchedAt: now,
    edits: carryOver ? carryOver.edits + 1 : 1,
  };

  mkdirSync(dirname(getHoldPath()), { recursive: true });
  writeFileSync(getHoldPath(), `${JSON.stringify(hold, null, 2)}\n`, "utf-8");
  return hold;
}

/** Drop the hold. Idempotent, so a duplicate `Stop` hook is harmless. */
export function releaseDevHold(): DevHold | null {
  const hold = readDevHold();
  rmSync(getHoldPath(), { force: true });
  return hold;
}

function describeStatus(status: DevHoldStatus): string {
  if (status.reason === "none") return "inactive - no hold file";

  const ageSeconds = Math.round((Date.now() - status.hold.acquiredAt) / 1000);
  const summary = `owner=${status.hold.owner} pid=${status.hold.pid} edits=${status.hold.edits} age=${ageSeconds}s`;

  if (status.reason === "stale") {
    return `inactive - hold went stale (no refresh for over ${STALE_HOLD_MS / 1000}s); ${summary}`;
  }
  if (status.reason === "expired") {
    return `inactive - hold passed the ${MAX_HOLD_MS / 1000}s cap; ${summary}`;
  }
  return `ACTIVE - browser reloads and Python restarts are deferred; ${summary}`;
}

function runCli(argv: string[]): number {
  const command = argv[0] ?? "status";
  const quiet = argv.includes("--quiet");
  const log = (message: string) => {
    if (!quiet) console.log(message);
  };

  if (command === "acquire") {
    const hold = acquireDevHold(process.env.CASPIAN_DEV_HOLD_OWNER || "agent");
    log(`[dev-hold] Held after ${hold.edits} edit(s); reloads deferred.`);
    return 0;
  }

  if (command === "release") {
    const hold = releaseDevHold();
    log(
      hold
        ? `[dev-hold] Released after ${hold.edits} edit(s); the dev stack will reload once.`
        : "[dev-hold] No hold was active.",
    );
    return 0;
  }

  if (command === "status") {
    console.log(`[dev-hold] ${describeStatus(evaluateDevHold())}`);
    return 0;
  }

  console.error(`[dev-hold] Unknown command: ${command}`);
  console.error("[dev-hold] Usage: dev-hold.ts <acquire|release|status> [--quiet]");
  return 1;
}

// Only act as a CLI when executed directly; `bs-config.ts` imports the helpers.
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exit(runCli(process.argv.slice(2)));
}
