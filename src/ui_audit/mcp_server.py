"""`ui-audit mcp`: the audit as tools for MCP clients (Claude Desktop, Cursor, Windsurf, ...).

A minimal Model Context Protocol server over stdio, standard library only: one JSON-RPC 2.0
message per line on stdin, one answer per line on stdout. stdout carries protocol messages
only; everything else, the audit's progress included, goes to stderr, which clients show
as the server's log.

Tools return the compact views from `summary.py`, so a client never pulls report.json whole.
An audit runs in its own process (`python -m ui_audit audit --json`), like the app's runs.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from . import __version__

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PAGE_SIZE = 20
AUDIT_TIMEOUT = 3600


def log(message: str) -> None:
    print(f"ui-audit mcp: {message}", file=sys.stderr, flush=True)


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


_STR = {"type": "string"}
_RUN = {"type": "string", "description": "run directory (the audit's output folder, holding report.json)"}
_PAGING = {"page": {"type": "integer", "minimum": 1, "description": "page number, from 1"},
           "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": f"entries per page (default {PAGE_SIZE})"}}

TOOLS = [
    {"name": "audit",
     "description": "Audit a running web app for responsive layout defects across routes, UI states and widths. "
                    "Returns a compact summary: counts, causes (groups) with one example each, pages to check by hand. "
                    "Takes from seconds (a few routes and widths) to minutes (a full sweep).",
     "inputSchema": _schema({
         "base_url": {"type": "string", "description": "URL of the running app, e.g. http://localhost:3000"},
         "routes": {"type": "array", "items": _STR, "description": "audit only these paths (default: discover)"},
         "widths": {"type": "array", "items": {"type": "integer"}, "description": "exact widths in px (default: sweep 320-1920)"},
         "fast": {"type": "boolean", "description": "probe opened menus and dialogs only at key widths"},
         "output": {"type": "string", "description": "run directory to write (default from ui-audit.toml, .ui-audit/latest)"},
         "project_root": {"type": "string", "description": "source folder for route discovery and source hints"},
     }, ["base_url"])},
    {"name": "verify",
     "description": "Compare a baseline run with a later one: which findings were fixed, introduced or persist. "
                    "Findings the later run did not look at are counted as out_of_scope, never as fixed.",
     "inputSchema": _schema({"baseline": _RUN, "current": _RUN}, ["baseline", "current"])},
    {"name": "list_findings",
     "description": "Page through a run's causes (groups), or with `group` through every finding of one cause "
                    "with source candidates, screenshot paths and the re-check command.",
     "inputSchema": _schema({"run_dir": _RUN, "group": {"type": "string", "description": "group id (or an issue id)"},
                             "severity": {"type": "string", "enum": ["P1", "P2", "P3"], "description": "only this severity"},
                             **_PAGING}, ["run_dir"])},
    {"name": "get_screenshot",
     "description": "The screenshot of a finding (issue or group id), with the measured element boxed where available.",
     "inputSchema": _schema({"run_dir": _RUN, "id": {"type": "string", "description": "issue or group id"},
                             "width": {"type": "integer", "description": "the captured width nearest to this (default: the best one)"}},
                            ["run_dir", "id"])},
    {"name": "accept",
     "description": "Mark a finding or a whole group as intentional, with a reason; later audits stop counting it.",
     "inputSchema": _schema({"run_dir": _RUN, "id": {"type": "string", "description": "issue or group id"},
                             "reason": {"type": "string", "description": "why this is fine"}}, ["run_dir", "id", "reason"])},
]


class ToolError(Exception):
    """A tool failed in a way the model should read (isError result), not a protocol error."""


def _text(data) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return {"type": "text", "text": text}


def _report(run_dir: str) -> tuple[Path, dict]:
    from . import report as report_mod

    path = Path(run_dir)
    if not (path / report_mod.REPORT_JSON).is_file():
        raise ToolError(f"no report.json in {run_dir}")
    return path, report_mod.read_json(path)


def _page(args: dict) -> tuple[int, int]:
    page = max(1, int(args.get("page") or 1))
    limit = min(100, max(1, int(args.get("limit") or PAGE_SIZE)))
    return page, limit


def tool_audit(args: dict) -> list[dict]:
    command = [sys.executable, "-m", "ui_audit", "audit", "--json", "--base-url", str(args["base_url"])]
    for route in args.get("routes") or []:
        command += ["--route", str(route)]
    if args.get("widths"):
        command += ["--width", ",".join(str(int(w)) for w in args["widths"])]
    if args.get("fast"):
        command.append("--fast")
    for key in ("output", "project_root"):
        if args.get(key):
            command += [f"--{key.replace('_', '-')}", str(args[key])]
    log("running " + " ".join(command[2:]))
    try:
        done = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=sys.stderr,
                              text=True, timeout=AUDIT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"the audit took longer than {AUDIT_TIMEOUT}s and was stopped") from exc
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise ToolError(f"the audit failed (exit code {done.returncode}); see the server log for details")
    data = json.loads(lines[-1])
    if data.get("report") is None:
        raise ToolError(f"the audit did not run (exit code {done.returncode}); see the server log for details")
    return [_text(data)]


def tool_verify(args: dict) -> list[dict]:
    from . import summary, verify

    _, baseline = _report(args["baseline"])
    current_dir, current = _report(args["current"])
    result = verify.compare(baseline, current)
    verify.write(result, current_dir)
    return [_text(summary.verify_summary(result))]


def tool_list_findings(args: dict) -> list[dict]:
    from . import summary

    run_dir, report = _report(args["run_dir"])
    page, limit = _page(args)
    severity = args.get("severity")
    if args.get("group"):
        try:
            data = summary.detail(report, run_dir, args["group"])
        except LookupError as exc:
            raise ToolError(str(exc)) from exc
        issues = [i for i in data["issues"] if not severity or i["severity"] == severity]
        data["issues"] = issues[(page - 1) * limit: page * limit]
        data.update(page=page, total=len(issues), more=max(0, len(issues) - page * limit))
        return [_text(data)]
    data = summary.summary(report, run_dir, max_groups=10_000)
    groups = [g for g in data.pop("groups") if not severity or g["severity"] == severity]
    data.pop("more_groups", None)
    data["groups"] = groups[(page - 1) * limit: page * limit]
    data.update(page=page, total=len(groups), more=max(0, len(groups) - page * limit))
    return [_text(data)]


def tool_get_screenshot(args: dict) -> list[dict]:
    from . import summary

    run_dir, report = _report(args["run_dir"])
    try:
        group, members = summary.find(report, args["id"])
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
    issue = summary.representative(group, {i["id"]: i for i in members}) if group else members[0]
    capture = summary.best_capture(report, issue, args.get("width"))
    if not capture:
        raise ToolError(f"no screenshot for {args['id']} ({issue['check']} has none)")
    relative = capture.get("annotated") or capture["file"]
    path = (run_dir / relative).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
        raise ToolError(f"screenshot {relative} is missing from {run_dir}")
    caption = (f"{issue['route']} [{issue['state']}] at {capture['width']}px"
               + (f" in {capture['browser']}" if capture.get("browser", "chromium") != "chromium" else "")
               + f": {issue['check']} {issue['selector']} — {path}")
    return [_text(caption),
            {"type": "image", "data": base64.b64encode(path.read_bytes()).decode("ascii"), "mimeType": "image/png"}]


def tool_accept(args: dict) -> list[dict]:
    from . import report as report_mod

    run_dir, _ = _report(args["run_dir"])
    if not str(args.get("reason") or "").strip():
        raise ToolError("give a reason")
    try:
        added, already, path = report_mod.accept(run_dir, [args["id"]], args["reason"])
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
    return [_text({"accepted": added, "already_accepted": already, "file": str(path)})]


HANDLERS = {"audit": tool_audit, "verify": tool_verify, "list_findings": tool_list_findings,
            "get_screenshot": tool_get_screenshot, "accept": tool_accept}


def handle(message: dict) -> dict | None:
    """The answer to one JSON-RPC message, or None for a notification."""
    method, ident = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if "id" not in message:  # notifications (initialized, cancelled) need no answer
        return None

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def error(code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "ui-audit", "version": __version__},
                   "instructions": "Start with `audit` (or `list_findings` on an existing run), work through one group "
                                   "at a time with `list_findings` and `get_screenshot`, and prove fixes with a "
                                   "targeted `audit` and `verify`."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return error(-32602, f"unknown tool: {name}")
        missing = [k for k in next(t for t in TOOLS if t["name"] == name)["inputSchema"]["required"] if k not in args]
        if missing:
            return ok({"content": [_text(f"missing argument(s): {', '.join(missing)}")], "isError": True})
        try:
            return ok({"content": handler(args), "isError": False})
        except ToolError as exc:
            return ok({"content": [_text(str(exc))], "isError": True})
        except Exception as exc:  # noqa: BLE001 - a broken run must not take the server down
            log(f"{name} failed: {exc!r}")
            return ok({"content": [_text(f"{name} failed: {exc}")], "isError": True})
    return error(-32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    log(f"ready (ui-audit {__version__}, protocol {PROTOCOL_VERSIONS[0]})")
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(message, list):  # batches were dropped from the spec in 2025-06-18; answer them anyway
                answers = [a for a in (handle(m) for m in message if isinstance(m, dict)) if a]
                answer = answers or None
            elif isinstance(message, dict):
                answer = handle(message)
            else:
                answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
