"""Read the dev-session browser log and report per-route front-end health.

Why this exists
---------------
`settings/dev-log-bridge.ts` forwards browser-side PulsePoint errors into the
`npm run dev` terminal. That only helps whoever owns that terminal: an AI agent
working in a different session cannot see stdout, and spawning a second
`npm run dev` to get its own copy would bind different ports and orphan the
browser tab the developer is actually looking at.

So the bridge also appends every event to `.casp/browser-log.jsonl`, and this
script renders it. `npm run logs`.

The hard part is not reading errors, it is not lying about their absence. Three
ways a naive error log misleads a reader, and how the format answers each:

* **Empty is ambiguous.** No errors could mean the route is fine, or that nobody
  ever opened it, or that the dev server is not running. The log records `load`
  events and a `session` header, so those three are distinguishable and this
  script names them separately.
* **Fixed errors look current.** A clean reload writes nothing, so an error from
  before the fix would sit in the file forever. Because every page load is
  recorded, a route's state is whatever happened during its *most recent* load.
* **A reload does not re-test everything.** It re-runs mount, so it genuinely
  clears a mount-phase error -- but it never clicks a button. An error from a
  click handler survives the reload as NEEDS RECHECK instead of being reported
  CLEAN, which is how a live bug would otherwise get signed off.
* **Reports race.** Two POSTs can arrive out of order, so an error is tied to its
  load by the client-generated `page` id, never by arrival time.

Anyone reading the raw JSONL would see a fixed error as current, so the `session`
line carries a `readme` explaining the supersession rule and a clean reload
appends an explicit `resolved` event. An error whose `page` never produced a
`load` in this log -- a tab left open across a dev restart -- is reported as
UNCONFIRMED rather than as a fresh failure.

Every source change compacts the file down to the session header, a `restart`
marker, and the errors still open, so a dev session that runs for hours without a
restart cannot grow an unbounded log. Errors that survive a compaction are marked
`carried` and dropped at the next one, so a stale interaction error cannot haunt
the log forever.

Usage:

    python settings/browser_log.py            # human-readable digest
    python settings/browser_log.py --json     # machine-readable status
    python settings/browser_log.py --fail-on-error   # exit 1 if any route is dirty

Exit code is 0 by default even when routes are failing: whether a route has been
exercised depends on someone clicking around in a browser, so this must never
become a flaky pass/fail gate. `settings/check.py` prints it, and does not let it
change the gate's exit code.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = PROJECT_ROOT / ".casp" / "browser-log.jsonl"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except AttributeError, ValueError:
    pass

_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def red(t: str) -> str:
    return _c("31", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def gray(t: str) -> str:
    return _c("90", t)


def bold(t: str) -> str:
    return _c("1", t)


def cyan(t: str) -> str:
    return _c("36", t)


@dataclass
class PageLoad:
    """One browser page load and everything the runtime reported during it."""

    page: str
    route: str
    at: str = ""
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    #: True when the error arrived but the matching `load` event never did.
    orphan: bool = False


@dataclass
class RouteStatus:
    route: str
    last_load: str
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    #: Mount errors from *earlier* loads, retested and cleared by a later load.
    healed: int
    #: The newest errors came from a page with no `load` in this log -- typically
    #: a tab opened before the last dev restart. Real, but possibly already fixed.
    unconfirmed: bool = False
    #: Interaction errors a reload could not retest, plus errors carried across a
    #: source change. Not proof of a live bug, and not proof of a fix either.
    recheck: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.errors and not self.recheck


@dataclass
class LogReport:
    """Everything a caller needs to describe front-end health without guessing."""

    #: "missing" (no dev session ever wrote), "live", "ended", "stale".
    session: str
    started: str = ""
    pid: int = 0
    port: int = 0
    routes: list[RouteStatus] = field(default_factory=list)
    #: When the log was last compacted because source files changed.
    last_restart: str = ""

    @property
    def failing(self) -> list[RouteStatus]:
        return [r for r in self.routes if not r.clean]

    @property
    def observed(self) -> bool:
        return bool(self.routes)


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            # A torn final line (server killed mid-write) must not hide the rest.
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _port_is_listening(port: int) -> bool:
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def build_report(path: Path = LOG_FILE) -> LogReport:
    """Collapse the raw event stream into current per-route status."""
    events = _read_events(path)
    if not events:
        return LogReport(session="missing")

    started = ""
    pid = 0
    port = 0
    ended = False
    last_restart = ""
    for event in events:
        if event.get("type") == "session":
            started = str(event.get("t") or "")
            pid = int(event.get("pid") or 0)
            port = int(event.get("port") or 0)
            ended = False
        elif event.get("type") == "session-end":
            ended = True
        elif event.get("type") == "restart":
            last_restart = str(event.get("t") or "")

    # Group by the client's page id so an error is attributed to the load that
    # produced it regardless of the order the two POSTs landed in.
    pages: dict[str, PageLoad] = {}
    order: list[str] = []
    # Errors that survived a compaction. Their `load` event was dropped with the
    # rest of the history, so they are tracked by route instead of by page.
    carried: dict[str, list[dict[str, Any]]] = {}

    def _page_for(event: dict[str, Any]) -> PageLoad:
        key = str(event.get("page") or f"anon-{len(order)}")
        if key not in pages:
            pages[key] = PageLoad(
                page=key,
                route=str(event.get("route") or "?"),
                at=str(event.get("t") or ""),
                orphan=True,
            )
            order.append(key)
        return pages[key]

    for event in events:
        kind = event.get("type")
        if event.get("carried"):
            carried.setdefault(str(event.get("route") or "?"), []).append(event)
        elif kind == "load":
            page = _page_for(event)
            page.orphan = False
            page.at = str(event.get("t") or page.at)
            page.route = str(event.get("route") or page.route)
        elif kind == "error":
            _page_for(event).errors.append(event)
        elif kind == "warn":
            _page_for(event).warnings.append(event)

    # Latest load wins: an error is only current if it happened on the most
    # recent load of that route.
    by_route: dict[str, list[PageLoad]] = {}
    for key in order:
        page = pages[key]
        by_route.setdefault(page.route, []).append(page)

    routes: list[RouteStatus] = []
    for route in sorted(set(by_route) | set(carried)):
        loads = by_route.get(route, [])
        # Carried errors always need rechecking: the code changed under them.
        recheck = list(carried.get(route, []))

        if not loads:
            routes.append(
                RouteStatus(
                    route=route, last_load="", errors=[], warnings=[], healed=0, recheck=recheck
                )
            )
            continue

        latest = loads[-1]
        healed = 0
        for page in loads[:-1]:
            for err in page.errors:
                # A later load re-ran mount, so a mount error is genuinely
                # retested. An interaction error is not: nothing reloaded here
                # clicked anything, so it stays open rather than reading CLEAN.
                if err.get("phase") == "interaction":
                    recheck.append(err)
                else:
                    healed += 1

        routes.append(
            RouteStatus(
                route=route,
                last_load=latest.at,
                errors=latest.errors,
                warnings=latest.warnings,
                healed=healed,
                unconfirmed=latest.orphan,
                recheck=recheck,
            )
        )

    if ended:
        session = "ended"
    elif _port_is_listening(port):
        session = "live"
    else:
        session = "stale"

    return LogReport(
        session=session,
        started=started,
        pid=pid,
        port=port,
        routes=routes,
        last_restart=last_restart,
    )


def _age(iso: str) -> str:
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = int((datetime.now(timezone.utc) - moment).total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def _clock(iso: str) -> str:
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return iso


_SESSION_LINES = {
    "missing": (
        "no browser log for this dev session",
        "Nothing has been observed. Start `npm run dev` and open the route "
        "in a browser before drawing any conclusion about the front end.",
    ),
    "stale": (
        "dev server is NOT running",
        "This log is left over from an exited dev session. Treat every line "
        "below as history, not as the current state of the app.",
    ),
    "ended": (
        "dev session ended cleanly",
        "The dev server has shut down. The results below are from that finished session.",
    ),
}


def _print_errors(errors: list[dict[str, Any]]) -> None:
    """Print each distinct message once, with the frames that locate it."""
    seen: set[str] = set()
    for err in errors:
        message = str(err.get("message") or "").strip()
        if message in seen:
            continue
        seen.add(message)
        after = err.get("afterMs")
        timing = ""
        if err.get("phase") == "interaction" and isinstance(after, int):
            timing = gray(f"   (fired {after // 1000}s after load -- interaction, not mount)")
        for line in message.split("\n"):
            print(f"      {red(line)}{timing}")
            timing = ""
        for frame in list(err.get("stack") or [])[:2]:
            print(gray(f"        {frame}"))


def print_report(report: LogReport) -> None:
    print()
    print(bold("Browser log") + gray(f"  ({LOG_FILE.relative_to(PROJECT_ROOT)})"))
    print("=" * 60)

    if report.session == "live":
        age = _age(report.started)
        detail = f"pid {report.pid}, port {report.port}, started {_clock(report.started)}"
        print(
            f"  {green('LIVE')}  dev session active {gray(f'({detail}{", " + age if age else ""})')}"
        )
    else:
        headline, advice = _SESSION_LINES[report.session]
        mark = yellow("WARN") if report.session != "missing" else gray("NONE")
        print(f"  {mark}  {headline}")
        print(gray(f"        {advice}"))
        if report.session == "missing":
            print()
            return

    print()

    if not report.observed:
        print(yellow("  No page loads recorded yet."))
        print(gray("  The log only knows about routes someone actually opened."))
        print(gray("  An empty log is not evidence that the front end is healthy."))
        print()
        return

    for status in sorted(report.routes, key=lambda r: (r.clean, r.route)):
        # Compaction drops load events, so a carried-only route has no load time.
        when = (
            gray(f"last load {_clock(status.last_load)} {_age(status.last_load)}")
            if status.last_load
            else gray("no load since the last source change")
        )
        if status.clean:
            healed = gray(f"  ({status.healed} earlier error(s) resolved)") if status.healed else ""
            warn = yellow(f"  {len(status.warnings)} warning(s)") if status.warnings else ""
            print(f"  {green('CLEAN')}  {cyan(status.route)}  {when}{warn}{healed}")
            continue

        if status.errors:
            label = "UNCONFIRMED" if status.unconfirmed else f"{len(status.errors)} ERROR(S)"
        else:
            label = "NEEDS RECHECK"
        header = f"  {red(bold(label))}  {cyan(status.route)}"
        print(header if status.unconfirmed else f"{header}  {when}")

        if status.unconfirmed:
            # No matching load: the reporting tab was opened before this log
            # existed, so the error may already be fixed. Say that plainly rather
            # than sending someone hunting a bug that no longer exists.
            print(
                gray(
                    "      Reported by a page loaded before this log started "
                    "(e.g. before the last dev restart)."
                )
            )
            print(gray("      Reload the route and re-run to confirm whether it is still live."))

        _print_errors(status.errors)

        if status.recheck:
            # The critical honesty case: a reload re-runs mount, so it clears a
            # mount error -- but it never clicks a button. Reporting these as
            # CLEAN is how a live bug gets signed off.
            print(gray("      Not re-tested by the reloads since:"))
            _print_errors(status.recheck)
            if any(e.get("carried") for e in status.recheck):
                print(gray("      Source changed since these fired; they may already be fixed."))
            print(gray("      Repeat the interaction (click/submit) and re-run to confirm."))

    print()
    if report.failing:
        print(red(bold(f"{len(report.failing)} route(s) failing in the browser.")))
    else:
        print(green(bold("Every route loaded this session is clean.")))
    print(gray("Routes not listed were never opened -- that is no signal, not a pass."))
    print()


def to_json(report: LogReport) -> str:
    return json.dumps(
        {
            "session": report.session,
            "started": report.started,
            "pid": report.pid,
            "port": report.port,
            "lastRestart": report.last_restart,
            "routes": [
                {
                    "route": r.route,
                    "lastLoad": r.last_load,
                    "clean": r.clean,
                    "unconfirmed": r.unconfirmed,
                    "needsRecheck": [
                        {
                            "message": e.get("message"),
                            "phase": e.get("phase"),
                            "carried": bool(e.get("carried")),
                        }
                        for e in r.recheck
                    ],
                    "errors": [
                        {"message": e.get("message"), "stack": e.get("stack")} for e in r.errors
                    ],
                    "warnings": [{"message": w.get("message")} for w in r.warnings],
                    "healed": r.healed,
                }
                for r in report.routes
            ],
        },
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Report browser-side health for this dev session.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable status.")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit 1 when a route is currently failing (off by default: presence of "
        "a signal depends on someone opening the page, so it is not a stable gate).",
    )
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(to_json(report))
    else:
        print_report(report)

    if args.fail_on_error and report.session == "live" and report.failing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
