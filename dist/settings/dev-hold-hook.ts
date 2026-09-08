/**
 * `PreToolUse` bridge between Claude Code and the dev-stack reload hold.
 *
 * `dev-hold.ts` explains why the hold exists. This file exists because of how it
 * is *triggered*: the matcher in `.claude/settings.json` keys on the tool name,
 * and `Edit|Write|NotebookEdit` is not the whole set of ways an agent writes a
 * file. An agent running under bypass-permissions mode is told to prefer the
 * Bash tool for file changes, so it edits with `cat > file <<'EOF'`, `sed -i`,
 * or a throwaway Python script -- none of which that matcher can ever see. That
 * gap is not hypothetical: it is what let one feature branch cost eight full
 * Python restarts and five browser reloads instead of one of each.
 *
 * Adding a blanket `Bash` matcher would over-correct. Every `git status`, every
 * `npm run test`, every `grep` would take the hold, and `npm run logs` would
 * then print its `DEV HOLD ACTIVE -- this digest is stale` banner over a digest
 * that is perfectly current -- training the reader to ignore the one warning
 * that matters. So a Bash command takes the hold only when it can plausibly
 * write into the tree (see `commandCanWrite`), and never when it is one of the
 * hold's own controls -- which would otherwise re-freeze the stack in the same
 * breath that released it -- or the read-only quality gate.
 *
 * The hook is fail-open by construction: unparseable input, an unknown tool, or
 * a thrown error all exit 0 without a hold. A missing hold degrades to the old
 * reload-per-edit behaviour; a hook that blocks tool calls would break the
 * session outright, so that trade is deliberate and one-directional. It matters
 * more than it looks: `PreToolUse` is fail-*closed* in GitHub Copilot, where a
 * non-zero exit denies the tool call, so this file must never exit non-zero for
 * any reason. Nothing here prints to stdout either -- an exit 0 with no output
 * is "continue normally" in all three hosts.
 *
 * One script serves Claude Code, GitHub Copilot and Codex CLI: all three deliver
 * the same PascalCase payload on stdin (`tool_name`, `tool_input.command`), so
 * only the config file that points at it differs. See the "Dev hold" section of
 * AGENTS.md for the three locations.
 *
 * Erasable-only TypeScript and dependency-free, like `dev-hold.ts`, so Node can
 * run it directly in front of every tool call without a bundler in the path.
 */

/**
 * The hold module is loaded lazily, inside the try/catch in `main()`, and never
 * imported at the top of this file.
 *
 * This is not a style choice. `PreToolUse` is **fail-closed** in GitHub Copilot:
 * a non-zero exit denies the tool call outright. A static import that fails to
 * resolve throws before any of this file's own code runs, so the process exits
 * 1 and the agent is left unable to use a single tool -- and the failure mode
 * is real, not theoretical: an extensionless `./dev-hold` specifier (valid under
 * tsx, invalid under plain `node`, which is what runs this hook) did exactly
 * that. Deferring the import keeps every failure inside a `catch` that exits 0.
 *
 * The `.ts` extension is load-bearing for the same reason and must not be
 * "tidied" away. Both are pinned by `dev-hold.test.ts` -> "the hook binary".
 */
const HOLD_MODULE = "./dev-hold.ts";

/**
 * Tool names are normalised before matching, because the three hosts spell the
 * same tool differently: Claude Code's `Edit`, Codex CLI's `apply_patch`, and
 * VS Code Copilot's `insert_edit_into_file` all mean "an agent is writing a
 * file". Lower-casing and dropping non-letters collapses those spellings so one
 * set covers every host, and a name nobody predicted simply falls through to
 * "do not hold" rather than to a crash.
 */
function normalizeToolName(name: string): string {
  return name.toLowerCase().replace(/[^a-z]/g, "");
}

/** Tools whose whole purpose is writing a file. Always take the hold. */
const ALWAYS_HOLD_TOOLS = new Set(
  [
    // Claude Code
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    // Codex CLI
    "apply_patch",
    "write_file",
    // Copilot (CLI + VS Code)
    "edit",
    "create",
    "str_replace",
    "str_replace_editor",
    "create_file",
    "insert_edit_into_file",
    "replace_string_in_file",
    "apply_diff",
  ].map(normalizeToolName),
);

/**
 * Tools that run a shell command. These hold only when the command itself looks
 * like a writer -- see `commandCanWrite`.
 */
const SHELL_TOOLS = new Set(
  ["Bash", "BashOutput", "bash", "shell", "exec_command", "run_in_terminal", "terminal"].map(
    normalizeToolName,
  ),
);

/**
 * Commands that must never take the hold, whatever else they look like.
 *
 * Two groups, for two different reasons. The hold's own controls come first:
 * `npm run dev:resume` releases and drains, so re-acquiring on the very next
 * Bash call would undo the drain the agent just asked for, and `npm run logs`
 * reads the result of that drain, so holding around it would stamp a fresh
 * digest stale.
 *
 * The quality gate is the second group. It runs through `uv run python`, which
 * the write-intent list below treats as a writer -- correctly, since a throwaway
 * Python script is a common way for an agent to edit a file. But `check.py` only
 * ever reports, so letting it hold would raise the stale-digest banner over a
 * digest nothing had invalidated.
 */
const NEVER_HOLD_PATTERN = new RegExp(
  [
    "dev-hold",
    "dev:hold",
    "dev:resume",
    "browser_log\\.py",
    "npm\\s+run\\s+logs",
    // The gate, by either path separator: `check.py` reports and never writes.
    "settings[\\\\/]check\\.py",
    "\\bpyright\\b",
    "\\bruff\\s+check\\b",
    "\\bpytest\\b",
  ].join("|"),
);

/**
 * Shapes of Bash command that can put bytes on disk.
 *
 * Deliberately generous: a false positive costs one deferred reload that the
 * `Stop` hook drains anyway, while a false negative costs a full server restart
 * mid-run. When in doubt, hold.
 */
const WRITE_INTENT_PATTERNS: RegExp[] = [
  />>?\s*\S/, //            shell redirection, including `cat > file <<'EOF'`
  /\btee\b/,
  /\bsed\b[^|]*-i/, //      in-place sed
  /\b(cp|mv|rm|mkdir|touch|ln)\b/,
  /\bgit\s+(checkout|restore|apply|stash|revert|merge|rebase|pull|clean|mv|rm)\b/,
  /\bnpm\s+run\s+(format|test:fix|build|css|static)\b/,
  /\bnpx\s+(ppy|prisma|maddex|ppicons)\b/,
  /\bpython\b/, //          a throwaway script is still a writer
  /\buv\s+run\b/,
  /\bruff\s+format\b/,
  /\bdjlint\b/,
];

export function commandCanWrite(command: string): boolean {
  if (!command) return false;
  if (NEVER_HOLD_PATTERN.test(command)) return false;
  return WRITE_INTENT_PATTERNS.some((pattern) => pattern.test(command));
}

export function shouldHold(toolName: string, command: string): boolean {
  const normalized = normalizeToolName(toolName);
  if (ALWAYS_HOLD_TOOLS.has(normalized)) return true;
  if (SHELL_TOOLS.has(normalized)) return commandCanWrite(command);
  return false;
}

function readStdin(): Promise<string> {
  return new Promise((resolve) => {
    let raw = "";
    // No stdin (a manual invocation, or a host that does not pipe the payload)
    // must not hang the tool call, so resolve on `end` and on nothing at all.
    if (process.stdin.isTTY) {
      resolve("");
      return;
    }
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      raw += chunk;
    });
    process.stdin.on("end", () => resolve(raw));
    process.stdin.on("error", () => resolve(""));
  });
}

async function main(): Promise<void> {
  let toolName = "";
  let command = "";
  try {
    const payload = JSON.parse((await readStdin()).trim() || "{}");
    // PascalCase events carry snake_case fields in all three hosts; Copilot's
    // camelCase event names carry camelCase ones. Accept either rather than
    // depending on which spelling a host's config happened to select.
    toolName = String(payload?.tool_name ?? payload?.toolName ?? "");
    const input = payload?.tool_input ?? payload?.toolArgs ?? payload?.toolInput ?? {};
    command = String(input?.command ?? input?.commandLine ?? input?.script ?? "");
  } catch {
    // Malformed payload: fail open rather than guessing at a hold.
    return;
  }

  if (!shouldHold(toolName, command)) return;
  const { acquireDevHold } = await import(HOLD_MODULE);
  acquireDevHold(process.env.CASPIAN_DEV_HOLD_OWNER || "agent");
}

if (process.argv[1] && import.meta.filename === process.argv[1]) {
  main()
    .catch(() => {
      // Fail open: never block a tool call over a reload optimisation.
    })
    .finally(() => process.exit(0));
}
